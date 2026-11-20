#!/usr/bin/env python3
"""Build the static viewer site into _site/ from previews/.

Converts each preview STL to GLB (for the in-browser viewer) and copies the
manifest and the page. Needs only numpy, and no Git LFS downloads.

    python scripts/build_site.py
    python -m http.server -d _site 8000    # then open http://localhost:8000
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stl_tools import read_stl, write_glb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"


def main() -> int:
    manifest_path = ROOT / "previews" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"parts": []}

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "models").mkdir(parents=True)
    shutil.copy(ROOT / "site" / "index.html", OUT / "index.html")

    for part in manifest["parts"]:
        stl = part.get("preview")
        if not stl or not (ROOT / stl).exists():
            continue
        glb_rel = Path("models") / Path(part["path"]).relative_to("cad").with_suffix(".glb")
        write_glb(read_stl(ROOT / stl), OUT / glb_rel)
        part["model"] = glb_rel.as_posix()

    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    manifest["repo_url"] = f"{server}/{repo}" if repo else ""
    manifest["branch"] = os.environ.get("GITHUB_REF_NAME", "main")
    (OUT / "manifest.json").write_text(json.dumps(manifest))
    (OUT / ".nojekyll").write_text("")
    print(f"built {OUT.relative_to(ROOT)}/ with {sum('model' in p for p in manifest['parts'])} models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
