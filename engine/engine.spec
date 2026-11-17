# PyInstaller spec for the engine sidecar (one-folder build: starts fast, signs cleanly).
# Build with scripts/build_engine.sh.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [("culler/db/migrations", "culler/db/migrations"), ("culler/assets/models", "culler/assets/models")]
binaries, hiddenimports = [], ["culler.api.app", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]
# torchvision must be collected whole: without its compiled operators, importing it (which
# open_clip does) fails inside the packaged app with "operator torchvision::nms does not exist".
for package in ("mediapipe", "open_clip", "torchvision", "rawpy", "pillow_heif", "xxhash"):
    d, b, h = collect_all(package)
    datas += d; binaries += b; hiddenimports += h
datas += collect_data_files("sklearn")

a = Analysis(["run_engine.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "torchaudio"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="culler-engine", console=True, target_arch="arm64",
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="culler-engine")
