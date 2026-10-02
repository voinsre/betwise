# Gemini API pause — 2026-10-02

Google/Gemini calls are disabled by default. A configured GEMINI_API_KEY does not enable them. No credentials or provider settings were changed.

The chat route returns an explicit paused response without constructing the Gemini service. The shared service checks the gate at construction, chat entry and before every provider send, including function-call rounds. The standalone backend/scripts/test_chat.py exits before creating a database engine or sending messages. No scheduler invokes Gemini outside that shared service in the audited source. Football data and prediction services are outside this Gemini pause.

Deployment: this repository is voinsre/betwise, with railway.toml and the root Dockerfile/start.sh defining its Railway backend. It is distinct from voinsre/wizer-bet-v2 and the wizer.bet Vercel site. After approval, deploy this revision to the existing Betwise Railway backend, if it still exists; its current status must be verified first. Do not recreate stopped services or deploy this change to Wizer.

## Resume

Only after approval, set GEMINI_API_ENABLED=true in the environment of the intended app/job and restart or redeploy it. Leave it unset or false to keep the pause. This is a server-only flag, not a NEXT_PUBLIC variable. Resuming may incur Google charges and should follow a model/key check. Old running deployments and already in-flight requests are not changed by local source edits.

## Verification

Offline regression checks stub Google, database and network dependencies. They cover default pause, configured-key pause, explicit enablement, route behavior, direct service/script calls, and no retries or fallback work while paused. No paid API calls are needed.
