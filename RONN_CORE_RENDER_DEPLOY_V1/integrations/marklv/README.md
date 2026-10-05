# Mark-LV → RONN phase 1

This integration keeps Mark-LV's Gemini Live audio/voice and local desktop actions, while delegating nontrivial reasoning to the existing RONN R23 Core.

## Existing RONN contract used

- `POST /api/v1/chat/complete`
- Stable `X-RONN-Client` and `X-RONN-Device` headers
- Optional `Authorization: Bearer <RONN_CORE_TOKEN>`
- `voice_session: true`
- R23 stays the planner/brain; the local PC shell keeps desktop actions local.

## Desktop configuration

Set these environment variables on the Windows PC running the Mark-LV/RONN shell:

- `RONN_CORE_URL` — deployed Render base URL, for example `https://<service>.onrender.com`
- `RONN_CORE_TOKEN` — optional; required only when Core bearer auth is enabled

No hosted model-provider API key belongs in this local bridge.

## Files

- `ronn_core.py` — small RONN Core v1 client
- `ronn_brain.py` — Mark-LV action definition that delegates substantive reasoning to R23

## Wake word boundary

The downloaded Mark-LV source currently uses openWakeWord's pretrained `hey_jarvis` model. Do not relabel that detector as `RONN`; a real RONN wake model or another local keyword detector is required first.

## Next phase

Expose the local Mark-LV action manifest to R23 and add a bounded local executor so R23 can choose PC actions while Gemini Live remains the voice layer.