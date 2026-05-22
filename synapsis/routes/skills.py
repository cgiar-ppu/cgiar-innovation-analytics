"""
Skills discovery API — lists available skills from .claude/skills/ directories.

- GET /api/skills — Returns list of available skills and SDK commands
"""

import time
import logging
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter

from synapsis.config import WORKSPACE, PROJECT_DIR

router = APIRouter()
logger = logging.getLogger("synapsis_agent")

# ---------------------------------------------------------------------------
# Module-level cache (keyed by invocable_only flag)
# ---------------------------------------------------------------------------

_cache: dict[bool, dict] = {}
_cache_ts: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes

# ---------------------------------------------------------------------------
# Hardcoded SDK commands
# ---------------------------------------------------------------------------

_SDK_COMMANDS = [
    {"name": "review", "description": "Review code changes for issues and improvements", "category": "command"},
    {"name": "security-review", "description": "Perform a security-focused code review", "category": "command"},
    {"name": "pr-comments", "description": "Address pull request review comments", "category": "command"},
    {"name": "release-notes", "description": "Generate release notes from recent changes", "category": "command"},
    {"name": "debug", "description": "Debug an issue with interactive investigation", "category": "command"},
    {"name": "simplify", "description": "Simplify and refactor complex code", "category": "command"},
    {"name": "loop", "description": "Run a command in a loop until a condition is met", "category": "command"},
    {"name": "claude-api", "description": "Generate code using the Claude API", "category": "command"},
    {"name": "compact", "description": "Compact conversation context to save tokens", "category": "command"},
    {"name": "init", "description": "Initialize a new CLAUDE.md project configuration", "category": "command"},
    {"name": "insights", "description": "Show insights about the current conversation", "category": "command"},
    {"name": "context", "description": "Manage conversation context and files", "category": "command"},
    {"name": "cost", "description": "Show token usage and cost for this session", "category": "command"},
]


def _parse_skill_frontmatter(skill_md_path: Path) -> Optional[dict]:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns a dict with name, description, category='skill' or None if
    the file is missing, unreadable, or lacks valid frontmatter.
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.debug("Skipping unreadable skill file: %s", skill_md_path)
        return None

    # Frontmatter must start with ---
    text = text.strip()
    if not text.startswith("---"):
        return None

    # Find the closing ---
    end_idx = text.find("---", 3)
    if end_idx == -1:
        return None

    frontmatter_str = text[3:end_idx].strip()
    if not frontmatter_str:
        return None

    try:
        fm = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError:
        logger.debug("Invalid YAML frontmatter in %s", skill_md_path)
        return None

    if not isinstance(fm, dict):
        return None

    name = fm.get("name")
    description = fm.get("description", "")

    if not name:
        return None

    user_invocable = fm.get("user-invocable", False)
    # Handle string "true"/"false" as well as boolean
    if isinstance(user_invocable, str):
        user_invocable = user_invocable.lower() == "true"

    return {
        "name": str(name),
        "description": str(description),
        "category": "skill",
        "invocable": bool(user_invocable),
    }


def _scan_skills_dir(skills_dir: Path, skills: list[dict], seen_names: set[str]) -> None:
    """Scan a single .claude/skills/ directory and append found skills."""
    if not skills_dir.is_dir():
        return
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        parsed = _parse_skill_frontmatter(skill_md)
        if parsed and parsed["name"] not in seen_names:
            skills.append(parsed)
            seen_names.add(parsed["name"])


def _discover_skills() -> list[dict]:
    """Scan .claude/skills/ directories for SKILL.md files and parse them.

    Searches in order of priority:
    1. Project-level skills (PROJECT_DIR/.claude/skills/)
    2. Workspace-level skills (WORKSPACE/.claude/skills/)
    3. Global user skills (~/.claude/skills/)
    """
    skills: list[dict] = []
    seen_names: set[str] = set()
    scanned: set[Path] = set()

    # Project-level skills (where the code lives)
    project_skills_dir = PROJECT_DIR / ".claude" / "skills"
    resolved = project_skills_dir.resolve()
    _scan_skills_dir(resolved, skills, seen_names)
    scanned.add(resolved)

    # Workspace-level skills (the working directory)
    workspace_skills_dir = WORKSPACE / ".claude" / "skills"
    resolved = workspace_skills_dir.resolve()
    if resolved not in scanned:
        _scan_skills_dir(resolved, skills, seen_names)
        scanned.add(resolved)

    # Global user skills
    global_skills_dir = Path.home() / ".claude" / "skills"
    resolved = global_skills_dir.resolve()
    if resolved not in scanned:
        _scan_skills_dir(resolved, skills, seen_names)

    return skills


def _build_response(invocable_only: bool = False) -> dict:
    """Build the full skills + commands response.

    When *invocable_only* is True, only skills with ``invocable=True`` and all
    SDK commands are included.
    """
    skills = _discover_skills()
    if invocable_only:
        skills = [s for s in skills if s.get("invocable", False)]
    all_items = skills + list(_SDK_COMMANDS)
    return {"skills": all_items}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/api/skills")
async def get_skills(invocable_only: bool = False):
    """Return all available skills and SDK commands.

    Results are cached for 5 minutes since skills do not change during runtime.
    Pass ``?invocable_only=true`` to return only user-invocable skills.
    """
    global _cache, _cache_ts

    now = time.monotonic()
    if (now - _cache_ts) >= _CACHE_TTL:
        _cache.clear()
        _cache_ts = now

    if invocable_only in _cache:
        return _cache[invocable_only]

    result = _build_response(invocable_only)
    _cache[invocable_only] = result
    return result
