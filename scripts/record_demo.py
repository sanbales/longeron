#!/usr/bin/env python
"""Record the README demo: the grand-tour dashboard, one take -> mp4 + GIF.

    python scripts/record_demo.py

re-records the whole thing after UI changes.  The take is deterministic.
The script generates a copy of tutorial 9 into a throwaway lab root, so
the notebooks of the repository never change.  The models ship with this
checkout (``examples/deepscout``), the dashboard fixes the Voronoi seed of
its scoreboard, and ``PYTHONHASHSEED=0`` fixes kernel hashing.  Every wait
of the take polls for the reaction that it shows, with the predicates of
``tests/browser/test_browser_grand_tour.py``.  Two recordings differ only in
sub-second timing and in the Cesium imagery tiles that the network streams.

The video starts on the finished dashboard.  Before the cut, the take opens
``09_grand_tour.ipynb`` at 1920x1080, collapses the file browser, and runs
every cell above the ``dash.dock()`` cell.  It also boots the Cesium pane
once, and it waits until the dashboard settles.  The **subject** of the
dashboard is one mission architecture, and the first frame shows the ISR
winner as the subject.  The storyline then shows one capability per beat
(about 60 s):

a. The cursor rests on the header.  The header names the subject and its
   requirements score.
b. The tree filter finds the twin-tip flying wing, and a click on its row
   makes it the subject.  The 3D pane, the header and the scoreboard follow.
   The fit button of the diagram toolbar frames the selected node.
c. A drag of the ``wingSpan`` knob to its maximum re-bakes the 3D pane under
   the drag.  The 3D pane keeps its camera, so the wing draws wider.
d. The *Requirements* tab shows the re-scored scoreboard: ``PitchStability``
   failed at the wider span.  A hover on ``IsrTasking`` shows its tooltip.
e. On the *Sizing* tab, *maximize station time* runs the OpenMDAO driver.
   The cursor passes the history plot, the table and the N2 matrix.  The
   *Z3* tab shows the SAT verdict and the UNSAT core of the what-if.
f. On the *Mission* tab, the take presses play and switches to the
   ``onboard`` view for about 5 s.  The wing banks through a turn, and the
   take switches back to ``follow`` and pauses the clock.
g. A click in the ``dash.dock()`` cell and Ctrl+Enter run it.  The nine
   docked panes open in the JupyterLab main area.  The take drags the split
   bar between the tree and the structure diagram, and the cursor then
   passes the tabs of the docked panes.
h. The video ends on the docked layout.

The take prints each beat with its time in the video.  Outputs land in
``build/demo/`` (gitignored):

* ``demo.webm``   -- the raw playwright capture (1920x1080)
* ``demo.mp4``    -- h264, crf 20, faststart (the shareable video)
* ``demo.gif``    -- palette-optimized, <= 10 MB (the GitHub release-asset
  budget; see the publish workflow below)
* ``frames/*.png``-- five representative stills for quick review
* ``summary.json``-- the sizes, the trim offset and the beat times

PUBLISH WORKFLOW -- media is NEVER committed to this repo.  The
maintainer attaches ``demo.gif`` (and ``demo.mp4``) to the GitHub
release; the README already embeds
``github.com/sanbales/longeron/releases/latest/download/demo.gif``, so
the latest release's asset is what renders.  Re-recording therefore
never touches git history: re-run this script, re-attach the files to
the next release.

The recording rig mirrors ``scripts/capture_widget_snapshots.py`` and
``tests/browser/conftest.py``: one real JupyterLab server (temp root,
temp user settings with ``autoStartDefaultKernel`` on, autosave OFF,
``windowingMode: none``), driven by headless Chromium.  Unlike those,
this script performs for a HUMAN camera: a fake cursor overlay follows
the mouse (playwright records no OS cursor), each cursor travel is an
eased glide of a fixed duration, and slider drags are paced so the
kernel repaints stream by on camera.  The models are parse-cached and the
three.js/Cesium CDN bundles are browser-cached before the cut.  On macOS,
Chromium draws WebGL on the GPU (``GPU_ARGS``).  Record on a quiet
machine: concurrent browser suites steal the smoothness of the frames.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

REPO = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO / "build" / "demo"
LAB_ROOT = DEMO_DIR / "lab-root"
FRAME_DIR = DEMO_DIR / "frames"
MODEL_CACHE = DEMO_DIR / "model-cache"
FFMPEG = os.environ.get("LONGERON_FFMPEG", "/opt/homebrew/bin/ffmpeg")

NOTEBOOK = "09_grand_tour.ipynb"
#: the dashboard's layout target (tests/browser/test_browser_grand_tour.py,
#: scenario 5): with the file browser collapsed, the whole dashboard fits
#: the notebook's visible output area at 1920x1080
VIEWPORT: ViewportSize = {"width": 1920, "height": 1080}
#: 1: the capture renders at the video's own size.  A supersampled page
#: (2) renders the 3D, Cesium and docked panes at 3840x2160, and the
#: slower frames then stretch every cursor move and drag of the take
DEVICE_SCALE_FACTOR = 1
#: headless Chromium draws WebGL in software (SwiftShader) by default.  The
#: 3D, Cesium and docked panes then hold the renderer so long that every
#: cursor step of the take lags; on macOS, ANGLE over Metal draws on the GPU
GPU_ARGS = (
    ("--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist")
    if sys.platform == "darwin"
    else ()
)
#: front-end CDN bundles fetched into the browser HTTP cache OFF camera
#: (the warm page), so the dashboard's 3D and Cesium panes land fast --
#: keep in sync with widgets/viewer3d.py and widgets/mission3d.py
CDN_WARM_URLS = (
    "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js",
    "https://cdn.jsdelivr.net/npm/cesium@1.144.0/Build/Cesium/Cesium.js",
    "https://cdn.jsdelivr.net/npm/cesium@1.144.0/Build/Cesium/Widgets/widgets.css",
)
#: GIF discipline: the artifact is a GitHub release asset (never
#: committed), so quality can run high -- but 10 MB is the budget the
#: README's embed stays friendly under.
GIF_BUDGET_BYTES = 10 * 1024 * 1024
#: quality ladder walked until the GIF fits the budget.  The full 1080p
#: frame is far over it (about 80 MB), so the ladder starts at 1280 px wide
#: and 12 fps.  The Cesium flight over satellite imagery is the
#: entropy-heavy stretch: about 1 MB per second at 1280 px and 12 fps
GIF_LADDER = (
    {"fps": 12, "width": 1280, "colors": 192},
    {"fps": 10, "width": 1280, "colors": 160},
    {"fps": 8, "width": 1280, "colors": 160},
    {"fps": 10, "width": 1024, "colors": 128},
    {"fps": 8, "width": 1024, "colors": 128},
    {"fps": 8, "width": 960, "colors": 112},
    {"fps": 8, "width": 800, "colors": 96},
)

# -- camera pacing (ms) -------------------------------------------------------

#: the human-readable pause after each reaction: every other wait in the
#: storyline polls for the reaction itself, so the take has no dead time
BEAT = 800
#: the onboard flight: the wing banks through its second turn in this window
ONBOARD_MS = 5200
#: the closing hold on the docked layout
END_MS = 2400
#: one cursor travel: eased, time-based (a renderer that lags slows the
#: steps, not the glide), slow enough for an eye to follow
GLIDE_MS = 1000
#: the slider drag: the 3D pane re-bakes under it, step by step
DRAG_MS = 2400

# -- the storyline's model facts (examples/deepscout) ---------------------------

#: the catalog craft the tree click makes the subject
TWIN_TIP = "ScoutMissions::Catalog::AirframeChoice::flyingWingTwinTip"
ISR_TASKING = "ScoutMissions::MissionRequirements::IsrTasking"
#: the playhead the Mission beat starts from (mission seconds).  The clock
#: runs at 4x, and the onboard view opens about 3 s (12 mission seconds)
#: after play, so it opens 2 s before the track's turn at 70-79 s
FLIGHT_START_S = 50.0

# -- the demo notebook ---------------------------------------------------------

CELLS: tuple[tuple[str, str], ...] = (
    ("markdown", "# 9. The grand tour: one mission architecture, every pane"),
    (
        "code",
        "import longeron\n"
        "from longeron.analysis.grand import grand_dashboard\n"
        "\n"
        'program = longeron.load("deepscout")  # the whole DeepScout program: one workspace\n'
        'dash = grand_dashboard(program)  # mission="ISR", airframe=None: the mission\'s winner\n'
        "dash",
    ),
    ("code", "dash.dock()  # JupyterLab: nine docked panes in the main area"),
)
#: the cell index of ``dash.dock()``: the take runs every cell above it
#: off camera, and runs this one on camera
DOCK_CELL = 2


def build_lab_root() -> None:
    """A throwaway lab root: the demo notebook plus the models it loads."""

    if LAB_ROOT.exists():
        shutil.rmtree(LAB_ROOT)
    LAB_ROOT.mkdir(parents=True)
    shutil.copytree(REPO / "examples" / "deepscout", LAB_ROOT / "deepscout")
    notebook = {
        "cells": [
            {
                "cell_type": kind,
                "id": f"cell-{index}",
                "metadata": {},
                "source": source,
                **({"execution_count": None, "outputs": []} if kind == "code" else {}),
            }
            for index, (kind, source) in enumerate(CELLS)
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (LAB_ROOT / NOTEBOOK).write_text(json.dumps(notebook, indent=1), encoding="utf-8")


def _kernel_env() -> dict[str, str]:
    """The environment the lab server (and so the kernel) runs under."""

    return dict(
        os.environ,
        PYTHONHASHSEED="0",
        # kernels inherit this: a contended machine can hold up the elkjs
        # layout roundtrip for minutes, and a tripped timeout is a FINAL
        # visible failure -- same choice as tests/browser/conftest.py
        LONGERON_BROWSER_TIMEOUT="600",
        # a rig-local parse cache, warmed off camera so the on-camera
        # Run All spends its seconds building the dashboard, not parsing
        LONGERON_CACHE_DIR=str(MODEL_CACHE),
        # the kernel must import THIS tree's sources even when the
        # editable install resolves elsewhere (ipyelk is the env's wheel)
        PYTHONPATH=os.pathsep.join(
            path for path in (str(REPO / "src"), os.environ.get("PYTHONPATH", "")) if path
        ),
    )


def warm_model_cache() -> None:
    """Parse-cache the demo models off camera (content-addressed)."""

    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import longeron\nlongeron.load({str(LAB_ROOT / 'deepscout')!r})\n",
        ],
        env=_kernel_env(),
        check=True,
        capture_output=True,
    )


# -- the lab server (mirrors scripts/capture_widget_snapshots.py) -------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class LabServer:
    base_url: str
    token: str
    process: subprocess.Popen[bytes]
    log_path: Path

    def url_for(self, notebook: str) -> str:
        # a fresh workspace (+ &reset): no restored layout steals the take
        return f"{self.base_url}/lab/workspaces/demo-take/tree/{notebook}?token={self.token}&reset"


def start_lab_server() -> LabServer:
    settings = DEMO_DIR / "lab-user-settings"
    if settings.exists():
        shutil.rmtree(settings)
    tracker = settings / "@jupyterlab" / "notebook-extension"
    tracker.mkdir(parents=True)
    (tracker / "tracker.jupyterlab-settings").write_text(
        # autoStartDefaultKernel: no modal kernel picker on open;
        # windowingMode none: every cell stays attached (browser-tier choice)
        json.dumps({"autoStartDefaultKernel": True, "windowingMode": "none"}),
        encoding="utf-8",
    )
    docmanager = settings / "@jupyterlab" / "docmanager-extension"
    docmanager.mkdir(parents=True)
    # autosave OFF: the demo notebook stays pristine take after take
    (docmanager / "plugin.jupyterlab-settings").write_text(
        json.dumps({"autosave": False}), encoding="utf-8"
    )
    apputils = settings / "@jupyterlab" / "apputils-extension"
    apputils.mkdir(parents=True)
    # no news toast / update banner photobombing the bottom-right corner
    (apputils / "notification.jupyterlab-settings").write_text(
        json.dumps({"fetchNews": "false", "checkForUpdates": False, "doNotDisturbMode": True}),
        encoding="utf-8",
    )
    env = dict(
        _kernel_env(),
        JUPYTERLAB_SETTINGS_DIR=str(settings),
        JUPYTERLAB_WORKSPACES_DIR=str(settings / "workspaces"),
    )
    port = _free_port()
    token = secrets.token_hex(16)
    log_path = DEMO_DIR / "lab-server.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "jupyterlab",
                "--no-browser",
                "--LabApp.expose_app_in_browser=True",
                f"--port={port}",
                "--ServerApp.port_retries=0",
                f"--ServerApp.token={token}",
                "--ServerApp.password=",
                f"--ServerApp.root_dir={LAB_ROOT}",
                "--ServerApp.disable_check_xsrf=True",
                "--LanguageServerManager.autodetect=False",
            ],
            cwd=LAB_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    server = LabServer(f"http://127.0.0.1:{port}", token, process, log_path)
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"jupyter lab exited with {process.returncode}; see {log_path}")
        try:
            with urllib.request.urlopen(
                f"{server.base_url}/api/status?token={token}", timeout=5
            ) as response:
                if response.status == 200:
                    return server
        except (urllib.error.URLError, OSError) as err:
            last_error = err
        time.sleep(0.5)
    raise RuntimeError(f"jupyter lab not ready after 120s ({last_error}); see {log_path}")


# -- the fake cursor (playwright records no OS pointer) ------------------------

CURSOR_JS = """
(() => {
  const attach = () => {
    if (!document.body || document.getElementById('lgn-demo-cursor')) return;
    const dot = document.createElement('div');
    dot.id = 'lgn-demo-cursor';
    Object.assign(dot.style, {
      position: 'fixed', left: '-40px', top: '-40px', width: '22px', height: '22px',
      border: '2.5px solid rgba(25, 103, 210, 0.95)', borderRadius: '50%',
      background: 'rgba(66, 133, 244, 0.30)', zIndex: '2147483647',
      pointerEvents: 'none', transform: 'translate(-50%, -50%)',
      boxShadow: '0 0 8px rgba(66, 133, 244, 0.55)',
      transition: 'width 90ms ease, height 90ms ease, background 90ms ease',
    });
    document.body.appendChild(dot);
    document.addEventListener('mousemove', (event) => {
      dot.style.left = event.clientX + 'px';
      dot.style.top = event.clientY + 'px';
    }, true);
    document.addEventListener('mousedown', () => {
      dot.style.width = '15px';
      dot.style.height = '15px';
      dot.style.background = 'rgba(217, 48, 37, 0.55)';
    }, true);
    document.addEventListener('mouseup', () => {
      dot.style.width = '22px';
      dot.style.height = '22px';
      dot.style.background = 'rgba(66, 133, 244, 0.30)';
    }, true);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
"""

# -- browser-truth probes (the predicates of tests/browser/test_browser_grand_tour.py)

#: the dashboard's structure-diagram framing (the one visible sprotty
#: pane in the notebook output area)
_VISIBLE_DIAGRAM_JS = r"""() => {
    const shown = [...document.querySelectorAll(
        '.jp-OutputArea div.sprotty[id^="sprotty"]',
    )].filter((div) => div.getBoundingClientRect().width > 0);
    if (shown.length !== 1) return { shown: shown.length };
    const g = shown[0].querySelector('svg.sprotty-graph > g');
    if (!g) return { shown: 1, rendered: false };
    const view = shown[0].getBoundingClientRect();
    const content = g.getBoundingClientRect();
    const transform = g.getAttribute('transform') || '';
    const zoom = /scale\(([\d.eE+-]+)/.exec(transform);
    return {
        shown: 1,
        rendered: content.width > 0,
        transform,
        scale: zoom ? Number(zoom[1]) : 1,
        fitted: transform !== '' && transform !== 'scale(1) translate(0,0)'
            && transform !== 'translate(0, 0) scale(1)',
        overflowX: Math.max(0, view.left - content.left, content.right - view.right),
        overflowY: Math.max(0, view.top - content.top, content.bottom - view.bottom),
    };
}"""

#: count the 3D pane's scene rebuilds: the viewer's rebuild() is the only
#: code that writes the canvas aria-label (a record on every write)
_ARM_REBUILDS_JS = """() => {
    const canvas = document.querySelector('.longeron-viewer3d canvas');
    if (!canvas) return false;
    window.__lgnRebuilds = 0;
    new MutationObserver((records) => { window.__lgnRebuilds += records.length; })
        .observe(canvas, {attributes: true, attributeFilter: ['aria-label']});
    return true;
}"""

#: a screen point inside the scoreboard cell whose qname ends with the
#: argument: the cell's vertex centroid (a Voronoi cell is convex), mapped
#: to the screen through the SVG's own transform
_CELL_POINT_JS = """(suffix) => {
    const path = [...document.querySelectorAll('.lgn-sb-cell')]
        .find((el) => (el.getAttribute('data-qname') || '').endsWith(suffix));
    if (!path) return null;
    const nums = (path.getAttribute('d').match(/-?[0-9.]+(?:e-?[0-9]+)?/g) || []).map(Number);
    let x = 0, y = 0;
    for (let i = 0; i + 1 < nums.length; i += 2) { x += nums[i]; y += nums[i + 1]; }
    const point = path.ownerSVGElement.createSVGPoint();
    point.x = x / (nums.length / 2);
    point.y = y / (nums.length / 2);
    const screen = point.matrixTransform(path.getScreenCTM());
    return {x: screen.x, y: screen.y, fill: path.getAttribute('fill'),
            hit: document.elementFromPoint(screen.x, screen.y) === path};
}"""

#: the Cesium pane: booted with its mission, the clock's playhead, the
#: active view-mode button and whether the imagery tiles have landed
_CESIUM_JS = """() => {
    const stage = document.querySelector('.longeron-mission3d-stage');
    const viewer = stage && stage.longeronViewer;
    if (!viewer || !viewer.dataSources.length) return {cesium: false};
    return {
        cesium: true,
        seconds: window.Cesium.JulianDate.secondsDifference(
            viewer.clock.currentTime, viewer.clock.startTime),
        animating: viewer.clock.shouldAnimate,
        tiles: viewer.scene.globe.tilesLoaded,
        active: [...stage.querySelectorAll('.longeron-mission3d-modes button.active')]
            .map((button) => button.textContent),
    };
}"""

#: the docked panes: one titled tab per pane in the Lab main area
GRAND_TABS = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey^="grand-"]'

#: the width of a docked pane's panel (LabShell writes the panel's DOM id
#: into its tab's dataset)
_PANEL_WIDTH_JS = """(key) => {
    const tab = document.querySelector(
        `#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="${key}"]`);
    const panel = tab && document.getElementById(tab.dataset.id);
    return panel ? panel.getBoundingClientRect().width : null;
}"""

#: the center of the split bar between the panels of two panes side by side
_HANDLE_JS = """([leftKey, rightKey]) => {
    const box = (key) => {
        const tab = document.querySelector(
            `#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="${key}"]`);
        const panel = tab && document.getElementById(tab.dataset.id);
        return panel ? panel.getBoundingClientRect() : null;
    };
    const a = box(leftKey), b = box(rightKey);
    if (!a || !b) return null;
    for (const handle of document.querySelectorAll(
        '#jp-main-dock-panel > .lm-DockPanel-handle')) {
        const r = handle.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        if (r.x >= a.right - 6 && r.right <= b.left + 6 && r.top <= a.top + 40
            && r.bottom >= a.top + a.height / 2) {
            return {x: r.x + r.width / 2, y: a.top + a.height / 2};
        }
    }
    return null;
}"""


def poll(probe: Any, label: str, *, timeout: float = 60.0, every: float = 0.1) -> Any:
    """Return ``probe()`` as soon as it is truthy (the reaction landed)."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = probe()
        if found:
            return found
        time.sleep(every)
    raise TimeoutError(f"never happened: {label}")


class Camera:
    """Human-paced choreography over one playwright page."""

    def __init__(self, page: Any) -> None:
        self.page = page
        #: the cursor position: every move of the take goes through the camera
        self.x, self.y = VIEWPORT["width"] / 2, VIEWPORT["height"] / 2
        self.frames: list[Path] = []
        self.beats: list[tuple[float, str]] = []
        #: set when the take starts: beat times are relative to the cut's t=0
        self.t0: float | None = None

    def mark(self, label: str) -> None:
        """Log a beat timestamp relative to the trimmed video's t=0."""

        assert self.t0 is not None, "mark() before the scene starts"
        at = time.monotonic() - self.t0
        self.beats.append((round(at, 1), label))
        print(f"  beat {at:5.1f}s  {label}", flush=True)

    def beat(self, ms: int = BEAT) -> None:
        self.page.wait_for_timeout(ms)

    def hold(self, since: float, ms: int) -> None:
        """Wait until ``ms`` have passed since the monotonic time ``since``
        (a still taken inside the hold costs no extra screen time)."""

        left = since + ms / 1000 - time.monotonic()
        if left > 0:
            self.page.wait_for_timeout(left * 1000)

    def jump(self, x: float, y: float) -> None:
        """Put the cursor at ``(x, y)`` at once (off camera only)."""

        self.page.mouse.move(x, y)
        self.x, self.y = x, y

    def glide_to(self, x: float, y: float, ms: int = GLIDE_MS) -> None:
        """Travel to ``(x, y)`` in ``ms``, eased in and out like a hand."""

        x0, y0 = self.x, self.y
        start = time.monotonic()
        while (elapsed := (time.monotonic() - start) * 1000) < ms:
            ease = (1 - math.cos(math.pi * elapsed / ms)) / 2
            self.page.mouse.move(x0 + (x - x0) * ease, y0 + (y - y0) * ease)
            self.page.wait_for_timeout(16)
        self.jump(x, y)

    def glide(self, locator: Any, ms: int = GLIDE_MS) -> tuple[float, float]:
        """Smoothly travel to the center of ``locator``; returns the point."""

        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError(f"no bounding box for {locator}")
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        self.glide_to(x, y, ms)
        return x, y

    def press(self) -> None:
        """A visible click where the cursor is (the overlay dips red)."""

        self.page.wait_for_timeout(120)
        self.page.mouse.down()
        self.page.wait_for_timeout(90)
        self.page.mouse.up()

    def click(self, locator: Any) -> None:
        self.glide(locator)
        self.press()

    def drag(self, start: tuple[float, float], end: tuple[float, float], ms: int) -> None:
        """Press at ``start``, travel to ``end`` in ``ms``, release.

        The sweep is paced (playwright's ``steps=`` runs at protocol speed,
        too fast to read as a human drag), so every intermediate value of a
        slider streams through ``continuous_update`` and the kernel-side
        repaints show live under the drag.
        """

        self.glide_to(*start)
        self.page.wait_for_timeout(150)
        self.page.mouse.down()
        self.glide_to(*end, ms=ms)
        self.page.wait_for_timeout(120)
        self.page.mouse.up()

    def drag_slider_to_max(self, slider: Any, ms: int = DRAG_MS) -> None:
        """Drag an ipywidgets slider handle past the right end of its track
        (noUiSlider clamps to the maximum)."""

        handle = slider.locator(".noUi-handle").first
        handle.scroll_into_view_if_needed()
        grip = handle.bounding_box()
        rail = slider.locator(".noUi-base").first.bounding_box()
        if grip is None or rail is None:
            raise RuntimeError("slider has no bounding box")
        y = grip["y"] + grip["height"] / 2
        start = (grip["x"] + grip["width"] / 2, y)
        self.drag(start, (rail["x"] + rail["width"] + 8, y), ms)

    def tab(self, title: str) -> None:
        """Click the dashboard tab titled ``title`` and wait until it is current."""

        tab = self.page.locator(
            ".jp-OutputArea-output .lgn-grand-tabs .lm-TabBar-tab", has_text=title
        ).first
        self.click(tab)
        poll(lambda: "lm-mod-current" in (tab.get_attribute("class") or ""), f"{title} tab")

    def shot(self, name: str) -> None:
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
        path = FRAME_DIR / f"{name}.png"
        self.page.screenshot(path=str(path))
        self.frames.append(path)

    def wait_scale(self, minimum: float, *, timeout: float = 30.0) -> None:
        """Wait for the diagram's zoom to reach ``minimum`` and settle (the
        animated fit runs client-side; the camera must not move on
        mid-flight)."""

        deadline = time.monotonic() + timeout
        stable: str | None = None
        streak = 0
        while time.monotonic() < deadline:
            state = dict(self.page.evaluate(_VISIBLE_DIAGRAM_JS))
            if state.get("scale", 0) >= minimum:
                streak = streak + 1 if state.get("transform") == stable else 0
                stable = state.get("transform")
                if streak >= 2:
                    return
            else:
                streak, stable = 0, None
            time.sleep(0.15)
        raise TimeoutError(f"diagram zoom never settled at or above {minimum}")

    def wait_diagram(self, *, timeout: float = 150.0) -> str:
        """Wait for the dashboard diagram: rendered, fitted, settled.

        Framing is part of the contract: the content must sit INSIDE the
        pane (the autofit lands a beat after the relayout), and the fit
        transform must hold for three polls.
        """

        deadline = time.monotonic() + timeout
        stable: str | None = None
        streak = 0
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = dict(self.page.evaluate(_VISIBLE_DIAGRAM_JS))
            good = (
                state.get("rendered")
                and state.get("fitted")
                # scale(0.01) is the hidden-viewport autofit sentinel
                and state.get("scale", 0) > 0.02
                and state.get("overflowX", 1e9) <= 1.5
                and state.get("overflowY", 1e9) <= 1.5
            )
            if good:
                streak = streak + 1 if state.get("transform") == stable else 0
                stable = state.get("transform")
                if streak >= 3:
                    return str(stable)
            else:
                streak, stable = 0, None
            time.sleep(0.5)
        raise TimeoutError(f"dashboard diagram never settled; last state: {state}")


def wait_kernel_idle(page: Any, timeout: float = 300.0) -> None:
    page.wait_for_selector(
        '.jp-Notebook-ExecutionIndicator[data-status="idle"]',
        state="attached",
        timeout=timeout * 1000,
    )


def open_demo_notebook(page: Any, server: LabServer, timeout: float = 120.0) -> None:
    page.goto(server.url_for(NOTEBOOK), wait_until="domcontentloaded")
    page.wait_for_selector(".jp-Notebook", state="attached", timeout=timeout * 1000)
    # reject any modal (Build Recommended etc.); the kernel picker cannot
    # appear (autoStartDefaultKernel) -- same belt as the browser tier
    page.add_locator_handler(
        page.locator(".jp-Dialog .jp-mod-reject"), lambda button: button.click()
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate("() => !!(window.jupyterapp || window.jupyterlab)"):
            break
        time.sleep(1)
    else:
        raise TimeoutError("JupyterLab app handle never appeared")
    wait_kernel_idle(page, timeout)


#: the demo notebook's panel, also after dock() makes a docked pane the
#: main area's current widget
_NOTEBOOK_PANEL_JS = """const app = window.jupyterapp || window.jupyterlab;
    const panel = Array.from(app.shell.widgets('main'))
        .find((widget) => widget.sessionContext && widget.content
              && widget.content.widgets);"""


def kernel_exec(page: Any, code: str, timeout_ms: int = 30_000) -> str:
    """Silently execute ``code`` on the notebook's kernel (no cell, no
    camera footprint).  Returns the reply status (``ok`` / ``error``), so
    an ``assert`` makes a kernel-truth probe."""

    return str(
        page.evaluate(
            "async ([code, timeout]) => {"
            + _NOTEBOOK_PANEL_JS
            + """
            const future = panel.sessionContext.session.kernel.requestExecute(
                { code, silent: true, store_history: false });
            const reply = await Promise.race([future.done, new Promise((_, reject) =>
                setTimeout(() => reject(new Error('kernel_exec timeout')), timeout))]);
            return reply.content.status;
        }""",
            [code, timeout_ms],
        )
    )


def kernel_assert(page: Any, expression: str, timeout: float = 30.0) -> None:
    """Poll ``expression`` on the kernel until it holds (kernel truth for
    state a comm write lands asynchronously)."""

    poll(
        lambda: kernel_exec(page, f"assert {expression}") == "ok",
        f"kernel: {expression}",
        timeout=timeout,
        every=0.2,
    )


# -- the scenario ----------------------------------------------------------------


def preroll(page: Any, server: LabServer, cam: Camera) -> None:
    """Off camera: open the notebook, run every cell above ``dash.dock()``,
    and let the dashboard compose and settle with the ISR winner as its
    subject.  The cut starts after this returns."""

    open_demo_notebook(page, server)
    print("  preroll: notebook open, running the cells above dash.dock()", flush=True)
    page.evaluate("() => { (window.jupyterapp || window.jupyterlab).shell.collapseLeft(); }")
    # Run All would dock the tour too: run the cells ABOVE the dock cell
    page.evaluate(
        "(index) => {"
        + _NOTEBOOK_PANEL_JS
        + """
        panel.content.activeCellIndex = index;
        void app.commands.execute('notebook:run-all-above');
    }""",
        DOCK_CELL,
    )
    page.wait_for_selector(".lgn-sb-cell", state="attached", timeout=300_000)
    page.wait_for_selector(".longeron-viewer3d canvas", timeout=120_000)
    page.wait_for_selector(".lgx-row", state="attached", timeout=60_000)
    wait_kernel_idle(page)
    page.evaluate(
        "() => document.querySelector('.jp-OutputArea-output:has(.lgn-grand-tour)')"
        ".scrollIntoView({block: 'start'})"
    )
    # the Cesium pane boots on its first reveal: pay the globe and its
    # imagery tiles here, then show the 3D tab again
    for title in ("Mission", "3D"):
        tab = page.locator(
            ".jp-OutputArea-output .lgn-grand-tabs .lm-TabBar-tab", has_text=title
        ).first
        tab.click()
        poll(lambda tab=tab: "lm-mod-current" in (tab.get_attribute("class") or ""), title)
        if title == "Mission":
            poll(lambda: page.evaluate(_CESIUM_JS)["cesium"], "the Cesium globe", timeout=120.0)
            try:  # best effort: a render-on-demand globe can idle with tiles pending
                poll(lambda: page.evaluate(_CESIUM_JS)["tiles"], "imagery tiles", timeout=20.0)
            except TimeoutError:
                print("  (preroll: Cesium imagery still streaming)", flush=True)
    cam.wait_diagram()
    print("  preroll: the dashboard has composed", flush=True)
    assert page.evaluate(_ARM_REBUILDS_JS), "no 3D canvas to watch"
    kernel_assert(page, 'dash.subject.mission == "ISR" and dash.subject.overrides == {}')
    # the cursor waits at the header's right end, clear of every pane
    header = page.locator(".widget-html", has_text="the grand tour").first
    box = header.bounding_box()
    assert box is not None, "no header"
    cam.jump(box["x"] + box["width"] * 0.78, box["y"] + box["height"] * 0.5)
    page.wait_for_timeout(1500)  # the last repaint lands before the cut


def perform(page: Any, server: LabServer) -> tuple[float, Camera]:
    """The scripted walkthrough; returns (scene-start offset s, camera)."""

    cam = Camera(page)
    t_page = time.monotonic()
    preroll(page, server, cam)
    cam.t0 = time.monotonic()
    scene_start = cam.t0 - t_page  # the cut: the composed, settled dashboard

    def rebuilds() -> int:
        return int(page.evaluate("() => window.__lgnRebuilds || 0"))

    # -- a) the header names the subject: the ISR mission's winner ---------
    cam.mark("a) header: the ISR winner is the subject")
    cam.shot("01-isr-winner")
    header = page.locator(".widget-html", has_text="the grand tour").first
    cam.glide(header.locator("b").first)
    cam.beat()
    box = header.bounding_box()
    assert box is not None, "no header"
    cam.glide_to(box["x"] + box["width"] * 0.9, box["y"] + box["height"] / 2)  # the score
    cam.beat()

    # -- b) a tree row click: the twin-tip flying wing becomes the subject -
    cam.mark("b) tree: filter, click flyingWingTwinTip")
    search = page.locator(".lgx-tree-search").first
    cam.click(search)
    page.keyboard.type("TwinTip", delay=110)
    row = page.locator(f'.lgx-row[data-id="{TWIN_TIP}"]').first
    row.wait_for(state="visible", timeout=30_000)
    before = rebuilds()
    cam.click(row)
    kernel_assert(page, 'dash.subject.airframe == "flyingWingTwinTip"')
    poll(lambda: rebuilds() > before, "the 3D pane rebuilt the twin-tip wing")
    poll(lambda: "flyingWingTwinTip" in (header.text_content() or ""), "the header names it")
    cam.mark("b) subject changed: 3D, header, scoreboard")
    cam.glide(header.locator("b").first)
    cam.beat()
    # the tree row selected the diagram node too: the toolbar's fit button
    # (hover-revealed over the diagram) frames the selection
    diagram = page.locator('.jp-OutputArea div.sprotty[id^="sprotty"]').first
    cam.glide(diagram)
    fit = page.locator('.jp-OutputArea button[title^="Fit the diagram to the view"]').first
    fit.wait_for(state="visible", timeout=10_000)
    cam.click(fit)
    cam.wait_scale(0.3)
    cam.mark("b) diagram framed on the selected craft")
    cam.beat()

    # -- c) the wingSpan knob to its maximum: the wing widens in 3D --------
    cam.mark("c) drag airframe.wingSpan to its maximum")
    span = page.locator(".widget-hslider").filter(has_text="wingSpan").first
    before = rebuilds()
    cam.drag_slider_to_max(span)
    kernel_assert(
        page,
        'dash.knobs["airframe.wingSpan"].value == dash.knobs["airframe.wingSpan"].max'
        ' and dash.subject.overrides.get("airframe.wingSpan") == dash.knobs['
        '"airframe.wingSpan"].max',
    )
    poll(lambda: rebuilds() > before, "the 3D pane rebuilt the wider wing")
    wait_kernel_idle(page)
    cam.glide(page.locator(".longeron-viewer3d canvas").first)
    since = time.monotonic()
    cam.shot("02-span-max-3d")
    cam.hold(since, BEAT)

    # -- d) the scoreboard: the re-scored leaf, then the IsrTasking tooltip -
    cam.mark("d) Requirements tab: the re-scored board")
    cam.tab("Requirements")
    poll(lambda: page.evaluate(_CELL_POINT_JS, "::PitchStability"), "the scoreboard cells")
    tip = page.locator(".lgn-sb-tip").first
    for leaf in ("::PitchStability", "::IsrTasking"):
        point = page.evaluate(_CELL_POINT_JS, leaf)
        cam.glide_to(point["x"], point["y"])
        name = leaf.removeprefix("::")
        poll(lambda name=name: tip.is_visible() and name in (tip.text_content() or ""), name)
        since = time.monotonic()
        if name == "IsrTasking":
            cam.mark("d) IsrTasking tooltip")
            cam.shot("03-requirements-tooltip")
        cam.hold(since, BEAT)

    # -- e) the Sizing tab: maximize station time, the driver history ------
    cam.mark("e) Sizing tab: maximize station time")
    cam.tab("Sizing")
    cam.click(page.locator('button:text-is("maximize station time")').first)
    kernel_assert(page, "dash.loiter.value == 11.0")
    history = page.locator('svg[aria-label="driver iteration history"]').first
    history.wait_for(state="visible", timeout=60_000)
    cam.mark("e) driver history drawn")
    sizing = page.locator(".lgn-grand-card", has_text="OpenMDAO sizing").first
    for rendering in (
        history,
        sizing.locator("table").first,
        sizing.locator('svg[aria-label="N2 matrix"]').first,
    ):
        cam.glide(rendering)
        cam.beat()

    # -- e2) the Z3 tab: the design point is SAT, the what-if UNSAT --------
    cam.mark("e2) Z3 tab: SAT, and the UNSAT core")
    cam.tab("Z3")
    verdicts = page.locator(".lgn-grand-card", has_text="at the design point").first
    for line in ("at the design point", "aboveStall"):
        cam.glide(verdicts.get_by_text(line).first)
        cam.beat()

    # -- f) the Mission tab: play, ride onboard through a turn, follow -----
    # the playhead goes to the turn while the pane is hidden (no visible jump)
    assert kernel_exec(page, f"dash.mission.time = {FLIGHT_START_S}") == "ok"
    cam.mark("f) Mission tab: play")
    cam.tab("Mission")
    poll(
        lambda: (lambda s: s["cesium"] and abs(s["seconds"] - FLIGHT_START_S) < 0.5)(
            page.evaluate(_CESIUM_JS)
        ),
        "the Cesium clock at the turn",
    )
    dial = page.locator(".cesium-animation-rectButton")
    cam.click(dial.filter(has_text="Play Forward").first)
    poll(lambda: page.evaluate(_CESIUM_JS)["animating"], "the clock animates")
    cam.beat(2 * BEAT)  # the follow view: the wing flies the track
    modes = page.locator(".longeron-mission3d-modes")
    cam.click(modes.locator('button:text-is("onboard")').first)
    poll(lambda: page.evaluate(_CESIUM_JS)["active"] == ["onboard"], "the onboard view")
    since = time.monotonic()
    cam.mark("f) onboard: through the mission camera")
    cam.glide_to(*_offstage(page), ms=600)  # the view, not the cursor
    cam.hold(since, ONBOARD_MS // 2)
    cam.shot("04-onboard-turn")
    cam.hold(since, ONBOARD_MS)
    cam.click(modes.locator('button:text-is("follow")').first)
    poll(lambda: page.evaluate(_CESIUM_JS)["active"] == ["follow"], "the follow view")
    cam.mark("f) follow")
    cam.beat()
    # pause: the docked layout below then holds a still globe
    cam.click(dial.filter(has_text="Pause").first)
    poll(lambda: not page.evaluate(_CESIUM_JS)["animating"], "the clock paused")

    # -- g) a cell runs dash.dock(): nine Lab tabs; drag one split bar -----
    cam.mark("g) run the dash.dock() cell")
    cell = page.locator(".jp-Notebook .jp-Cell").nth(DOCK_CELL)
    cam.click(cell.locator(".jp-InputArea-editor").first)
    page.keyboard.press("Control+Enter")
    poll(lambda: page.locator(GRAND_TABS).count() == 9, "nine docked panes", timeout=90.0)
    page.wait_for_selector(".lgn-grand-pane .longeron-viewer3d canvas", timeout=120_000)
    page.wait_for_selector(".lgn-grand-pane .lgx-row", timeout=60_000)
    handle = poll(
        lambda: page.evaluate(_HANDLE_JS, ["grand-tree", "grand-structure"]),
        "the split bar between the tree and the diagram",
    )
    cam.mark("g) docked: nine tabs")
    cam.beat()
    # the split bar first: the resize also makes the docked diagram refit
    width = page.evaluate(_PANEL_WIDTH_JS, "grand-tree")
    cam.drag((handle["x"], handle["y"]), (handle["x"] + 180, handle["y"]), ms=1600)
    poll(
        lambda: (page.evaluate(_PANEL_WIDTH_JS, "grand-tree") or 0) > width + 100,
        "the tree pane widened",
    )
    cam.mark("g) split bar dragged")
    for key in ("tree", "structure", "3d", "scoreboard", "subject", "mission"):
        cam.glide(page.locator(f'{GRAND_TABS}[data-lgxkey="grand-{key}"]').first, ms=500)

    # -- h) end on the docked layout ---------------------------------------
    since = time.monotonic()
    cam.glide_to(*_offstage(page), ms=600)
    cam.shot("05-docked")
    cam.hold(since, END_MS)
    cam.mark("h) cut")
    return scene_start, cam


def _offstage(page: Any) -> tuple[float, float]:
    """A cursor rest point on the Lab's status bar, clear of every pane."""

    bar = page.locator("#jp-main-statusbar").bounding_box()
    if bar is None:
        return VIEWPORT["width"] * 0.5, VIEWPORT["height"] - 10
    return bar["x"] + bar["width"] * 0.5, bar["y"] + bar["height"] * 0.5


# -- post-production ---------------------------------------------------------------


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{result.stderr[-2000:]}")


def _probe_duration(path: Path) -> float:
    ffprobe = str(Path(FFMPEG).with_name("ffprobe"))
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def encode_outputs(webm: Path, trim_s: float) -> dict[str, Any]:
    """webm -> mp4 (h264) + palette-optimized GIF under the size budget."""

    mp4 = DEMO_DIR / "demo.mp4"
    _run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{trim_s:.2f}",
            "-i",
            str(webm),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
    )

    gif = DEMO_DIR / "demo.gif"
    rung_used: dict[str, Any] = {}
    for rung in GIF_LADDER:
        # the capture's VP8 noise changes every frame: a temporal denoise and
        # a drop of the near-duplicate frames let the GIF encode only the
        # rectangle that changed (about half the size of a plain encode)
        filters = (
            f"fps={rung['fps']},scale={rung['width']}:-1:flags=lanczos,"
            "hqdn3d=0:0:8:8,mpdecimate,"
            f"split[s0][s1];[s0]palettegen=max_colors={rung['colors']}:stats_mode=diff[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
        )
        _run(
            [
                FFMPEG,
                "-y",
                "-ss",
                f"{trim_s:.2f}",
                "-i",
                str(webm),
                "-filter_complex",
                filters,
                "-fps_mode",
                "vfr",
                str(gif),
            ]
        )
        rung_used = dict(rung)
        if gif.stat().st_size <= GIF_BUDGET_BYTES:
            break
    return {
        "mp4": {"path": str(mp4), "bytes": mp4.stat().st_size, "s": _probe_duration(mp4)},
        "gif": {"path": str(gif), "bytes": gif.stat().st_size, "rung": rung_used},
    }


# -- main ---------------------------------------------------------------------------


def main() -> int:
    from playwright.sync_api import sync_playwright

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    if FRAME_DIR.exists():
        shutil.rmtree(FRAME_DIR)
    build_lab_root()
    warm_model_cache()
    server = start_lab_server()
    webm = DEMO_DIR / "demo.webm"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--disable-dev-shm-usage", *GPU_ARGS])
            context = browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=DEVICE_SCALE_FACTOR,
                record_video_dir=str(DEMO_DIR / "video"),
                record_video_size=VIEWPORT,
            )
            context.add_init_script(CURSOR_JS)
            # warm take: pays the extension/asset cold start OFF camera,
            # including the CDN bundles the 3D and Cesium panes import
            warm = context.new_page()
            warm.goto(f"{server.base_url}/lab?token={server.token}", wait_until="domcontentloaded")
            warm.wait_for_selector("#jp-main-dock-panel", state="attached", timeout=120_000)
            warm.evaluate(
                "(urls) => Promise.allSettled(urls.map("
                "(u) => fetch(u, {cache: 'force-cache'}).then((r) => r.blob())))",
                list(CDN_WARM_URLS),
            )
            warm_video = warm.video
            warm.close()

            page = context.new_page()
            try:
                trim_s, cam = perform(page, server)
            except Exception:
                page.screenshot(path=str(DEMO_DIR / "failure.png"))
                raise
            finally:
                video = page.video
                page.close()
                context.close()
                if video is not None:
                    shutil.move(video.path(), webm)
                if warm_video is not None:
                    Path(warm_video.path()).unlink(missing_ok=True)
            browser.close()
    finally:
        server.process.terminate()
        try:
            server.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.process.kill()
            server.process.wait()

    outputs = encode_outputs(webm, trim_s)
    outputs["webm"] = {"path": str(webm), "bytes": webm.stat().st_size}
    outputs["frames"] = [str(path) for path in cam.frames]
    outputs["beats"] = cam.beats
    outputs["trim_s"] = round(trim_s, 2)
    (DEMO_DIR / "summary.json").write_text(json.dumps(outputs, indent=1), encoding="utf-8")

    print(f"webm : {webm}  ({webm.stat().st_size / 1e6:.1f} MB)")
    mp4 = outputs["mp4"]
    print(f"mp4  : {mp4['path']}  ({mp4['bytes'] / 1e6:.1f} MB, {mp4['s']:.1f}s)")
    gif = outputs["gif"]
    print(f"gif  : {gif['path']}  ({gif['bytes'] / 1e6:.1f} MB, rung {gif['rung']})")
    for frame in cam.frames:
        print(f"frame: {frame}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
