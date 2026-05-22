"""Schema initialization for the workflow runs database."""

from synapsis.config import SYNAPSIS_DIR, logger
from synapsis.database.workflow_connection import get_workflow_db, WORKFLOW_DB_PATH


async def init_workflow_db() -> None:
    """Create tables and indexes if they don't exist.

    Tables:
    - workflow_runs:          Pipeline run metadata (status, timing, cost)
    - workflow_run_steps:     Per-step details (agent, model, I/O, cost)
    - workflow_run_messages:  Individual messages within each step
    """
    SYNAPSIS_DIR.mkdir(parents=True, exist_ok=True)

    async with get_workflow_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id                TEXT PRIMARY KEY,
                workflow_id       TEXT NOT NULL,
                workflow_name     TEXT,
                status            TEXT NOT NULL DEFAULT 'running',
                started_at        REAL NOT NULL,
                completed_at      REAL,
                total_duration_s  REAL,
                total_cost_usd    REAL,
                initial_prompt    TEXT,
                agent_sequence    TEXT,
                step_count        INTEGER,
                completed_steps   INTEGER DEFAULT 0,
                progress          INTEGER DEFAULT 0,
                log_filename      TEXT,
                summary           TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_run_steps (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            TEXT NOT NULL,
                step_index        INTEGER NOT NULL,
                agent_id          TEXT,
                agent_name        TEXT,
                model             TEXT,
                input_prompt      TEXT,
                output_text       TEXT,
                tool_calls_count  INTEGER DEFAULT 0,
                turns             INTEGER,
                estimated_cost    REAL,
                claude_session_id TEXT,
                error             TEXT,
                started_at        REAL,
                completed_at      REAL,
                duration_s        REAL,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_run_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                step_index  INTEGER NOT NULL,
                ts          REAL NOT NULL,
                type        TEXT NOT NULL,
                data        TEXT,
                tool_use_id TEXT,
                is_error    INTEGER DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
        """)

        # Indexes
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_runs_wf "
            "ON workflow_runs(workflow_id, started_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_runs_status "
            "ON workflow_runs(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_run_steps "
            "ON workflow_run_steps(run_id, step_index)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_run_msgs "
            "ON workflow_run_messages(run_id, step_index, ts)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_run_msgs_full "
            "ON workflow_run_messages(run_id, ts)"
        )

        await db.commit()
        logger.info("Workflow runs database initialized at %s", WORKFLOW_DB_PATH)
