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

## Own-only visibility (2026-09-14, supersedes admin legacy exception)

Jose explicitly requires that pre-login history not be visible after sign-in,
including for administrators. All roles see only their own conversations. Legacy
and unowned sessions remain stored but cannot be listed, searched, opened, exported,
changed or resumed by another identity. Missing ownership fails closed. Conversation
search and agent history tools now enforce the same rule. Missing agent identity
cannot read the legacy archive. Hidden app databases cannot be downloaded via Files,
and chat exports require their originating session's owner.

The shared execution/filesystem limitation above remains; this is not an OS sandbox.

## Workspace-files API now requires auth (added 2026-07-20)

`GET /api/files`, `GET /api/files/{path}`, and `POST /api/upload`
(`synapsis/routes/files.py`) were previously unauthenticated on the deployed
dev app — closed as a gap, not a new isolation boundary. Any authenticated
user (any role) may list, download, or upload, consistent with the shared-
workspace limitation described above: the workspace is common to all users,
so per-file ownership scoping was never part of this build's promise. The
download route additionally accepts `?token=` (same query-param pattern as
`routes/export.py`) so plain `<a href>` download links rendered from chat
markdown — which cannot attach an `Authorization` header — keep working.

## Interim self-signup, no email confirmation (added 2026-07-20)

`POST /api/auth/signup` lets anyone create an account instantly (role always
`researcher`, no email verification step) — an interim measure so
researchers aren't blocked on a manual allow-list edit + redeploy while
CGIAR Entra ID SSO is still being onboarded. It is gated behind the
`IA_SELF_SIGNUP` env flag (default OFF in code; `deploy.yml` only sets it
`true` for the dev stage), so it can be disabled instantly by unsetting the
flag and does not reach the prod lineage unless explicitly re-enabled there.

### Email-domain allow-list (added 2026-08-03)

Self-signup is additionally restricted to CGIAR email addresses, matching the
policy already stated to Marc Schut on 2026-07-22 ("the sign up is not allowed
to avoid anyone just using it — without a CG email"). Until now the code did
not enforce it: any address could self-register on dev.

- Config: `IA_SIGNUP_ALLOWED_DOMAINS`, comma-separated, **default
  `cgiar.org`**. Unset/blank falls back to that default (fail closed — an
  accidentally-empty variable must not open signup to the internet). The only
  way to disable the restriction is the explicit value `*`.
- Matching is an **exact, case-insensitive** comparison of the part after
  `@`. Subdomains do NOT match: `x@mail.cgiar.org` is rejected under the
  default; centre domains (e.g. `cimmyt.org`) must be listed explicitly.
- Rejection is `403` with a user-facing sentence naming the allowed domains;
  the login screen surfaces that sentence verbatim and also shows the rule as
  a hint before submission (`/api/config → signup_allowed_domains`).
- The check runs after the `IA_SELF_SIGNUP` flag gate and the rate limit, and
  **before** the uniqueness lookup, so a disallowed address never learns
  whether an account exists.

This narrows, but does not replace, the SSO path: it is domain-level trust of
a self-asserted address (no mailbox verification), so it remains an interim
measure until Entra ID federation lands.
