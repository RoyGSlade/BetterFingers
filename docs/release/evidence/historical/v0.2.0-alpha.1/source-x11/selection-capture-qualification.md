# BetterFingers selected-text qualification

- Overall: **PASS**
- Generated (UTC): `2026-08-04T08:02:17.716819+00:00`
- Platform/session: `linux / x11`
- Sentinel: `78 characters; sha256 472278aafcc725e8f54ad8a2e18e18b5f10a26249848624804255b9b3b1da4b9`
- Observed workflow checks: `8` pass, `0` fail, `0` untested

> PASS means the operator observed the expected result. UNTESTED is not a pass.
> This report intentionally contains no selected text, rewritten text, or clipboard contents.

## Capability snapshot

| Capability | Backend | Available | Required |
|---|---|---:|---|
| Clipboard | `xclip` | `True` | xclip |
| Copy trigger | `xdotool` | `True` | native |
| Global hotkey | `X11-global-hotkey` | `True` | DISPLAY |
| Typing/injection | `xdotool` | `True` | xdotool |

## Checks

| Check | Status | Detail |
|---|---|---|
| platform/session detected | **PASS** | linux / x11 |
| clipboard backend available | **PASS** | xclip detected |
| copy trigger backend available | **PASS** | xdotool |
| global hotkey path available | **PASS** | X11-global-hotkey |
| typing/injection path available | **PASS** | xdotool |
| selected-text capture | **PASS** | operator observed the expected result |
| rewrite opens review-only draft | **PASS** | operator observed the expected result |
| clipboard is restored | **PASS** | operator observed the expected result |
| no automatic send occurs | **PASS** | operator observed the expected result |
| selected-text capture | **PASS** | operator observed the expected result |
| rewrite opens review-only draft | **PASS** | operator observed the expected result |
| clipboard is restored | **PASS** | operator observed the expected result |
| no automatic send occurs | **PASS** | operator observed the expected result |

## Run metadata

| Field | Value | Status |
|---|---|---|
| OS build | `Linux-7.0.0-28-generic-x86_64-with-glibc2.39` | **PASS** |
| Python version | `3.12.3` | **PASS** |
| Repository commit | `ef1ed0ded80aede0ab97838acc138283f8378376` | **PASS** |
| App version | `0.2.0-alpha.1` | **PASS** |
| Model identifier | `gemma-4-e2b-q4` | **PASS** |
| Runtime identifier | `llama-server-build-9936-64c8b7db7` | **PASS** |
| Artifact | `UNTESTED` | **UNTESTED** |

## Per-target workflow outcomes

| Target application | Check | Status | Detail |
|---|---|---|---|
| a GTK/Qt editor (for example Kate or gedit) | selected-text capture | **PASS** | operator observed the expected result |
| a GTK/Qt editor (for example Kate or gedit) | rewrite opens review-only draft | **PASS** | operator observed the expected result |
| a GTK/Qt editor (for example Kate or gedit) | clipboard is restored | **PASS** | operator observed the expected result |
| a GTK/Qt editor (for example Kate or gedit) | no automatic send occurs | **PASS** | operator observed the expected result |
| a browser text area | selected-text capture | **PASS** | operator observed the expected result |
| a browser text area | rewrite opens review-only draft | **PASS** | operator observed the expected result |
| a browser text area | clipboard is restored | **PASS** | operator observed the expected result |
| a browser text area | no automatic send occurs | **PASS** | operator observed the expected result |

## Operator safety

- Keep private application text out of this report; use only the supplied sentinel.
- Do not accept, apply, send, or otherwise deliver the rewritten draft during the check.
- Verify clipboard restoration privately, without copying its contents into a terminal or report.
- On Wayland, a missing compositor/global-hotkey path is UNTESTED for the product flow; do not convert it to PASS because wl-clipboard is installed.

## Reproduction

```text
python3 tools/selection_capture_qualification.py
```
