# Synapsis Agent — Next Steps

> Generated: 2026-03-29
> Reflects the state of the project after the v4 session code review, bug fixes, and test suite creation.

---

## Table of Contents

1. [Current State Summary](#1-current-state-summary)
2. [Known Remaining Issues](#2-known-remaining-issues)
3. [Roadmap — Phase 5 and Phase 6](#3-roadmap--phase-5-and-phase-6)
4. [Testing Gaps](#4-testing-gaps)
5. [Architecture Improvements](#5-architecture-improvements)
6. [Frontend Polish](#6-frontend-polish)
7. [Developer Experience](#7-developer-experience)
8. [Security Considerations](#8-security-considerations)
9. [Quick Wins](#9-quick-wins)

---

## 1. Current State Summary

The v4 session brought the codebase from a working-but-fragile prototype to a stable, well-tested foundation. The following work was completed:

### Bugs Fixed (Critical)
- **SQL parameter ordering** in `synapsis/workflow_ws.py` — incorrect positional arguments caused silent data corruption on workflow saves.
- **Race condition** in `synapsis/session_manager.py` — concurrent session lookups could resolve to the wrong session during rapid re-connects.
- **FTS5 index leak** in `synapsis/tools/memory.py` — the full-text search index was not cleaned up when memories were deleted, causing the index to drift from the table.
- **`entrypoint.sh` permissions** — the script was committed without execute bit, causing Docker container startup failures.

### Bugs Fixed (High Priority)
- `aiosqlite` connection timeout configuration
- Workflow step error handling (steps now propagate failure correctly rather than silently swallowing exceptions)
- Agent validation on creation (server-side guards against invalid tool names and missing required fields)
- Audit log rotation to prevent unbounded file growth
- Four additional high-severity issues identified during the code review

### Features Added
- `StepConfigurator.tsx` — the final missing roadmap item; provides per-step orchestrator configuration in the workflow creation UI (subagent selection, extra instructions, max turns)
- `ErrorBoundary` component — catches uncaught React render errors and shows a user-friendly fallback instead of a blank page

### Type Safety
- Removed all `as any` type casts from the frontend; proper types are now enforced throughout the service and store layers

### Test Suite
- **114 backend tests** across `test_database.py`, `test_agents_route.py`, `test_memory_tools.py`, `test_safety.py`, `test_hooks.py`, `test_workflow.py`, `test_constants.py`
- **67 frontend tests** covering Zustand stores, service layer, `useApi` hook, `ErrorBoundary`, and `StepConfigurator`
- **181 tests total**

### Roadmap Completion
All 12 items from the previous session's `NEXT_SESSION_PROMPT.md` are done. The app now has:
- 6-page React SPA (Dashboard, Chat, Agents, Workflows, Files, Settings)
- 5 built-in specialist subagents plus dynamic custom agent creation persisted in SQLite
- Sequential workflow pipelines over WebSocket with orchestrator-as-step support
- Persistent memory (SQLite + FTS5), session resumption, safety hooks, audit logging
- Mock data graceful degradation, AWS deployment (CloudFormation + Lambda + EC2 ASG)
- PR #2 open on GitHub

---

## 2. Known Remaining Issues

These were identified during the code review but deliberately deferred. They are grouped by severity.

### 2.1 Medium Severity

| # | File | Issue | Impact |
|---|------|-------|--------|
| M1 | `synapsis/tools/computer_macos.py` | No subprocess kill on timeout — a hung `screencapture` or `cliclick` call will block the event loop indefinitely | Computer-use tasks can freeze the entire backend |
| M2 | `synapsis/workflow_ws.py` | `step_configs` NULL handling is fragile — a malformed JSON value in the column causes an unhandled exception rather than a graceful fallback to defaults | Workflow execution fails with an opaque error for any workflow that has been manually edited in the DB |
| M3 | `frontend/src/hooks/useApi.ts` | `useApi` fetcher dependency changes are not detected correctly — the hook closes over the initial fetcher reference, creating a stale closure risk when the caller passes an inline function | Stale data in components that change their fetch parameters after mount |
| M4 | `frontend/src/pages/Chat.tsx` | `__chatInputSetText` is assigned directly onto `window` — this is a global side-channel between components that bypasses React's data flow | Fragile coupling; breaks in strict mode and is invisible to React DevTools |
| M5 | `synapsis/hooks/` | AUP (Acceptable Use Policy) error detection uses hardcoded string matching against Anthropic error messages | Any wording change in the Anthropic API response breaks the detection silently |
| M6 | `synapsis/routes/agents.py` | No validation of agent tool names against the SDK's allowed tools list — invalid tool names are stored and only fail at runtime when the agent is invoked | Custom agents with invalid tools appear to save successfully but fail on first use |

### 2.2 Low Severity / Polish

| # | File | Issue | Impact |
|---|------|-------|--------|
| L1 | `frontend/src/components/common/CommandPalette.tsx` | `setTimeout` in `useEffect` without storing the return value — the timer cannot be cancelled on unmount | Minor memory leak; benign in practice but violates React cleanup contract |
| L2 | `synapsis/` (all service callers) | No retry logic — any network timeout or transient API error fails immediately | Reduced resilience on flaky connections |
| L3 | `frontend/src/hooks/useWebSocket.ts` | WebSocket reconnection does not wait for a session-switch acknowledgement from the server — messages for the previous session can briefly appear in the new session's view | Cosmetic flicker during reconnection |
| L4 | All list pages | No pagination for sessions, memories, or files — lists are fetched in full and rendered without virtual scrolling | Performance degrades with large datasets |
| L5 | All data-fetching pages | No loading skeleton components — pages flash blank content while data loads | Poor perceived performance |
| L6 | Frontend forms | No client-side input validation for file uploads, workflow creation, or agent creation — only the backend validates | Unnecessary round-trips; delayed error feedback |

---

## 3. Roadmap — Phase 5 and Phase 6

Phases 1–4 are complete. The following phases are defined in `docs/ROADMAP.md` and have not yet been started.

### Phase 5: Advanced Features

---

#### 5.1 Workflow Templates
**Priority: 🟡 Medium | Effort: Small (2–3 hours)**

Pre-built pipeline templates that users can instantiate without configuring steps from scratch.

**What to build:**
- `synapsis/routes/workflow_templates.py` — `GET /api/workflow-templates` (list), `POST /api/workflow-templates/{id}/instantiate` (create a workflow from a template)
- `references/workflow_templates/` — directory of JSON template definitions

**Suggested starter templates:**

| Template | Steps |
|----------|-------|
| `data_pipeline.json` | Scrape → Clean → Analyze → Visualize |
| `research_cycle.json` | Design → Power Analysis → Data Collection Plan → Report |
| `report_generation.json` | Analyze → Write → Format → Export |

**Frontend:** Add a "From Template" button in the workflow creation modal that opens a template picker.

---

#### 5.2 Workflow Branching (Conditional Steps)
**Priority: 🟢 Low | Effort: Large (8–12 hours) | Status: Deferred**

Allow a step to evaluate a condition on its output and route to one of two downstream steps (e.g., "if significance found, run visualization; otherwise, collect more data").

This requires a DAG execution model rather than the current linear array, which is a significant architectural change. Document it as a known limitation for now. Do not implement until Phase 6 hardening work is complete.

---

#### 5.3 Parallel Workflow Steps
**Priority: 🟢 Low | Effort: Large (6–10 hours) | Status: Deferred**

Run independent steps concurrently and synchronise results before the next sequential step:

```
Step 1: data_analysis (sequential)
  ├── Step 2a: visualization_reporting (parallel)
  └── Step 2b: code_automation (parallel)
Step 3: orchestrator — synthesise (waits for 2a + 2b)
```

This requires replacing the current `for step in steps` loop in `workflow_ws.py` with an `asyncio.gather` scheduler and a more expressive step dependency model. Defer until after branching is evaluated.

---

#### 5.4 Confidence Framework
**Priority: 🟡 Medium | Effort: Small (1–2 hours)**

Adapt the GREEN / AMBER / RED confidence assessment pattern for general use in all agent outputs.

**What to build:**
- Add confidence assessment instructions to `synapsis/system_prompt.py` so the orchestrator is directed to include a confidence section in every substantive response
- `references/analysis_report_template.md` already has a confidence section — ensure the system prompt references this template explicitly

**Output format to mandate:**

```
CONFIDENCE: GREEN | AMBER | RED
REASON: <one sentence explaining the rating>
```

---

#### 5.5 Agent Skills / Reusable Prompts
**Priority: 🟡 Medium | Effort: Medium (3–5 hours)**

Let users save reusable prompt snippets ("skills") that can be attached to agents or injected into workflow steps.

**Database schema:**

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    prompt_template TEXT NOT NULL,   -- Supports {{variable}} placeholders
    variables TEXT DEFAULT '[]',     -- JSON array of variable names
    category TEXT DEFAULT 'general',
    created_at REAL,
    updated_at REAL
);
```

**New MCP tool:** `mcp__synapsis__skill_use(id, variables)` — injects a skill's rendered prompt into the current conversation turn.

**Frontend:** Add a "Skills" tab or section within the Agents page; allow skills to be attached when configuring a workflow step in `StepConfigurator.tsx`.

---

### Phase 6: Production Hardening

---

#### 6.1 Error Recovery in Pipelines
**Priority: 🔴 High | Effort: Medium (3–4 hours)**

When a workflow step fails, the entire pipeline currently aborts with no way to resume. Add a recovery mechanism:

- On step failure, send a `step_error` WebSocket event to the frontend with options: **Retry**, **Skip**, **Abort**
- Save partial results so completed steps are not re-run if the user retries from the failed step
- Add a `step_timeout_s` field to step configs, defaulting to a configurable global (suggested: 300 s)

**Files to modify:** `synapsis/workflow_ws.py`, `synapsis/models.py`, `frontend/src/pages/Workflows.tsx`

---

#### 6.2 Workflow Execution History
**Priority: 🟡 Medium | Effort: Medium (2–4 hours)**

Store a per-run record of every pipeline execution rather than only the latest status on the workflow row.

**Database schema:**

```sql
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    status TEXT,                -- running | completed | failed | partial
    started_at REAL,
    completed_at REAL,
    total_duration_s REAL,
    step_results TEXT,          -- JSON: [{step_index, agent_id, output_preview, duration_s, status}]
    prompt TEXT,
    error TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id)
);
```

**Backend:** Populate this table in `workflow_ws.py`; add `GET /api/workflows/{id}/runs` endpoint.

**Frontend:** Add a "Run History" tab on the workflow detail view.

---

#### 6.3 Rate Limiting
**Priority: 🔴 High | Effort: Small (2–3 hours)**

Essential before any multi-user or public deployment.

- **WebSocket:** Per-connection message rate limit (suggested default: 10 messages / 60 s)
- **REST API:** Per-IP rate limit using `slowapi` (a FastAPI-compatible wrapper around `limits`)
- Both limits should be configurable via environment variables (`WS_RATE_LIMIT`, `API_RATE_LIMIT`)

**Files to modify:** `synapsis/server.py`, `synapsis/websocket.py`, `synapsis/workflow_ws.py`

---

#### 6.4 Searchable Audit Log
**Priority: 🟡 Medium | Effort: Medium (3–4 hours)**

The current audit log is a flat file that cannot be queried or filtered. Migrate to SQLite and expose it through the API.

**Database schema:**

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session_id TEXT,
    event_type TEXT,       -- PreToolUse | PostToolUse | SessionStart | SessionEnd
    tool_name TEXT,
    agent_id TEXT,
    input_summary TEXT,
    output_summary TEXT,
    flagged INTEGER DEFAULT 0
);
```

**Backend:** Write audit events to this table in `synapsis/hooks/`; add `GET /api/audit` with query parameters for `session_id`, `tool_name`, `since`, `flagged`, and `limit`.

**Frontend:** Add an Audit Log view in the Settings page (filterable table, "flagged only" toggle).

---

### Phase 5 & 6 Priority Summary

| Item | Priority | Effort | Recommended Order |
|------|----------|--------|-------------------|
| 6.1 Pipeline error recovery | 🔴 High | Medium | 1 |
| 6.3 Rate limiting | 🔴 High | Small | 2 |
| 5.1 Workflow templates | 🟡 Medium | Small | 3 |
| 5.4 Confidence framework | 🟡 Medium | Small | 4 |
| 6.2 Execution history | 🟡 Medium | Medium | 5 |
| 6.4 Searchable audit log | 🟡 Medium | Medium | 6 |
| 5.5 Skills system | 🟡 Medium | Medium | 7 |
| 5.3 Parallel steps | 🟢 Low | Large | Deferred |
| 5.2 Workflow branching | 🟢 Low | Large | Deferred |

---

## 4. Testing Gaps

### 4.1 What Is Currently Tested

| Area | Files | Coverage |
|------|-------|----------|
| Database CRUD | `tests/test_database.py` | Sessions, messages, memories, workflows, agents |
| Agent REST API | `tests/test_agents_route.py` | List, create, update, delete, clone |
| Memory MCP tools | `tests/test_memory_tools.py` | Store, retrieve, search, delete |
| Safety hooks | `tests/test_safety.py` | Block/allow decisions, AUP detection |
| Audit hooks | `tests/test_hooks.py` | Pre/post tool use event emission |
| Workflow status | `tests/test_workflow.py` | Status transitions, step count |
| Constants | `tests/test_constants.py` | Allowed tools list, model identifiers |
| Zustand stores | `frontend/src/components/__tests__/` | UI store, session store, agent store |
| Service layer | `frontend/src/components/__tests__/` | All five service modules |
| `useApi` hook | `frontend/src/components/__tests__/` | Loading states, error handling, mock fallback |
| `ErrorBoundary` | `frontend/src/components/__tests__/ErrorBoundary.test.tsx` | Render error catch, fallback UI |
| `StepConfigurator` | `frontend/src/components/__tests__/StepConfigurator.test.tsx` | Orchestrator mode, subagent selection |

### 4.2 What Is NOT Tested

**Backend — High Priority Gaps:**

| Module | Gap | Suggested Approach |
|--------|-----|--------------------|
| `synapsis/websocket.py` | WebSocket message handling, session routing, stream events | Use `fastapi.testclient.TestClient` with `websocket_connect()` |
| `synapsis/workflow_ws.py` | Pipeline execution loop, per-step config application, inter-step handoff | Mock `build_agent_options()` and a fake `run()` coroutine; assert step sequence and event emissions |
| `synapsis/stream_handler.py` | Streaming token accumulation, tool-use event interleaving, completion detection | Feed synthetic SDK event sequences and assert handler state |
| `synapsis/system_prompt.py` | Dynamic agent listing, per-config section insertion, confidence framework text | Unit test the string-building functions with fixture agent dicts |
| `synapsis/agent_options.py` | `ClaudeAgentOptions` assembly, custom agent merging, tool allowlist enforcement | Mock `load_all_agents()` and assert the resulting options object |

**Frontend — High Priority Gaps:**

| Area | Gap | Suggested Approach |
|------|-----|--------------------|
| Page components | Dashboard, Chat, Agents, Workflows, Files, Settings are not render-tested | Vitest + `@testing-library/react`; assert key UI elements present, not implementation details |
| End-to-end flow | No test covers: send message → receive streamed response → verify UI update | Playwright or Cypress against a local dev server with a mocked backend |

**Integration Test (Recommended):**

Add one integration test that starts the full FastAPI application with `TestClient`, creates a session, sends a message over the chat WebSocket, and asserts that a response event is received. This validates the entire backend stack end-to-end without requiring a real Anthropic API key (use `ANTHROPIC_API_KEY=test` with a mock SDK shim).

---

## 5. Architecture Improvements

These are not bugs — the current design works — but each item below will become a bottleneck or operational problem as the deployment scales.

### 5.1 Replace In-Memory Session Dict with Redis
**Priority: 🔴 High (for multi-instance deployments) | Effort: Medium (3–5 hours)**

`session_manager.py` stores active sessions in a Python `dict`. This means all WebSocket connections must be handled by the same process. In the current single-EC2 deployment this works, but it blocks horizontal scaling.

**Recommendation:** Replace the dict with a Redis hash using `aioredis`. Session metadata is stored in Redis; the SDK session object (which cannot be serialised) lives in-process but is re-created on cache miss using the SDK's resumption API.

### 5.2 Add WebSocket Authentication
**Priority: 🔴 High | Effort: Small (1–2 hours)**

The WebSocket endpoints at `/ws/chat` and `/ws/workflow` are currently unauthenticated. Any client that can reach the server can open a session.

**Recommendation:** Accept a short-lived token (issued by a `POST /api/auth/token` endpoint) as a query parameter on the WebSocket upgrade request. Validate the token in the WebSocket handshake handler before the connection is established.

### 5.3 CORS Configuration for Production
**Priority: 🔴 High | Effort: Trivial (30 minutes)**

The FastAPI app currently runs with `allow_origins=["*"]`. This must be restricted before any public deployment.

**Recommendation:** Read the allowed origins from an environment variable (`CORS_ORIGINS`, comma-separated). Default to `["http://localhost:5173"]` for local development.

### 5.4 PostgreSQL Migration Path
**Priority: 🟡 Medium | Effort: Large (5–8 hours)**

SQLite is appropriate for single-user local deployments. For multi-user AWS deployments with concurrent writes from multiple EC2 instances, it becomes a bottleneck (WAL mode helps but does not eliminate write serialisation).

**Recommendation:** Audit all raw SQL in `synapsis/database.py` for SQLite-specific syntax (particularly FTS5, `REAL` timestamps, and `WITHOUT ROWID` tables). Document a migration path to PostgreSQL using `asyncpg` as the driver. The FTS5 search would need to be replaced with `pg_trgm` or a dedicated search service.

### 5.5 Subagent Health Checks
**Priority: 🟡 Medium | Effort: Small (1–2 hours)**

There is no way to know if a particular subagent is degraded (e.g., a tool dependency is missing on the host) without sending it a real task.

**Recommendation:** Add a `GET /api/agents/{id}/health` endpoint that sends a minimal no-op prompt to the subagent and returns `{"status": "ok", "latency_ms": ...}`. Surface this in the Agents page UI.

### 5.6 Observability
**Priority: 🟡 Medium | Effort: Medium (3–5 hours)**

There is currently no structured metrics or tracing. Log lines exist but are not queryable.

**Recommendation:** Add OpenTelemetry instrumentation to the FastAPI app. Export traces to an OTLP-compatible backend (Jaeger locally, AWS X-Ray in production via the ADOT collector). At minimum, create spans for: WebSocket message received, agent run started/completed, workflow step started/completed, tool call pre/post.

### 5.7 Message Queue for Workflow Step Handoffs
**Priority: 🟢 Low | Effort: Large (6–10 hours)**

Workflow steps currently hand off by passing a string variable in-memory within a single async function. If the backend process restarts mid-workflow, the entire run is lost.

**Recommendation (future):** Use a lightweight task queue (Celery with Redis broker, or AWS SQS) to persist step inputs/outputs. Each step is a task that can be retried independently. This also enables parallel steps (Phase 5.3) without requiring them to share a Python event loop.

---

## 6. Frontend Polish

### 6.1 Loading Skeletons
**Priority: 🟡 Medium | Effort: Small (2–3 hours)**

All six pages currently show a blank content area while data is fetching. Replace the empty state with Tailwind-styled skeleton placeholder blocks that match the shape of the real content.

### 6.2 Pagination and Virtual Scrolling
**Priority: 🟡 Medium | Effort: Medium (2–4 hours)**

Sessions list, memories list, and files list all fetch the full dataset. As usage grows these will become slow.

- Add `?page=&limit=` query parameters to `GET /api/sessions`, `GET /api/memories`, and `GET /api/files`
- Use `@tanstack/react-virtual` or `react-window` for the rendered lists on the frontend

### 6.3 Client-Side Input Validation
**Priority: 🟡 Medium | Effort: Small (2–3 hours)**

Workflow creation, agent creation, and file upload forms only validate on the backend. The frontend should mirror the same constraints to give immediate feedback without a network round-trip.

Key rules to enforce client-side:
- Agent name: 2–64 characters, alphanumeric + underscores
- Agent tools: must be from the published allowed tools list
- Workflow steps: at least one step required
- File upload: enforce the same extension/size block list that the backend uses

### 6.4 Keyboard Shortcuts Reference Panel
**Priority: 🟢 Low | Effort: Trivial (1 hour)**

The Command Palette (Cmd+K) is discoverable but the full list of keyboard shortcuts is not documented anywhere in the UI. Add a `?` button in the TopBar that opens a modal listing all shortcuts.

### 6.5 Workflow Execution History Page
**Priority: 🟡 Medium | Effort: Small (1–2 hours, after 6.2 backend work)**

Once the `workflow_runs` table exists (Phase 6.2), add a "Run History" drawer or tab to the Workflow detail view. Show: run timestamp, duration, step-by-step status, and a preview of each step's output.

### 6.6 Agent Usage Analytics
**Priority: 🟢 Low | Effort: Small (1–2 hours)**

Add a simple query to the Dashboard that aggregates how many times each subagent has been invoked (derivable from the audit log or a new `agent_invocations` counter column). Render this as a bar chart alongside the existing activity chart.

### 6.7 File Preview in Files Page
**Priority: 🟢 Low | Effort: Medium (2–3 hours)**

The Files page lists files but cannot show their contents. Add inline preview support:
- CSV: render as a scrollable `<table>` (first 100 rows)
- Markdown: render via `react-markdown`
- Images (PNG, JPEG, GIF): render as `<img>`
- All other types: show a hex dump or "preview not available"

### 6.8 Drag-and-Drop Step Reordering
**Priority: 🟢 Low | Effort: Small (1–2 hours)**

Workflow steps can currently only be reordered by deleting and re-adding them. Use `@dnd-kit/sortable` (already a common pattern with Tailwind + React) to add drag handles to the step list in the workflow editor.

### 6.9 Mobile Responsiveness
**Priority: 🟢 Low | Effort: Medium (3–5 hours)**

The layout is designed for desktop. The sidebar and TopBar collapse poorly on narrow viewports. At minimum:
- Make the sidebar a slide-over drawer on screens narrower than `md` breakpoint
- Ensure the Workflows React Flow canvas is touch-scrollable
- Test the Chat page on 375 px width (iPhone SE)

---

## 7. Developer Experience

### 7.1 Pre-Commit Hooks
**Priority: 🟡 Medium | Effort: Trivial (30–60 minutes)**

Add a `.pre-commit-config.yaml` that runs the following on every commit:
- `black` — Python formatting
- `ruff` — Python linting
- `eslint` — TypeScript/React linting (using the existing `eslint.config.js`)
- `pyright` / `tsc --noEmit` — type checking (fail fast rather than at CI time)

### 7.2 CI Pipeline
**Priority: 🔴 High | Effort: Small (1–2 hours)**

There is no automated check on pull requests. Add a GitHub Actions workflow at `.github/workflows/ci.yml`:

```
Steps:
1. Python: pip install, pytest (backend 114 tests)
2. Frontend: npm ci, tsc --noEmit, vitest run (frontend 67 tests)
3. (Optional) Docker build smoke test
```

This prevents regressions from being merged silently.

### 7.3 Test Coverage Reporting
**Priority: 🟡 Medium | Effort: Trivial (30 minutes)**

- Backend: add `pytest-cov` and `--cov=synapsis --cov-report=xml` to `pytest.ini`
- Frontend: add `coverage: { reporter: ["text", "lcov"] }` to `vite.config.ts`
- Upload both reports to Codecov or display inline in the CI summary

### 7.4 Storybook for Component Development
**Priority: 🟢 Low | Effort: Medium (2–4 hours initial setup)**

The component library has grown to 30+ components. Storybook would allow:
- Isolated development of UI components without running the full backend
- Visual regression testing with Chromatic
- Living documentation for component props

Highest-value stories to write first: `AgentCard`, `StepConfigurator`, `ErrorBoundary`, `CommandPalette`.

### 7.5 Expanded API Documentation
**Priority: 🟢 Low | Effort: Small (1–2 hours)**

FastAPI's built-in `/docs` (Swagger UI) is available but the schemas lack descriptions. Add `description=` strings to all Pydantic models and `summary=` / `description=` to all route decorators. This makes `docs/API_REFERENCE.md` auto-derivable from the code rather than maintained separately.

---

## 8. Security Considerations

### 8.1 Authentication and Authorization Layer
**Priority: 🔴 High | Effort: Medium (4–6 hours)**

The application has no authentication. Any user who can reach the server can read all sessions, memories, files, and audit logs belonging to any other user.

**Recommended approach:**
- Add a `users` table and a `POST /api/auth/login` + `POST /api/auth/token` endpoint
- Use JWT bearer tokens (short-lived access + long-lived refresh)
- Add a FastAPI dependency `get_current_user` and apply it to all non-public routes
- Scope all DB queries to `WHERE owner_id = :user_id`

### 8.2 Input Sanitization Middleware
**Priority: 🔴 High | Effort: Small (1–2 hours)**

Add a FastAPI middleware layer that:
- Strips null bytes from all string fields (SQLite injection vector)
- Enforces maximum field lengths before hitting Pydantic validation
- Rejects requests with `Content-Type` that doesn't match the declared body type

### 8.3 Request Size Limits
**Priority: 🔴 High | Effort: Trivial (30 minutes)**

FastAPI does not enforce a request body size limit by default. A malicious client can POST an arbitrarily large body.

Add to `synapsis/server.py`:
```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
app.add_middleware(RequestSizeLimitMiddleware, max_content_size=10 * 1024 * 1024)  # 10 MB
```

Also set `client_max_body_size` in the nginx/ALB config for the AWS deployment.

### 8.4 File Upload Security Hardening
**Priority: 🟡 Medium | Effort: Small (1–2 hours)**

The current file upload logic blocks `../` path traversal and dotfiles. Add:
- Explicit allow-list of permitted MIME types (do not rely solely on file extension)
- Maximum file size enforcement server-side (currently only blocked at the infrastructure layer)
- Virus scan hook (ClamAV or AWS GuardDuty Malware Protection) for production deployments

### 8.5 HTTPS Enforcement
**Priority: 🔴 High | Effort: Trivial (30 minutes)**

For any deployment that is not `localhost`:
- Redirect all `http://` requests to `https://` using `HTTPSRedirectMiddleware`
- Set `Strict-Transport-Security: max-age=31536000; includeSubDomains` response header
- Ensure the CloudFormation template provisions an ACM certificate and configures HTTPS on the ALB

### 8.6 Session Expiry and Cleanup
**Priority: 🟡 Medium | Effort: Small (1–2 hours)**

Sessions are never expired. The `sessions` table grows indefinitely, and old SDK session objects stay in memory.

**Recommendation:** Add a background task (APScheduler or a FastAPI startup task using `asyncio`) that runs hourly and:
- Marks sessions as expired if `last_active` is older than a configurable TTL (default: 7 days)
- Removes the corresponding in-memory entry from `session_manager`
- Optionally archives the session's messages to a cold-storage table

### 8.7 `bypassPermissions` Mode Review
**Priority: 🔴 High | Effort: Small (review only, 1 hour)**

The `bypassPermissions` flag in the SDK causes the agent to skip the normal tool-use confirmation flow. Review every code path where this flag is set and ensure it is never enabled in multi-user deployments. Add an environment variable guard (`ALLOW_BYPASS_PERMISSIONS=false` by default) and document the implications clearly in `CLAUDE.md` and the deployment guide.

---

## 9. Quick Wins

The following items can each be completed in under two hours and have a high impact-to-effort ratio. These are good candidates for the start of the next session.

| # | Item | Effort | Impact | Section |
|---|------|--------|--------|---------|
| Q1 | Add GitHub Actions CI workflow (pytest + vitest) | ~1 hour | Prevents regressions from being merged undetected | 7.2 |
| Q2 | Add CORS origin restriction via environment variable | ~30 min | Required for any non-localhost deployment | 5.3 |
| Q3 | Add request body size limit middleware | ~30 min | Closes a trivial denial-of-service vector | 8.3 |
| Q4 | Fix `CommandPalette` `setTimeout` ref leak (store and clear ref on unmount) | ~15 min | Correct React cleanup contract; no user-visible impact | 2.2 / L1 |
| Q5 | Fix `step_configs` NULL/JSON parse error handling in `workflow_ws.py` | ~30 min | Prevents opaque crashes for any DB-edited workflow | 2.1 / M2 |
| Q6 | Add subprocess kill on timeout in `computer_macos.py` | ~45 min | Prevents event loop hangs during computer-use tasks | 2.1 / M1 |
| Q7 | Replace `window.__chatInputSetText` with a React Context | ~1 hour | Removes a hidden global side-channel between components | 2.1 / M4 |
| Q8 | Add `pytest-cov` to `pytest.ini` and `coverage` to `vite.config.ts` | ~30 min | Gives immediate visibility into untested code paths | 7.3 |
| Q9 | Add loading skeleton components for Dashboard and Agents pages | ~1.5 hours | Eliminates the most-visible blank-flash on first load | 6.1 |
| Q10 | Add `description=` strings to all Pydantic models for Swagger docs | ~1 hour | Makes `/docs` a usable API reference without extra work | 7.5 |

---

*This document was generated at the end of the v4 session. The next session should begin by reviewing the Quick Wins table above, then the Phase 6 hardening items, as those have the highest production risk.*
