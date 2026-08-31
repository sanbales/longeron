"""Fly a MissionTrack on a CesiumJS globe (anywidget).

:func:`mission_viewer` renders a
:class:`~longeron.analysis.mission3d.MissionTrack`'s baked CZML document
on a Cesium ``Viewer``: a grey planned-route polyline, small waypoint
pins, and a drone entity that flies the samples with an orange trail,
its label following the ACTIVE STATE name through the mission.  The
track synthesis itself -- waypoints, state-machine timelines, CZML and
glTF baking -- lives in :mod:`longeron.analysis.mission3d`: it is
analysis, deterministic and testable without a browser.

The camera tracks the drone with an offset sized from the route (CZML
``viewFrom``).  Cesium's native timeline + animation dial are the
mission-playback UI (play/pause/scrub); the chrome that needs Cesium
ion (base-layer picker, geocoder) stays off.  Clicking the drone (or
any mission entity) reports its CZML id on the ``picked_json`` trait --
the same pick seam as :mod:`longeron.widgets.viewer3d` -- and the
bidirectional ``time`` trait (seconds past the track epoch) lets kernel
code scrub or follow the playhead.  The ``playing`` / ``rate`` /
``drift_s`` traits are the time seam's Cesium bridge
(:func:`longeron.widgets.link_time`): ``playing`` mirrors the Cesium
dial (``clock.shouldAnimate``) both ways, ``rate`` mirrors the
``multiplier``, and while the dial animates a kernel seek inside
``drift_s`` (scaled by the multiplier) is treated as peer integration
and ignored -- the bounded-drift reconciliation that keeps the clock
and the dial from fighting; a paused viewer converges exactly (echo
tolerance ``1e-3``).  The stage keeps a fixed explicit height
(``height_px``, default 480) at 98% width, so it never overflows a
notebook cell or the sidebar.

No Cesium ion token is required: every ``imagery`` base is tokenless
on the plain WGS84 ellipsoid.  The default ``'satellite'`` is Esri
World Imagery -- the keyless ArcGIS Online ``World_Imagery`` tile
service, acceptable for light development/demo use with the attribution
the widget's credit bar shows (heavy or production use should bring an
ArcGIS API key or a Cesium ion token instead); ``'plain'`` draws no
imagery at all -- a neutral dark-slate globe on which the route, trail,
and model read cleanly; ``'osm'`` is OpenStreetMap street tiles.
Passing ``ion_token=`` upgrades to Cesium World Terrain + imagery
regardless of ``imagery``.

Offline tradeoff: the front-end loads CesiumJS (~6 MB plus workers and
assets) from the pinned jsDelivr CDN at view time -- the same judgment
as :mod:`longeron.widgets.viewer3d`'s three.js (~630 kB was already too
big to vendor; Cesium is ~10x that, a fortiori).  On an offline
front-end the widget degrades to a printed notice instead of a globe,
and a later re-render retries the load.  This is also why there is no
browser-tier test for this widget: rendering truth would hard-depend on
live CDN access (see ``tests/test_mission3d.py``).

Requires the ``viz`` extra for anywidget:
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..analysis._expr import AnalysisError
from ..errors import MissingExtraError

if TYPE_CHECKING:
    from collections.abc import Mapping

    import anywidget

    from ..analysis.mission3d import MissionTrack

__all__ = [
    "CESIUM_BASE_URL",
    "CESIUM_CSS_URL",
    "CESIUM_JS_URL",
    "CESIUM_VERSION",
    "mission_viewer",
]

#: the imagery bases mission_viewer accepts (all tokenless)
_IMAGERY_BASES = ("satellite", "plain", "osm")

#: pinned CDN release (monthly Cesium train); bump deliberately, with the
#: evidence capture re-run -- never float a `latest` tag
CESIUM_VERSION = "1.144.0"
#: workers/assets/widgets resolve against this base (window.CESIUM_BASE_URL)
CESIUM_BASE_URL = f"https://cdn.jsdelivr.net/npm/cesium@{CESIUM_VERSION}/Build/Cesium/"
CESIUM_JS_URL = CESIUM_BASE_URL + "Cesium.js"
CESIUM_CSS_URL = CESIUM_BASE_URL + "Widgets/widgets.css"


# Conventions per viewer3d/replay: the DOM is built once, Python bakes the
# whole payload (the CZML document) into a JSON traitlet, and the front-end
# only plays it.  Cesium ships no single-file ESM build, so the pinned IIFE
# bundle is injected as a classic <script> (plus its widgets.css) with the
# load promise cached on `window` -- many viewers share one ~6 MB load, and
# a failed load clears the cache so a later render can retry.
_ESM = (
    r"""
async function loadCesium() {
  if (window.Cesium) return window.Cesium;
  if (!window._longeronCesiumLoad) {
    window.CESIUM_BASE_URL = "%CESIUM_BASE_URL%";
    if (!document.querySelector("link[data-longeron-cesium]")) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "%CESIUM_CSS_URL%";
      link.setAttribute("data-longeron-cesium", "1");
      document.head.appendChild(link);
    }
    window._longeronCesiumLoad = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "%CESIUM_JS_URL%";
      script.onload = () => resolve();
      script.onerror = () => {
        delete window._longeronCesiumLoad;  // let a later render retry
        script.remove();
        reject(new Error("CesiumJS failed to load"));
      };
      document.head.appendChild(script);
    });
  }
  await window._longeronCesiumLoad;
  return window.Cesium;
}

async function render({ model, el }) {
  el.classList.add("longeron-mission3d");
  el.innerHTML = "";
  let Cesium;
  try {
    Cesium = await loadCesium();
  } catch (err) {
    const note = document.createElement("div");
    note.className = "longeron-mission3d-offline";
    note.textContent = "Mission view unavailable: CesiumJS could not " +
      "be loaded from the CDN (offline front-end?).";
    el.appendChild(note);
    return;
  }

  const stage = document.createElement("div");
  stage.className = "longeron-mission3d-stage";
  stage.style.height = model.get("height_px") + "px";
  const caption = document.createElement("div");
  caption.className = "longeron-mission3d-caption";
  el.append(stage, caption);

  // no ion token required: every imagery base is tokenless on the
  // plain WGS84 ellipsoid -- 'satellite' (default) is Esri World
  // Imagery (keyless ArcGIS Online tile service; the credit bar shows
  // the required attribution), 'plain' is no imagery at all (a neutral
  // dark-slate globe), 'osm' is OpenStreetMap streets.  A token
  // upgrades to Cesium World Terrain + imagery.  The ion-backed chrome
  // (base-layer picker, geocoder) stays off either way -- the timeline
  // + animation dial ARE the mission-playback UI.
  const token = model.get("ion_token");
  const imagery = model.get("imagery") || "satellite";
  if (token) Cesium.Ion.defaultAccessToken = token;
  const options = {
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    animation: true,
    timeline: true,
    shouldAnimate: false,
    requestRenderMode: true,       // an idle globe costs nothing...
    maximumRenderTimeChange: 0.0,  // ...but every clock tick paints
  };
  if (token) {
    options.baseLayer = Cesium.ImageryLayer.fromWorldImagery();
    options.terrain = Cesium.Terrain.fromWorldTerrain();
  } else if (imagery === "plain") {
    options.baseLayer = false;  // no tiles at all: globe.baseColor shows
  } else if (imagery === "osm") {
    options.baseLayer = new Cesium.ImageryLayer(
      new Cesium.OpenStreetMapImageryProvider(
        { url: "https://tile.openstreetmap.org/" }));
  } else {  // "satellite": Esri World Imagery, keyless
    options.baseLayer = new Cesium.ImageryLayer(
      new Cesium.UrlTemplateImageryProvider({
        url: "https://services.arcgisonline.com/ArcGIS/rest/services/" +
          "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        credit: "Esri, Maxar, Earthstar Geographics, and the GIS " +
          "User Community",
        maximumLevel: 19,
      }));
  }
  const viewer = new Cesium.Viewer(stage, options);
  // the browser-test seam: the tier drives the dial and reads the clock
  // through this handle (tests/browser/test_browser_timeseam.py)
  stage.longeronViewer = viewer;
  if (!token && imagery === "plain") {
    // a tasteful dark slate the grey route, orange trail, and drone
    // model all read against; no atmosphere haze over the bare globe
    viewer.scene.globe.baseColor =
      Cesium.Color.fromCssColorString("#2e3440");
    viewer.scene.globe.showGroundAtmosphere = false;
  }

  const hint = document.createElement("div");
  hint.className = "longeron-mission3d-hint";
  hint.textContent = "\u25b6 plays the mission \u00b7 drag the timeline " +
    "to scrub \u00b7 click the drone to pick";
  stage.appendChild(hint);

  async function load() {
    viewer.trackedEntity = undefined;
    viewer.dataSources.removeAll(true);
    let packets;
    try { packets = JSON.parse(model.get("czml_json") || "[]"); }
    catch (err) { packets = []; }
    if (!packets.length) return;
    const source = await viewer.dataSources.add(
      Cesium.CzmlDataSource.load(packets));
    // the camera follows the drone; the CZML viewFrom sets the offset
    viewer.trackedEntity = source.entities.getById("mission-drone");
    viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
    // the CZML document clock carries a baked multiplier as the initial
    // rate; a linked clock's stated state overrides it (the time seam),
    // and a playhead seeked before this view rendered is adopted here
    applyRate();
    applyPlaying();
    const stated = model.get("time");
    if (stated && Math.abs(stated - seconds()) > 1e-3) {
      viewer.clock.currentTime = Cesium.JulianDate.addSeconds(
        viewer.clock.startTime, stated, new Cesium.JulianDate());
    }
    viewer.scene.requestRender();
  }

  // --- playhead sync: `time` is seconds past the track epoch; the
  // front-end writes ~4 Hz while the clock animates, Python writes seek
  const seconds = () => Cesium.JulianDate.secondsDifference(
    viewer.clock.currentTime, viewer.clock.startTime);
  let lastSync = 0;
  const unTick = viewer.clock.onTick.addEventListener(() => {
    const now = performance.now();
    if (now - lastSync < 250) return;
    lastSync = now;
    const s = seconds();
    if (Math.abs(s - model.get("time")) > 1e-3) {
      model.set("time", s);
      model.save_changes();
    }
  });
  model.on("change:time", () => {
    const value = model.get("time");
    const current = seconds();
    // bounded-drift reconciliation (the time seam's non-fighting rule):
    // while the dial animates, a kernel write inside the tolerance is a
    // peer's local integration, not a seek -- ignore it; a paused
    // viewer converges exactly (the 1e-3 echo tolerance)
    const tolerance = viewer.clock.shouldAnimate
      ? Math.max(model.get("drift_s") || 0.25,
                 0.25 * Math.abs(viewer.clock.multiplier))
      : 1e-3;
    if (Math.abs(value - current) <= tolerance) return;
    viewer.clock.currentTime = Cesium.JulianDate.addSeconds(
      viewer.clock.startTime, value, new Cesium.JulianDate());
    viewer.scene.requestRender();
  });

  // --- the Cesium bridge (the time seam): playing/rate mirror the
  // dial's shouldAnimate/multiplier both ways.  Cesium's Clock emits no
  // change event for either, so a 250 ms watcher (the seam's sync rate)
  // reports dial presses and shuttle changes to the kernel.
  let lastAnimate = viewer.clock.shouldAnimate;
  let lastMultiplier = viewer.clock.multiplier;
  const watchDial = setInterval(() => {
    if (viewer.clock.shouldAnimate !== lastAnimate) {
      lastAnimate = viewer.clock.shouldAnimate;
      model.set("playing", lastAnimate);
      // the pauser owns the final t: report it with the flip, so every
      // follower converges exactly (the throttled onTick may not fire
      // again once the dial stops)
      if (!lastAnimate) model.set("time", seconds());
      model.save_changes();
    }
    if (viewer.clock.multiplier !== lastMultiplier) {
      lastMultiplier = viewer.clock.multiplier;
      model.set("rate", lastMultiplier);
      model.save_changes();
    }
  }, 250);
  function applyPlaying() {
    const value = model.get("playing");
    if (viewer.clock.shouldAnimate !== value) {
      viewer.clock.shouldAnimate = value;
      lastAnimate = value;
      viewer.scene.requestRender();
    }
  }
  function applyRate() {
    const value = model.get("rate");
    if (value && viewer.clock.multiplier !== value) {
      viewer.clock.multiplier = value;
      lastMultiplier = value;
    }
  }
  model.on("change:playing", applyPlaying);
  model.on("change:rate", applyRate);

  // --- picking: a click reports the hit entity's CZML id on
  // picked_json (the same pick seam as viewer3d.picked_json)
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((movement) => {
    const hit = viewer.scene.pick(movement.position);
    const id = hit && hit.id && hit.id.id;
    model.set("picked_json", JSON.stringify(id ? [String(id)] : []));
    model.save_changes();
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  function recaption() {
    caption.textContent = model.get("label");
    caption.style.display = model.get("label") ? "" : "none";
  }
  model.on("change:label", recaption);
  model.on("change:czml_json", load);
  model.on("change:height_px", () => {
    stage.style.height = model.get("height_px") + "px";
    viewer.scene.requestRender();
  });
  recaption();
  await load();
  return () => {
    clearInterval(watchDial);
    unTick();
    handler.destroy();
    viewer.destroy();
  };
}
export default { render };
""".replace("%CESIUM_BASE_URL%", CESIUM_BASE_URL)
    .replace("%CESIUM_CSS_URL%", CESIUM_CSS_URL)
    .replace("%CESIUM_JS_URL%", CESIUM_JS_URL)
)

# 98%-width stage with an explicit fixed height: Cesium's own chrome
# (timeline, animation dial, credits) lives INSIDE the container, so the
# widget never overflows a notebook cell or the sidebar.
_CSS = """
.longeron-mission3d { font-family: Helvetica, Arial, sans-serif; }
.longeron-mission3d-stage {
  width: 98%; box-sizing: border-box; position: relative;
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #0b1522;
}
.longeron-mission3d-hint {
  position: absolute; right: 8px; top: 6px; font-size: 10px;
  color: #d5d9de; background: rgba(11, 21, 34, 0.55);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  user-select: none; z-index: 1;
}
.longeron-mission3d-caption {
  margin-top: 6px; font-size: 12px; color: #555555;
  font-variant-numeric: tabular-nums;
}
.longeron-mission3d-offline {
  border: 1px dashed #d4d4d4; border-radius: 8px; padding: 14px;
  font-size: 12px; color: #777777;
}
"""

_VIEWER_CLS: type[anywidget.AnyWidget] | None = None


def _viewer_class() -> type[anywidget.AnyWidget]:
    """Define MissionViewer lazily -- anywidget is an optional extra."""

    global _VIEWER_CLS
    if _VIEWER_CLS is not None:
        return _VIEWER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the mission viewer", "anywidget", "viz") from err

    class MissionViewer(_anywidget.AnyWidget):
        """CesiumJS playback of a MissionTrack's CZML document."""

        _esm = _ESM
        _css = _CSS
        #: the baked CZML document (JSON text); assign to swap missions
        czml_json = traitlets.Unicode("").tag(sync=True)
        label = traitlets.Unicode("").tag(sync=True)
        #: fixed stage height (the width fills 98% of the host)
        height_px = traitlets.Int(480).tag(sync=True)
        #: optional Cesium ion token (world terrain/imagery); applied at
        #: render time -- set it before displaying the widget
        ion_token = traitlets.Unicode("").tag(sync=True)
        #: tokenless imagery base -- 'satellite' (Esri World Imagery,
        #: the default), 'plain' (no tiles: a neutral dark globe), or
        #: 'osm' (OpenStreetMap streets); applied at render time
        imagery = traitlets.Unicode("satellite").tag(sync=True)
        #: JSON array with the CZML id of the last clicked entity
        #: ("[]" for a background click); written by the front-end
        picked_json = traitlets.Unicode("[]").tag(sync=True)
        #: bidirectional playhead, seconds past the track epoch
        time = traitlets.Float(0.0).tag(sync=True)
        #: bidirectional transport state: mirrors the Cesium dial
        #: (``clock.shouldAnimate``) both ways -- the time seam's bridge
        playing = traitlets.Bool(False).tag(sync=True)
        #: bidirectional playback rate: mirrors the Cesium ``multiplier``
        #: (track seconds per wall second); 0.0 means "no stated rate",
        #: leaving the CZML document clock's baked multiplier in charge
        rate = traitlets.Float(0.0).tag(sync=True)
        #: bounded-drift reconciliation tolerance while animating, in
        #: track seconds (``link_time`` scales it for step-mode bindings)
        drift_s = traitlets.Float(0.25).tag(sync=True)

    _VIEWER_CLS = MissionViewer
    return MissionViewer


def mission_viewer(
    track: MissionTrack,
    *,
    mesh: Mapping[str, Any] | None = None,
    model_scale: float = 1.0,
    label: str | None = None,
    height_px: int = 480,
    imagery: str = "satellite",
    ion_token: str = "",
) -> anywidget.AnyWidget:
    """Fly ``track`` on a Cesium globe in the notebook.

    The viewer starts paused at the track epoch with the camera
    tracking the drone; Cesium's native timeline and animation dial
    play, pause, scrub, and re-speed the mission.  Pass ``mesh`` (a
    :mod:`longeron.analysis.geometry` mesh dict) to fly the airframe's
    own geometry as a glTF model at ``model_scale`` times true size,
    flown with the multirotor attitude (yaw along the track heading,
    props level in vertical phases, the track's ``tilt_deg`` forward
    tilt in cruise); without a mesh the drone is a point.
    ``imagery`` picks the tokenless base: ``'satellite'`` (Esri World
    Imagery, the default), ``'plain'`` (a neutral dark globe, no
    tiles), or ``'osm'`` (OpenStreetMap streets); ``ion_token``
    upgrades to Cesium World Terrain + imagery regardless.  Click the
    drone (or a waypoint pin) to report its CZML id on ``picked_json``;
    drive or observe the playhead through the bidirectional ``time``
    trait.  Assign a new JSON string to ``czml_json`` to swap the
    mission in place.
    """

    if imagery not in _IMAGERY_BASES:
        raise AnalysisError(f"imagery must be one of {_IMAGERY_BASES} (got {imagery!r})")
    cls = _viewer_class()
    return cls(
        czml_json=json.dumps(track.to_czml(mesh=mesh, model_scale=model_scale)),
        label=track.name if label is None else label,
        height_px=height_px,
        imagery=imagery,
        ion_token=ion_token,
    )
