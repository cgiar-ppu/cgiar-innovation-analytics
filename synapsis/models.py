"""
Synapsis Pydantic models — request/response validation for the REST API.

Using Pydantic models instead of raw dicts gives us:
- Automatic request validation with clear error messages
- OpenAPI/Swagger documentation generation
- Type safety throughout the codebase
"""

from pydantic import BaseModel, Field
from typing import Optional


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------

class MemoryCreate(BaseModel):
    """POST /api/memories — create a new memory."""
    category: str = Field(default="fact", min_length=1)
    content: str = Field(..., min_length=1)
    importance: int = Field(default=5, ge=1, le=10)
    tags: str = ""
    source_session: str = "api"


class MemoryResponse(BaseModel):
    """Single memory in list responses."""
    id: int
    category: str
    content: str
    importance: int
    source_session: str
    created_at: float
    updated_at: float
    access_count: int
    tags: str
    active: int


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------

class SessionUpdate(BaseModel):
    """PATCH /api/sessions/{session_id} — rename a session."""
    title: str = ""


# ---------------------------------------------------------------------------
# Query endpoint
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """POST /api/query — single-shot query.

    ``scope`` is the same optional active-data-scope object the chat WebSocket
    accepts (e.g. ``{"years": [2024], "programs": ["SP09 — Scaling for Impact"]}``).
    Omitted/empty ⇒ no scope and behaviour identical to before. See
    synapsis/scope.py.
    """
    message: str = Field(..., min_length=1, max_length=50000)
    scope: Optional[dict] = None
