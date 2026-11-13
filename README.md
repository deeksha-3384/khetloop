# KhetLoop

A voice-first agricultural intelligence and early-warning system. Team Code Stack, AgriTech track, Colossus 3.0.

A small farmer sends a Kannada or Hindi voice note and a leaf photo on Telegram. KhetLoop gives a **preliminary** assessment (or asks for a clearer photo), remembers the report on the farm's timeline, escalates unclear or concerning cases to a human agri expert, warns nearby farmers when similar reports form a potential cluster, and follows up with reminders.

## Design rules

- Rules decide, the LLM only words. Escalation, abstention and clustering are plain Python in `backend/rules/`.
- Never prescribe. No pesticide names or dosages. Approved non-chemical guidance only, with a safety filter on every generated reply.
- Every assessment is a preliminary assessment, not a confirmed diagnosis.
- The cluster label is always `potential_cluster`.
- Every object shows its `data_source`: live, cached, simulated or unverified. Seed and demo data is always simulated.
- Privacy: coordinates are rounded to 2 decimals, and public endpoints never return farm ids, report ids or exact locations.
- Graceful failure: if AI, speech, weather or text-to-speech fails, the report is still saved and a reply is still sent.

## Team

| Role | Owner | Folders |
|------|-------|---------|
| P1 Backend lead | Deeksha J | `backend/`, `shared/`, `docs/CONTRACT.md`, `tests/backend/` |
| P2 Database | Dhruva | `database/`, `tests/database/` |
| P3 Frontend | Manjunath S | `frontend/` |
| P4 Integrations, data, pitch | Nishanth | `integrations/`, `data/`, `docs/pitch/`, `tests/integrations/` |

The shared spec is `KhetLoop_Master_Contract_v2_1.pdf`, plus the change log in `docs/CONTRACT.md`.

## Setup

Requires Python 3.10 or higher (3.11 to 3.13 recommended) and ffmpeg (for Telegram voice notes).

```bash
git clone <repo-url>
cd khetloop
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
copy .env.example .env            # cp .env.example .env on macOS / Linux
```

Fill in `.env`. Never commit it and never paste keys in chat.

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Shared Supabase project (service_role key, backend only) |
| `SUPABASE_STORAGE_BUCKET` | Private image bucket, `report-images` |
| `DB_MODE` | `supabase` for the shared database, `memory` for solo development |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini vision (fallback provider) |
| `GROQ_API_KEY`, `GROQ_MODEL` | Groq vision (first provider), speech-to-text, reply wording |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `EXPERT_API_KEY` | Value of the `X-Expert-Key` header (`demo-expert-key`) |
| `API_BASE_URL`, `APP_PORT` | API address, default `http://localhost:5000` and `5000` |
| `SPEECH_PROVIDER` | `groq_gtts` (default) or legacy `gemini_gtts` |
| `TMP_DIR` | Temporary audio files |

## Run

Use one terminal per process, each with the venv active.

```bash
python -m backend.app             # Flask API on port 5000
python -m backend.bot.bot         # Telegram bot (long polling). Run only one copy.
python -m http.server 8000        # Frontend, then open http://localhost:8000/frontend/index.html
```

Check the API: `GET http://localhost:5000/api/health` should show `"database": "ok"`.

The frontend uses mock data until `USE_MOCK` in `frontend/js/config.js` is set to `false`.

## Seed data

```bash
python -m database.seed_loader            # load simulated seed data
python -m database.seed_loader --reset    # remove all simulated rows first, then load
```

`--reset` only removes simulated rows. Live data is never touched. Run it before each demo rehearsal so timestamps stay inside the 72-hour cluster window.

## Tests

Set `DB_MODE=memory` in `.env` first, because some route tests expect memory mode and the integration check writes rows. Set it back to `supabase` afterwards.

```bash
python -m pytest tests/backend -q
python -m tests.backend.try_routes
```

## API

Eleven endpoints, all returning `{"ok": true, "data": ...}` or `{"ok": false, "error": {"code", "message"}}`. Expert and admin endpoints require the `X-Expert-Key` header.

| Endpoint | Purpose | Key |
|----------|---------|-----|
| `POST /api/reports` | Submit a report (multipart: farm_id, image, optional audio, voice_text, language) | No |
| `GET /api/reports/<report_id>` | One report | No |
| `GET /api/farms` | List farms | No |
| `GET /api/farms/<farm_id>/timeline` | Farm history | No |
| `GET /api/expert/cases?status=` | Expert queue | Yes |
| `POST /api/expert/cases/<report_id>/review` | Submit an expert review | Yes |
| `GET /api/radar/clusters` | Public clusters | No |
| `GET /api/radar/clusters/<cluster_id>` | Cluster detail | Yes |
| `POST /api/reminders/run` | Send due reminders | Yes |
| `POST /api/demo/simulate-cluster` | Scripted community scenario | Yes |
| `GET /api/health` | Status | No |

A Postman collection is in `tests/backend/KhetLoop.postman_collection.json`.

## Demo flow

1. Start Flask, the bot and the frontend. Run the seed loader with `--reset`.
2. Farmer sends `/start`, picks a language, crop and area (Kolar North), then sends a leaf photo and a voice note.
3. The bot replies in the farmer's language with a "Why am I seeing this?" list and an audio reply.
4. A blurry photo gets an abstain reply. A report with a severity word (for example "spreading fast") is escalated to the expert.
5. The expert opens `dashboard.html`, reviews the case, and the farmer receives the guidance on Telegram.
6. Run `POST /api/demo/simulate-cluster` for Kolar North. The radar shows a simulated `potential_cluster` and the nearby farmer gets the alert.

Do not send a live early blight report from Chikkaballapur during the demo, because the seeded cluster would form.

## Folder structure

```
backend/      Flask app, routes, rules, services, Telegram bot
database/     schema, db_client, seed loader
frontend/     five HTML pages, shared JS and CSS
integrations/ weather, speech, reminders
data/         approved guidance, seed JSON, test images
shared/       constants and mock JSON
docs/         CONTRACT.md change log, pitch material
tests/        backend, database, integrations
```

## Troubleshooting

- Health shows `"database": "memory"`: `.env` has `DB_MODE=memory`, or a stale Windows variable overrides it. Run `echo $env:DB_MODE`, remove it with `Remove-Item Env:DB_MODE`, then restart Flask.
- Bot log shows 409 Conflict: two bot processes are running. Stop one.
- Voice notes fail: install ffmpeg, or use `/skip` and type the description.
- A value in `.env` seems ignored: check for a User-level Windows environment variable with the same name.