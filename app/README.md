# BetterFingers Electron Shell

## Linux Development

From this directory:

```bash
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r ../requirements.txt
npm install
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

## Notes

- `BETTERFINGERS_PYTHON` overrides the default Python executable used by the Electron dev launcher.
- The Electron shell starts the existing FastAPI backend automatically on port `8000`.
- The legacy Python/PyInstaller app at the repository root is unchanged.
