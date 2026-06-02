# BetterFingers Electron Shell

## Linux Development

If you are working from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cd app
npm install
npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

If you are already inside `app/`, use `../requirements.txt` instead of `requirements.txt`.

## Notes

- `BETTERFINGERS_PYTHON` overrides the default Python executable used by the Electron dev launcher.
- `npm run fix:electron` forces Electron's Linux binary download if npm's install script approval does not run it automatically.
- The Electron shell starts the existing FastAPI backend automatically on port `8000`.
- The legacy Python/PyInstaller app at the repository root is unchanged.

## Linux llama-server

BetterFingers looks for a repo-local Linux llama-server binary at:

```bash
.betterfingers/llama-server/bin/llama-server
```

If you already have a `llama-server` binary:

```bash
python tools/setup_linux_llama_server.py --from /path/to/llama-server
```

If you have a local llama.cpp checkout:

```bash
git clone https://github.com/ggml-org/llama.cpp .betterfingers/llama.cpp
python tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp
```

For CUDA builds, pass extra CMake flags:

```bash
python tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp --cmake-arg=-DGGML_CUDA=ON
```

You can also point BetterFingers at any existing binary:

```bash
export BETTERFINGERS_LLAMA_SERVER=/path/to/llama-server
```

Optional local model override:

```bash
export BETTERFINGERS_MODEL_PATH=/path/to/model.gguf
```
