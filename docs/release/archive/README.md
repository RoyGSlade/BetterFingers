# Release archive — historical wave records

These documents recorded the work of Waves 3 through 12A as it happened. They
are kept because they are the evidence trail behind accepted gates, and because
several `DECISIONS.md` entries cite them. **They are not planning documents and
their numbers are not current.**

For what is left to do, read [`../PUBLISH_PLAN.md`](../PUBLISH_PLAN.md). For gate
status, read [`../RELEASE_BOARD.md`](../RELEASE_BOARD.md). File issues in
[`../QA_NOTES.md`](../QA_NOTES.md).

| Document | What it recorded |
|---|---|
| `WAVE3_SERVER_WIRING.md`, `WAVE3_LIBRARY_CONTRACT.md` | Library domain semantics and its server contract |
| `WAVE5_INTEGRATION_DIFFS.md` | Studio, contacts/audience, Settings integration |
| `WAVE7_INTEGRATION_DIFFS.md` | Application context and automatic profiles |
| `WAVE8A_WIRING.md`, `WAVE8B_WIRING.md` | Audio ducking split, AudioInputBroker, capture isolation, privacy lease, wake handoff |
| `WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md` | Whether Wave 8B's isolation model ports to Windows |
| `WAVE9_INTEGRATION_DIFFS.md` | Restricted action engine, application registry, workflow builder |
| `WAVE10_INTEGRATION_DIFFS.md` | Controller, Stream Deck, workflow run executor |
| `WAVE11_INTEGRATION_DIFFS.md` | Version centralization and the default-UI flip |
| `WAVE11_BLOCKERS.md` | The parity blocker analysis. **Self-superseded twice** — its headline 161/10/267 was already wrong when written; the live count is produced by `python3 tools/parity_validator.py` |
| `WAVE12A_UI_CONTROLS.md`, `WAVE12A_PROBE_EVIDENCE.md` | Native form-control styling, the P0 data-root resolver fix, and what the scratch probes did and did not establish |

Still live in `../`, deliberately **not** archived:

- `WAVE10_QA.md` — an operator checklist with an outstanding hardware pass, not history
- `PARITY_INVENTORY.md`, `PACKAGE_BASELINE.md`, `PRESERVATION_BASELINE.md` — regenerated evidence the gates read
- `TRUE_BETTERFINGERS_RELEASE_PLAN.md` — the wave 1–13 scope directive
- `DECISIONS.md`, `KNOWN_LIMITATIONS.md`, `RELEASE_BOARD.md`, `WAKE_MODEL_PROVENANCE.md`
