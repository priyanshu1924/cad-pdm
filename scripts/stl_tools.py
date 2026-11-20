"""Small, dependency-light helpers for STL meshes (numpy only).

read_stl()  -> (N, 3, 3) float32 array of triangles, from binary or ASCII STL
mesh_stats() -> bounding box, size and triangle count
write_glb() -> minimal binary glTF 2.0 file that browsers / <model-viewer> load
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np


def read_stl(path: str | Path) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + count * 50 == len(data):
            rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            return np.frombuffer(data, dtype=rec, count=count, offset=84)["v"].astype(np.float32)
    # ASCII fallback
    verts = [
        [float(x) for x in line.split()[1:4]]
        for line in data.decode("ascii", errors="ignore").splitlines()
        if line.strip().startswith("vertex")
    ]
    if not verts or len(verts) % 3:
        raise ValueError(f"{path}: not a readable STL file")
    return np.asarray(verts, dtype=np.float32).reshape(-1, 3, 3)


def mesh_stats(tris: np.ndarray) -> dict:
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return {
        "bbox_min_mm": [round(float(x), 3) for x in lo],
        "bbox_max_mm": [round(float(x), 3) for x in hi],
        "size_mm": [round(float(x), 3) for x in (hi - lo)],
        "triangles": int(len(tris)),
    }


def _pad(b: bytes, fill: bytes) -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(tris: np.ndarray, path: str | Path, color=(0.62, 0.66, 0.72, 1.0)) -> None:
    """Write triangles as a glTF binary. Coordinates are converted mm -> m
    (glTF's unit) and Z-up CAD space is rotated to glTF's Y-up."""
    pts = tris.reshape(-1, 3).astype(np.float32) / 1000.0
    pts = np.stack([pts[:, 0], pts[:, 2], -pts[:, 1]], axis=1).astype(np.float32)

    # Flat per-face normals so edges look crisp, like a CAD viewer.
    t = pts.reshape(-1, 3, 3)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    length = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, length, out=np.zeros_like(n), where=length > 0)
    normals = np.repeat(n, 3, axis=0).astype(np.float32)

    pos_bytes, nrm_bytes = pts.tobytes(), normals.tobytes()
    binary = _pad(pos_bytes + nrm_bytes, b"\x00")
    count = int(len(pts))

    gltf = {
        "asset": {"version": "2.0", "generator": "cad-pdm stl_tools"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "material": 0}]}],
        "materials": [{
            "pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": 0.1, "roughnessFactor": 0.6},
            "doubleSided": True,
        }],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(nrm_bytes), "target": 34962},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3",
             "min": [float(x) for x in pts.min(axis=0)], "max": [float(x) for x in pts.max(axis=0)]},
            {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
        ],
    }
    js = _pad(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(js) + 8 + len(binary)
    out = struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(binary), 0x004E4942) + binary
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(out)
