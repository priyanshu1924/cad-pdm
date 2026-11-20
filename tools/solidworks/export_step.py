#!/usr/bin/env python3
"""Batch-export STEP files from SolidWorks parts and assemblies (Windows only).

Run this on a Windows PC with SolidWorks installed. For every .SLDPRT / .SLDASM
under cad/, it writes <same name>.step next to it when the STEP is missing or
older than the SolidWorks file. Then commit as usual and CI makes the previews.

    pip install pywin32
    python tools/solidworks/export_step.py            # export stale ones
    python tools/solidworks/export_step.py --all      # re-export everything
    python tools/solidworks/export_step.py --dry-run  # just list what it would do
    python tools/solidworks/export_step.py cad/PN-1001_base-plate   # one folder

STEP settings (AP214 vs AP242, etc.) come from SolidWorks:
Tools > Options > System Options > Export > STEP. Set them once and they apply here.

Files already open in your SolidWorks session are exported but left open.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# SolidWorks API constants (swconst)
SW_DOC_PART, SW_DOC_ASSEMBLY = 1, 2
SW_OPEN_SILENT, SW_OPEN_READONLY = 1, 2
SW_SAVEAS_CURRENT_VERSION = 0
SW_SAVEAS_SILENT, SW_SAVEAS_COPY = 1, 2
DOC_TYPES = {".sldprt": SW_DOC_PART, ".sldasm": SW_DOC_ASSEMBLY}


def find_natives(paths: list[Path]) -> list[Path]:
    out = []
    for base in paths:
        files = [base] if base.is_file() else base.rglob("*")
        out += [f for f in files
                if f.is_file() and f.suffix.lower() in DOC_TYPES and not f.name.startswith("~$")]
    # Parts before assemblies, so an assembly's parts are exported first
    return sorted(set(out), key=lambda f: (DOC_TYPES[f.suffix.lower()], str(f).lower()))


def step_for(native: Path) -> Path:
    for ext in (".step", ".STEP", ".stp", ".STP"):  # reuse an existing STEP's name
        if native.with_suffix(ext).exists():
            return native.with_suffix(ext)
    return native.with_suffix(".step")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _commit_time(p: Path) -> int:
    out = _git("log", "-1", "--format=%ct", "--", str(p.relative_to(ROOT)))
    return int(out) if out else 0


def is_stale(native: Path, step: Path) -> bool:
    """Is the STEP missing or older than the SolidWorks file?

    Uses modification times when either file has uncommitted changes, and commit
    times otherwise (a fresh clone gives every file the same, meaningless mtime)."""
    if not step.exists():
        return True
    dirty = _git("status", "--porcelain", "--", str(native.relative_to(ROOT)), str(step.relative_to(ROOT)))
    if dirty:
        return step.stat().st_mtime < native.stat().st_mtime
    return _commit_time(step) < _commit_time(native)


def connect():
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        sys.exit("This needs pywin32 on Windows:  pip install pywin32")
    sw = win32com.client.Dispatch("SldWorks.Application")
    return sw, pythoncom, win32com.client


def export_one(sw, pythoncom, client, native: Path, step: Path) -> str | None:
    """Export one file. Returns an error message, or None on success."""
    path = str(native.resolve())
    doc = sw.GetOpenDocumentByName(path)
    opened_here = doc is None
    if opened_here:
        errors = client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = sw.OpenDoc6(path, DOC_TYPES[native.suffix.lower()],
                          SW_OPEN_SILENT | SW_OPEN_READONLY, "", errors, warnings)
        if doc is None:
            return f"SolidWorks could not open it (error code {errors.value})"
    try:
        before = step.stat().st_mtime if step.exists() else 0
        result = doc.SaveAs3(str(step.resolve()), SW_SAVEAS_CURRENT_VERSION,
                             SW_SAVEAS_SILENT | SW_SAVEAS_COPY)
        if not step.exists() or step.stat().st_mtime <= before:
            return f"SolidWorks did not write the STEP file (SaveAs3 returned {result})"
        return None
    finally:
        if opened_here:
            sw.CloseDoc(doc.GetTitle())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path, help="files or folders (default: cad/)")
    ap.add_argument("--all", action="store_true", help="re-export even if the STEP is up to date")
    ap.add_argument("--dry-run", action="store_true", help="list what would be exported")
    a = ap.parse_args()

    natives = find_natives(a.paths or [ROOT / "cad"])
    todo = [(n, step_for(n)) for n in natives if a.all or is_stale(n, step_for(n))]
    print(f"{len(natives)} SolidWorks files, {len(todo)} need a STEP export")
    if a.dry_run or not todo:
        for n, s in todo:
            print(f"  would export {n.relative_to(ROOT)} -> {s.name}")
        return 0

    sw, pythoncom, client = connect()
    failed = 0
    for i, (n, s) in enumerate(todo, 1):
        t = time.time()
        err = export_one(sw, pythoncom, client, n, s)
        label = f"[{i}/{len(todo)}] {n.relative_to(ROOT)}"
        if err:
            failed += 1
            print(f"FAILED {label}: {err}")
        else:
            print(f"ok     {label} -> {s.name} ({time.time() - t:.1f}s)")
    print(f"\nDone: {len(todo) - failed} exported, {failed} failed.")
    if len(todo) - failed:
        print("Next: git add the .step files and commit them with your SolidWorks changes.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
