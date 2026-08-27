"""Minimal in-house binary glTF 2.0 (GLB) export for analysis meshes.

Turns the mesh dict the geometry builders produce
(:func:`longeron.analysis.geometry.drone_geometry` and friends:
``{"unit": "m", "parts": [{"name", "color", "opacity", "vertices",
"faces"}, ...]}``) into one self-contained ``.glb`` byte string --
pure stdlib (``json`` + ``struct``), no glTF library, so the mission
viewer can embed the ACTUAL airframe as a ``data:`` URI with no new
dependency and no file on disk.

Container layout (glTF 2.0 spec, section 4 "GLB File Format"):

* a 12-byte header -- magic ``glTF``, version ``2``, total file length;
* chunk 0: the JSON scene description (type ``JSON``, space-padded to a
  4-byte boundary);
* chunk 1: one binary buffer (type ``BIN\\0``, zero-padded) carrying
  every vertex attribute and index array back to back, each bufferView
  4-byte aligned.

Scene shape: a single root node whose rotation quaternion yaws the
geometry module's +X-forward / +Y-up frame onto glTF's +Z-forward /
+Y-up convention (Cesium's glTF axis correction then treats +Z as the
platform-forward axis -- exactly the axis a velocity orientation steers,
so the nose leads the track); one child node per part, each with its own
single-primitive mesh and material.  Triangles are UNWELDED -- three
fresh vertices per face -- so the computed per-face normals give honest
flat shading on boxes, arms, and prop disks: ``POSITION`` + ``NORMAL``
(float32 VEC3, with the spec-required min/max on positions) plus
uint16/uint32 ``indices``.  Materials are metal-free
``pbrMetallicRoughness`` with the part color as ``baseColorFactor``
(sRGB hex converted to the factor's linear color space) and the part
opacity as its alpha (``BLEND`` when translucent); everything is
double-sided so thin disks never vanish edge-on.

Deliberately NOT supported (this exports our own primitive meshes, not
arbitrary scenes): textures/UVs, tangents, skins, animations, sparse
accessors, interleaved attributes, extensions, and accessor sharing.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Mapping
from typing import Any

from ._expr import AnalysisError

__all__ = ["mesh_to_glb"]

_GLB_MAGIC = 0x46546C67  # b"glTF"
_CHUNK_JSON = 0x4E4F534A  # b"JSON"
_CHUNK_BIN = 0x004E4942  # b"BIN\0"
_UNSIGNED_SHORT = 5123
_UNSIGNED_INT = 5125
_FLOAT = 5126
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4

#: the -90 degree yaw quaternion (x, y, z, w) mapping the mesh frame's
#: +X (forward, per geometry.py's house convention) onto glTF's +Z
#: (forward, per the glTF spec); +Y stays up in both
_ROOT_ROTATION = (0.0, -math.sqrt(0.5), 0.0, math.sqrt(0.5))


def _srgb_to_linear(channel: float) -> float:
    """One sRGB channel (0..1) to linear -- baseColorFactor's space."""

    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)


def _base_color_factor(color: str, opacity: float) -> list[float]:
    """A ``#rrggbb`` hex + opacity as a linear RGBA baseColorFactor."""

    value = color.lstrip("#")
    try:
        if len(value) != 6:
            raise ValueError(value)
        rgb = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError as err:
        raise AnalysisError(f"part color must be #rrggbb hex (got {color!r})") from err
    if not 0.0 <= opacity <= 1.0:
        raise AnalysisError(f"part opacity must be within 0..1 (got {opacity!r})")
    return [round(_srgb_to_linear(c), 5) for c in rgb] + [round(float(opacity), 5)]


def _flat_triangles(
    vertices: list[float], faces: list[int], name: str
) -> tuple[list[float], list[float]]:
    """Unwelded positions + per-face normals (three vertices a triangle).

    The geometry builders wind every face outward (counter-clockwise
    seen from outside -- glTF's front face), so the right-handed cross
    product of the triangle edges IS the outward flat normal.
    """

    if not vertices or len(vertices) % 3:
        raise AnalysisError(f"part {name!r} has no valid vertices (need flat XYZ triples)")
    if not faces or len(faces) % 3:
        raise AnalysisError(f"part {name!r} has no valid faces (need flat index triples)")
    point_count = len(vertices) // 3
    positions: list[float] = []
    normals: list[float] = []
    for face in range(0, len(faces), 3):
        corners = []
        for index in faces[face : face + 3]:
            if not 0 <= index < point_count:
                raise AnalysisError(
                    f"part {name!r} face index {index} is out of range (has {point_count} vertices)"
                )
            corners.append(vertices[3 * index : 3 * index + 3])
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = corners
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-12:  # degenerate sliver: any unit normal will do
            nx, ny, nz = 0.0, 1.0, 0.0
        else:
            nx, ny, nz = nx / length, ny / length, nz / length
        for corner in corners:
            positions.extend(corner)
            normals.extend((nx, ny, nz))
    return positions, normals


def _add_view(blob: bytearray, views: list[dict[str, int]], data: bytes, target: int) -> int:
    """Append ``data`` as a new 4-byte-aligned bufferView; its index."""

    while len(blob) % 4:
        blob.append(0)
    views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
    blob.extend(data)
    return len(views) - 1


def _vec3_accessor(
    blob: bytearray,
    views: list[dict[str, int]],
    accessors: list[dict[str, Any]],
    values: list[float],
    *,
    bounded: bool,
) -> int:
    """Pack VEC3 float32 data; min/max from the PACKED values, so the
    declared bounds match the accessor bytes exactly (spec requirement
    for POSITION -- float32 quantization included)."""

    data = struct.pack(f"<{len(values)}f", *values)
    quantized = struct.unpack(f"<{len(values)}f", data)
    accessor: dict[str, Any] = {
        "bufferView": _add_view(blob, views, data, _ARRAY_BUFFER),
        "componentType": _FLOAT,
        "count": len(values) // 3,
        "type": "VEC3",
    }
    if bounded:
        accessor["min"] = [min(quantized[i::3]) for i in range(3)]
        accessor["max"] = [max(quantized[i::3]) for i in range(3)]
    accessors.append(accessor)
    return len(accessors) - 1


def _index_accessor(
    blob: bytearray,
    views: list[dict[str, int]],
    accessors: list[dict[str, Any]],
    count: int,
) -> int:
    """Trivial 0..count-1 indices (the vertices are already unwelded)."""

    if count <= 0xFFFF:
        kind, component = "H", _UNSIGNED_SHORT
    else:
        kind, component = "I", _UNSIGNED_INT
    data = struct.pack(f"<{count}{kind}", *range(count))
    accessors.append(
        {
            "bufferView": _add_view(blob, views, data, _ELEMENT_ARRAY_BUFFER),
            "componentType": component,
            "count": count,
            "type": "SCALAR",
        }
    )
    return len(accessors) - 1


def mesh_to_glb(mesh: Mapping[str, Any]) -> bytes:
    """A viewer3d-style mesh dict as one binary glTF 2.0 blob.

    ``mesh`` is the dict the :mod:`longeron.analysis.geometry` builders
    produce -- ``parts`` with ``name``/``color``/``opacity`` and flat
    ``vertices``/``faces`` arrays.  Every part becomes its own node +
    mesh + material under a single rotated root (see the module
    docstring for the exact container and scene shape), so per-part
    colors and translucency survive the export.  Raises
    :class:`~longeron.analysis._expr.AnalysisError` on a mesh with no
    parts, malformed vertex/face arrays, or out-of-range indices.
    """

    parts = mesh.get("parts") if isinstance(mesh, Mapping) else None
    if not parts:
        raise AnalysisError("mesh has no parts to export (need the geometry mesh dict)")

    blob = bytearray()
    views: list[dict[str, int]] = []
    accessors: list[dict[str, Any]] = []
    meshes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = [
        {
            "name": "model",
            "rotation": list(_ROOT_ROTATION),
            "children": list(range(1, len(parts) + 1)),
        }
    ]
    for part in parts:
        name = str(part.get("name", f"part{len(meshes)}"))
        opacity = float(part.get("opacity", 1.0))
        positions, normals = _flat_triangles(part["vertices"], part["faces"], name)
        material: dict[str, Any] = {
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": _base_color_factor(part.get("color", "#888888"), opacity),
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
            "doubleSided": True,  # thin prop disks must not vanish edge-on
        }
        if opacity < 1.0:
            material["alphaMode"] = "BLEND"
        materials.append(material)
        meshes.append(
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": _vec3_accessor(
                                blob, views, accessors, positions, bounded=True
                            ),
                            "NORMAL": _vec3_accessor(
                                blob, views, accessors, normals, bounded=False
                            ),
                        },
                        "indices": _index_accessor(blob, views, accessors, len(positions) // 3),
                        "material": len(materials) - 1,
                        "mode": _TRIANGLES,
                    }
                ],
            }
        )
        nodes.append({"name": name, "mesh": len(meshes) - 1})

    while len(blob) % 4:
        blob.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "longeron.analysis._glb"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    payload = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)  # JSON chunks pad with spaces

    header_and_chunks = struct.pack("<III", _GLB_MAGIC, 2, 12 + 8 + len(payload) + 8 + len(blob))
    header_and_chunks += struct.pack("<II", len(payload), _CHUNK_JSON) + payload
    header_and_chunks += struct.pack("<II", len(blob), _CHUNK_BIN) + bytes(blob)
    return header_and_chunks
