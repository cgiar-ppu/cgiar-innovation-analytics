"""
Git repository information endpoints.

- GET /api/git/status  — Current branch, staged/unstaged/untracked files, ahead/behind
- GET /api/git/diff    — Unified diff for a file (or all files), plus old/new content
- GET /api/git/log     — Recent commit history
- GET /api/git/show    — File content at a specific ref
"""

import asyncio
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from synapsis.config import WORKSPACE, logger

router = APIRouter(prefix="/api/git", tags=["git"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Cached git root directory — resolved once on first call.
_git_root: Optional[Path] = None


async def _resolve_git_root() -> Path:
    """Find the git root directory, searching from WORKSPACE upward.

    The WORKSPACE config may point to a directory that is not the git repo
    root (e.g. /Users/user/workspace) while the .git lives in a subdirectory
    (e.g. /Users/user/workspace/project-name). We first check WORKSPACE
    itself, then search children, and finally try ``git rev-parse --show-toplevel``.
    """
    global _git_root
    if _git_root is not None:
        return _git_root

    # 1. Check the CWD first — in dev the app runs from the project directory
    cwd = Path.cwd()
    if (cwd / ".git").exists():
        _git_root = cwd
        logger.info("Git root detected at CWD: %s", _git_root)
        return _git_root

    # 2. Check if WORKSPACE itself is a git repo
    if (WORKSPACE / ".git").exists():
        _git_root = WORKSPACE
        return _git_root

    # 3. Ask git from CWD (handles worktrees or nested repos)
    for search_dir in [cwd, WORKSPACE]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--show-toplevel",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(search_dir),
            )
            stdout_bytes, _ = await proc.communicate()
            if proc.returncode == 0:
                _git_root = Path(stdout_bytes.decode().strip())
                logger.info("Git root resolved via git rev-parse: %s", _git_root)
                return _git_root
        except Exception:
            pass

    raise HTTPException(
        422, detail="No git repository found in or under the workspace directory."
    )


async def _run_git(
    *args: str,
    cwd: Optional[Path] = None,
    check: bool = True,
) -> tuple[str, str, int]:
    """Run a git command asynchronously and return (stdout, stderr, returncode).

    Raises HTTPException(500) when *check* is True and the command fails, unless
    the failure is a recognisable "not a git repo" situation (422).
    """
    work_dir = cwd or await _resolve_git_root()
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    if check and proc.returncode != 0:
        # Friendly error when the workspace is not a git repo
        if "not a git repository" in stderr.lower():
            raise HTTPException(
                422,
                detail="The workspace directory is not a git repository.",
            )
        logger.error("git %s failed (rc=%d): %s", " ".join(args), proc.returncode, stderr.strip())
        raise HTTPException(500, detail=f"git error: {stderr.strip()}")

    return stdout, stderr, proc.returncode


def _parse_status_porcelain(output: str) -> dict:
    """Parse the output of ``git status --porcelain=v1 -b`` into structured data."""
    lines = output.splitlines()
    branch = ""
    ahead = 0
    behind = 0
    staged: list[dict] = []
    unstaged: list[dict] = []
    untracked: list[str] = []

    for line in lines:
        # Branch header: ## main...origin/main [ahead 1, behind 2]
        if line.startswith("## "):
            branch_info = line[3:]
            # Extract branch name (before "..." or end of string)
            branch = branch_info.split("...")[0]
            # Parse ahead/behind from trailing bracket info
            m = re.search(r"\[ahead (\d+)", branch_info)
            if m:
                ahead = int(m.group(1))
            m = re.search(r"behind (\d+)", branch_info)
            if m:
                behind = int(m.group(1))
            continue

        if len(line) < 3:
            continue

        index_status = line[0]
        worktree_status = line[1]
        file_path = line[3:]

        # Handle renames: "R  old -> new"
        if " -> " in file_path:
            file_path = file_path.split(" -> ", 1)[1]

        if index_status == "?" and worktree_status == "?":
            untracked.append(file_path)
            continue

        # Staged: first column is not a space and not '?'
        if index_status not in (" ", "?"):
            staged.append({"path": file_path, "status": index_status})

        # Unstaged: second column is not a space
        if worktree_status not in (" ", "?"):
            unstaged.append({"path": file_path, "status": worktree_status})

    return {
        "branch": branch,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "ahead": ahead,
        "behind": behind,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def git_status():
    """Return the current git status: branch, staged/unstaged/untracked files, ahead/behind."""
    stdout, _, _ = await _run_git("status", "--porcelain=v1", "-b")
    return _parse_status_porcelain(stdout)


@router.get("/diff")
async def git_diff(
    file: Optional[str] = Query(None, description="Path to a specific file (relative to repo root)"),
    staged: bool = Query(False, description="Show staged (cached) diff instead of working-tree diff"),
):
    """Return the unified diff for a file or the entire working tree.

    Optionally returns old and new file content when *file* is specified so
    the frontend can perform structured side-by-side diffing.
    """
    cmd: list[str] = ["diff"]
    if staged:
        cmd.append("--cached")
    if file:
        cmd.extend(["--", file])

    diff_stdout, _, _ = await _run_git(*cmd)

    result: dict = {"diff": diff_stdout}

    if file:
        result["file"] = file

        # Old content: file at HEAD (may not exist for new files)
        ref = "HEAD" if staged else "HEAD"
        old_stdout, _, rc = await _run_git("show", f"{ref}:{file}", check=False)
        result["old_content"] = old_stdout if rc == 0 else ""

        # New content: staged version or working-tree file
        if staged:
            # For staged diff, "new" is the index version
            new_stdout, _, rc = await _run_git("show", f":{file}", check=False)
            result["new_content"] = new_stdout if rc == 0 else ""
        else:
            git_root = await _resolve_git_root()
            file_path = (git_root / file).resolve()
            root_resolved = git_root.resolve()
            if not str(file_path).startswith(str(root_resolved)):
                raise HTTPException(403, "Access denied: path outside repository")
            try:
                result["new_content"] = file_path.read_text(errors="replace")
            except FileNotFoundError:
                result["new_content"] = ""
    else:
        result["file"] = None
        result["old_content"] = None
        result["new_content"] = None

    return result


@router.get("/log")
async def git_log(
    limit: int = Query(20, ge=1, le=500, description="Maximum number of commits to return"),
):
    """Return recent commit history."""
    fmt = "%H|%h|%an|%ae|%ar|%s"
    stdout, _, _ = await _run_git("log", f"--format=format:{fmt}", f"-n{limit}")

    commits = []
    for line in stdout.splitlines():
        parts = line.split("|", 5)
        if len(parts) < 6:
            continue
        commits.append({
            "hash": parts[0],
            "short_hash": parts[1],
            "author": parts[2],
            "email": parts[3],
            "relative_date": parts[4],
            "message": parts[5],
        })

    return {"commits": commits}


@router.get("/show")
async def git_show(
    file: str = Query(..., description="File path relative to repo root"),
    ref: str = Query("HEAD", description="Git ref (branch, tag, or commit hash)"),
):
    """Return the content of a file at a specific git ref."""
    # Basic validation to prevent shell injection via ref
    if not re.match(r"^[\w./@^~{}\-]+$", ref):
        raise HTTPException(400, detail="Invalid ref format")

    stdout, _, _ = await _run_git("show", f"{ref}:{file}")
    return {"file": file, "ref": ref, "content": stdout}
