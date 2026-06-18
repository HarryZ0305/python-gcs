# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect Qt WebEngine resources
datas_we, binaries_we, hiddenimports_we = collect_all('PyQt6.QtWebEngineCore')
datas_wew, binaries_wew, hiddenimports_wew = collect_all('PyQt6.QtWebEngineWidgets')

# Collect pymavlink dialects
datas_pm, binaries_pm, hiddenimports_pm = collect_all('pymavlink')

# Collect QtTextToSpeech if available
datas_tts, binaries_tts, hiddenimports_tts = [], [], []
try:
    import PyQt6.QtTextToSpeech
    datas_tts, binaries_tts, hiddenimports_tts = collect_all('PyQt6.QtTextToSpeech')
    print("PyQt6.QtTextToSpeech successfully collected.")
except ImportError:
    print("PyQt6.QtTextToSpeech not available. Skipping collection.")

# Combine all datas, binaries, hiddenimports
datas = [
    ('gcs/ui/static', 'gcs/ui/static'),
    ('gcs/ui/fonts', 'gcs/ui/fonts'),
] + datas_we + datas_wew + datas_pm + datas_tts

binaries = binaries_we + binaries_wew + binaries_pm + binaries_tts

hiddenimports = [
    'pymavlink.dialects.v20.common',
    'pymavlink.dialects.v20.standard',
    'pymavlink.dialects.v20.px4',
    'pymavlink.dialects.v20.ardupilotmega',
] + hiddenimports_we + hiddenimports_wew + hiddenimports_pm + hiddenimports_tts

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PythonGCS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PythonGCS',
)
