"""Build the Rust extension lanestyle._rust for this Python and put it next to the Python package (a development build; the wheels
come from maturin in CI). Run it with the Python that runs lanestyle:

    python rust/lanestyle-py/build.py            # release build
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env = {**os.environ, "PYO3_PYTHON": sys.executable, "CARGO_BUILD_JOBS": os.environ.get("CARGO_BUILD_JOBS", "4")}
subprocess.run(["cargo", "build", "--release", "-p", "lanestyle-py"], cwd=ROOT / "rust", env=env, check=True)
target = Path(env.get("CARGO_TARGET_DIR", ROOT / "rust" / "target")) / "release"
lib = {"linux": "lib_rust.so", "darwin": "lib_rust.dylib", "win32": "_rust.dll"}[sys.platform]
dest = ROOT / "src" / "lanestyle" / ("_rust.pyd" if sys.platform == "win32" else "_rust.abi3.so")
shutil.copyfile(target / lib, dest)
print(f"{dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")
