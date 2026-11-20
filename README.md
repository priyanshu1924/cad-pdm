# CAD repo with automatic 3D previews

A lightweight PDM built on Git + Git LFS:

- **Versioning and locking** for SolidWorks, Fusion and STEP files (Git LFS, lockable)
- **Automatic 3D previews.** Every STEP file under `cad/` gets a mesh in `previews/`,
  which GitHub shows in its built-in 3D viewer, including side-by-side diffs between versions
- **Parts manifest.** `previews/manifest.json` lists every part with its size, STEP
  header info, related native files, lock owner and revision history
- **Optional viewer site** (GitHub Pages): searchable part list, 3D view and history,
  for people without CAD or a Git client

## One-time setup

1. Create an **empty private repo** on GitHub and push this folder to it:
   ```bash
   git init -b main
   git lfs install
   git add . && git commit -m "Initial CAD repo"
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```
2. In the repo, open **Settings → Actions → General → Workflow permissions** and select
   **Read and write permissions**, so the workflow can commit previews.
3. *(Optional)* Viewer site: **Settings → Pages → Source: GitHub Actions**, then
   **Settings → Secrets and variables → Actions → Variables** and add `ENABLE_PAGES` = `true`.
   ⚠️ On most GitHub plans **a Pages site is public even if the repo is private.**
   Don't turn this on for proprietary parts unless you're on GitHub Enterprise Cloud
   (which supports private Pages). Instead, view the site locally (see below).

## SolidWorks → STEP

Nothing open-source can read SolidWorks geometry, so STEP exports have to come from
SolidWorks itself. Three things help with that:

- **Batch exporter** (Windows PC with SolidWorks): double-click
  `tools/solidworks/export_step.bat`, or run
  `python tools/solidworks/export_step.py` (needs `pip install pywin32`). It exports a
  STEP next to every `.SLDPRT`/`.SLDASM` whose STEP is missing or out of date. Use
  `--dry-run` to preview and `--all` to re-export everything. STEP options (AP214/AP242)
  come from SolidWorks → Tools → Options → Export.
- **Commit check**: run `git config core.hooksPath tools/hooks` once per clone. Commits
  that change a SolidWorks file without its STEP are then stopped
  (`git commit --no-verify` skips the check).
- **Flags in the manifest and viewer**: SolidWorks files with no STEP, or with a STEP older
  than the native file, are listed with a warning so nothing goes missing.

## Daily workflow

```bash
git pull
git lfs lock cad/PN-1001_base-plate/PN-1001_base-plate.SLDPRT   # claim the file
# ...edit in SolidWorks and save...
tools/solidworks/export_step.bat                                # or File → Save As → STEP
git add cad/PN-1001_base-plate/
git commit -m "PN-1001 rev B: widen mounting slots to 6.5 mm"
git push
git lfs unlock cad/PN-1001_base-plate/PN-1001_base-plate.SLDPRT
```

About a minute after you push, the **CAD previews** action commits the new mesh. Open
`previews/PN-1001_base-plate/PN-1001_base-plate.stl` on GitHub to rotate it, or open the
preview commit's diff to compare it against the old version.

- `git lfs locks` shows who has what checked out.
- Lockable files are read-only on disk until you lock them; that's intentional.
- **Always commit a STEP export with native changes.** Only STEP files get previews,
  and they're the format anyone can open.

## Viewing the site locally

```bash
python scripts/build_site.py          # needs numpy only
python -m http.server -d _site 8000   # open http://localhost:8000
```

## Running the converter locally (optional)

```bash
pip install -r scripts/requirements.txt
python scripts/convert.py build        # or --all to rebuild everything
```

## Costs and limits

- GitHub Free includes 10 GiB of LFS storage and 10 GiB/month of downloads; beyond that,
  storage is $0.07/GiB/month and downloads $0.0875/GiB. **Every saved version stores the
  whole file**, so large assemblies add up. Check *Settings → Billing* now and then.
- The workflow downloads only the STEP files that changed, to keep LFS bandwidth low.
- Previews are deliberately coarse (0.2 mm tolerance) and capped near 20 MB each.
- Git doesn't understand SolidWorks references: rename and move parts **inside SolidWorks**
  (Pack and Go or Rename with references), then commit the result.
- Avoid commas in file names; the LFS download step uses them as separators.

## Layout

```
cad/                     your parts, one folder per part or assembly
previews/                generated: do not edit by hand
  manifest.json
  <same folders as cad/>/*.stl
site/index.html          the viewer page
scripts/convert.py       STEP → STL + manifest (uses CadQuery)
scripts/build_site.py    previews → GLB + static site (numpy only)
scripts/stl_tools.py     STL reader / GLB writer
tools/solidworks/        batch STEP exporter (Windows + SolidWorks)
tools/hooks/pre-commit   blocks SolidWorks commits without a STEP
.github/workflows/previews.yml
```
