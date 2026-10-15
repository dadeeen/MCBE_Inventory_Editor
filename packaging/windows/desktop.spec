# Build only in the isolated environment described in docs/desktop.md.
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from scripts.make_release_zip import should_include
from scripts.runtime_layout import iter_runtime_files

data = [(str(ROOT / "pyproject.toml"), ".")]
for path in iter_runtime_files(ROOT):
    relative = path.relative_to(ROOT)
    if relative.parts[0] in {"static", "templates", "mcbe_editor"} and path.suffix != ".py" and should_include(path):
        data.append((str(path), str(relative.parent)))
for package in ("flask", "waitress", "colorama", "pywebview"):
    data += copy_metadata(package, recursive=True)

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    datas=data,
    hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms"],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "cefpython3", "pytest", "numpy", "leveldb", "amulet_nbt"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MCBEInventoryEditor", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="MCBEInventoryEditor", upx=False)
