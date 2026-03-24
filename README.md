# zentry

Zentry is a Django productivity app for daily planning, ideas, goals, and reviews.

## New features started (March 2026)

### 1) ZenAI foundation
- Persistent chat sessions and messages via `ZenChatSession` and `ZenChatMessage`.
- User preference memory (`UserPreference`) including:
	- default landing page
	- books being read this month
	- favorite authors/thinking influences
- Memory-aware context building from tasks, goals, ideas, and journal snippets.
- AI route support:
	- `GET /zenai/`
	- `GET /zenai/sessions/`
	- `GET /zenai/session/<id>/`
	- `POST /zenai/send/`

### 2) Navigation + default page
- Top navigation has been moved into a left sidebar in `templates/base.html`.
- Default post-login destination is configurable from `Preferences`.

### 3) PWA scaffold
- `manifest.json` route: `/manifest.json`
- Service worker route: `/service-worker.js`
- Basic icon placeholders in `static/icons/`

## Environment notes
- Set `SECRET_KEY` in environment (required by settings).
- Optional: set `ANTHROPIC_API_KEY` to enable live model responses in ZenAI.

## Migration
Apply database updates for new models:

```bash
python manage.py migrate
```
