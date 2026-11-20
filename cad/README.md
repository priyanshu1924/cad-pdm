# cad/

Put parts and assemblies here, one folder per part or subassembly:

```
cad/
  PN-1001_base-plate/
    PN-1001_base-plate.SLDPRT    native file (source of truth)
    PN-1001_base-plate.step      STEP export: commit it with every change
    PN-1001_base-plate.pdf       drawing (optional)
  PN-2000_gripper-assy/
    ...
```

Every `.step` / `.stp` file under this folder gets a 3D preview automatically.
Native SolidWorks/Fusion files don't, so **export a STEP file each time you
save a change you're committing.** For SolidWorks, `tools/solidworks/export_step.bat`
does this in bulk.
