# Live voice guide — development integration

The persistent **Voice guide** button opens an optional conversation alongside the app. It survives route/chat navigation. Users can speak or type to the guide, inspect captions and source excerpts, mute, pause actions, minimize or end the call.

## Implemented capabilities

| User goal | Action and completion |
| --- | --- |
| Explain purpose / workflow | Shipped product brief and bounded knowledge excerpts; no mutation |
| Explain formulas / methods | Search the actual deployed dashboard SQL, scope code, PRMS guide and citation helper; source file, lines and hash returned |
| Describe available data | Read-only configured PRMS snapshot table/phase catalog; no invented snapshot date |
| List/open/cycle chats | Existing identity-scoped sessions/history APIs and shared native chat commands; server selection receipt |
| Create chat | Shared native New Chat command and server-created ID |
| Read/summarize answers | Current chat's recent user/assistant messages, bounded with explicit truncation and running state |
| Send analysis or verification question | Shared native Send command, current scope and specialist; require exact selected chat ID and server run receipt |
| Navigate | Dashboard, Chat, Agents, Settings |

The guide does not execute arbitrary source code or expose a filesystem browser. It does not delete chats, change permissions, edit PRMS, automatically export, or independently certify accuracy. Verification uses the existing analytics chat and its usual execution boundary. A submitted analytics query continues if voice ends; use Chat's Stop button to cancel it. Existing voice dictation remains available separately.

The selected code files are an explicit application-owned allowlist, not the entire repository. They are read from the deployed build. No environment files, credentials, private chat database, deployment files or arbitrary paths are retrievable through the knowledge endpoint. Product terminology lives in `references/voice_product_guide.md`; update this brief with product changes. Do not use historical example counts as live facts.

## Configuration and deployment

DEV deploys from `feature/innovation-platform-foundation` via `deploy.yml` (account 972793825893), which sets `IA_VOICE_ENABLED=true` only for the dev stage. Staging and production are deployed by `release-promote` + `.github/scripts/release-host.py`, which enables voice on every release target and reads the key from that stage's SSM parameter `/cgiar-ia-<stage>/openai-api-key`. Do not push main directly; promotions go through the release lane.

Server-only settings:

- `OPENAI_API_KEY`: per-stage GitHub environment secret, installed into that stage's SSM parameter by CI. A non-empty value is not proof of validity (see the provider probe below).
- `IA_VOICE_ENABLED`: false by default.
- `IA_VOICE_MODEL`: defaults to `gpt-live-1`.
- `IA_VOICE_BACKEND_MODEL`: defaults to `gpt-5.6-terra`.
- `IA_VOICE_ORIGINS`: defaults to the exact development HTTPS origin; comma-separated explicit origins for private local testing.

Model, prompt, tools and permitted provider commands are server-fixed. Browser requests carry the existing application JWT. Audio goes directly to OpenAI via WebRTC. No key is sent to the browser. The host keeps its existing FastAPI/EC2 deployment, avoiding a second voice stack.

### Provider health (`provider_ok`)

`GET /api/voice/status` returns `enabled`, `configured` (key present), `provider_ok` and `max_seconds`. `provider_ok` comes from a server-side probe `GET https://api.openai.com/v1/models/{IA_VOICE_MODEL}` with the configured key (`synapsis/voice/health.py`): 5 s timeout, cached 10 minutes (failures cached too), one probe in flight at a time, never raises, `null` when no key is configured. A failed probe logs `voice_provider_probe_failed model=… provider_status=…` (never the key). A 401/403 from session creation invalidates the cache so the next status call re-probes.

The panel hides the voice button only when `enabled` is false. When `configured` is false or `provider_ok` is false it renders a disabled button titled "Voice is temporarily unavailable" and re-checks the status every 60 s until the provider recovers. The hosted release smoke (`.github/scripts/release-smoke.py::check_voice_status`) fails a promotion whose `provider_ok` is not `true` while voice is enabled — this is what would have caught the dead production key on 2026-09-14.

Administrators (JWT role `admin`) additionally receive `usage_today: {sessions, seconds}` — the rolling 24 h total of closed sessions, using the provider-reported seconds when the browser relayed them and the server-observed lease duration otherwise.

## Connection lifecycle

`voice_sessions` is an additive table in the existing persisted/replicated chat SQLite database. It stores owner, client request UUID, offer hash, provider ID, temporary SDP answer, state, expiry and heartbeat deadline, plus (added 2026-09-14 by a guarded `PRAGMA table_info`/`ALTER TABLE ADD COLUMN` migration in `sessions.init()`) `closed`, `usage_seconds` (server-observed created→closed), `provider_seconds` (the provider's `usage.seconds` relayed by the browser on `session.closed`, stored as a client claim), `provider_status` (HTTP status of the confirming hangup), `attempts` and `attempted` (reaper retry bookkeeping). It does not store voice audio or captions. Closed/rejected metadata is retained seven days, `closed_unconfirmed` rows thirty days; unresolved records are retained for reconciliation.

One connection per user, six concurrently, twenty start attempts per user per rolling day, one hundred globally per rolling day, four attempts per user per minute. These are admission limits, not a dollar budget; the refusal messages are environment-neutral. Mute leaves the paid call connected. Maximum duration is `max_seconds` (600 s) — the panel and the in-call limit notice derive their wording from the server value, not a hard-coded figure. Browser heartbeats every twenty seconds renew a sixty-second lease with the current app token. A server reaper checks leases every ten seconds. Lease deadlines survive restart. While the entire host is offline, its reaper cannot execute; recovery resumes cleanup.

Start IDs are idempotent for the same active offer. End before or during creation leaves a cancellation tombstone. HTTP creation is shielded from browser cancellation so provider IDs can be recorded and compensated. Known calls are closed via the provider hangup endpoint. A provider rejection is reported as `503`/`502` with the provider HTTP status and a safe hint (e.g. "HTTP 401 — check the API key"), never the provider body, and logged as `voice_create_rejected owner=… request_id=… provider_status=…`.

Unknown creation outcomes (provider timeout, 5xx, incomplete answer) retain an `uncertain` lease that blocks additional starts for that owner; they are never blindly retried. Since 2026-09-14 such leases no longer count against the shared six-connection pool (only `creating`/`active` leases and `closing` leases with a known provider ID do), and the reaper resolves them within bounds (`sessions._resolve_unconfirmed`): with a known provider ID it retries the hangup with backoff (60 s doubling to 600 s) up to eight attempts or 24 h; without one — the SDP answer never reached the browser, so no media session could have connected — it waits the maximum call length plus one heartbeat window. Either way the row then becomes `closed_unconfirmed` and a `voice_lease_unconfirmed owner=… request_id=… provider_id=… attempts=… reason=…` warning names what an operator needs to reconcile against provider records. Do not simply delete unresolved rows.

The browser retries a start at most once, and only when the `POST /api/voice/sessions` request produced no HTTP response at all (network failure): it replays the same request ID and offer, which the server treats idempotently (unseen → created; already active → same answer; still in flight → 409 and the client stops). Any HTTP answer, including 5xx, is final.

End reads the current auth token for cleanup (falling back to the start-time token after logout/unload). It stops the mic immediately, waits briefly for provider finalization, and falls back to authenticated server hangup, relaying the provider's final usage seconds. Heartbeat and duration expiry cover tab crashes. A failed close remains visible as unconfirmed cleanup. Every confirmed close emits one CloudWatch-friendly line `voice_session_closed owner=… request_id=… seconds=… provider_seconds=… provider_status=…` (with `voice_session_started` and `voice_hangup_unconfirmed` as companions) in the container's `/cgiar-ia/<stage>` log group; no AWS resources were added. Live recording storage is disabled (`store:false`); this is not a promise of Zero Data Retention.

## Manual edits and acceptance

Voice uses the normal stores/router/WebSocket, without a second chat state. Source and knowledge results are data, never action authority. Runtime schemas reject unknown actions/fields. Tool call IDs are deduplicated within a voice connection. After a manual selection/filter/draft change, pending commands are invalidated. A history fetch may not overwrite a more recent manual chat selection. Busy chats, drafts and attachments block voice submission. A disconnected socket throws before clearing a draft or attachments. Query acceptance is based on a server run event, not an optimistic message bubble. A lost receipt is reported as uncertain and is not automatically retried. Closing voice or pausing actions cannot undo an already sent query.

## Verification

Backend: `python -m pytest tests/test_voice.py tests/test_voice_health.py tests/test_release_smoke.py tests/test_auth_scoping.py tests/test_scope.py tests/test_prms_dashboard.py tests/test_export_dependencies.py` (provider probe caching/failure, provider-status error detail, usage recording and migration, uncertain-lease resolution and capacity, admin-only usage, smoke gate).
Frontend: `npm test -- src/lib/voice src/components/voice` (protocol, actions, network-only start retry, disabled/unavailable panel state and recovery re-check), `npm run build`, and the existing frontend suite.
Hosted checks: authenticated/unauthenticated voice endpoints, forbidden origin and unknown source, `provider_ok` true on the target; actual panel on desktop/mobile; synthetic transport/action/lifecycle checks; a short real audio/semantic-action test only with paid API test authorization. Human microphone/accent/interruption quality is a separate usability check.

Official protocol references checked 2026-09-11: https://developers.openai.com/api/docs/guides/live, https://developers.openai.com/api/docs/guides/voice-webrtc?api=live, https://developers.openai.com/api/docs/guides/live-delegation, https://developers.openai.com/api/docs/guides/live-conversations.
