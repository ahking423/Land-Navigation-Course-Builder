#!/usr/bin/env python3
"""
build.py — build standalone executables for the Land Nav Course Generator.

Produces two onefile executables in dist/:
  - landnav-cli(.exe)        : CLI, from landnav_generator.py
  - LandNavGenerator(.exe)   : GUI, from landnav_gui.py (windowed, no console)

Both are named with an OS suffix so cross-platform CI builds don't collide
when uploaded together to a GitHub Release, e.g.:
  landnav-cli-linux, landnav-cli-macos, landnav-cli-windows.exe
  LandNavGenerator-linux, LandNavGenerator-macos, LandNavGenerator-windows.exe

Usage:
    pip install -r requirements.txt
    pip install pyinstaller
    python build.py

Notes on why this isn't just a plain `pyinstaller landnav_gui.py`:
  - `pyproj`, `matplotlib`, and `folium` all ship non-code data files
    (proj.db, mpl-data, HTML/JS templates) that need `--collect-all` too.

Earlier versions of this project used the `mgrs` package (native GeoTrans
C extension) and `contextily`/`rasterio` (GDAL bindings) for MGRS parsing
and satellite basemaps respectively. Both wrap compiled native code that
PyInstaller can't reliably freeze — failures were inconsistent across
machines (worked on the dev box, broke on a clean install) because a dev
machine often has other copies of these native libraries already on its
search path (conda, QGIS, GIS tooling, etc.) masking the real bundling
gap. Both were replaced with pure-Python implementations:
  - `mgrs` -> `pygeodesy` (pure Python MGRS<->lat/lon conversion)
  - `contextily`/`rasterio` -> a small hand-rolled XYZ tile fetcher in
    map_generator.py, using only `urllib` (stdlib) and `Pillow`
    (already a matplotlib dependency)
This removes the entire class of "works on my machine, not on a clean
PC" bundling bug for this project — there's no native/compiled
dependency left that needs special PyInstaller handling.
"""

import os
import platform
import subprocess

OS_TAG = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
if OS_TAG is None:
    raise SystemExit(f"Unsupported OS for build: {platform.system()}")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "app.ico")

COLLECT_ALL = [
    "pygeodesy",
    "pyproj",
    "folium",
    "matplotlib",
    "matplotlib_scalebar",
    "reportlab",
    "PIL",
]


def run_pyinstaller(entry: str, name: str, windowed: bool, extra_hidden=None):
    args = ["pyinstaller", "--onefile", "--noconfirm", "--name", name]
    if windowed:
        args.append("--windowed")
    for mod in COLLECT_ALL:
        args += ["--collect-all", mod]
    if os.path.isfile(ICON_PATH):
        # Windows uses this .ico directly; PyInstaller auto-converts it to
        # .icns for macOS (via Pillow, already pulled in by matplotlib);
        # Linux ignores --icon with a harmless warning (no embedded icon
        # support in ELF executables).
        args += ["--icon", ICON_PATH]
    else:
        print(f"NOTE: {ICON_PATH} not found — building without a custom icon.")
    for h in extra_hidden or []:
        args += ["--hidden-import", h]
    args.append(entry)
    print("\n>>>", " ".join(args), "\n")
    subprocess.run(args, check=True)


def main():
    run_pyinstaller(
        "landnav_generator.py", f"landnav-cli-{OS_TAG}",
        windowed=False, extra_hidden=["map_generator"],
    )
    run_pyinstaller(
        "landnav_gui.py", f"LandNavGenerator-{OS_TAG}",
        windowed=True, extra_hidden=["map_generator", "landnav_generator"],
    )
    print("\nBuild complete. Executables are in dist/.")


if __name__ == "__main__":
    main()
