"""Speech-to-text for notebook voice notes.

Backends are pluggable and optional:
  • ``openai``      – OpenAI's audio transcription API (OPENAI_API_KEY).
  • ``whisper``     – the ``whisper`` CLI from ``pip install openai-whisper``.
  • ``faster-whisper`` – the ``faster-whisper`` Python package.
  • browser         – a transcript supplied by the browser as a fallback.

If no server engine is configured the audio is still stored; the browser's
SpeechRecognition transcript (when available) is used, otherwise the block is
saved without text and can be transcribed later.
"""

import importlib.util
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger('core.transcription')

OPENAI_TRANSCRIPTION_URL = 'https://api.openai.com/v1/audio/transcriptions'

MIME_SUFFIXES = {
    'audio/webm': '.webm',
    'audio/ogg': '.ogg',
    'audio/mp4': '.m4a',
    'audio/x-m4a': '.m4a',
    'audio/mpeg': '.mp3',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/aac': '.aac',
    'audio/flac': '.flac',
}
ALLOWED_SUFFIXES = {'.webm', '.ogg', '.oga', '.m4a', '.mp4', '.mp3', '.wav', '.aac', '.flac'}

_faster_whisper_model = None
_faster_whisper_key = None


def _openai_available():
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _whisper_cli_available():
    return bool(shutil.which('whisper') and shutil.which('ffmpeg'))


def _faster_whisper_available():
    return importlib.util.find_spec('faster_whisper') is not None


def resolve_backend():
    """Return the transcription backend that will be used, or ''."""
    requested = (getattr(settings, 'AUDIO_TRANSCRIPTION_BACKEND', 'auto') or 'auto').lower()

    if requested == 'openai':
        return 'openai' if _openai_available() else ''
    if requested == 'whisper':
        return 'whisper' if _whisper_cli_available() else ''
    if requested == 'faster-whisper':
        return 'faster-whisper' if _faster_whisper_available() else ''
    if requested == 'browser':
        return ''

    # auto
    if _openai_available():
        return 'openai'
    if _whisper_cli_available():
        return 'whisper'
    if _faster_whisper_available():
        return 'faster-whisper'
    return ''


def transcription_available():
    return bool(resolve_backend())


def transcription_backend_label():
    backend = resolve_backend()
    return {
        'openai': 'OpenAI transcription API',
        'whisper': 'local Whisper CLI',
        'faster-whisper': 'local faster-whisper',
    }.get(backend, '')


def max_audio_bytes():
    megabytes = int(getattr(settings, 'MAX_AUDIO_UPLOAD_MB', 25) or 25)
    return megabytes * 1024 * 1024


def is_audio_file(uploaded_file):
    """Accept MediaRecorder output even when the browser sends a generic MIME."""
    content_type = (getattr(uploaded_file, 'content_type', '') or '').split(';')[0].lower()
    suffix = Path(getattr(uploaded_file, 'name', '') or '').suffix.lower()
    return content_type.startswith('audio/') or suffix in ALLOWED_SUFFIXES


def _suffix_for(filename, content_type):
    suffix = Path(filename or '').suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return suffix
    mime = (content_type or '').split(';')[0].lower()
    return MIME_SUFFIXES.get(mime, '.webm')


def _read_audio(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass
    return uploaded_file.read()


def _transcribe_openai(audio_bytes, filename, content_type):
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    model = getattr(settings, 'OPENAI_TRANSCRIBE_MODEL', 'whisper-1') or 'whisper-1'
    timeout = int(getattr(settings, 'TRANSCRIPTION_TIMEOUT', 300) or 300)

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            OPENAI_TRANSCRIPTION_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            data={'model': model, 'response_format': 'json'},
            files={
                'file': (
                    filename or 'voice-note.webm',
                    audio_bytes,
                    content_type or 'application/octet-stream',
                ),
            },
        )
    response.raise_for_status()
    payload = response.json()
    return (payload.get('text') or '').strip()


def _transcribe_whisper_cli(audio_path, work_dir):
    model = getattr(settings, 'WHISPER_MODEL', 'base') or 'base'
    language = (getattr(settings, 'WHISPER_LANGUAGE', '') or '').strip()
    timeout = int(getattr(settings, 'TRANSCRIPTION_TIMEOUT', 300) or 300)

    command = [
        shutil.which('whisper'),
        str(audio_path),
        '--model', model,
        '--output_format', 'txt',
        '--output_dir', str(work_dir),
        '--verbose', 'False',
        '--fp16', 'False',
    ]
    if language:
        command += ['--language', language]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    transcript_file = Path(work_dir) / f'{audio_path.stem}.txt'
    if transcript_file.exists():
        return transcript_file.read_text(encoding='utf-8').strip()

    stderr = (result.stderr or '').strip().splitlines()
    detail = stderr[-1] if stderr else f'whisper exited with code {result.returncode}'
    raise RuntimeError(detail)


def _get_faster_whisper_model():
    global _faster_whisper_model, _faster_whisper_key

    from faster_whisper import WhisperModel  # imported lazily on purpose

    model_name = getattr(settings, 'WHISPER_MODEL', 'base') or 'base'
    device = getattr(settings, 'WHISPER_DEVICE', 'cpu') or 'cpu'
    compute_type = getattr(settings, 'WHISPER_COMPUTE_TYPE', 'int8') or 'int8'
    key = (model_name, device, compute_type)

    if _faster_whisper_model is None or _faster_whisper_key != key:
        _faster_whisper_model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
        _faster_whisper_key = key

    return _faster_whisper_model


def _transcribe_faster_whisper(audio_path):
    model = _get_faster_whisper_model()
    language = (getattr(settings, 'WHISPER_LANGUAGE', '') or '').strip() or None
    segments, _info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language=language,
    )
    return ' '.join(segment.text.strip() for segment in segments).strip()


def transcribe_audio(uploaded_file, filename='', browser_transcript=''):
    """Transcribe an uploaded audio file.

    Returns a dict with ``transcript``, ``source`` and ``error``. The original
    upload is never modified; callers should reset its file pointer before
    saving it.
    """
    fallback = (browser_transcript or '').strip()
    backend = resolve_backend()

    if not backend:
        return {
            'transcript': fallback,
            'source': 'browser' if fallback else '',
            'error': '' if fallback else (
                'No transcription engine is configured. '
                'Add OPENAI_API_KEY or install a local Whisper backend.'
            ),
        }

    audio_bytes = None
    content_type = getattr(uploaded_file, 'content_type', '') or 'application/octet-stream'
    filename = filename or getattr(uploaded_file, 'name', '') or 'voice-note.webm'
    suffix = _suffix_for(filename, content_type)

    try:
        audio_bytes = _read_audio(uploaded_file)
        with tempfile.TemporaryDirectory(prefix='zentry-audio-') as tmp_dir:
            audio_path = Path(tmp_dir) / f'voice-note{suffix}'
            audio_path.write_bytes(audio_bytes)

            if backend == 'openai':
                transcript = _transcribe_openai(audio_bytes, filename, content_type)
            elif backend == 'whisper':
                transcript = _transcribe_whisper_cli(audio_path, Path(tmp_dir))
            else:
                transcript = _transcribe_faster_whisper(audio_path)

        transcript = (transcript or '').strip()
        if transcript:
            return {'transcript': transcript, 'source': backend, 'error': ''}

        if fallback:
            return {'transcript': fallback, 'source': 'browser', 'error': ''}

        return {
            'transcript': '',
            'source': backend,
            'error': 'No speech was detected in the recording.',
        }
    except subprocess.TimeoutExpired:
        logger.exception('[transcription] %s timed out', backend)
        error = 'Transcription timed out. Try a shorter recording.'
    except Exception:
        logger.exception('[transcription] %s failed', backend)
        error = 'Transcription failed. Check the server logs or try again.'

    if fallback:
        return {'transcript': fallback, 'source': 'browser', 'error': ''}

    return {'transcript': '', 'source': '', 'error': error}
