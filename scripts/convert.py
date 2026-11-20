#!/usr/bin/env python3
"""Generate 3D previews and a parts manifest from the STEP files under cad/.

Two steps, so CI only downloads (from Git LFS) the STEP files that changed:

    python scripts/convert.py plan    # prints STEP paths whose preview is stale
    git lfs pull --include="<those paths>"
    python scripts/convert.py build   # meshes them and rewrites previews/manifest.json

Change detection uses the SHA-256 that Git LFS already stores in each pointer
file, so `plan` works without downloading anything.

Options:
    --all        rebuild every preview, not just stale ones
    --no-mesh    skip meshing (metadata + history only; handy for testing)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stl_tools import mesh_stats, read_stl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAD = ROOT / "cad"
PREVIEWS = ROOT / "previews"
MANIFEST = PREVIEWS / "manifest.json"

STEP_EXT = {".step", ".stp"}
NATIVE_EXT = {".sldprt", ".sldasm", ".slddrw", ".f3d", ".f3z", ".iges", ".igs", ".x_t", ".pdf", ".dxf", ".dwg"}
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"

# Meshing settings: coarse on purpose, previews should stay small.
TOLERANCE_MM = 0.2
ANGULAR_TOL_RAD = 0.3
MAX_STL_BYTES = 20 * 1024 * 1024
HISTORY_LIMIT = 15


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def step_files() -> list[Path]:
    return sorted(p for p in CAD.rglob("*") if p.is_file() and p.suffix.lower() in STEP_EXT)


def is_lfs_pointer(p: Path) -> bool:
    with p.open("rb") as f:
        return f.read(len(LFS_HEADER)) == LFS_HEADER


def content_sha256(p: Path) -> str:
    """SHA-256 of the real file content, read from the LFS pointer if needed."""
    if is_lfs_pointer(p):
        m = re.search(r"oid sha256:([0-9a-f]{64})", p.read_text(errors="ignore"))
        if m:
            return m.group(1)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preview_path(step: Path) -> Path:
    return PREVIEWS / step.relative_to(CAD).with_suffix(".stl")


def load_manifest() -> dict:
    if MANIFEST.exists():
        return {p["path"]: p for p in json.loads(MANIFEST.read_text()).get("parts", [])}
    return {}


# ---------------------------------------------------------------- STEP header

_STR = r"'((?:[^']|'')*)'"


def _strings(s: str) -> list[str]:
    return [m.replace("''", "'") for m in re.findall(_STR, s)]


def step_metadata(p: Path) -> dict:
    """Read the human-readable bits of a STEP file: header and product names."""
    text = p.read_bytes()[: 8 * 1024 * 1024].decode("latin-1", errors="ignore")
    meta: dict = {}
    m = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", text, re.S)
    if m:
        s = _strings(m.group(1))
        keys = ["file_name", "timestamp", "author", "organization", "preprocessor", "originating_system"]
        meta.update({k: v for k, v in zip(keys, s) if v.strip()})
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*" + _STR, text)
    if m:
        meta["schema"] = m.group(1).split()[0]
    products = []
    for pm in re.finditer(r"=\s*PRODUCT\s*\(\s*" + _STR + r"\s*,\s*" + _STR, text):
        name = (pm.group(2) or pm.group(1)).replace("''", "'").strip()
        if name and name not in products:
            products.append(name)
    meta["products"] = products
    return meta


# ------------------------------------------------------------------- git info

def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def history(p: Path) -> list[dict]:
    out = git("log", "--follow", f"-n{HISTORY_LIMIT}", "--format=%H%x1f%aI%x1f%an%x1f%s", "--", rel(p))
    hist = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            sha, date, author, subject = parts
            hist.append({"commit": sha, "date": date, "author": author, "message": subject})
    return hist


def lock_owners() -> dict[str, str]:
    """Path -> who holds its Git LFS lock (one call; empty if offline)."""
    out = git("lfs", "locks", "--json")
    try:
        locks = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return {}
    return {l["path"]: l.get("owner", {}).get("name", "someone") for l in locks}


# -------------------------------------------------------------------- meshing

def mesh(step: Path, out: Path) -> None:
    import cadquery as cq  # imported lazily: only needed in CI

    shape = cq.importers.importStep(str(step))
    out.parent.mkdir(parents=True, exist_ok=True)
    tol, ang = TOLERANCE_MM, ANGULAR_TOL_RAD
    for _ in range(3):
        cq.exporters.export(shape, str(out), exportType="STL", tolerance=tol, angularTolerance=ang)
        if out.stat().st_size <= MAX_STL_BYTES:
            return
        tol, ang = tol * 3, min(ang * 2, 1.0)  # too big: try a coarser mesh
    print(f"::warning file={rel(step)}::Preview is still over {MAX_STL_BYTES // 2**20} MB at the coarsest setting")


# ---------------------------------------------------------------------- main

def stale(steps: list[Path], manifest: dict, rebuild_all: bool) -> list[Path]:
    todo = []
    for s in steps:
        entry = manifest.get(rel(s))
        if (rebuild_all or not entry or entry.get("sha256") != content_sha256(s)
                or entry.get("error") or not preview_path(s).exists()):
            todo.append(s)
    return todo


def build(rebuild_all: bool, do_mesh: bool) -> int:
    old = load_manifest()
    steps = step_files()
    todo = set(stale(steps, old, rebuild_all))
    parts, failures = [], 0
    locks = lock_owners()

    for s in steps:
        key = rel(s)
        entry = dict(old.get(key, {}))
        entry["path"] = key
        entry["name"] = s.stem
        entry["folder"] = s.parent.relative_to(CAD).as_posix()
        entry["sha256"] = content_sha256(s)
        entry["related_files"] = sorted(
            rel(f) for f in s.parent.iterdir()
            if f.is_file() and f.suffix.lower() in NATIVE_EXT
        )
        out = preview_path(s)

        if s in todo:
            if is_lfs_pointer(s):
                print(f"::warning file={key}::Content not downloaded (run git lfs pull); skipped")
                entry["error"] = "STEP content not downloaded from Git LFS"
            else:
                entry.pop("error", None)
                entry["size_bytes"] = s.stat().st_size
                entry["step"] = step_metadata(s)
                if do_mesh:
                    try:
                        mesh(s, out)
                        print(f"meshed  {key}")
                    except Exception as e:  # keep going; record the problem
                        failures += 1
                        entry["error"] = f"Could not convert: {e}"
                        print(f"::error file={key}::Could not convert STEP: {e}")

        if out.exists():
            entry["preview"] = rel(out)
            if s in todo or "mesh" not in entry:
                entry["mesh"] = mesh_stats(read_stl(out))
        else:
            entry.pop("preview", None)

        entry["history"] = history(s)
        owner = locks.get(key)
        if owner:
            entry["locked_by"] = owner
        else:
            entry.pop("locked_by", None)
        parts.append(entry)

    # Remove previews whose STEP file was deleted or renamed.
    live = {preview_path(s) for s in steps}
    for stl in PREVIEWS.rglob("*.stl"):
        if stl not in live:
            stl.unlink()
            print(f"removed {rel(stl)}")

    PREVIEWS.mkdir(exist_ok=True)
    new_text = json.dumps({"version": 1, "parts": parts}, indent=2) + "\n"
    if not MANIFEST.exists() or MANIFEST.read_text() != new_text:
        MANIFEST.write_text(new_text)
        print(f"wrote   {rel(MANIFEST)} ({len(parts)} parts)")
    return 1 if failures and failures == len(todo) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "build"])
    ap.add_argument("--all", action="store_true", help="rebuild every preview")
    ap.add_argument("--no-mesh", action="store_true", help="skip meshing (metadata only)")
    a = ap.parse_args()

    if a.command == "plan":
        for s in stale(step_files(), load_manifest(), a.all):
            print(rel(s))
        return 0
    return build(a.all, not a.no_mesh)


if __name__ == "__main__":
    sys.exit(main())
