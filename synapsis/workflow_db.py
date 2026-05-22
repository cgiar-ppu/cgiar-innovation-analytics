"""Workflow runs database -- thin re-export shim.

All implementation has moved to ``synapsis.database.workflow_*`` submodules.
This file exists solely for backward compatibility so existing imports like
``from synapsis.workflow_db import get_workflow_db`` continue to work.
"""

# Connection
from synapsis.database.workflow_connection import (  # noqa: F401
    WORKFLOW_DB_PATH,
    get_workflow_db,
    _get_shared_workflow_db,
    close_workflow_db,
)

# Schema
from synapsis.database.workflow_schema import init_workflow_db  # noqa: F401

# Run CRUD
from synapsis.database.workflow_runs import (  # noqa: F401
    create_workflow_run,
    update_workflow_run,
    get_workflow_runs,
    get_workflow_run,
    get_active_workflow_runs,
    delete_workflow_run,
)

# Step CRUD
from synapsis.database.workflow_steps import (  # noqa: F401
    create_workflow_run_step,
    update_workflow_run_step,
    get_workflow_run_steps,
)

# Messages
from synapsis.database.workflow_messages import (  # noqa: F401
    save_workflow_run_message,
    get_workflow_run_messages,
)
