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
