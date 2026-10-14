# DEV-only: restored PRMS tables (Innovation Use level 0–9 + use numbers) — 2026-10-14

## Why
Since the 13 Sep 2026 snapshot the local MySQL→SQLite converter silently dropped every PRMS table whose DDL carries a column `COMMENT '…'`. The snapshot published on 14 Sep (`snapshots/20260913/`, 203 tables) therefore lacks `results_innovations_use` (the 0–9 Innovation Use level, one row per result), `result_actors` (use numbers: how many / women / men / youth per actor type), `investment_discontinued_option` and `result_innovation_merge_split`. The agent could not answer "use level + use numbers" questions (reported by Marc Schut, 13 Oct). The converter is fixed upstream (prms-refresh); this change only restores the tables on DEV.

## What changes (DEV only)
- **`publish-prms-dev.yml` + `.github/scripts/publish-prms-dev.py`** — runs on a push to `feature/innovation-platform-foundation` that changes `.github/prms-publish-dev-request.json`, in the DEV environment with the DEV OIDC role. It reads the global pointer `prdb.manifest.json` (never writes it), downloads and checksums the snapshot it points at, downloads an AES-256-GCM encrypted supplement (an SQLite file with only the missing tables; key only in a temporary DEV environment secret), adds the tables, and proves that every pre-existing table is unchanged (CREATE SQL + row count + per-table row hash), that the restored tables match the supplement's fingerprints, that `pragma quick_check` is ok and that the `result` count/date equal the manifest. It then uploads to a **new immutable prefix** (refuses to reuse one), copies the unchanged search index server-side, and writes the **DEV-only pointer `prdb.manifest.dev.json`**.
- **`deploy.yml` / `ci.yml` (this branch only)** — prefer `prdb.manifest.dev.json` when it exists, else the global pointer. A push that only changes a DEV request file does not redeploy (`paths-ignore`); DEV is redeployed by `workflow_dispatch` after the publish run is green.
- **`dev-chat-e2e.yml` + `.github/scripts/dev-chat-e2e.py`** — opt-in DEV check that asks the deployed app real questions as a synthetic researcher (same in-container pattern as the Opus 5.5 check / QA smoke). The public log shows only cost, turns and tool names; transcripts are encrypted to the requester's RSA key and kept as a 1-day artifact. Its chats are deleted at the end.

## What does not change
- The release line `feat/ia-release-20260914`, `main`, staging and production are untouched. Staging/production never read S3 data: `release-promote.yml` promotes an immutable DEV image (`Dockerfile.prod` bakes `data/prdb.sqlite` into it). **Note:** every DEV image built after the DEV pointer exists contains the restored tables, so promoting such a SHA later also ships them to staging/production — that is the intended path, but it needs a release decision.
- Same data vintage (extracted 13 Sep 2026, data as of 12 Sep 2026); all 203 existing tables are byte-for-byte identical in content, so dashboard numbers do not change.
- No raw data in git, logs or chat. The supplement contained no e-mail addresses, passwords or URL tokens (scanned with the sanitised-edition patterns).

## Rollback (DEV)
Delete `prdb.manifest.dev.json` through a DEV CI job (DEV deploys fall back to the global pointer) and redeploy DEV. The immutable `snapshots/20260913-r2/` prefix can stay for audit.
