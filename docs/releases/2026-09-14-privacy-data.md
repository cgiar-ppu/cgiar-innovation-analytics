# Privacy and latest-snapshot follow-up — 2026-09-14

Jose's production review requires **own chats only for every role**, including administrators. The former administrator legacy exception is removed. Missing owners fail closed, unknown WebSocket resume IDs are denied, and conversation search and agent history retrieval/list/search are owner-scoped. The legacy archive remains stored, with no automatic reassignment. Hidden app databases cannot be downloaded through Files; chat-export files require their originating session's owner. Stateless paid queries and PRMS dashboard APIs now require authentication.

The application still executes agents in a shared workspace; these changes do not constitute a per-user OS/container sandbox or a public-data-only external tier.

All three environments now run application image **c7c9c9c7cbc81d3902a60c151540be1a2e82672a** with Sonnet 5 default, the verified **2026-09-13** PRMS snapshot (data-as-of **2026-09-12**, **32,203 raw result rows**, **203 SQLite tables**) and its rebuilt **23,201-record** search index. Published source SHA-256: `7e30ce9dbf0a5e9f29b37ac24e89ae6f3f80e955a9d78d40774cdb0ebf79a118`. These dataset counts are not a canonical innovation total.

The previously unmerged September 7 snapshot-awareness changes were integrated, with current auth/model code preserved. A runtime manifest explicitly identifies the extraction date; dashboard, snapshot API, agent context, voice catalog and export footers use it. Open Reporting 2026/IPSR 2026 phases remain provisional and excluded from default dashboard reporting. Snapshot and index hashes plus result count/update date are verified before building each new image.

AWS publication uses the isolated `publish-prms.yml` lane: an AES-256-GCM encrypted transfer, decrypt/verify in the authenticated DEV Actions job, upload immutable objects under `s3://cgiar-ia-artifacts-972793825893/snapshots/20260913/`, then update the versioned `prdb.manifest.json` pointer. No raw data is committed or posted to Slack. The temporary transfer endpoint and secret were removed after successful publication. The prior `prdb.sqlite` object is retained for rollback; the new build reads the manifest/prefix, not that old fixed key.

The local daily refresh continues to maintain `/Users/smithai/workspace/coding/PRMSDB/current`. Hosted refreshes use a separate controlled publish/build/promotion; this change does not silently auto-deploy production on every local refresh. A future publication needs a fresh encrypted transfer/key and matching metadata; an old one-time request should not be blindly replayed.

Validation: 454 backend tests passed, 13 opt-in live-harness cases skipped; 175 frontend tests and build passed. Hosted checks in DEV/staging/production verified source dates/rows, matching index, keyword retrieval, dashboard, voice catalog and an actual default Sonnet query. Final staging/production also verified admin legacy/unowned denial, anonymous search rejection, hidden-database rejection, invitation activation/revocation, cross-user history/export denial, and watermark plus snapshot-date presence in MD/HTML/DOCX/real PDF exports.

Evidence runs: privacy DEV 34793656243, staging 34793829179 / 34793979779, production 34794100983 / 34794315021; data publication 34794218421; data DEV 34794573861 / 34794964596; staging 34795114491 / 34795390898; production 34795472314 / 34795693880.

Commitments review: most July/August asks were already shipped. Direct public result PDFs still need a confirmed working source (two provided reference links, including phase=6, returned 404); current public dashboard references remain. Canonical counting, reconciled financial figures, and the separately scoped isolation/external-tier/reviewer/Nikki-onboarding decisions remain explicit. No email was sent to Marc or Jules.

Reports and the unsent Marc→Jules draft: `/Users/smithai/workspace/outputs/innovation-analytics-followup-20260914/`.
