# DEV E2E probes (not triggered from here)

Ready-made request files for `.github/workflows/dev-chat-e2e.yml`. A push that
changes **`.github/dev-e2e-request.json`** on the DEV branch runs the probe; files
in this folder never trigger anything.

To run one: wait until the DEV deploy of the change under test is green
(`/api/health` shows the new commit), then copy the probe over
`.github/dev-e2e-request.json` (bump `sequence`) in its own commit and push. The
run fails if a question's `expect` check fails; the encrypted transcript is
uploaded either way and opens only with the private key matching
`public_key_pem` (kept outside the repository).

| Probe | What it proves |
|---|---|
| `external-role-budget-refusal.json` | An `external` account asking for USD budgets / allocations is declined ("not available in this external view", no amounts), a normal innovation-use question still works, and a researcher still reads the budget tables. |
| `external-view-freetext.json` | After the verification-round fixes: an `external` account gets no currency amount from internal project narratives (word-for-word quote), from a result description (amounts read "[amount withheld in external view]") or in an Excel export of `clarisa_projects` with all columns (the harness reads the produced file back); budget asks are still declined, a normal innovation-use question still works, and a researcher still gets budget amounts. |
