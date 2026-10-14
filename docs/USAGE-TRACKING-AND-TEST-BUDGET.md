# Usage tracking and MVP test budget

Two features for the one-month MVP test (SYN-2305, SYN-2306). Both are
app-side only: no new infrastructure, no third-party service, no CSP change.

## 1. First-party, cookieless usage tracking (SYN-2305)

**What is collected.** The SPA (`frontend/src/lib/telemetry.ts`) records:

| Event | When | Stored fields |
|---|---|---|
| `page_view` | each route opened | path only (query strings and fragments dropped) |
| `click` | click on an element tagged `data-track` (preferred) or `data-testid`; other buttons/links as `untagged:<tag>` | the tag label, never element text |
| `heartbeat` | every 30 s while the tab is visible and the user interacted in the last 5 min | engaged seconds (max 120 per beat) |
| `visit_end` | page hidden/closed | - |

Every row also carries the signed-in account id, role, invited-test cohort,
the active chat id (joins to the question ledger `usage_events`), the
environment label and a per-page-load visit id held **in memory only**.
No cookies, no local/session storage, no IP address, user agent, coordinates
or free text.

**Transport.** Same origin only (`connect-src 'self'` already allows it):
timer flushes every 10 s use `fetch(..., {keepalive: true})` with the normal
bearer header; when the page is hidden or closed the queue goes out with
`navigator.sendBeacon`, which cannot set headers, so the app token is sent in
the JSON body and verified exactly like the header.

**Schema.** Table `ui_events` in the chat database, modelled on the
open-source [Umami](https://umami.is) `website_event` model (`event_id`,
`visit_id`, `created_at`→`ts`, `url_path`, `event_type`, `event_name`,
`event_data`→`value`) so the log can be imported into a self-hosted Umami
later if dashboards are wanted. Mapping in `synapsis/database/telemetry.py`.

**Endpoints.**

| Endpoint | Who | Purpose |
|---|---|---|
| `POST /api/telemetry` | any signed-in user | batch of ≤ 50 events, 64 KB max, 240 events/min/user; `204` |
| `GET /api/admin/engagement?days=N` | admin | totals, per day, per account (`user_key` pseudonym), per cohort, top tagged controls |
| `GET /api/admin/engagement.csv?days=N` | admin | one row per day × account: questions, cost, visits, page views, clicks, session minutes |

Session length = per visit, the wall time between its first and last event,
but at least the engaged seconds reported by heartbeats. Accounts are shown as
`user_key` (keyed hash of the account id), with role and cohort.

Settings → Usage and cost (admins) shows the engagement section and its CSV.

**Tagging new controls.** Add `data-track="area.action"` (e.g.
`chat.send`, `export.pdf`) to any element whose clicks should be counted by
name.

## 2. MVP test budget and caps (SYN-2306)

| Variable | Default | Meaning |
|---|---|---|
| `IA_TEST_BUDGET_USD` | `5000` | model spend allowed in the test window (SDK list prices); `0` = off |
| `IA_TEST_START` | empty | ISO date/time (UTC). Empty = the first time the environment runs with this feature, persisted in the chat DB (so restarts do not move it) |
| `IA_TEST_END` | empty | ISO date/time (UTC); a bare date includes that whole day. Empty = start + `IA_TEST_DAYS` |
| `IA_TEST_DAYS` | `30` | window length when `IA_TEST_END` is empty |
| `IA_SESSION_BUDGET_USD` | `3` | per-chat spend cap for non-admins; `0` = off |
| `IA_BUDGET_ALERT_THRESHOLDS` | `0.5,0.75,0.9` | fractions (or percentages) that each log one alert line |
| `IA_VOICE_USD_PER_MINUTE` | `0.10` | conversion used to count voice minutes against the budget |
| `IA_TELEMETRY_ENABLED` | `true` | kill-switch for `POST /api/telemetry` (client stops on `404`) |

Existing caps stay as they were: `IA_MAX_BUDGET_USD_RESEARCHER` (per question,
1.00), `IA_MAX_BUDGET_USD_ADMIN` (5.00), `IA_DAILY_USER_BUDGET_USD` (5.00).
`deploy.yml` passes `IA_TEST_BUDGET_USD`, `IA_TEST_START`, `IA_TEST_END`,
`IA_SESSION_BUDGET_USD`, `IA_BUDGET_ALERT_THRESHOLDS`,
`IA_MAX_BUDGET_USD_RESEARCHER`, `IA_DAILY_USER_BUDGET_USD` and
`IA_TELEMETRY_ENABLED` through from GitHub environment variables; unset
variables fall back to the defaults above (`IA_TEST_DAYS` and
`IA_VOICE_USD_PER_MINUTE` use their defaults).

**Who is stopped.** Before every question (chat socket, retry and
`POST /api/query`) the runtime checks, cheapest refusal first:

1. global test budget used up → code `test_budget`; window closed or not yet
   open → code `test_ended`;
2. this chat's spend ≥ `IA_SESSION_BUDGET_USD` → code `session_limit`
   (the user can start a new chat);
3. the existing daily cap → code `daily_limit`.

Each refusal is a normal error frame with a plain-English message
(`synapsis/constants.py`); the socket stays open and earlier chats stay
readable. **Admins are never stopped**, but their spend counts toward the
global budget. All checks fail open on a database error (logged): they are
cost guards, not security boundaries. A question already running can finish,
so the budget can be overrun by at most one question's ceiling per active
chat.

**Alert signal.** When cumulative spend in the window crosses a threshold,
the app writes one log line per threshold per window (recorded in the
`budget_state` table so restarts do not repeat it):

```
IA_TEST_BUDGET_THRESHOLD pct=75 spent=3751.20 budget=5000.00 window=2026-10-15..2026-11-14 env=prod
IA_TEST_BUDGET_EXHAUSTED pct=100 spent=5000.40 budget=5000.00 window=2026-10-15..2026-11-14 env=prod
```

The same information is in `GET /api/admin/usage` → `test_budget`:

```json
{"enabled": true, "budget_usd": 5000.0, "spent_usd": 3751.2, "remaining_usd": 1248.8,
 "pct": 75.02, "state": "open",
 "window": {"start": "...", "end": "...", "start_source": "first_run", "end_source": "start+30d", "days_left": 12.5},
 "thresholds": [50, 75, 90], "alerts": [{"pct": 50, "crossed_at": "..."}, {"pct": 75, "crossed_at": "..."}],
 "session_budget_usd": 3.0, "voice": {"minutes": 0.0, "usd": 0.0, "usd_per_minute": 0.1}}
```

`state` is `open`, `exhausted`, `ended`, `not_started` or `disabled`.
Delivering the alert to people (e-mail/chat) is done by an external monitor
that polls this endpoint or watches the log group for the tag; the app itself
sends nothing outbound.
