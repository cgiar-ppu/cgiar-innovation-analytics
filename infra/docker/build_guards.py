"""Build-time security guards for the IA image (run by Dockerfile.prod after pip install).

CVE-2026-111497 "Node2Shell" (Brotli decoder out-of-bounds write, google/brotli
1.0.3-1.2.0). The build fails when:
  * the Claude Code CLI bundled in claude-agent-sdk (the binary the SDK runs)
    lacks the Brotli fix -- fixed builds contain ``_ERROR_FORMAT_BLOCK_SWITCH``
    (CLI >= 2.1.309, i.e. claude-agent-sdk >= 0.2.173);
  * a vulnerable Python Brotli / brotlicffi is installed (fixed: Brotli 1.2.1,
    brotlicffi 1.2.1.0). Neither is a dependency today; this keeps it that way
    unless a fixed version is pinned.
Prints the SDK / CLI versions so the CI build log is the evidence.
"""
import importlib.metadata as md
import pathlib
import sys

import claude_agent_sdk
from claude_agent_sdk._cli_version import __cli_version__

MARKER = b"_ERROR_FORMAT_BLOCK_SWITCH"
FIXED_PY_BROTLI = {"Brotli": (1, 2, 1), "brotlicffi": (1, 2, 1, 0)}


def _ver(text: str, width: int) -> tuple[int, ...]:
    parts = []
    for piece in text.split(".")[:width]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def main() -> int:
    errors = []
    cli = pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    has_fix = cli.is_file() and MARKER in cli.read_bytes()
    print(f"claude-agent-sdk {claude_agent_sdk.__version__} bundled CLI {__cli_version__} "
          f"({cli}) brotli-fix-marker={'present' if has_fix else 'ABSENT'}")
    if not has_fix:
        errors.append("bundled claude CLI lacks Brotli fix (need claude-agent-sdk >= 0.2.173)")
    for dist, fixed in FIXED_PY_BROTLI.items():
        try:
            installed = md.version(dist)
        except md.PackageNotFoundError:
            print(f"{dist}: not installed")
            continue
        print(f"{dist}: {installed}")
        if _ver(installed, len(fixed)) < fixed:
            errors.append(f"vulnerable Python {dist} {installed} (need >= {'.'.join(map(str, fixed))})")
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
