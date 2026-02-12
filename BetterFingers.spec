# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


_data_packages = [
    "flet",
    "flet_desktop",
    "kokoro_onnx",
    "language_tags",
    "espeakng_loader",
]
_hiddenimport_packages = [
    "flet",
    "flet_desktop",
    "kokoro_onnx",
    "language_tags",
    "espeakng_loader",
]

_dynamic_datas = []
for _pkg in _data_packages:
    _dynamic_datas.extend(collect_data_files(_pkg))

_dynamic_hiddenimports = []
for _pkg in _hiddenimport_packages:
    _dynamic_hiddenimports.extend(collect_submodules(_pkg))
_dynamic_hiddenimports = sorted(set(_dynamic_hiddenimports))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
        ('Tutorial_Script.txt', '.'),
        ('images', 'images'),
    ] + _dynamic_datas,
    hiddenimports=_dynamic_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'torchaudio',
        'transformers',
        'accelerate',
        'triton',
        'tensorflow',
        'jax',
        'matplotlib',
        'IPython',
        'notebook',
        'pandas',
        'sentencepiece',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BetterFingers',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BetterFingers',
)
