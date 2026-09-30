# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # config_local.py e so do ambiente de desenvolvimento (planilha/Google de TESTE): se entrasse no
    # .exe, o app instalado usaria os dados de teste no lugar dos reais
    excludes=['config_local'],
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
    name='GestaoFinanciamentos',
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
    icon=['desktop/assets/icone_app.ico'],
)
