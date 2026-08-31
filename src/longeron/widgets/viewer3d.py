"""A small three.js mesh viewer for baked geometry (anywidget).

Renders the mesh dicts produced by :mod:`longeron.analysis.geometry`
following the house widget pattern (:mod:`longeron.widgets.replay`): Python bakes
the geometry once per configuration into a JSON-string traitlet; the
inline vanilla-JS front-end only paints -- it builds three.js buffer
geometries on load and per-interaction work is a camera move plus one
render.  Rendering is on-demand (no free-running animation loop), so an
idle viewer costs nothing.

Interaction: drag to orbit, shift-drag or right-drag to pan (the canvas
swallows the context-menu event so JupyterLab's menu stays out of the
way), scroll to zoom, double-click to re-fit; a subtle overlay hint
names the bindings.  The canvas fills the available cell width (a
ResizeObserver re-sizes the renderer and re-fits the camera on host
resizes); ``width_px``/``height_px`` set the aspect ratio and the
fallback width.  An optional second mesh (``mesh_b_json``) renders side
by side at true scale for A/B comparison, with captions from
``label``/``label_b``.  A mesh dict may carry ``labels`` --
``{text, anchor}`` entries as produced by
:func:`longeron.analysis.geometry.lineup` -- rendered as billboard
sprites above each configuration, so a grid lineup names its cells
in-scene.  Updating ``mesh_json`` from Python (e.g. observing another
widget's traitlet) re-bakes the scene in place.

Linked selection: ``highlight_json`` (a JSON array of part identity
keys -- each part's ``key`` if tagged via
:func:`longeron.analysis.geometry.tag_parts`, else its ``name``) pops
the matched meshes with an emissive accent (the JupyterLab selection
blue, read live from ``--jp-brand-color2``) and dims the rest;
``"[]"`` restores every material instantly.  A plain click (no drag)
raycasts the scene and reports the hit part's key on ``picked_json``
(``"[]"`` for a background click), so Python can select the
corresponding diagram node --
:func:`longeron.analysis.link.link_selection` wires both directions.

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

from ..errors import MissingExtraError

if TYPE_CHECKING:
    from collections.abc import Iterable

    import anywidget

__all__ = ["mesh_viewer"]

THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js"

# Conventions (as in longeron.widgets.replay's front-end):
# DOM built once; geometry buffers rebuilt only when a mesh traitlet
# changes; the orbit handler is ~30 lines of spherical-coordinate math
# instead of an OrbitControls import (whose bare "three" specifier needs
# an import map the notebook front-end does not have).
_ESM = r"""
async function render({ model, el }) {
  el.classList.add("longeron-viewer3d");
  el.innerHTML = "";
  let THREE;
  try {
    THREE = await import("%THREE_URL%");
  } catch (err) {
    const note = document.createElement("div");
    note.className = "longeron-viewer3d-offline";
    note.textContent = "3D view unavailable: three.js could not be " +
      "loaded from the CDN (offline front-end?).";
    el.appendChild(note);
    return;
  }

  const aspect = Math.max(
    0.4, model.get("width_px") / Math.max(1, model.get("height_px")));
  const stage = document.createElement("div");
  stage.className = "longeron-viewer3d-stage";
  const captions = document.createElement("div");
  captions.className = "longeron-viewer3d-captions";
  el.append(stage, captions);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);
  const hint = document.createElement("div");
  hint.className = "longeron-viewer3d-hint";
  hint.textContent = "drag orbit \u00b7 shift-drag or right-drag pan " +
    "\u00b7 wheel zoom \u00b7 double-click fit";
  stage.appendChild(hint);
  renderer.domElement.setAttribute("role", "img");

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#f4f4f2");
  const camera = new THREE.PerspectiveCamera(38, aspect, 0.001, 50);
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
  let height = model.get("height_px");
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

  // --- sizing: fill the host width at a fixed aspect; re-fit on resize
  function layout(refit) {
    const w = Math.max(240, el.clientWidth || model.get("width_px"));
    height = Math.round(w / aspect);
    stage.style.height = height + "px";
    renderer.setSize(w, height);
    camera.aspect = w / height;
    camera.updateProjectionMatrix();
    if (refit) fit(); else requestRender();
  }
  let lastWidth = 0;
  const observer = new ResizeObserver(() => {
    const w = el.clientWidth;
    if (w && Math.abs(w - lastWidth) > 1) { lastWidth = w; layout(true); }
  });
  observer.observe(el);
  layout(false);

  // --- geometry: one BufferGeometry + material per baked part; the
  // optional mesh.labels ride above their anchors as billboard sprites
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
      const node = new THREE.Mesh(geometry, material);
      // model identity for linked selection: the tagged key (a model
      // part's qualified name) or the bare part name
      node.userData.key = part.key || part.name;
      node.userData.baseOpacity = opacity;
      group.add(node);
    }
    const span = Math.max(
      mesh.bounds[1][0] - mesh.bounds[0][0],
      mesh.bounds[1][2] - mesh.bounds[0][2], 0.2);
    for (const label of mesh.labels || []) {
      const canvas = document.createElement("canvas");
      canvas.width = 512; canvas.height = 96;
      const ctx = canvas.getContext("2d");
      const size = Math.min(44, Math.floor(920 / (label.text.length + 1)));
      ctx.font = "600 " + size + "px Helvetica, Arial, sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = 8; ctx.lineJoin = "round";
      ctx.strokeStyle = "rgba(244, 244, 242, 0.9)";  // halo on the sky
      ctx.strokeText(label.text, 256, 48);
      ctx.fillStyle = "#2b2d31";
      ctx.fillText(label.text, 256, 48);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: new THREE.CanvasTexture(canvas), transparent: true,
        depthTest: false }));
      sprite.position.set(...label.anchor);
      sprite.scale.set(span * 0.3, span * 0.05625, 1);
      group.add(sprite);
    }
    return group;
  }

  function dispose(group) {
    group.traverse((node) => {
      if (node.isMesh) { node.geometry.dispose(); node.material.dispose(); }
      if (node.isSprite) {
        if (node.material.map) node.material.map.dispose();
        node.material.dispose();
      }
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
    applyHighlight();  // a swapped-in mesh keeps the active highlight
    fit();
  }

  // --- linked selection: highlighted keys pop (emissive accent -- the
  // JupyterLab selection blue, so the 3D pop matches the diagram's),
  // the rest dim; an empty set restores every material instantly
  function applyHighlight() {
    let keys;
    try { keys = new Set(JSON.parse(model.get("highlight_json") || "[]")); }
    catch (err) { keys = new Set(); }
    const accent = (getComputedStyle(el)
      .getPropertyValue("--jp-brand-color2") || "").trim() || "#2196f3";
    content.traverse((node) => {
      if (!node.isMesh) return;
      const material = node.material;
      const base = node.userData.baseOpacity === undefined
        ? 1.0 : node.userData.baseOpacity;
      if (keys.size && keys.has(node.userData.key)) {
        material.emissive.set(accent);
        material.emissiveIntensity = 0.55;
        material.opacity = base;
        material.transparent = base < 1;
      } else if (keys.size) {
        material.emissiveIntensity = 0;
        material.opacity = Math.max(0.08, 0.16 * base);
        material.transparent = true;
      } else {
        material.emissiveIntensity = 0;
        material.opacity = base;
        material.transparent = base < 1;
      }
    });
    requestRender();
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

  // --- interaction: drag orbits, shift/right-drag pans, wheel zooms,
  // double-click re-fits; the canvas owns the context-menu event so
  // JupyterLab's menu cannot hijack the right-drag pan
  const canvas = renderer.domElement;
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  let dragging = null;  // { mode: "orbit" | "pan", x, y, x0, y0, moved }
  canvas.addEventListener("pointerdown", (event) => {
    const pan = event.button === 2 || event.shiftKey;
    dragging = { mode: pan ? "pan" : "orbit",
                 x: event.clientX, y: event.clientY,
                 x0: event.clientX, y0: event.clientY, moved: false };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - dragging.x;
    const dy = event.clientY - dragging.y;
    dragging.x = event.clientX;
    dragging.y = event.clientY;
    if (Math.abs(event.clientX - dragging.x0)
        + Math.abs(event.clientY - dragging.y0) > 5) dragging.moved = true;
    if (dragging.mode === "pan") {
      // world units per screen pixel at the target distance
      const scale = 2 * radius
        * Math.tan((camera.fov / 2) * Math.PI / 180) / height;
      camera.updateMatrixWorld();
      const right = new THREE.Vector3()
        .setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3()
        .setFromMatrixColumn(camera.matrixWorld, 1);
      target.addScaledVector(right, -dx * scale);
      target.addScaledVector(up, dy * scale);
    } else {
      theta += dx * 0.008;
      phi = Math.min(Math.PI - 0.15,
                     Math.max(0.1, phi + dy * 0.008));
    }
    applyCamera();
  });
  canvas.addEventListener("pointerup", (event) => {
    // a still left-click (no drag, no shift) is a pick, not an orbit
    const wasClick = dragging && dragging.mode === "orbit" && !dragging.moved;
    dragging = null;
    if (wasClick) pick(event);
  });

  // --- picking: raycast the baked parts and report the hit key so the
  // Python side can select the matching diagram node (reverse link)
  const raycaster = new THREE.Raycaster();
  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    raycaster.setFromCamera(new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1), camera);
    const hit = raycaster.intersectObject(content, true)
      .find((h) => h.object.isMesh);
    model.set("picked_json",
              JSON.stringify(hit ? [hit.object.userData.key] : []));
    model.save_changes();
  }
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    radius = Math.min(20, Math.max(0.02,
                                   radius * Math.exp(event.deltaY * 0.001)));
    applyCamera();
  }, { passive: false });
  canvas.addEventListener("dblclick", fit);

  model.on("change:mesh_json", rebuild);
  model.on("change:mesh_b_json", rebuild);
  model.on("change:highlight_json", applyHighlight);
  model.on("change:label", relabel);
  model.on("change:label_b", relabel);
  relabel();
  rebuild();
  return () => { observer.disconnect(); renderer.dispose(); };
}
export default { render };
""".replace("%THREE_URL%", THREE_URL)

_CSS = """
.longeron-viewer3d { font-family: Helvetica, Arial, sans-serif; }
.longeron-viewer3d-stage {
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #f4f4f2; position: relative; width: 100%;
}
.longeron-viewer3d-stage canvas { display: block; cursor: grab; }
.longeron-viewer3d-stage canvas:active { cursor: grabbing; }
.longeron-viewer3d-hint {
  position: absolute; right: 8px; bottom: 6px; font-size: 10px;
  color: #8a8f98; background: rgba(244, 244, 242, 0.78);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  user-select: none;
}
.longeron-viewer3d-captions {
  display: flex; justify-content: space-around; margin-top: 6px;
  font-size: 12px; color: #555555; font-variant-numeric: tabular-nums;
}
.longeron-viewer3d-offline {
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
        raise MissingExtraError("the 3D viewer", "anywidget", "viz") from err

    class MeshViewer(_anywidget.AnyWidget):
        """three.js rendering of baked mesh dicts (A, optionally A|B)."""

        _esm = _ESM
        _css = _CSS
        mesh_json = traitlets.Unicode("").tag(sync=True)
        mesh_b_json = traitlets.Unicode("").tag(sync=True)  # "" = single
        label = traitlets.Unicode("").tag(sync=True)
        label_b = traitlets.Unicode("").tag(sync=True)
        #: JSON array of part identity keys to pop ("[]" = none): each
        #: part's tagged ``key`` if present, else its ``name``
        highlight_json = traitlets.Unicode("[]").tag(sync=True)
        #: JSON array with the key of the last clicked part ("[]" =
        #: background click); written by the front-end raycaster
        picked_json = traitlets.Unicode("[]").tag(sync=True)
        #: aspect ratio + fallback width; the canvas fills the host width
        width_px = traitlets.Int(760).tag(sync=True)
        height_px = traitlets.Int(430).tag(sync=True)

        def highlight(self, keys: Iterable[str] = ()) -> None:
            """Pop the parts whose identity key is in ``keys``.

            Matched meshes get the emissive accent, the rest dim; an
            empty ``keys`` (the default) clears the highlight and
            restores every material.
            """

            self.highlight_json = json.dumps(sorted({str(key) for key in keys}))

    _VIEWER_CLS = MeshViewer
    return MeshViewer


def mesh_viewer(
    mesh: dict[str, Any],
    mesh_b: dict[str, Any] | None = None,
    *,
    label: str = "",
    label_b: str = "",
    width_px: int = 760,
    height_px: int = 430,
) -> anywidget.AnyWidget:
    """View one baked mesh dict, or two side by side at true scale.

    ``mesh``/``mesh_b`` come from :mod:`longeron.analysis.geometry` (or any
    producer of the same schema).  The canvas fills the notebook cell's
    width; ``width_px``/``height_px`` set its aspect ratio (and the
    fallback width when the host width cannot be measured).  Drag to
    orbit, shift-drag or right-drag to pan, scroll to zoom, double-click
    to re-fit.  Assign a new JSON string to the returned widget's
    ``mesh_json`` to swap the scene in place -- e.g. from an ``observe``
    handler on another widget.

    Linked selection: ``widget.highlight(keys)`` pops the parts whose
    identity key (the ``key`` stamped by
    :func:`longeron.analysis.geometry.tag_parts`, else the part
    ``name``) is in ``keys`` and dims the rest; ``widget.highlight()``
    clears.  A plain click on a part reports its key on the
    ``picked_json`` traitlet.  See
    :func:`longeron.analysis.link.link_selection` for wiring both to a
    diagram.
    """

    cls = _viewer_class()
    return cls(
        mesh_json=json.dumps(mesh),
        mesh_b_json=json.dumps(mesh_b) if mesh_b is not None else "",
        label=label,
        label_b=label_b,
        width_px=width_px,
        height_px=height_px,
    )
