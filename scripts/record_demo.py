#!/usr/bin/env python
"""Record the README demo: the grand-tour dashboard, one take -> mp4 + GIF.

    python scripts/record_demo.py

re-records the whole thing after UI changes.  The walkthrough is
DETERMINISTIC by construction: a purpose-built copy of the tutorial-9
notebook is generated into a throwaway lab root (the repo's notebooks are
never touched), the models it loads ship with this checkout
(the ``examples/deepscout`` program directory), the
scoreboard's Voronoi seed is fixed inside ``grand_dashboard``,
``PYTHONHASHSEED=0`` pins kernel hashing, and every camera beat is a
fixed pause -- so two recordings differ only in sub-second layout-arrival
jitter plus Cesium imagery-tile streaming (the finale's camera framing is
CZML ``viewFrom`` tracking and therefore stable; only tile sharpness
varies with the network).

The story is ONE LINEAR pass over ONE surface (~70 s), every beat
motivated, no back-and-forth: open ``09_grand_tour.ipynb`` -> Run All
Cells -> scroll once to the dashboard and let the composition land ->
the diagram dives into the ``QuadCopter`` node (the DeepScout program
is ~18k px of diagram, so the camera frames what it is about to touch:
an animated kernel-side ``fit``, the same move the toolbar's fit button
makes) -> click the ``motors : Motor [4]`` row (all four motors flash
in 3D) -> the frame pulls back one step to the multirotor family -> click
into the ``HexaCopter`` (its ``motors : Motor [6]`` row) and the 3D
pane BECOMES that craft, six rotors baked from its own M0 population
(0.11's config-keyed viewer: ``bind_config_view`` is on by default;
any selection resolves to its owning craft), then click ``QuadCopter``
and the home craft returns, view cone and all
-> drag the azimuth slider until the view cone sweeps into the airframe
(occludedFraction goes red, ``clearView`` flips red on the Voronoi, the
obstructing parts light up) and drag back to clear (the score recovers
live) -> drag the loiter slider down to the stall floor (the generated
OpenMDAO problem re-runs on every step; station time climbs to its
maximum) -> a cursor pass over the Z3 SAT verdict
and the what-if's UNSAT conflict core -> double-click the ``endurance``
cell (the Voronoi zooms to the performance branch) and Esc back -> press
play on the Cesium timeline and end mid-flight over satellite Atlanta.
Outputs land in ``build/demo/`` (gitignored):

* ``demo.webm``   -- the raw playwright capture (1600x1200)
* ``demo.mp4``    -- h264, crf 20, faststart (the shareable video)
* ``demo.gif``    -- palette-optimized, <= 10 MB (the GitHub release-asset
  budget; see the publish workflow below)
* ``frames/*.png``-- five representative stills for quick review

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
the mouse (playwright records no OS cursor), travel is smoothed with
``mouse.move(steps=...)``, slider drags are paced segment by segment so
the kernel repaints stream by on camera, and every action gets a beat to
breathe.  The models are parse-cached and the three.js/Cesium CDN
bundles are browser-cached OFF camera, so the on-camera Run All lands in
seconds.  Record on a quiet machine -- concurrent browser suites steal
the frames' smoothness.
"""

from __future__ import annotations

import json
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
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO / "build" / "demo"
LAB_ROOT = DEMO_DIR / "lab-root"
FRAME_DIR = DEMO_DIR / "frames"
MODEL_CACHE = DEMO_DIR / "model-cache"
VENDOR_LABEXTENSIONS = REPO / "vendor/ipyelk/src/_d/share/jupyter/labextensions"
FFMPEG = os.environ.get("LONGERON_FFMPEG", "/opt/homebrew/bin/ffmpeg")

NOTEBOOK = "09_grand_tour.ipynb"
#: the dashboard is ~1010 px tall; 1200 px of viewport leaves it filling
#: the frame under the Lab chrome after the one scroll to its top
VIEWPORT = {"width": 1600, "height": 1200}
#: 2 supersamples the capture on high-DPI text (the video is downscaled
#: back to the viewport size; stills come out at 3200x2400 and crisp)
DEVICE_SCALE_FACTOR = 2
#: front-end CDN bundles fetched into the browser HTTP cache OFF camera
#: (the warm page), so the dashboard's 3D and Cesium panes land fast --
#: keep in sync with analysis/viewer3d.py and analysis/mission3d.py
CDN_WARM_URLS = (
    "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js",
    "https://cdn.jsdelivr.net/npm/cesium@1.144.0/Build/Cesium/Cesium.js",
    "https://cdn.jsdelivr.net/npm/cesium@1.144.0/Build/Cesium/Widgets/widgets.css",
)
#: GIF discipline: the artifact is a GitHub release asset (never
#: committed), so quality can run high -- but 10 MB is the budget the
#: README's embed stays friendly under.
GIF_BUDGET_BYTES = 10 * 1024 * 1024
#: quality ladder walked until the GIF fits the budget (the Cesium
#: finale over satellite imagery is entropy-heavy, and the slider sweeps
#: repaint half the surface -- ~70 s of dashboard lands near the bottom)
GIF_LADDER = (
    {"fps": 14, "width": 1280, "colors": 192},
    {"fps": 10, "width": 1024, "colors": 128},
    {"fps": 10, "width": 900, "colors": 112},
    {"fps": 8, "width": 800, "colors": 96},
    {"fps": 8, "width": 760, "colors": 96},
    {"fps": 8, "width": 720, "colors": 96},
    {"fps": 7, "width": 660, "colors": 96},
)

# -- camera pacing (ms) -------------------------------------------------------

BEAT_SHORT = 800
BEAT = 1200
BEAT_LONG = 1700
MOVE_STEPS = 45

# -- the demo notebook ---------------------------------------------------------

#: tutorial 9's performance graft, condensed: parsed from SysML text,
#: grafted into the loaded model, measured through the model's own calcs
_PERF_CELL = '''\
program.find("DeepScout").add(
    longeron.loads("""
package _Perf {
    requirement performance {
        attribute hoverMinutes : Real;      // measured: HoverTime(battery.capacity)
        attribute thrustToWeight : Real;    // measured: ThrustToWeight(4 rotors, MTOW)
        requirement endurance {
            attribute weight : Real = 2.0;
            attribute utility : String = "larger-is-better";
            attribute ramp0 : Real = 10.0;
            attribute ramp1 : Real = 30.0;
            attribute measure : Real = hoverMinutes;
            attribute unit : String = "min";
        }
        requirement agility {
            attribute utility : String = "larger-is-better";
            attribute ramp0 : Real = 1.0;
            attribute ramp1 : Real = 3.0;
            attribute measure : Real = thrustToWeight;
            attribute unit : String = "T/W";
            require constraint hoverMargin { thrustToWeight >= 1.8 }
        }
    }
}""").find("_Perf::performance")
)

interp = longeron.Interpreter(program)
quad = interp.instantiate("Rotorcraft::QuadCopter")
scope = program.find("DeepScout")
capacity = quad.slots["battery"].slots["capacity"]
thrust = 4.0 * quad.slots["thrustPerRotor"]
mass = quad.slots["totalMass"]
measured = {
    "hoverMinutes": interp.evaluate(
        longeron.parse_expression(f"HoverTime(capacity = {capacity})"), scope
    ),
    "thrustToWeight": interp.evaluate(
        longeron.parse_expression(f"ThrustToWeight(thrust = {thrust}, mass = {mass})"), scope
    ),
}
'''

CELLS: tuple[tuple[str, str], ...] = (
    (
        "markdown",
        "# 9 · The grand tour: one dashboard, every seam\n\n"
        "Diagram · CAD · occlusion · scoreboard · OpenMDAO · Z3 · Cesium —\n"
        "one reactive surface, every reaction kernel-side.",
    ),
    (
        "code",
        "import longeron\n"
        "from longeron.analysis.grand import grand_dashboard\n"
        "\n"
        'program = longeron.load("deepscout")  # the whole DeepScout program: one workspace',
    ),
    (
        "markdown",
        "A performance branch, grafted from SysML text and measured through\n"
        "the model's own calcs — then **one call** composes the dashboard.",
    ),
    ("code", _PERF_CELL),
    (
        "code",
        "from longeron.analysis import mission3d\n"
        "from longeron.analysis.grand import ATLANTA_LOOP\n"
        "\n"
        "# mission time is analysis: the route legs measured kernel-side,\n"
        "# priced by the model's own physics -- then one call composes it all\n"
        "measured |= mission3d.mission_values(interp, ATLANTA_LOOP, ground_alt=300.0)\n"
        "dash = grand_dashboard(program, values=measured)\n"
        "dash",
    ),
)


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
        # the kernel must import THIS tree's sources (and its vendored
        # ipyelk) even when the editable install resolves elsewhere
        PYTHONPATH=os.pathsep.join(
            path
            for path in (
                str(REPO / "src"),
                str(REPO / "vendor" / "ipyelk" / "src"),
                os.environ.get("PYTHONPATH", ""),
            )
            if path
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
                f"--LabApp.extra_labextensions_path={VENDOR_LABEXTENSIONS}",
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

# -- browser-truth probes -------------------------------------------------------

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
        text: g.textContent || '',
        transform,
        scale: zoom ? Number(zoom[1]) : 1,
        fitted: transform !== '' && transform !== 'scale(1) translate(0,0)'
            && transform !== 'translate(0, 0) scale(1)',
        overflowX: Math.max(0, view.left - content.left, content.right - view.right),
        overflowY: Math.max(0, view.top - content.top, content.bottom - view.bottom),
    };
}"""


class Camera:
    """Human-paced choreography over one playwright page."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self.frames: list[Path] = []

    def beat(self, ms: int = BEAT) -> None:
        self.page.wait_for_timeout(ms)

    def glide(self, locator: Any, steps: int = MOVE_STEPS) -> tuple[float, float]:
        """Smoothly travel to the center of ``locator``; returns the point."""

        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError(f"no bounding box for {locator}")
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        self.page.mouse.move(x, y, steps=steps)
        return x, y

    def click(self, locator: Any, *, settle_ms: int = BEAT_SHORT) -> None:
        self.glide(locator)
        self.page.wait_for_timeout(220)
        self.page.mouse.down()
        self.page.wait_for_timeout(90)
        self.page.mouse.up()
        self.beat(settle_ms)

    def dblclick(self, locator: Any, *, settle_ms: int = BEAT) -> None:
        x, y = self.glide(locator)
        self.page.wait_for_timeout(220)
        self.page.mouse.dblclick(x, y)
        self.beat(settle_ms)

    def drag_slider(
        self,
        slider: Any,
        value: float,
        *,
        minimum: float,
        maximum: float,
        segments: int = 40,
        pace_ms: int = 28,
    ) -> None:
        """Drag an ipywidgets slider handle to ``value``, paced for camera.

        The sweep is segment-by-segment (playwright's ``steps=`` runs at
        protocol speed, too fast to read as a human drag), so every
        intermediate value streams through ``continuous_update`` and the
        dashboard's kernel-side repaints show live under the drag.
        noUiSlider maps position to value linearly and snaps to the
        slider's step, which also forgives the handle-center offset.
        """

        handle = slider.locator(".noUi-handle")
        x0, y = self.glide(handle)
        self.page.wait_for_timeout(250)
        base = slider.locator(".noUi-base").bounding_box()
        if base is None:
            raise RuntimeError("slider track has no bounding box")
        x1 = base["x"] + (value - minimum) / (maximum - minimum) * base["width"]
        self.page.mouse.down()
        for i in range(1, segments + 1):
            self.page.mouse.move(x0 + (x1 - x0) * i / segments, y, steps=2)
            self.page.wait_for_timeout(pace_ms)
        self.page.wait_for_timeout(150)
        self.page.mouse.up()

    def shot(self, name: str) -> None:
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
        path = FRAME_DIR / f"{name}.png"
        self.page.screenshot(path=str(path))
        self.frames.append(path)

    # -- waits ------------------------------------------------------------

    def wait_scale(self, minimum: float, maximum: float = 1e9, *, timeout: float = 30.0) -> None:
        """Wait for the diagram's zoom to land INSIDE ``[minimum, maximum]``
        and settle (the animated ``fit`` runs client-side; the camera must
        not click mid-flight, and a zoom-out starts from a scale that may
        already satisfy a bare minimum -- hence the band)."""

        deadline = time.monotonic() + timeout
        stable: str | None = None
        streak = 0
        while time.monotonic() < deadline:
            state = dict(self.page.evaluate(_VISIBLE_DIAGRAM_JS))
            if minimum <= state.get("scale", 0) <= maximum:
                streak = streak + 1 if state.get("transform") == stable else 0
                stable = state.get("transform")
                if streak >= 2:
                    return
            else:
                streak, stable = 0, None
            time.sleep(0.25)
        raise TimeoutError(f"diagram zoom never settled inside [{minimum}, {maximum}]")

    def wait_diagram(self, marker: str | None, *, timeout: float = 150.0) -> str:
        """Wait for the dashboard diagram: fitted (and showing ``marker``).

        Framing is part of the contract: the content must sit INSIDE the
        pane (the autofit lands a beat after the relayout -- the camera
        must not fire early).  ``marker`` must be ``None`` for overview
        framings: sprotty CULLS label text below ~5% zoom, and the full
        DeepScout program autofits near 4%, so at overview the diagram
        renders boxes only -- the act-2 dive re-checks its own labels.
        """

        deadline = time.monotonic() + timeout
        stable: str | None = None
        streak = 0
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = dict(self.page.evaluate(_VISIBLE_DIAGRAM_JS))
            text = state.get("text", "")
            good = (
                state.get("rendered")
                and state.get("fitted")
                and (marker is None or marker in text)
                # scale(0.01) is the hidden-viewport autofit sentinel: tiny
                # content has no overflow, so require a real autofit zoom
                # (the full DeepScout program lands near 0.04)
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
        state.pop("text", None)
        raise TimeoutError(f"dashboard diagram never settled on {marker!r}; last state: {state}")


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


def kernel_exec(page: Any, code: str, timeout_ms: int = 30_000) -> str:
    """Silently execute ``code`` on the notebook's kernel (no cell, no
    camera footprint) -- the invisible-cleanup seam for gestures whose
    mouse form would misread on camera.  Returns the reply status
    (``ok`` / ``error``), so an ``assert`` makes a kernel-truth probe."""

    return str(
        page.evaluate(
            """async ([code, timeout]) => {
            const app = window.jupyterapp || window.jupyterlab;
            const kernel = app.shell.currentWidget.sessionContext.session.kernel;
            const future = kernel.requestExecute(
                { code, silent: true, store_history: false });
            const reply = await Promise.race([future.done, new Promise((_, reject) =>
                setTimeout(() => reject(new Error('kernel_exec timeout')), timeout))]);
            return reply.content.status;
        }""",
            [code, timeout_ms],
        )
    )


def kernel_assert(page: Any, expression: str, timeout: float = 20.0) -> None:
    """Poll ``expression`` on the kernel until it holds (kernel truth for
    state a comm write lands asynchronously, e.g. a diagram click's
    selection reaching ``bind_config_view``)."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if kernel_exec(page, f"assert {expression}") == "ok":
            return
        time.sleep(0.5)
    raise TimeoutError(f"kernel never satisfied: {expression}")


# -- the scenario ----------------------------------------------------------------


def perform(page: Any, server: LabServer) -> tuple[float, Camera]:
    """The scripted walkthrough; returns (scene-start offset s, camera)."""

    cam = Camera(page)
    t_page = time.monotonic()

    open_demo_notebook(page, server)
    # a tidy stage: hide the file-browser sidebar, then let layout settle
    page.evaluate(
        "() => { void (window.jupyterapp || window.jupyterlab)"
        ".commands.execute('application:toggle-left-area'); return true; }"
    )
    page.wait_for_timeout(1500)
    page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2, steps=10)
    page.wait_for_timeout(500)

    scene_start = time.monotonic() - t_page  # trim the boot right here

    def mark(label: str) -> None:
        """Log a beat timestamp relative to the trimmed video's t=0."""

        print(f"  beat {time.monotonic() - t_page - scene_start:5.1f}s  {label}", flush=True)

    cam.beat(BEAT_SHORT)

    # -- act 1: Run All Cells, scroll ONCE to the dashboard ----------------
    mark("act 1: Run All Cells")
    cam.click(page.locator('.lm-MenuBar-itemLabel:text-is("Run")'), settle_ms=400)
    cam.click(page.locator('.lm-Menu-itemLabel:text-is("Run All Cells")'), settle_ms=300)
    # the dashboard output exists as soon as the last cell displays it;
    # scroll to it while the panes are still landing (that IS the shot)
    page.wait_for_selector(".lgn-sb-cell", state="attached", timeout=240_000)
    page.evaluate(
        "() => document.querySelector('.jp-Notebook .jp-CodeCell:last-child .jp-OutputArea')"
        ".scrollIntoView({block: 'start', behavior: 'smooth'})"
    )
    # park the cursor in the left gutter while the composition lands
    page.mouse.move(VIEWPORT["width"] * 0.05, VIEWPORT["height"] * 0.58, steps=25)
    page.wait_for_selector(".longeron-mission3d .cesium-viewer", timeout=240_000)
    cam.wait_diagram(None)  # overview: boxes only, labels culled at ~4% zoom
    wait_kernel_idle(page)
    mark("act 1: dashboard landed")
    cam.beat(BEAT_LONG)
    cam.shot("01-dashboard-landed")

    # -- act 2: the diagram is the selection hub -- click a part ----------
    # the full DeepScout program autofits near scale 0.04 (a smudge), so
    # the camera FRAMES what it touches first: an animated kernel-side
    # fit to the QuadCopter node (the toolbar fit button's own move)
    mark("act 2: frame the quad, click motors -> 3D flash")
    diagram_pane = page.locator('.jp-OutputArea div.sprotty[id^="sprotty"]')
    cam.glide(diagram_pane.first)
    kernel_exec(
        page,
        'dash.diagram.view.fit(model_ids=["Rotorcraft::QuadCopter"], animate=True, padding=24)',
    )
    cam.wait_scale(0.9, 2.0)  # the dive lands: the node fills the pane, readable
    cam.beat(BEAT_SHORT)
    motors = diagram_pane.locator('text.elklabel:text-is("motors : Motor [4]")')
    cam.click(motors.first, settle_ms=BEAT_SHORT)
    cam.beat(BEAT)  # all four motors pop in 3D, the rest of the craft dims
    cam.shot("02-diagram-3d-link")
    cam.beat(BEAT_SHORT)
    # release the selection invisibly (a background click would read as a
    # misfire on camera; the next beat repaints the highlight anyway)
    kernel_exec(page, "dash.diagram.view.selection.ids = []")

    # -- act 3: the config click -- the 3D pane BECOMES the clicked craft -
    # 0.11's headliner: bind_config_view is on by default, so a click
    # anywhere inside ANOTHER craft resolves to that craft and swaps the
    # viewer to it.  The frame pulls back one step to the multirotor
    # family first (the hexa sits one node above the quad; the teardrop
    # shell lives ~4k px away across the fleet branch -- a second cut's
    # beat, not this one).  The click target is the hexa's motors row:
    # mid-pane, well clear of the hover-revealed toolbar strip that sits
    # over the node titles at the pane's top edge.
    mark("act 3: config click (HexaCopter)")
    kernel_exec(
        page,
        "dash.diagram.view.fit(model_ids="
        '["Rotorcraft::QuadCopter", "Rotorcraft::HexaCopter"], animate=True, padding=24)',
    )
    cam.wait_scale(0.35, 0.8)  # both craft in frame (pulled back from ~1.15)
    cam.beat(BEAT_SHORT)
    cam.click(diagram_pane.locator('text.elklabel:text-is("motors : Motor [6]")').first)
    kernel_assert(page, 'dash.config_view.current == "Rotorcraft::HexaCopter"')
    cam.beat(BEAT_LONG)  # six rotors: the hexa bakes from its own M0 population
    cam.shot("03-config-swap-hexa")
    cam.beat(BEAT_SHORT)
    # ...and home again: the quad returns WITH its view cone, one write
    cam.click(diagram_pane.locator('text.elklabel:text-is("QuadCopter")').first)
    kernel_assert(page, 'dash.config_view.current == "Rotorcraft::QuadCopter"')
    mark("act 3: home again")
    cam.beat(BEAT)
    kernel_exec(page, "dash.diagram.view.selection.ids = []")

    # -- act 4: the money shot -- swing the view cone into the airframe ---
    mark("act 4: azimuth sweep (occlusion)")
    azimuth = page.locator('.widget-hslider:has(.widget-label:text-is("azimuth"))')
    cam.drag_slider(azimuth, 180.0, minimum=-180.0, maximum=180.0)
    # browser truth: the readout card lists the obstructing parts red
    page.wait_for_selector('text="view cone clear of the airframe"', state="hidden", timeout=20_000)
    cam.beat(BEAT_LONG)  # occludedFraction red, clearView red, parts lit
    cam.shot("04-occlusion-red")
    cam.beat(BEAT_SHORT)
    cam.drag_slider(azimuth, 0.0, minimum=-180.0, maximum=180.0)
    page.wait_for_selector('text="view cone clear of the airframe"', timeout=20_000)
    mark("act 4: recovered")
    cam.beat(BEAT)  # ...and the score recovers: live, both directions

    # -- act 5: the OpenMDAO sizing strip -- maximize station time -------
    mark("act 5: loiter drag (OpenMDAO)")
    # NOT the driver button: the strip card's fixed height clips it out of
    # view in the browser (QA note for the dashboard).  The slider is the
    # same seam -- every step re-runs the generated Problem kernel-side,
    # and dragging to the stall floor IS maximizing station time.
    loiter = page.locator('.widget-hslider:has(.widget-label:text-is("loiter m/s"))')
    cam.drag_slider(loiter, 11.0, minimum=11.0, maximum=24.0, segments=30)
    loiter.locator('.widget-readout:text-is("11.0")').wait_for(timeout=30_000)
    cam.beat(BEAT_LONG)  # stationMinutes climbed to the stall-floor optimum

    # -- act 6: the Z3 verdicts (static cards -- a cursor pass) ------------
    mark("act 6: Z3 verdict pass")
    cam.glide(page.locator('span:text-is("SAT")').first)
    cam.beat(BEAT_SHORT)
    cam.glide(page.locator("div", has_text="aboveStall").last, steps=30)
    cam.beat(BEAT)

    # -- act 7: the scoreboard zooms -- double-click, Esc back -------------
    mark("act 7: scoreboard zoom")
    endurance = page.locator('.lgn-sb-cell[data-qname$="::endurance"]')
    cam.dblclick(endurance, settle_ms=BEAT_SHORT)
    # the dblclick word-selects whatever text sits under the pointer --
    # drop the selection, it reads as a glitch
    page.evaluate("() => window.getSelection().removeAllRanges()")
    page.wait_for_selector(".lgn-sb-crumbs", state="visible", timeout=20_000)
    cam.beat(BEAT_LONG)  # the performance branch fills the canvas
    page.keyboard.press("Escape")  # one level back out
    page.wait_for_selector(".lgn-sb-crumbs", state="hidden", timeout=20_000)
    kernel_exec(page, "dash.board.selected = []")  # drop the click-selection ring
    cam.beat(BEAT)

    # -- act 8: the Cesium finale -- fly the mission ----------------------
    mark("act 8: Cesium play")
    play = page.locator(".cesium-animation-rectButton", has_text="Play Forward")
    cam.click(play.first, settle_ms=400)
    cam.beat(3500)  # the drone banks over Piedmont Park...
    cam.shot("05-mission-finale")
    cam.beat(3500)  # ...and we cut mid-flight
    mark("cut")
    return scene_start, cam


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
        filters = (
            f"fps={rung['fps']},scale={rung['width']}:-1:flags=lanczos,"
            f"split[s0][s1];[s0]palettegen=max_colors={rung['colors']}[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=5"
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
            browser = playwright.chromium.launch(args=["--disable-dev-shm-usage"])
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
