"""
Synapsis hooks package — safety validation and audit logging for tool usage.

Hooks are called by the Claude Agent SDK before/after each tool invocation.
This package is split into two focused modules:

- :mod:`synapsis.hooks.safety` — Pre-tool dangerous-command blocking
- :mod:`synapsis.hooks.audit`  — Pre- and post-tool audit trail logging

All public names are re-exported here so that existing imports of the form
``from synapsis.hooks import safety_validator`` continue to work without
change.
"""

from synapsis.hooks.safety import safety_validator, DANGEROUS_PATTERNS
from synapsis.hooks.audit import audit_logger, audit_logger_post

__all__ = [
    "safety_validator",
    "DANGEROUS_PATTERNS",
    "audit_logger",
    "audit_logger_post",
]
