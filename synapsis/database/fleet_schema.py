"""Schema initialization for the fleet database (fleet.db).

Contains all CREATE TABLE statements and indexes for the fleet management
system: fleets, fleet_agents, fleet_runs, fleet_messages, and fleet_health.
"""

import synapsis.config as _config
from synapsis.config import logger
from synapsis.database.fleet_connection import get_fleet_db


async def init_fleet_db() -> None:
    """Create fleet tables and indexes if they don't exist.

    Tables:
    - fleets:         High-level grouping of agents by project/purpose
    - fleet_agents:   Individual agents within a fleet
    - fleet_runs:     Batch operations (spawn, mediate, broadcast, interrogate)
    - fleet_messages: Messages exchanged with individual agents
    - fleet_health:   System health snapshots
    """
    _config.SYNAPSIS_DIR.mkdir(parents=True, exist_ok=True)

    async with get_fleet_db() as db:
        # -- Fleets table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fleets (
                fleet_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                project_path TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                chat_session_id TEXT DEFAULT '',
                config TEXT DEFAULT '{}'
            )
        """)

        # -- Fleet agents table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fleet_agents (
                agent_id TEXT PRIMARY KEY,
                fleet_id TEXT NOT NULL,
                name TEXT NOT NULL,
                specialty TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                claude_session_id TEXT DEFAULT '',
                worker_node TEXT DEFAULT 'local',
                status TEXT DEFAULT 'idle',
                turn_count INTEGER DEFAULT 0,
                last_active REAL,
                context_summary TEXT DEFAULT '',
                result TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (fleet_id) REFERENCES fleets(fleet_id)
            )
        """)

        # -- Fleet runs table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fleet_runs (
                run_id TEXT PRIMARY KEY,
                fleet_id TEXT NOT NULL,
                run_type TEXT DEFAULT 'batch',
                status TEXT DEFAULT 'pending',
                agent_ids TEXT DEFAULT '[]',
                concurrency INTEGER DEFAULT 3,
                prompt TEXT DEFAULT '',
                result_summary TEXT DEFAULT '',
                progress_current INTEGER DEFAULT 0,
                progress_total INTEGER DEFAULT 0,
                started_at REAL,
                completed_at REAL,
                error_message TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (fleet_id) REFERENCES fleets(fleet_id)
            )
        """)

        # -- Fleet messages table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fleet_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                run_id TEXT DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                turn_number INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                FOREIGN KEY (agent_id) REFERENCES fleet_agents(agent_id)
            )
        """)

        # -- Fleet health table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fleet_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                ram_total_gb REAL,
                ram_available_gb REAL,
                ram_used_pct REAL,
                cpu_pct REAL,
                active_agents INTEGER DEFAULT 0,
                claude_processes INTEGER DEFAULT 0
            )
        """)

        # -- Indexes --
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_agents_fleet_status
            ON fleet_agents (fleet_id, status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_runs_fleet_status
            ON fleet_runs (fleet_id, status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_messages_agent_created
            ON fleet_messages (agent_id, created_at)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_health_timestamp
            ON fleet_health (timestamp)
        """)

        await db.commit()

    logger.info("Fleet database initialized successfully")
