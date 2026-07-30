# Archive — superseded planning documents

These drove the project before the publish plan existed. They are kept for
history and for the citations in `REMEDIATION_CHANGELOG.md`. **Do not plan work
from them** — several of their open/closed statuses were already wrong when they
were archived (the GPU blocker, the parity totals, the lifespan migration, and
Finding #3-residual are all known-stale; see `QA-DOC-001` through `QA-DOC-003`
in [`../release/QA_NOTES.md`](../release/QA_NOTES.md)).

The current plan is [`../release/PUBLISH_PLAN.md`](../release/PUBLISH_PLAN.md).

| Document | What it was |
|---|---|
| `REMEDIATION_WHATS_LEFT.md` | Forward-looking status of the 9-phase remediation plan. Superseded by `PUBLISH_PLAN.md`, which carries the items that still block publishing and defers the rest explicitly |
| `REMEDIATION_CHANGELOG.md` | Per-chunk history of that same plan — the record of what each remediation commit did |
| `backburn.md` | Older running list of deferred ideas. Its successor is `QA_NOTES.md` §Backlog |
| `accomplish.md` | Early lowercase draft, superseded by the root `ACCOMPLISH.md` (still live, still referenced by `AGENTS.md`) |
| `kickoff-prompts.md`, `worker-prompts.md` | Hand-written prompt scaffolding for the remediation loop, from before the `/hierarchy` and `/collab` skills. Task framing now lives in `PUBLISH_PLAN.md` §3–§4 |

Note: the root `ACCOMPLISH.md` was **not** archived — it is referenced by
`AGENTS.md` and about two dozen other files, and is still current.
