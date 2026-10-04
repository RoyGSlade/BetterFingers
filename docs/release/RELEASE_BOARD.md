# BetterFingers Release Board

Last reviewed: 2026-08-27

This board separates what is public, what is verified only in the development
checkout, and what still requires external or clean-machine qualification.
Historical Alpha 1 gate tables are superseded; they are not evidence for the
current release.

## Release identity

| Surface | Current truth |
|---|---|
| Public release | `v1.1.0-alpha.3` |
| Public tag commit | `7e03d09c2aa3217b8105b70609a198165a193d23` |
| Public release page | <https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.3> |
| Public Windows installer | Signed; SHA-256 `56254ef9c224d3e94366cff4691b4aaff24f6e31fe7f1e7f369cd250cbbcd696` |
| Public Linux artifact | Experimental AppImage |
| Public release workflow | <https://github.com/RoyGSlade/BetterFingers/actions/runs/32281801195> |
| Development checkout | Based on local `main` commit `782c9eaae8c0127201cbbc980293d10a979d2fc7`, with uncommitted stabilization changes |
| Are local fixes in Alpha 3? | **No.** They have not been committed, tagged, or published. |

## Stabilization closeout

| Area | State | Evidence boundary |
|---|---|---|
| Clipboard safety | Done locally | Pointer-width Win32 calls, safe format policy, bounded all-or-nothing restore, focused tests, and a live Windows crash smoke |
| Settings synchronization | Done locally | Profile changes refresh runtime/output before model and Studio consumers, with failure isolation and focused tests |
| Status navigation and accessibility | Done locally | Dead control routed to Runtime Diagnostics; false tab semantics removed; muted contrast raised and tested |
| Backend contracts | Done locally | History deletion reports clear failures; safe archive-link extraction supports Windows privilege fallback without swallowing unrelated errors |
| Bug-report client | Done locally | Review-first report, explicit consent, bounded safe diagnostics, strict structured acknowledgement, no provider credentials in the renderer |
| Bug-report relay | Code complete locally | Strict schema/size limits, rate limiting, content-free dedupe, neutralized Discord delivery, and optional Resend delivery are tested; no public endpoint is deployed |
| Parity inventory | Complete locally | `409 wired / 29 intentional cuts / 0 blocked`; all six former evidence gaps now have executable renderer coverage and canonical regeneration is deterministic |
| Release documentation | Reconciled locally | Public Alpha 3 is distinguished from unpublished development work and network/privacy claims are bounded |

## Remaining qualification gates

| Gate | State | What closes it |
|---|---|---|
| Aggregate Python, renderer, relay, and release-contract suites | Passed locally | Filtered Python: `3242 passed / 16 skipped / 129 deselected`; renderer: `1888 passed / 6 skipped`; relay: `9 passed`; signing contract: `12 passed`; parity validator/regeneration: `8 passed`; package/updater: `33 passed` |
| Fresh signed local Windows package | Passed locally | Authenticode `Valid`, signer `Donaven Crenshaw`; installer SHA-256 `f024f92975eba708d9790182af76bb1b1df57d6e26203b585a428f44fa3de5d5`; combined report verified `342` backend-build, `342` packaged-backend, `351` packaged-native, and `3` final-output records |
| Six former parity evidence rows | Passed locally | `104` focused renderer tests and `8` parity validator/regeneration tests pass; the tracked `409 / 29 / 0` ledger is byte-identical to fresh canonical output |
| Public bug-report relay | Blocked on external configuration | Provision a Cloudflare Worker hostname, Rate Limit binding, KV namespace, Discord webhook, and optional Resend domain/credentials; then perform a live privacy-safe delivery test |
| Clean consumer Windows 11 | Unverified | Install/launch/uninstall on a clean representative machine without developer tooling |
| Hardware/application matrix | Unverified | Exercise representative microphones, audio devices, Discord/OBS, and target games/applications |
| SmartScreen reputation | Unverified external state | Observe the exact downloaded release on consumer Windows; signing alone cannot guarantee reputation |
| WDAC/enterprise policy | Unverified | Test under representative application-control policies |
| Future live update | Not yet possible | Publish a later signed version, then qualify the real Alpha 3-to-next upgrade and rollback/recovery path |
| Commit, push, tag, or publish | Not authorized | Maintainer separately reviews and authorizes the exact staged scope and release action |

## Release decision

The public Alpha 3 remains the latest published build. The development checkout
is now locally code/package verified on this signing host, not a public release.
It must not be called release-ready for broader distribution until the intended
clean-machine and external gates are either passed or explicitly accepted as
documented Alpha risk by the maintainer.

## Next release checklist

1. Review the exact local diff and decide the intended release scope.
2. Perform clean Windows and representative hardware/application checks.
3. Deploy and live-test the relay only after the required accounts, secrets,
   hostname, retention policy, and operator ownership exist.
4. Stage, commit, tag, and publish only after explicit maintainer authorization.

See [known limitations](KNOWN_LIMITATIONS.md) and
[supported platforms](SUPPORTED_PLATFORMS.md) for the user-facing contract.
