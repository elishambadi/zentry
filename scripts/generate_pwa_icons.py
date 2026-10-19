#!/usr/bin/env python3
"""Generate the PNG icons required by the web app manifest.

Run from the project root:

    python scripts/generate_pwa_icons.py

The script uses Pillow only (already a project dependency) and writes:
  static/icons/icon-192.png
  static/icons/icon-512.png
  static/icons/icon-maskable-192.png
  static/icons/icon-maskable-512.png
  static/icons/apple-touch-icon.png
  static/icons/badge-72.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / 'static' / 'icons'
GREEN = (22, 163, 74, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

FONT_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
]


def load_font(size):
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def draw_z(draw, size, font_ratio=0.427, y_ratio=0.52):
    font = load_font(max(8, round(size * font_ratio)))
    draw.text(
        (size / 2, size * y_ratio),
        'Z',
        font=font,
        fill=WHITE,
        anchor='mm',
    )


def rounded_icon(size):
    image = Image.new('RGBA', (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    radius = round(size * (32 / 192))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=GREEN)
    draw_z(draw, size)
    return image


def maskable_icon(size):
    image = Image.new('RGBA', (size, size), GREEN)
    draw = ImageDraw.Draw(image)
    # Keep the glyph inside the central 80% safe zone.
    draw_z(draw, size, font_ratio=0.32)
    return image


def apple_icon(size=180):
    image = Image.new('RGB', (size, size), GREEN[:3])
    draw = ImageDraw.Draw(image)
    draw_z(draw, size)
    return image


def badge(size=72):
    image = Image.new('RGBA', (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw_z(draw, size, font_ratio=0.72, y_ratio=0.52)
    return image


def main():
    ICON_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        'icon-192.png': rounded_icon(192),
        'icon-512.png': rounded_icon(512),
        'icon-maskable-192.png': maskable_icon(192),
        'icon-maskable-512.png': maskable_icon(512),
        'apple-touch-icon.png': apple_icon(180),
        'badge-72.png': badge(72),
    }

    for filename, image in outputs.items():
        image.save(ICON_DIR / filename)
        print(f'wrote {ICON_DIR / filename}')


if __name__ == '__main__':
    main()
