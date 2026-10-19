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

### 3) PWA + notifications
- Installable manifest at `/manifest.json` with PNG/maskable icons, shortcuts, and iOS meta tags.
- Service worker at `/service-worker.js`:
	- precached, self-contained `/offline/` fallback
	- cache-first static assets, network-first navigations
	- authenticated HTML/API responses are never cached
	- Web Push delivery and notification-click routing
- Custom install banner (`static/js/pwa.js`) plus install controls in Preferences.
- Web Push (`static/js/notifications.js`, `core/push.py`):
	- per-device `PushSubscription` records
	- notification permission and subscription management endpoints
	- test notification button
	- daily task digest sent by `send_daily_pushes`
- Pomodoro timer sends a system notification when focus/break sessions end.

## Environment notes
- Set `SECRET_KEY` in environment (required by settings).
- Optional: set `ANTHROPIC_API_KEY` to enable live model responses in ZenAI.
- Web Push requires VAPID keys. Generate and add them to `.env`:

```bash
python manage.py generate_vapid_keys --write-env
```

  Set `VAPID_ADMIN_EMAIL` to a real contact address (used in the VAPID claim).
  Push notifications require HTTPS in production (`localhost` is allowed for development).

## Daily reminder cron
The included `cron` service runs the digest every 5 minutes:

```bash
python manage.py send_daily_pushes
```

Useful flags: `--dry-run`, `--force`, `--user <username>`, `--window <minutes>`.
Reminder times are interpreted in each user's browser time zone (saved
automatically from Preferences), falling back to `TIME_ZONE`.

## Migration
Apply database updates for new models:

```bash
python manage.py migrate
```
