# v1.1.0-alpha.1 qualification record

Copy this template for each platform/artifact run. Do not replace `UNTESTED`
with `PASS` unless the named operator performed the check against the exact
artifact hash.

## Release and artifact identity

- Tag: `v1.1.0-alpha.1`
- Commit: `<40-character source commit>`
- Artifact filename: `<exact filename>`
- Artifact size (bytes): `<exact size>`
- SHA-256: `<64 hexadecimal characters>`
- Authenticode status (Windows): `<status or not-applicable>`

## Environment

- Operating-system edition/build: `<exact value>`
- Session/display server: `<X11, Wayland, Windows desktop, or not-applicable>`
- CPU: `<exact value>`
- RAM: `<exact value>`
- GPU/driver: `<exact value or none>`
- Microphone: `<exact value>`
- BetterFingers runtime: `<backend/runtime identifier>`
- Whisper model: `<identifier>`
- LLM model/runtime: `<identifier>`
- TTS model/runtime: `<identifier or not tested>`
- Tester: `<name or stable tester identifier>`
- Date/time with timezone: `<ISO 8601>`

## Results

Use only `PASS`, `FAIL`, or `UNTESTED`.

| Check | Result | Detail |
|---|---|---|
| Checksum verification | UNTESTED | |
| Clean install or ordinary package launch | UNTESTED | |
| First-run onboarding and consent | UNTESTED | |
| Initial model installation | UNTESTED | |
| Interrupted model download and resume | UNTESTED | |
| Restart and cache rediscovery | UNTESTED | |
| Record, transcribe, rewrite, review/edit | UNTESTED | |
| Read aloud | UNTESTED | |
| Placement or copy | UNTESTED | |
| Clipboard restoration | UNTESTED | |
| No unintended Enter or send | UNTESTED | |
| Forced transcription/LLM/placement recovery | UNTESTED | |
| Raw recording and draft recovery | UNTESTED | |
| Microphone unplug/replug | UNTESTED | |
| Sleep/resume | UNTESTED | |
| Privacy wipe | UNTESTED | |
| Uninstall/reinstall or artifact replacement | UNTESTED | |
| Platform injection matrix | UNTESTED | |

Overall result: `UNTESTED`

Notes and known limitations: `<facts only; do not include dictated text,
recordings, clipboard contents, prompts, or private paths>`
