# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for SkyForge GCS
# Build with: pyinstaller skyforge_gcs.spec

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('skyforge_config.json', '.'),
        ('version.txt', '.'),
        ('PRD_operator_mapping_app.md', '.'),
        ('README.md', '.'),
        ('QUICKSTART.md', '.'),
    ],
    hiddenimports=[
        'pymavlink',
        'pymavlink.dialects.v10.ardupilotmega',
        'scipy.spatial',
        'scipy.spatial.transform',
        'cv2',
        'numpy',
        'pyproj',
        'PIL',
        'matplotlib',
        'matplotlib.backends.backend_pdf',
        'updater',
        'tile_downloader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SkyForge_GCS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
