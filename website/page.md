BetterFingers is a private desktop speech editor. It captures speech, transcribes it locally, refines the result with a local language model persona, gives the user a review step, and places approved text into the focused application.

## Current capabilities

The current application includes local speech capture and Whisper-based transcription, local LLM refinement with personas, formatting commands, a personal dictionary, text macros, an editable review overlay, text-to-speech read-back, cross-application text placement, searchable history, recording recovery, privacy reporting, and data-wipe controls. Hardware-aware model recommendations help identify local model tiers for a machine.

## Boundaries and supported platforms

The project documents Windows and Linux support. Linux X11 is the primary path described by the repository; global hotkeys and text injection on Wayland are best effort with capability reporting. macOS is not supported by the current project evidence.

BetterFingers is local-first: speech-to-text, language-model refinement, and text-to-speech processing are intended to run on the user's machine. A local language-model runtime and suitable model files are required for refinement, and the resource footprint varies with the selected hardware tier.

## Running from source

The available way to run BetterFingers is from a source checkout. On Linux, the repository documents a hardware-aware environment setup followed by the Electron development command:

```bash
python3 tools/setup_venv.py
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

The local language-model runtime must also be provisioned as described in the repository README. These instructions describe source-running only; they do not represent a packaged artifact or hosted demo.

## Release status

BetterFingers is pre-release, with alpha work in progress. The repository describes a real application and an extensive test surface, but it is not a tagged public release. Release qualification, reliability evidence, and platform compatibility work remain in the project roadmap.
