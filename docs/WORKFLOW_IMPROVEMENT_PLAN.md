# Workflow "Super Chat" Improvement Plan

> **Produced**: 2026-03-29
> **Repo Commit**: `90379e6` — *Fix background task notifications contaminating active streaming session*
> **Based on**: `docs/CHAT_VS_WORKFLOW_ANALYSIS.md` gap analysis

---

## Goal

Transform the Workflow system from a "fire-and-forget modal" into a **Super Chat**: long-running tasks you can launch, switch between, come back to inspect, download outputs from, and continue working from — while keeping Chat and Workflow histories fully separated.

---

## Phase 1 — Safety & Feature Parity (Quick Wins)

**Scope**: Add missing safety checks and streaming features to `_stream_step()`.
**Files changed**: 1 backend file + 1 new shared utility.
**Risk**: Low — all additive, no existing behavior changed.

### 1.1 Agent Activity Events

When the orchestrator uses the `Task` tool to delegate to a subagent, emit an `agent_activity` event so the workflow UI can show which specialist is running.

**Where**: `synapsis/services/workflow_executor.py`, inside the `ToolUseBlock` handler in `_stream_step`, after the `step_log["tool_calls_count"] += 1` line.

```python
if block.name == "Task":
    agent_name = ""
    if isinstance(block.input, dict):
        agent_name = block.input.get("agent", block.input.get("description", ""))
    await self._send({
        "type": "agent_activity",
        "agent": agent_name,
        "status": "started",
        "tool_use_id": block.id,
        "step": step_idx,
    })
```

**Frontend**: Add handling for `agent_activity` events in `usePipelineExecution.ts` to display which subagent is working within a step.

### 1.2 SystemMessage Handling

Currently `_stream_step` silently drops `SystemMessage`. Add a handler branch to capture the Claude session UUID and forward non-noise system messages.

**Where**: `synapsis/services/workflow_executor.py`, new `elif isinstance(message, SystemMessage):` branch.

- Capture `session_id` from `init` subtypes into `step_log["session_id"]`
- Skip `api_key_source` (noise)
- Forward other system messages to the frontend with `"step": step_idx`
- Add `SystemMessage` to the import from `claude_agent_sdk`

### 1.3 Context Window Exhaustion Detection

Add a `got_result` flag. If the stream ends without a `ResultMessage` and wasn't cancelled, send a `CONTEXT_WINDOW_ERROR`.

**Where**: `synapsis/services/workflow_executor.py` in `_stream_step`, after the `async for` loop exits.

### 1.4 AUP Violation Checking

Track `accumulated_text` during streaming. After `ResultMessage` and in the `except` handler, check with `is_aup_error()`.

**Where**: `synapsis/services/workflow_executor.py` — add `accumulated_text` accumulation in the text_delta handler, check after result and in exception handler.

### 1.5 Shared Error Handler (DRY)

Extract a `handle_stream_error()` utility that both Chat and Workflow use, avoiding duplicating the context-keyword detection + AUP check + enhanced messaging logic.

**New file**: `synapsis/stream_core.py`

```python
async def handle_stream_error(error, send, context_label="chat"):
    """Shared error handler: detects context-window, AUP errors, sends typed events."""
```

**Refactor**: `stream_handler.py` except block → call `handle_stream_error()`
**Use in**: `workflow_executor.py` except block → call `handle_stream_error()`

### 1.6 Connect Retry

Extract `create_client_with_retry()` from `session_manager.py` (parameterized with `max_retries`, `retry_delay`). Use in workflow's `execute_step()`. Refactor Chat's `_create_and_connect_client()` to call it internally.

**New function in**: `synapsis/session_manager.py`
**Use in**: `synapsis/services/workflow_executor.py` execute_step()

---

## Phase 2 — Workflow Persistence (Separate DB)

**Scope**: Persist run data to a dedicated SQLite database so runs are queryable, inspectable, and downloadable via API.
**Files changed**: 3 backend files + 1 new.
**Risk**: Low-Medium — new DB, additive persistence calls alongside existing JSON logs.

### 2.1 New Database: `workflow_runs.db`

Separate from `chat.db` to keep histories isolated. Located at `~/workspace/.synapsis/workflow_runs.db`.

**New file**: `synapsis/workflow_db.py` (modeled on `database.py` patterns)

**Tables**:

```sql
-- One row per pipeline execution
CREATE TABLE workflow_runs (
    id                TEXT PRIMARY KEY,     -- run_id UUID
    workflow_id       TEXT NOT NULL,
    workflow_name     TEXT,
    status            TEXT NOT NULL DEFAULT 'running',
    started_at        REAL NOT NULL,
    completed_at      REAL,
    total_duration_s  REAL,
    total_cost_usd    REAL,
    initial_prompt    TEXT,
    agent_sequence    TEXT,                 -- JSON array
    step_count        INTEGER,
    completed_steps   INTEGER DEFAULT 0,
    progress          INTEGER DEFAULT 0,
    log_filename      TEXT,                 -- path in ~/workspace/workflow_logs/
    summary           TEXT                  -- first 500 chars of final output
);

CREATE INDEX idx_workflow_runs_wf ON workflow_runs(workflow_id, started_at DESC);
CREATE INDEX idx_workflow_runs_status ON workflow_runs(status);

-- One row per step within a run
CREATE TABLE workflow_run_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    agent_id        TEXT,
    agent_name      TEXT,
    model           TEXT,
    input_prompt    TEXT,
    output_text     TEXT,
    tool_calls_count INTEGER DEFAULT 0,
    turns           INTEGER,
    estimated_cost  REAL,
    claude_session_id TEXT,
    error           TEXT,
    started_at      REAL,
    completed_at    REAL,
    duration_s      REAL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_run_steps ON workflow_run_steps(run_id, step_index);

-- Individual messages (mirrors chat's messages table pattern)
CREATE TABLE workflow_run_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    step_index  INTEGER NOT NULL,
    ts          REAL NOT NULL,
    type        TEXT NOT NULL,              -- text, thinking, tool_use, tool_result, result, system
    data        TEXT,                       -- JSON blob
    tool_use_id TEXT,
    is_error    INTEGER DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_run_msgs ON workflow_run_messages(run_id, step_index, ts);
CREATE INDEX idx_run_msgs_full ON workflow_run_messages(run_id, ts);
```

### 2.2 Persistence Calls in Executor

**File**: `synapsis/services/workflow_executor.py` — 8 insertion points (all additive):

1. After `run_log` dict is built → `INSERT INTO workflow_runs` (makes run visible immediately)
2. After step starts → `INSERT INTO workflow_run_steps`
3. At each of the 5 `step_log["messages"].append()` sites → `INSERT INTO workflow_run_messages`
4. After step completes → `UPDATE workflow_run_steps` with output, duration, cost
5. After step errors/cancels → `UPDATE workflow_run_steps` with error info
6. In `_log_pipeline_result` → `UPDATE workflow_runs` with final status, duration, cost, summary

**JSON log files are kept** as a backup/export mechanism. DB becomes the primary source of truth.

### 2.3 Startup Migration

On startup, if `workflow_runs` table is empty but `~/workspace/workflow_logs/` has files, backfill from existing JSON logs.

### 2.4 DRY with database.py

Reuse patterns (not the actual chat DB):
- `get_db()` async context manager → clone as `get_workflow_db()`
- `_get_shared_db()` singleton → clone as `_get_shared_workflow_db()` for high-frequency writes
- `close_db()` shutdown hook → add `close_workflow_db()` to the lifespan
- `init_db()` migration pattern → same try/except ALTER TABLE approach

---

## Phase 3 — Run History API & Output Viewing

**Scope**: REST endpoints + frontend components to browse, view, and download historical runs.
**Files changed**: 2 backend, 4-5 frontend.
**Risk**: Medium — new UI components, but no changes to existing functionality.

### 3.1 New API Endpoints

Added to `synapsis/routes/workflows.py`:

| Endpoint | Description |
|----------|-------------|
| `GET /api/workflows/{id}/runs` | List all runs for a workflow (from `workflow_runs` table, ordered by `started_at DESC`) |
| `GET /api/workflows/{id}/runs/{run_id}` | Full run detail with step messages (from DB or log file) |
| `GET /api/workflows/{id}/runs/{run_id}/download?format=json\|md\|html` | Download run log in requested format |
| `POST /api/workflows/{id}/runs/{run_id}/continue` | Create a new chat session pre-seeded with workflow output context |

### 3.2 Workflow Run Exporters

**New file**: `synapsis/exporters/workflow_run.py`

Two functions following the existing exporter pattern:
- `export_workflow_run_markdown(run_log)` → structured Markdown with step headers, tool calls, output
- `export_workflow_run_html(run_log)` → styled HTML reusing `_STYLES` from `html.py`

### 3.3 Frontend: Run History Panel

**New file**: `frontend/src/components/workflows/RunHistoryPanel.tsx`

Shown in `WorkflowDetail.tsx` below the existing metadata. Fetches run list and renders compact cards (status badge, date, duration, cost, truncated summary). Each card is clickable.

### 3.4 Frontend: Run Detail View

**New file**: `frontend/src/components/workflows/RunDetailView.tsx`

Full view for a historical run. Fetches the run detail from API, transforms the data into the existing `StepState[]` shape, and reuses:
- `PipelineStatusBar` — as-is (just needs `agentSequence`, `steps`, `progressPct`)
- `PipelineStepCard` — as-is (already renders from `StepMessage[]`)

Extract the step rendering loop from `PipelineLogViewer.tsx` into a new shared `StepOutputList.tsx` component.

Action buttons: "Download" (format picker), "Continue in Chat".

### 3.5 Frontend: Service & Types

**Modify**: `frontend/src/services/workflows.ts` — add `getRuns()`, `getRunDetail()`, `downloadRun()`, `continueFromRun()`
**Modify**: `frontend/src/lib/types-extended.ts` — add `RunSummary`, `RunLog`, `RunStep` interfaces

### 3.6 "Continue in Chat"

The `POST /api/workflows/{id}/runs/{run_id}/continue` endpoint:
1. Reads the run log
2. Creates a new chat session titled "Continue: {workflow_name}"
3. Inserts a synthetic system message with workflow context (original prompt + final output)
4. Returns `{ session_id, title }`

Frontend navigates to `/chat` with that session.

---

## Phase 4 — Multi-Workflow Concurrency

**Scope**: Run multiple workflows simultaneously, switch between them, close and come back.
**Files changed**: 1 new backend module, refactors to backend WS + frontend hooks/components.
**Risk**: Medium-High — architectural change to execution model. Most complex phase.

### 4.1 Backend: Run Manager (Decouple Executor from WebSocket)

**New file**: `synapsis/workflow_run_manager.py`

Singleton that owns executor lifecycles independently of WebSocket connections.

```python
class WorkflowRunManager:
    _active_runs: dict[str, RunHandle]   # keyed by run_id

    async def start_run(workflow_id, prompt, step_prompts) -> str
    async def attach(run_id) -> AsyncIterator[dict]    # buffered + live events
    async def cancel(run_id) -> None
    def get_active_runs() -> list[RunSummary]
    def get_run(run_id) -> RunHandle | None
```

**RunHandle** holds: `run_id`, `workflow_id`, `status`, `asyncio.Task`, `cancel_event`, `event_buffer: list[dict]` (every emitted event), `subscribers: list[asyncio.Queue]`.

The executor's `send` callback pushes to `event_buffer` AND all subscriber queues.

### 4.2 Backend: Refactor workflow_ws.py

The WebSocket handler becomes a thin transport adapter:

- `{"type": "run", ...}` → call `run_manager.start_run()`, then `run_manager.attach(run_id)`, forward events
- `{"type": "attach", "run_id": "..."}` → reconnect to a running pipeline, receive buffered + live events
- `{"type": "cancel", "run_id": "..."}` → call `run_manager.cancel(run_id)`
- **On disconnect**: detach subscriber queue, do NOT cancel the run (executor continues in background)

### 4.3 Backend: New REST Endpoint

`GET /api/workflows/runs/active` → returns all currently-running pipelines from the run manager.

### 4.4 Frontend: Zustand Store for Runs

**New file**: `frontend/src/stores/workflowRuns.ts`

```typescript
interface WorkflowRunsState {
  runs: Record<string, WorkflowRun>;    // keyed by runId
  activeRunId: string | null;
  startRun(workflow, prompt, stepPrompts): void;
  attachToRun(runId): void;
  setActiveRun(runId | null): void;
}
```

All run state lives here (persistent across component mount/unmount cycles), not in local hook state.

### 4.5 Frontend: Refactor Pipeline Execution Hook

Rewrite `usePipelineExecution.ts` → `useWorkflowRunConnection.ts`:

- Does not auto-run on mount; takes a `runId` and connects to existing run or starts new
- Sends `{"type": "attach", "run_id": ...}` when reconnecting
- Stores state in Zustand store, not local `useState`
- Supports exponential backoff reconnection (reuse pattern from `useWebSocket.ts`)
- On disconnect: reconnect — do NOT assume the run stopped

### 4.6 Frontend: Replace Modal with Inline Panel

- Remove the full-screen modal `PipelineRunner.tsx`
- New `WorkflowRunPanel.tsx` — embedded panel (right side or slide-out drawer) showing one run's output
- New `ActiveRunsBar.tsx` — persistent bar showing all active/recent runs as tabs with progress indicators
- Clicking a tab sets `activeRunId` in the store and shows that run's panel

### 4.7 Page Load Hydration

On Workflows page mount:
1. `GET /api/workflows/runs/active` → populate store with active runs
2. For each active run, open a WebSocket with `attach` to resume live streaming
3. Previously buffered events are replayed through the store's reducer, reconstructing full state

---

## Phase 5 — DRY Refactor of Streaming Core (Optional)

**Scope**: Extract the shared streaming loop into a reusable abstraction.
**Risk**: Medium — refactors both Chat and Workflow hot paths. Do after Phase 1-4 are stable.

### 5.1 StreamCallbacks Protocol

**New file**: `synapsis/stream_callbacks.py`

```python
@dataclass
class StreamCallbacks:
    send: Callable[[dict], Awaitable[None]]
    persist_message: Callable[[str, dict], Awaitable[None]]
    persist_session_id: Callable[[str], Awaitable[None]]
    on_text_complete: Optional[Callable[[str], None]] = None
    extra_fields: dict = field(default_factory=dict)
```

Chat constructs one version (DB persistence, `sid` tagging). Workflow constructs another (step_log appending, `step` tagging).

### 5.2 Shared process_stream()

**In**: `synapsis/stream_core.py`

```python
async def process_stream(client, callbacks, cancel_event=None) -> StreamResult:
    """Core streaming loop shared by Chat and Workflow."""
```

Contains the `async for message in client.receive_response()` loop, all block dispatch, flag tracking, text accumulation — but NOT the try/except/finally lifecycle (that stays in the callers).

### 5.3 Refactor Message Handlers

Modify `handle_assistant_block()`, `handle_result_message()`, `handle_system_message()` to accept `StreamCallbacks` instead of raw `session_id` + `send_json`.

---

## Implementation Priority & Effort Estimates

| Phase | Effort | Impact | Dependencies |
|-------|--------|--------|-------------|
| **Phase 1** — Safety Parity | ~1 day | High (closes safety gaps) | None |
| **Phase 2** — Workflow DB | ~1-2 days | High (enables everything else) | None |
| **Phase 3** — History API & UI | ~2-3 days | High (user-facing output access) | Phase 2 |
| **Phase 4** — Multi-Concurrency | ~3-4 days | Medium-High (multi-tasking) | Phase 2 |
| **Phase 5** — DRY Streaming | ~1-2 days | Low (code quality) | Phases 1-4 stable |

**Recommended order**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5

Phases 1 and 2 have no dependencies on each other and could be done in parallel.

---

## Files Summary

### New Files

| File | Phase | Purpose |
|------|-------|---------|
| `synapsis/stream_core.py` | 1 | Shared error handler (later: shared streaming loop in Phase 5) |
| `synapsis/workflow_db.py` | 2 | Workflow runs DB init, helpers, CRUD |
| `synapsis/exporters/workflow_run.py` | 3 | Markdown + HTML export for run logs |
| `synapsis/workflow_run_manager.py` | 4 | Singleton run manager for concurrent execution |
| `frontend/src/components/workflows/RunHistoryPanel.tsx` | 3 | Run list in workflow detail view |
| `frontend/src/components/workflows/RunDetailView.tsx` | 3 | Full historical run viewer |
| `frontend/src/components/workflows/StepOutputList.tsx` | 3 | Extracted shared step rendering |
| `frontend/src/components/workflows/ActiveRunsBar.tsx` | 4 | Tab bar for active/recent runs |
| `frontend/src/components/workflows/WorkflowRunPanel.tsx` | 4 | Inline run output panel (replaces modal) |
| `frontend/src/stores/workflowRuns.ts` | 4 | Zustand store for multi-run state |
| `frontend/src/hooks/useWorkflowRunConnection.ts` | 4 | Reconnectable WebSocket hook for runs |
| `synapsis/stream_callbacks.py` | 5 | StreamCallbacks protocol for DRY |

### Modified Files

| File | Phase(s) | Changes |
|------|----------|---------|
| `synapsis/services/workflow_executor.py` | 1, 2 | Safety checks, DB persistence calls |
| `synapsis/session_manager.py` | 1 | Extract `create_client_with_retry()` |
| `synapsis/stream_handler.py` | 1, 5 | Use shared error handler; later use StreamCallbacks |
| `synapsis/message_handlers.py` | 5 | Accept StreamCallbacks |
| `synapsis/database.py` | 2 | Register workflow DB in lifespan |
| `synapsis/server.py` | 2, 4 | Register workflow DB + run manager |
| `synapsis/routes/workflows.py` | 3, 4 | New API endpoints |
| `synapsis/exporters/__init__.py` | 3 | Export new functions |
| `synapsis/workflow_ws.py` | 4 | Thin adapter using run manager |
| `frontend/src/hooks/usePipelineExecution.ts` | 1, 4 | Agent activity handling; later full rewrite |
| `frontend/src/components/workflows/WorkflowDetail.tsx` | 3 | Add RunHistoryPanel |
| `frontend/src/components/workflows/PipelineLogViewer.tsx` | 3 | Extract StepOutputList |
| `frontend/src/components/workflows/PipelineRunner.tsx` | 4 | Replace with inline panel |
| `frontend/src/hooks/useWorkflowState.ts` | 4 | Remove single-run state |
| `frontend/src/pages/Workflows.tsx` | 4 | Integrate ActiveRunsBar, inline panel |
| `frontend/src/services/workflows.ts` | 3 | New API client methods |
| `frontend/src/lib/types-extended.ts` | 3 | New type interfaces |

---

*This plan should be re-evaluated if the referenced files change significantly after commit `90379e6`.*
