# Security Scoping Note — Per-User Chat Isolation (Honest Limitation)

**Status:** deliberate, agreed scope for the July-7 2026 guardrails sprint.
**Audience:** Marc Schut, Julien Colomer (Jules), and any future maintainer.

## What this build provides

The July-7 sprint added **UI/API-level per-user chat isolation**:

- Each user authenticates (app-level password now; CGIAR Entra ID SSO via
  Cognito later — see `AZURE-SSO-SETUP.md`).
- Every chat session carries a `user_id` (the authenticated identity claim).
- All chat-list, history, export, rename, delete, and WebSocket-resume paths
  filter by that `user_id`. A user sees, resumes, and exports **only their own**
  conversations; another user's sessions return `404`.

This is real, enforced isolation of **conversation content and history**.

## What this build does NOT provide (read carefully)

**UI/API-level scoping is not the same as agent-sandbox isolation.**

The Innovation Analytics agent is a Claude Agent SDK process that executes code
(shell commands, file reads/writes, MCP tools) in a **single shared
workspace/VM** common to all users. The per-user `user_id` filtering governs
which chats a user can *see and manage* — it does **not** partition the
*execution environment*:

- All users' agent runs share the same filesystem, the same workspace
  directory, and the same process-level credentials.
- A sufficiently determined prompt could, in principle, cause the agent to read
  or write files created during another user's session, because those files
  live in the shared workspace, not in a per-user sandbox.
- There is no per-user OS-level, container-level, or network-level boundary
  around agent execution.

In short: **prompts and chat lists are private; the underlying execution
environment is not partitioned per user.**

## Why it is scoped this way

This is the "lighter-weight illusion of separation" the team explicitly agreed
to on the **July 7, 2026** call, given the budget envelope (~$5k remaining for
the core package) and the July-20 first-testable-version deadline. True
per-user execution-sandbox isolation — separate containers/VMs or a
per-request stateless execution model — is **technically nontrivial and would
exceed the available budget**. It is deferred to a **separately costed future
phase** (estimated $3–5k in the itemized cost breakdown).

Per the team's decision, this limitation is **disclosed honestly to Marc rather
than shipped as a false sense of security.**

## Where this is enforced / documented in code

- `synapsis/auth/middleware.py` — `resolve_user_id()` + a prominent code comment
  restating this limitation next to the auth middleware.
- `synapsis/auth/context.py` — per-connection identity context (chat scoping,
  not execution sandboxing).
- `synapsis/routes/sessions.py`, `synapsis/routes/export.py`,
  `synapsis/websocket.py` — the `user_id` filters.

## The one-liner for the build report / Marc

> Login plus per-user-visible chat lists give each user private conversations
> and history. The agent still runs in a shared workspace, so this is UI/API
> scoping, not execution-sandbox isolation. Full per-user sandboxing is a
> costed future phase, flagged openly rather than implied.

## Admin-legacy-chat exception (added 2026-07-20)

The `user_id` migration attributed every session that predates login to a
sentinel identity, `LEGACY_USER_ID = "legacy@innovation-analytics"`
(`synapsis/config.py`). Strict per-user filtering therefore hid that entire
pre-login history from everyone, including admins, who reasonably expect to
still see it. The fix widens *visibility* only, in one centralized place
(`synapsis/auth/scoping.py::allowed_user_ids` / `is_visible_to`, consumed by
`routes/sessions.py`, `routes/export.py`, and the WebSocket `switch_session`
ownership check in `websocket.py`): a user whose **verified JWT `role`
claim** is `"admin"` sees, opens, exports, resumes, renames, pins, and may
delete BOTH their own sessions AND sentinel-owned ("legacy") sessions;
non-admin roles are unaffected and remain strictly own-sessions-only with the
existing 404-not-403 semantics. The role is read only from the
signature-verified token (`auth/tokens.py::verify_token` → `resolve_role()`),
never from client-supplied input, and is threaded into the WebSocket path via
the same per-connection `contextvar` that already carries `user_id`
(`auth/context.py`). Creation attribution is unchanged: a session an admin
creates is still owned by that admin's own `user_id`, never silently
re-attributed to the sentinel. This exception is a *visibility* widening
only — it does not alter the honest execution-sandbox limitation described
above.
