# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：pyinstaller OilLab.spec
# 产物：dist/OilLab.exe（单文件、无控制台窗口），首次启动会在 exe 同目录生成缓存与报告目录。

a = Analysis(
    ['oil_monitor_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('app.ico', '.'), ('templates/磨损分析模板.xlsx', 'templates')],
    hiddenimports=[
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends._backend_tk',
        'docx',
        'openpyxl',
        'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'pandas', 'PyQt5', 'PySide2', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OilLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
