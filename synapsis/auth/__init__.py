"""
Authentication package for the CGIAR Innovation Analytics Platform.

Ported and adapted from the ast-chatbot sibling (same ``synapsis/`` scaffold).
This is the Step-3 "Option A" app-level password login: a JWT/bcrypt allow-list
that runs now and remains the issued-password path once CGIAR Entra ID SSO is
federated via Cognito.

Identity abstraction
--------------------
Every consumer reads a single stable claim — ``user_id`` — via
:func:`resolve_user_id`. Today that is the JWT ``sub`` (the user's email from
the allow-list). When Cognito/Entra ID federation lands, the same ``sub`` claim
carries the Cognito user id and NOTHING downstream changes. This is the swap
point the July-7 brief calls for.
"""

from synapsis.auth.middleware import (
    get_current_user,
    get_optional_user,
    resolve_user_id,
)
from synapsis.auth.tokens import create_access_token, verify_token
from synapsis.auth.users import authenticate_user, hash_password

__all__ = [
    "get_current_user",
    "get_optional_user",
    "resolve_user_id",
    "create_access_token",
    "verify_token",
    "authenticate_user",
    "hash_password",
]
