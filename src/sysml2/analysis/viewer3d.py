"""A small three.js mesh viewer for baked geometry (anywidget).

Renders the mesh dicts produced by :mod:`sysml2.analysis.geometry`
following the house widget pattern (:mod:`sysml2.replay`): Python bakes
the geometry once per configuration into a JSON-string traitlet; the
inline vanilla-JS front-end only paints -- it builds three.js buffer
geometries on load and per-interaction work is a camera move plus one
render.  Rendering is on-demand (no free-running animation loop), so an
idle viewer costs nothing.

Interaction: drag to orbit, scroll to zoom, double-click to re-fit.
An optional second mesh (``mesh_b_json``) renders side by side at true
scale for A/B comparison, with captions from ``label``/``label_b``.
Updating ``mesh_json`` from Python (e.g. observing another widget's
traitlet) re-bakes the scene in place.

Offline tradeoff: the front-end imports three.js (~630 kB) from the
jsDelivr CDN at view time -- the one exception to the otherwise
self-contained widget.  Vendoring the library into the package would add
those bytes to every install for a demo-grade viewer; on an offline
front-end the widget degrades to a printed notice instead of a scene.

Requires the ``viz`` extra for anywidget:
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import anywidget

__all__ = ["mesh_viewer"]

THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js"

# Conventions per .handoff/scene-viewer-mechanics.md and sysml2.replay:
# DOM built once; geometry buffers rebuilt only when a mesh traitlet
# changes; the orbit handler is ~30 lines of spherical-coordinate math
# instead of an OrbitControls import (whose bare "three" specifier needs
# an import map the notebook front-end does not have).
_ESM = r"""
async function render({ model, el }) {
  el.classList.add("sysml2-viewer3d");
  el.innerHTML = "";
  let THREE;
  try {
    THREE = await import("%THREE_URL%");
  } catch (err) {
    const note = document.createElement("div");
    note.className = "sysml2-viewer3d-offline";
    note.textContent = "3D view unavailable: three.js could not be " +
      "loaded from the CDN (offline front-end?).";
    el.appendChild(note);
    return;
  }

  const width = model.get("width_px");
  const height = model.get("height_px");
  const stage = document.createElement("div");
  stage.className = "sysml2-viewer3d-stage";
  stage.style.width = width + "px";
  stage.style.height = height + "px";
  const captions = document.createElement("div");
  captions.className = "sysml2-viewer3d-captions";
  captions.style.maxWidth = width + "px";
  el.append(stage, captions);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(width, height);
  stage.appendChild(renderer.domElement);
  renderer.domElement.setAttribute("role", "img");

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#f4f4f2");
  const camera = new THREE.PerspectiveCamera(38, width / height, 0.001, 50);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 0.95));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(2, 3, 1.5);
  const fill = new THREE.DirectionalLight(0xffffff, 0.4);
  fill.position.set(-2, 1.2, -1);
  scene.add(key, fill);

  const content = new THREE.Group();  // rebuilt on mesh changes
  const floor = new THREE.Group();    // grid, sized to the content
  scene.add(content, floor);

  // --- camera: spherical orbit about a fit target, render on demand
  let target = new THREE.Vector3();
  let radius = 1, theta = 0.9, phi = 1.05;
  let pending = false;
  function requestRender() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false;
                                  renderer.render(scene, camera); });
  }
  function applyCamera() {
    camera.position.set(
      target.x + radius * Math.sin(phi) * Math.cos(theta),
      target.y + radius * Math.cos(phi),
      target.z + radius * Math.sin(phi) * Math.sin(theta));
    camera.lookAt(target);
    requestRender();
  }
  function fit() {
    const box = new THREE.Box3().setFromObject(content);
    if (box.isEmpty()) return;
    box.getCenter(target);
    const size = box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1e-6);
    radius = (span / 2) / Math.tan((camera.fov / 2) * Math.PI / 180) * 1.35;
    applyCamera();
  }

  // --- geometry: one BufferGeometry + material per baked part
  function buildGroup(meshJson) {
    const mesh = JSON.parse(meshJson);
    const group = new THREE.Group();
    for (const part of mesh.parts) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(
        new Float32Array(part.vertices), 3));
      geometry.setIndex(part.faces);
      geometry.computeVertexNormals();  // once per load, never per frame
      const opacity = part.opacity === undefined ? 1.0 : part.opacity;
      const material = new THREE.MeshStandardMaterial({
        color: part.color, roughness: 0.65, metalness: 0.05,
        transparent: opacity < 1, opacity });
      group.add(new THREE.Mesh(geometry, material));
    }
    return group;
  }

  function dispose(group) {
    group.traverse((node) => {
      if (node.isMesh) { node.geometry.dispose(); node.material.dispose(); }
    });
    group.clear();
  }

  function rebuild() {
    dispose(content);
    dispose(floor);
    const a = model.get("mesh_json");
    const b = model.get("mesh_b_json");
    if (!a) return;
    const groupA = buildGroup(a);
    content.add(groupA);
    if (b) {
      const groupB = buildGroup(b);
      const boxA = new THREE.Box3().setFromObject(groupA);
      const boxB = new THREE.Box3().setFromObject(groupB);
      const spanA = boxA.max.x - boxA.min.x;
      const spanB = boxB.max.x - boxB.min.x;
      const gap = 0.18 * Math.max(spanA, spanB);
      groupA.position.x = -(spanA / 2 + gap / 2);
      groupB.position.x = spanB / 2 + gap / 2;
      content.add(groupB);
    }
    const box = new THREE.Box3().setFromObject(content);
    const span = Math.max(box.max.x - box.min.x, box.max.z - box.min.z);
    const cell = span > 0.6 ? 0.1 : 0.05;
    const size = Math.ceil((span * 1.5) / cell) * cell;
    const grid = new THREE.GridHelper(size, Math.round(size / cell),
                                      0xc9ccd1, 0xe3e5e8);
    grid.position.y = box.min.y - 0.003;
    floor.add(grid);
    renderer.domElement.setAttribute("aria-label",
      "3D drone view: " + [model.get("label"), model.get("label_b")]
        .filter(Boolean).join(" vs. "));
    fit();
  }

  function relabel() {
    captions.innerHTML = "";
    for (const name of ["label", "label_b"]) {
      const text = model.get(name);
      if (!text) continue;
      const span = document.createElement("span");
      span.textContent = text;
      captions.appendChild(span);
    }
    captions.style.justifyContent =
      captions.children.length > 1 ? "space-around" : "center";
  }

  // --- interaction: drag orbits, wheel zooms, double-click re-fits
  let dragging = null;
  renderer.domElement.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY };
    renderer.domElement.setPointerCapture(event.pointerId);
  });
  renderer.domElement.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    theta += (event.clientX - dragging.x) * 0.008;
    phi = Math.min(Math.PI - 0.15,
                   Math.max(0.1, phi + (event.clientY - dragging.y) * 0.008));
    dragging = { x: event.clientX, y: event.clientY };
    applyCamera();
  });
  renderer.domElement.addEventListener("pointerup", () => (dragging = null));
  renderer.domElement.addEventListener("wheel", (event) => {
    event.preventDefault();
    radius = Math.min(20, Math.max(0.02,
                                   radius * Math.exp(event.deltaY * 0.001)));
    applyCamera();
  }, { passive: false });
  renderer.domElement.addEventListener("dblclick", fit);

  model.on("change:mesh_json", rebuild);
  model.on("change:mesh_b_json", rebuild);
  model.on("change:label", relabel);
  model.on("change:label_b", relabel);
  relabel();
  rebuild();
  return () => renderer.dispose();
}
export default { render };
""".replace("%THREE_URL%", THREE_URL)

_CSS = """
.sysml2-viewer3d { font-family: Helvetica, Arial, sans-serif; }
.sysml2-viewer3d-stage {
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #f4f4f2; position: relative;
}
.sysml2-viewer3d-stage canvas { display: block; cursor: grab; }
.sysml2-viewer3d-stage canvas:active { cursor: grabbing; }
.sysml2-viewer3d-captions {
  display: flex; justify-content: space-around; margin-top: 6px;
  font-size: 12px; color: #555555; font-variant-numeric: tabular-nums;
}
.sysml2-viewer3d-offline {
  border: 1px dashed #d4d4d4; border-radius: 8px; padding: 14px;
  font-size: 12px; color: #777777;
}
"""

_VIEWER_CLS: type[anywidget.AnyWidget] | None = None


def _viewer_class() -> type[anywidget.AnyWidget]:
    """Define MeshViewer lazily -- anywidget is an optional extra."""

    global _VIEWER_CLS
    if _VIEWER_CLS is not None:
        return _VIEWER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise ImportError(
            "the 3D viewer needs anywidget; install the extra with "
            "'pip install \"longeron[viz]\"'") from err

    class MeshViewer(_anywidget.AnyWidget):
        """three.js rendering of baked mesh dicts (A, optionally A|B)."""

        _esm = _ESM
        _css = _CSS
        mesh_json = traitlets.Unicode("").tag(sync=True)
        mesh_b_json = traitlets.Unicode("").tag(sync=True)  # "" = single
        label = traitlets.Unicode("").tag(sync=True)
        label_b = traitlets.Unicode("").tag(sync=True)
        width_px = traitlets.Int(760).tag(sync=True)
        height_px = traitlets.Int(430).tag(sync=True)

    _VIEWER_CLS = MeshViewer
    return MeshViewer


def mesh_viewer(mesh: dict[str, Any], mesh_b: dict[str, Any] | None = None,
                *, label: str = "", label_b: str = "",
                width_px: int = 760,
                height_px: int = 430) -> anywidget.AnyWidget:
    """View one baked mesh dict, or two side by side at true scale.

    ``mesh``/``mesh_b`` come from :mod:`sysml2.analysis.geometry` (or any
    producer of the same schema).  Assign a new JSON string to the
    returned widget's ``mesh_json`` to swap the scene in place -- e.g.
    from an ``observe`` handler on another widget.
    """

    cls = _viewer_class()
    return cls(mesh_json=json.dumps(mesh),
               mesh_b_json=json.dumps(mesh_b) if mesh_b is not None else "",
               label=label, label_b=label_b,
               width_px=width_px, height_px=height_px)
