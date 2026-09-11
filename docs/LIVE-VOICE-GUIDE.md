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

Use the existing DEV workflow, `feature/innovation-platform-foundation`, account 972793825893. The development container sets `IA_VOICE_ENABLED=true`; other stages leave it disabled. Do not push main or deploy production for this feature.

Server-only settings:

- `OPENAI_API_KEY`: the DEV GitHub environment secret, installed into existing DEV SSM parameter by CI.
- `IA_VOICE_ENABLED`: false by default.
- `IA_VOICE_MODEL`: defaults to `gpt-live-1`.
- `IA_VOICE_BACKEND_MODEL`: defaults to `gpt-5.6-terra`.
- `IA_VOICE_ORIGINS`: defaults to the exact development HTTPS origin; comma-separated explicit origins for private local testing.

Model, prompt, tools and permitted provider commands are server-fixed. Browser requests carry the existing application JWT. Audio goes directly to OpenAI via WebRTC. No key is sent to the browser. The host keeps its existing FastAPI/EC2 deployment, avoiding a second voice stack.

## Connection lifecycle

`voice_sessions` is a new additive table in the existing persisted/replicated chat SQLite database. It stores owner, client request UUID, offer hash, provider ID, temporary SDP answer, state, expiry and heartbeat deadline. It does not store voice audio or captions. Completed/rejected metadata is retained seven days; unresolved records are retained for reconciliation.

One connection per user, six concurrently, twenty start attempts per user per rolling day, one hundred globally per rolling day, four attempts per user per minute. These are admission limits, not a dollar budget. Mute leaves the paid call connected. Maximum duration is ten minutes; browser heartbeats every twenty seconds renew a sixty-second lease. A server reaper checks leases every ten seconds and retries failed hangups. Lease deadlines survive restart. While the entire host is offline, its reaper cannot execute; recovery resumes cleanup.

Start IDs are idempotent for the same active offer. End before or during creation leaves a cancellation tombstone. HTTP creation is shielded from browser cancellation so provider IDs can be recorded and compensated. Known calls are closed via the provider hangup endpoint. Unknown creation outcomes retain an `uncertain` lease and block additional starts for that owner; they are never blindly retried. An operator must reconcile unknown provider IDs with provider records before resolving that lease. Do not simply delete unresolved rows.

End captures the original auth token for cleanup after logout/unmount. It stops the mic immediately, waits briefly for provider finalization, and falls back to authenticated server hangup. Heartbeat and duration expiry cover tab crashes. A failed close remains visible as unconfirmed cleanup. Live recording storage is disabled (`store:false`); this is not a promise of Zero Data Retention.

## Manual edits and acceptance

Voice uses the normal stores/router/WebSocket, without a second chat state. Source and knowledge results are data, never action authority. Runtime schemas reject unknown actions/fields. Tool call IDs are deduplicated within a voice connection. After a manual selection/filter/draft change, pending commands are invalidated. A history fetch may not overwrite a more recent manual chat selection. Busy chats, drafts and attachments block voice submission. A disconnected socket throws before clearing a draft or attachments. Query acceptance is based on a server run event, not an optimistic message bubble. A lost receipt is reported as uncertain and is not automatically retried. Closing voice or pausing actions cannot undo an already sent query.

## Verification

Backend: `python -m pytest tests/test_voice.py tests/test_auth_scoping.py tests/test_scope.py tests/test_prms_dashboard.py tests/test_export_dependencies.py`.
Frontend: `npm test -- src/lib/voice/__tests__`, `npm run build`, and the existing frontend suite. The baseline has four agent-service error-text expectation failures; compare against the pre-change branch.
Hosted checks: authenticated/unauthenticated voice endpoints, forbidden origin and unknown source; actual panel on desktop/mobile; synthetic transport/action/lifecycle checks; a short real audio/semantic-action test only with paid API test authorization. Human microphone/accent/interruption quality is a separate usability check.

Official protocol references checked 2026-09-11: https://developers.openai.com/api/docs/guides/live, https://developers.openai.com/api/docs/guides/voice-webrtc?api=live, https://developers.openai.com/api/docs/guides/live-delegation, https://developers.openai.com/api/docs/guides/live-conversations.
