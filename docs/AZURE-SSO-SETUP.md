# Azure / CGIAR Entra ID SSO — Manual Setup Checklist (for Jose)

**Purpose:** the July-7 sprint ships **app-level password login now** (Step 3,
Option A). This document is the click-by-click checklist for the **target
end-state** — federating CGIAR **Microsoft Entra ID (Azure AD)** into an **AWS
Cognito** user pool via OIDC — so CGIAR staff sign in with their institutional
account. The Entra **App Registration** is the ~half-day of manual Azure clicks
that only Jose (with CGIAR tenant admin / approver) can do; the AWS/Cognito/IaC
side is automatable with the `ai--cgiar-cognito-azure-sso` skill.

> **Sibling that already does this, verbatim-portable:**
> `progress-tracking-solution` (live Cognito + Entra ID OIDC). Cross-check
> `backend/dependencies.py`, its Cognito CloudFormation, and
> `meliaf-study-stocktake/backend/functions/cognito_triggers/pre_signup.py`
> (email-domain allow-list Lambda) as you go.

---

## Architecture (target)

```
CGIAR staff ──▶ Cognito Hosted UI ──▶ (OIDC federation) ──▶ CGIAR Entra ID
                     │                                          (Azure AD tenant)
External users ─────▶ Cognito user pool (username/password)
                     │
                     ▼
        Cognito issues a JWT whose `sub` claim IS the user_id
                     │
                     ▼
   Innovation Analytics backend (verify JWT `sub` → resolve_user_id → chat scope)
```

Because the backend already keys on the JWT **`sub`** claim
(`synapsis/auth/tokens.py` / `resolve_user_id`), swapping the token issuer from
the app-password JWT to Cognito's JWT is a **configuration change, not a code
rewrite**: point `verify_token` at the Cognito JWKS / issuer and the same
`user_id` scoping keeps working unchanged.

---

## Part A — What JOSE must click in Azure (the manual half-day)

Estimated time: ~half a day including CGIAR approval latency. Start this FIRST
(it has external approval latency).

1. **Create (or reuse the DEV) Cognito user pool + Hosted UI domain** for
   Innovation Analytics — the agent can do this via IaC. You'll get:
   - a **Cognito domain**, e.g. `cgiar-ia-dev.auth.eu-central-1.amazoncognito.com`
   - the **redirect URI Azure needs** (computed by the agent):
     `https://<cognito-domain>/oauth2/idpresponse`

2. **Entra ID → App registrations → New registration**
   - Portal: <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations** → **New registration**.
   - **Name:** `CGIAR Innovation Analytics (dev)`.
   - **Supported account types:** *Accounts in this organizational directory only* (CGIAR single tenant).
   - **Redirect URI:** platform **Web**, value = the `.../oauth2/idpresponse`
     URL from step 1. **Paste it exactly.**
   - Click **Register**.

3. **Copy back these THREE values** (you'll hand them to the agent / store as
   secrets — NOT in git):
   - **Application (client) ID**
   - **Directory (tenant) ID**
   - A **client secret**: *Certificates & secrets* → *New client secret* →
     copy the **Value** (not the Secret ID) immediately.

4. **API permissions** (Microsoft Graph, delegated): `openid`, `profile`,
   `email`. Click **Grant admin consent for CGIAR** (this is the approval step
   that may need a tenant admin — allow latency here).

5. **Token configuration** (optional but recommended): add the **email** and
   **name** optional claims so Cognito receives them.

6. **Redirect URIs for the app itself** — confirm the app origins that are valid
   login-return targets:
   - `https://innovation-analytics-dev.synapsis-analytics.com`
   - (later) `https://innovation-analytics.synapsis-analytics.com`

That's the entire Azure-side surface. Everything below is AWS/IaC.

---

## Part B — What the AGENT / IaC does (automatable)

Run the `ai--cgiar-cognito-azure-sso` skill against this repo
(`cgiar-innovation-analytics`). It will:

1. Store the Entra **client secret** in AWS Secrets Manager (never in git).
2. Add a **Cognito OIDC identity provider** to the user pool:
   - Issuer: `https://login.microsoftonline.com/<tenant-id>/v2.0`
   - Client ID / secret: from Part A step 3.
   - Scopes: `openid profile email`.
   - Attribute mapping: `email → email`, `name → name`, `sub → username`.
3. Enable the IdP on the app client and add the callback/sign-out URLs.
4. Add the **domain-allowlist Pre-Sign-Up Lambda** (port
   `meliaf-study-stocktake/.../cognito_triggers/pre_signup.py`) so only
   `@cgiar.org` (and any explicitly allowed partner domains) can federate,
   while the separate username/password pool still serves external users.
5. Capture all of the above in `infra/` CloudFormation so it is reproducible
   via CI/CD — not hand-clicked.

---

## Part C — Backend swap (small, already architected)

Once Cognito issues tokens:

1. Point `synapsis/auth/tokens.py:verify_token` at the Cognito **JWKS**
   (`https://cognito-idp.eu-central-1.amazonaws.com/<pool-id>/.well-known/jwks.json`)
   and validate the `iss`/`aud` — keep reading the **`sub`** claim as `user_id`.
2. Add a frontend "Sign in with CGIAR" button that redirects to the Cognito
   Hosted UI; keep the existing email/password form for external users (Cognito
   supports both simultaneously).
3. No change to the per-user chat scoping — it already keys on `user_id`.

**Fallback plan (if Azure approval stalls past July 20):** ship the
password-pool login for July 20 (already done) and federate Entra ID during the
July 21–22 window. This checklist is what unblocks that window.
