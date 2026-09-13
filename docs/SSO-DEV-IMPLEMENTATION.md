# CGIAR SSO — DEV implementation (13 September 2026)

Scope: DEV only. The application uses a dedicated Cognito pool and CGIAR Entra OIDC registration. Production is not promoted by this work.

## Configuration
- App origin: https://innovation-analytics-dev.synapsis-analytics.com
- App callback: /auth/callback
- Cognito pool: eu-central-1_QDmB1qeBE, account 972793825893, eu-central-1
- Cognito public client: 7vu6dhatj39qsbe21t58cr38an
- Cognito domain: https://cgiar-ia-dev-972793825893.auth.eu-central-1.amazoncognito.com
- Entra Web callback: the Cognito domain + /oauth2/idpresponse
- Entra app: 19b794e5-88cc-49bf-8c93-74f23f653ddb; CGIAR tenant 6afa0e00-fa14-40b7-8a2e-22a7f8c357d5
- Provider: AzureAD; scopes openid email profile; mapping email/name and Cognito's derived username/sub.
- Secret: GitHub DEV environment IA_ENTRA_CLIENT_SECRET; AWS Secrets Manager cgiar-ia-dev-entra-client-secret (plain SecretString). Never store a credential value in this document.

## Login and identities
The backend uses Authlib for authorization code + S256 PKCE. A ten-minute, one-use database transaction binds random state and nonce to an opaque Secure/HttpOnly/SameSite=Lax browser cookie. ID tokens are verified against the configured Cognito JWKS, RS256 only, issuer, client audience, expiration, issued-at, token_use=id, nonce on the initial exchange, and AzureAD identity. The configured work-email domain restriction is an application audience filter; email is never used on its own to link existing accounts.

Jose's explicit ruling during implementation: CGIAR accounts only; no account linkages. Every verified CGIAR SSO identity receives a fresh opaque sso: UUID owner key and researcher role. No email matching, legacy-role inheritance or historical-chat migration occurs. Later upstream email changes do not change the owner ID. Historical data remains in storage; it is not attached to fresh SSO accounts.

DEV disables both password login and password signup. Previously issued password tokens are rejected by the shared verifier on APIs and WebSocket authentication. SSO-issued app tokens carry an auth_source=sso claim. This is enforced by the backend, not merely by hiding a form.

Cognito credentials stay encrypted on the server in sso_sessions. Cookie identifiers are hashed in the DB; token payloads use Fernet with a key derived from the existing environment JWT secret. Keep that JWT secret stable through deployments. The SPA receives a five-minute application token and refreshes it every two minutes or on focus; the server refreshes Cognito tokens when needed. The server session expires after one day. These tables ride the existing chat.db replication.

Logout deletes the server session and browser cookies and requests Cognito refresh-token revocation and hosted logout. A previously issued app bearer token can remain valid for up to five minutes. An already-open WebSocket follows the app's existing connection lifecycle. Logging out of this app does not terminate the upstream Microsoft session. DEV offers only CGIAR SSO, under the explicit user ruling.

## Deployment and rollback
Identity and application deployments are separate. The identity stack is cgiar-ia-dev-identity, with retained/deletion-protected pool. Its isolated workflow verifies the DEV account and pins checkout to the triggering SHA. The normal DEV application workflow retains the established infrastructure template and container volumes. It reads non-secret hashed snapshots of users, roles and chat ownership before/after replacement; existing rows must remain, and message counts must not decrease. Health reports GIT_SHA for exact deployment verification. Uvicorn access logs are disabled to avoid recording OAuth query strings; application/error logs remain enabled.

Before deployment: local SSO/auth/scoping/signup/export dependency tests 69 passed, frontend auth/login/SSO tests 23 passed, production frontend build passed, full server import passed, workflow YAML parsed and diff whitespace checked. Existing infrastructure template SHA matches deployed source. Actual deployed-login results are recorded in the run report outside this repository.

Rollback triggers: SSO grants an incorrect role/private data, existing storage rows are lost, or auth fails persistently. Preserve the CGIAR-only decision: do not silently re-enable password accounts as a fallback. Apply fixes through the DEV lane; if a temporary outage is needed, keep login closed. Restoring the old password-based build requires a new explicit ruling. Preserve volumes, Cognito pool, registration and identities; no data restore/delete belongs to this auth rollout.
