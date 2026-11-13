# KhetLoop Contract: v2.2 change log

The full contract is `KhetLoop_Master_Contract_v2_1.pdf`. This file records changes made after v2.1.
Nothing else in v2.1 changed.

## Changes in v2.2

| # | Change | Affects |
|---|--------|---------|
| C22 | `SPEECH_PROVIDER` default is now `groq_gtts` (Groq Whisper for speech-to-text, gTTS for text-to-speech). `gemini_gtts` is still accepted as a legacy value. | P1, P4 |
| C23 | Vision tries Groq first, then Gemini. Provider order is `PROVIDER_ORDER` in `backend/services/gemini_vision.py`. Both keys are read from `.env`. | P1 |
| C24 | `requirements.txt` now includes `supabase`, `pillow` and `gTTS`. | all |
| C25 | `get_or_create_farm` accepts an optional `data_source="live"`; `insert_report` and `add_report_event` accept an optional `created_at`; `count_simulated()` and `delete_simulated()` were added to `db_client.py`. | P1, P2 |
| C26 | `--reset` on `database.seed_loader` removes simulated farms, reports, clusters and alerts only. Live data is never touched. | P2 |

## Backend notes

- `escalation_reason` values: `AI_UNAVAILABLE`, `UNCLEAR_AFTER_RETRY`, `SEVERITY_KEYWORD`, `MEDIUM_CONFIDENCE_HIGH_RISK`.
- The cluster alert text never contains the word "outbreak".
- Public radar endpoints never return farm ids, report ids or exact coordinates.
- Run order for the demo: `python -m backend.app`, then `python -m backend.bot.bot`.