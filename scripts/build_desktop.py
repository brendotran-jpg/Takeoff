"""Build the desktop app with PyInstaller.

    python scripts/build_desktop.py            # -> dist/Takeoff/ (folder build, fast start)
    python scripts/build_desktop.py --onefile  # -> single executable (slower start; AV false positives more likely)

Build on the OS you are targeting: PyInstaller does not cross-compile.
Windows -> dist/Takeoff/Takeoff.exe ; macOS -> dist/Takeoff.app ; Linux -> dist/Takeoff/Takeoff
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
SEP = os.pathsep


def main():
    onefile = "--onefile" in sys.argv
    os.chdir(ROOT)
    for d in ("build", "dist"):
        shutil.rmtree(d, ignore_errors=True)
    args = [
        "desktop.py",
        "--name", "Takeoff",
        "--noconfirm",
        "--windowed",
        "--onefile" if onefile else "--onedir",
        "--add-data", f"static{SEP}static",
        "--add-data", f"rules/schema.json{SEP}rules",
        "--add-data", f"rules/starter_rules.yaml{SEP}rules",
        # uvicorn is configured explicitly in desktop.py (asyncio + h11), so only these are needed
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.lifespan.off",
        "--hidden-import", "uvicorn.loops.asyncio",
        "--collect-submodules", "app",
        # keep the bundle lean
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pytest",
    ]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "local.takeoff.desktop"]
    PyInstaller.__main__.run(args)

    exe = {"win32": ROOT / "dist" / "Takeoff" / "Takeoff.exe",
           "darwin": ROOT / "dist" / "Takeoff.app" / "Contents" / "MacOS" / "Takeoff"}.get(
        sys.platform, ROOT / "dist" / "Takeoff" / "Takeoff")
    if onefile:
        exe = ROOT / "dist" / ("Takeoff.exe" if sys.platform == "win32" else "Takeoff")
    print(f"\nBuilt: {exe}\nRunning bundle self-test…")
    tmp = ROOT / "build" / "selftest.qto"
    r = subprocess.run([str(exe), str(tmp), "--self-test"], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "TAKEOFF_CONFIG": str(ROOT / "build" / "selftest-config")})
    print(r.stdout or r.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
