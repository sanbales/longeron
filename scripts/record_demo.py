#!/usr/bin/env python
"""Record the README demo: a scripted JupyterLab walkthrough -> mp4 + GIF.

    python scripts/record_demo.py

re-records the whole thing after UI changes.  The walkthrough is
DETERMINISTIC by construction: a purpose-built demo notebook is generated
into a throwaway lab root (the repo's notebooks are never touched), the
models it loads ship with this checkout (``examples/drone.sysml`` plus the
ScoutUAV requirements hierarchy inlined below), the scoreboard's Voronoi
seed is fixed, ``PYTHONHASHSEED=0`` pins kernel hashing, and every camera
beat is a fixed pause -- so two recordings differ only in sub-second
layout-arrival jitter.  The story is ONE LINEAR pass (~35 s), every beat
motivated: open the notebook -> ``explore()`` docks the explorer -> click
QuadCopter in the tree (diagram highlight + breadcrumb) -> one kind-switch
to the state-machine view -> run the scoreboard cell -> hover one Voronoi
cell (units tooltip) -> double-click zoom -> hold -> end.  No tab-hopping,
no switch-backs.  Outputs land in ``build/demo/`` (gitignored):

* ``demo.webm``   -- the raw playwright capture (1600x900)
* ``demo.mp4``    -- h264, crf 20, faststart (the shareable video)
* ``demo.gif``    -- palette-optimized, <= 10 MB (the GitHub-attachment
  ceiling; see the publish workflow below)
* ``frames/*.png``-- three representative stills for quick review

PUBLISH WORKFLOW -- media is NEVER committed to this repo.  A maintainer
drags ``demo.mp4`` and/or ``demo.gif`` into a GitHub issue comment (the
usual assets-issue pattern); GitHub rehosts the file at a stable
``github.com/user-attachments/...`` URL, and the README then embeds that
hosted URL.  Re-recording therefore never touches git history: re-run this
script, re-drag the file, update the URL.

The recording rig mirrors ``scripts/capture_widget_snapshots.py`` and
``tests/browser/conftest.py``: one real JupyterLab server (temp root,
temp user settings with ``autoStartDefaultKernel`` on, autosave OFF,
``windowingMode: none``), driven by headless Chromium.  Unlike those, this
script performs for a HUMAN camera: a fake cursor overlay follows the
mouse (playwright records no OS cursor), travel is smoothed with
``mouse.move(steps=...)``, and every action gets a beat to breathe.
Record on a quiet machine -- concurrent browser suites steal the frames'
smoothness.
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
VENDOR_LABEXTENSIONS = REPO / "vendor/ipyelk/src/_d/share/jupyter/labextensions"
FFMPEG = os.environ.get("LONGERON_FFMPEG", "/opt/homebrew/bin/ffmpeg")

NOTEBOOK = "longeron_demo.ipynb"
VIEWPORT = {"width": 1600, "height": 900}
#: 2 supersamples the capture on high-DPI text (the video is downscaled
#: back to the viewport size; stills come out at 3200x1800 and crisp)
DEVICE_SCALE_FACTOR = 2
#: GIF discipline: the artifact is hosted via a GitHub-issue upload (never
#: committed), so quality can run high -- but GitHub caps attachments at
#: 10 MB, and that ceiling is the budget.
GIF_BUDGET_BYTES = 10 * 1024 * 1024
#: quality ladder walked until the GIF fits the budget
GIF_LADDER = (
    {"fps": 15, "width": 1400, "colors": 256},
    {"fps": 14, "width": 1280, "colors": 192},
    {"fps": 12, "width": 1200, "colors": 160},
    {"fps": 10, "width": 1024, "colors": 128},
)

# -- camera pacing (ms) -------------------------------------------------------

BEAT_SHORT = 800
BEAT = 1200
BEAT_LONG = 1700
MOVE_STEPS = 45

# -- the demo notebook ---------------------------------------------------------

#: the ScoutUAV requirements hierarchy from tutorial 13 (catalog omitted:
#: the scoreboard act only needs the measured requirement tree)
SCOUT_SRC = """\
package ScoutUAV {
    // the current design point: what the requirements score by default
    attribute hoverTime : Real = 12.0 [SI::min];   // full-hover endurance
    attribute cruiseTime : Real = 20.0 [SI::min];  // full-cruise endurance
    attribute radius_km : Real = 8.5 [SI::km];
    attribute totalMass : Real = 1.62 [SI::kg];
    attribute unitCost : Real = 950.0;             // USD -- no SI unit
    attribute noise_dB : Real = 68.0 [SI::dB];     // at 50 m

    requirement mission {
        requirement performance {
            attribute weight : Real = 3.0;
            requirement endurance {
                attribute weight : Real = 3.0;
                requirement hoverEndurance {
                    attribute utility : String = "larger-is-better";
                    attribute ramp0 : Real = 5.0;
                    attribute ramp1 : Real = 20.0;
                    attribute measure : Real = hoverTime;
                    attribute unit : String = "min";
                }
                requirement cruiseEndurance {
                    attribute weight : Real = 2.0;
                    attribute utility : String = "larger-is-better";
                    attribute ramp0 : Real = 10.0;
                    attribute ramp1 : Real = 30.0;
                    attribute measure : Real = cruiseTime;
                    attribute unit : String = "min";
                }
            }
            requirement radius {
                attribute weight : Real = 2.0;
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 3.0;
                attribute ramp1 : Real = 12.0;
                attribute measure : Real = radius_km;
                attribute unit : String = "km";
            }
        }
        requirement affordability {
            attribute weight : Real = 2.0;
            requirement cost {
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 1500.0;
                attribute ramp1 : Real = 500.0;
                attribute measure : Real = unitCost;
                attribute unit : String = "USD";
            }
        }
        requirement operability {
            attribute weight : Real = 2.0;
            requirement mass {
                attribute weight : Real = 2.0;
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 2.5;
                attribute ramp1 : Real = 1.0;
                attribute measure : Real = totalMass;
                attribute unit : String = "kg";
            }
            requirement regulatory {
                require constraint { totalMass <= 25.0 }
            }
            requirement quiet {
                attribute utility : String = "target-is-best";
                attribute target : Real = 60.0;
                attribute limit : Real = 15.0;
                attribute measure : Real = noise_dB;
                attribute unit : String = "dB";
            }
            requirement futureProofing;  // deliberately unmeasured
        }
    }
}
"""

CELLS: tuple[tuple[str, str], ...] = (
    (
        "markdown",
        "# Longeron: SysML v2 in Python\n\n"
        "Define, execute, and **explore** SysML v2 models — live in JupyterLab.",
    ),
    (
        "code",
        "import longeron\n"
        "from longeron.explorer import explore\n"
        "\n"
        'model = longeron.load("drone.sysml")  # a small quad-copter model\n'
        "explore(model)  # docks a tree + diagram explorer as its own Lab tab",
    ),
    (
        "markdown",
        "## Score requirements with MAUT\n\n"
        "`scoreboard` maps measured values onto utilities and aggregates them\n"
        "up the requirement hierarchy — **area = importance, color = utility**.",
    ),
    (
        "code",
        "from longeron.analysis.scoreboard import scoreboard\n"
        "\n"
        'scout = longeron.load("scout_uav.sysml")  # a UAV requirements hierarchy\n'
        'scoreboard(scout).widget(tessellation="voronoi", height_px=430)',
    ),
)


def build_lab_root() -> None:
    """A throwaway lab root: the demo notebook plus the models it loads."""

    if LAB_ROOT.exists():
        shutil.rmtree(LAB_ROOT)
    LAB_ROOT.mkdir(parents=True)
    shutil.copy(REPO / "examples" / "drone.sysml", LAB_ROOT / "drone.sysml")
    (LAB_ROOT / "scout_uav.sysml").write_text(SCOUT_SRC, encoding="utf-8")
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
        os.environ,
        PYTHONHASHSEED="0",
        # kernels inherit this: a contended machine can hold up the elkjs
        # layout roundtrip for minutes, and a tripped timeout is a FINAL
        # visible failure -- same choice as tests/browser/conftest.py
        LONGERON_BROWSER_TIMEOUT="600",
        JUPYTERLAB_SETTINGS_DIR=str(settings),
        JUPYTERLAB_WORKSPACES_DIR=str(settings / "workspaces"),
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

#: the VISIBLE explorer diagram's framing (from tests/browser/test_browser_explorer.py)
_VISIBLE_DIAGRAM_JS = r"""() => {
    const shown = [...document.querySelectorAll(
        '.lgx-diagram-box div.sprotty[id^="sprotty"]',
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

    def shot(self, name: str) -> None:
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
        path = FRAME_DIR / f"{name}.png"
        self.page.screenshot(path=str(path))
        self.frames.append(path)

    # -- waits ------------------------------------------------------------

    def wait_diagram(
        self,
        marker: str,
        *,
        absent: str = "",
        timeout: float = 150.0,
    ) -> str:
        """Wait for the visible explorer diagram: fitted and showing ``marker``.

        ``absent`` distinguishes look-alike kinds (the structure view also
        prints state names inside the FlightStates compound, so the state
        view is recognized by what it LACKS).  Framing is part of the
        contract: the content must sit INSIDE the pane (the kind-switch
        re-fit is a kernel roundtrip that lands a beat after the relayout
        -- the camera must not fire early).
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
                and marker in text
                and (not absent or absent not in text)
                # scale(0.01) is the hidden-viewport autofit sentinel: tiny
                # content has no overflow, so require a human-visible zoom
                and state.get("scale", 0) > 0.05
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
        raise TimeoutError(f"explorer diagram never settled on {marker!r}; last state: {state}")


def wait_kernel_idle(page: Any, timeout: float = 120.0) -> None:
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
    cam.beat(BEAT_SHORT)

    # -- act 1: load the drone model, dock the explorer -------------------
    code_cells = page.locator(".jp-Notebook .jp-CodeCell")
    cam.click(code_cells.nth(0).locator(".jp-InputArea-editor"), settle_ms=500)
    page.keyboard.press("Shift+Enter")
    dock_tab = page.locator("#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey]")
    dock_tab.wait_for(state="attached", timeout=180_000)
    cam.beat(BEAT)

    # -- act 2: the model explorer ----------------------------------------
    cam.click(dock_tab.first, settle_ms=400)
    page.wait_for_selector(".lgx-explorer .lgx-row", state="visible", timeout=60_000)
    cam.wait_diagram("QuadCopter")  # first reveal fits the structure view
    cam.beat(BEAT_SHORT)

    # the dock split starts ~50/50: drag the handle left like a person
    # would, giving the diagram the stage (the tree needs ~430px)
    handle = page.locator(".lgx-explorer .lm-SplitPanel-handle").first
    if handle.count():
        box = handle.bounding_box()
        if box is not None:
            y = box["y"] + box["height"] / 2
            page.mouse.move(box["x"] + box["width"] / 2, y, steps=30)
            page.wait_for_timeout(200)
            page.mouse.down()
            page.mouse.move(430, y, steps=35)
            page.mouse.up()
            cam.beat(BEAT_SHORT)
            cam.wait_diagram("QuadCopter")  # the pane re-fits to its new width
    cam.beat(BEAT_SHORT)

    row = page.locator(".lgx-explorer .lgx-row", has_text="QuadCopter")
    cam.click(row.first)
    page.wait_for_selector("text=Drone::QuadCopter", timeout=60_000)
    cam.beat(BEAT)
    cam.shot("01-explorer-structure")

    # the ONE kind switch: FlightStates offers the state-machine view
    row = page.locator(".lgx-explorer .lgx-row", has_text="FlightStates")
    cam.click(row.first)
    switcher = page.locator(".lgx-explorer .widget-toggle-buttons").first
    state_button = switcher.locator("button", has_text="state")
    state_button.wait_for(state="visible", timeout=30_000)
    cam.click(state_button)
    # the state view is recognized by what it lacks: no QuadCopter node
    cam.wait_diagram("takingOff", absent="QuadCopter")
    cam.beat(BEAT_LONG)
    cam.shot("02-state-machine")
    cam.beat(BEAT_SHORT)

    # -- act 3: the requirements scoreboard --------------------------------
    notebook_tab = page.locator("#jp-main-dock-panel .lm-TabBar-tab", has_text=NOTEBOOK)
    cam.click(notebook_tab.first, settle_ms=600)
    cam.click(code_cells.nth(1).locator(".jp-InputArea-editor"), settle_ms=400)
    page.keyboard.press("Control+Enter")  # run in place (no cell added below)
    page.wait_for_selector(".lgn-sb-cell", state="attached", timeout=120_000)
    # center the board: scroll_into_view stops at 'barely visible', which
    # leaves the bottom row of cells kissing the status bar
    page.evaluate(
        "() => document.querySelector('.lgn-sb-wrap')"
        ".scrollIntoView({block: 'center', behavior: 'smooth'})"
    )
    cam.beat(BEAT)

    # hover ONE leaf: the tooltip narrates raw measure -> utility, units on
    cam.glide(page.locator('.lgn-sb-cell[data-qname$="hoverEndurance"]'), steps=60)
    cam.beat(BEAT_LONG)

    # double-click zooms to the endurance group -- the closing image
    cam.dblclick(page.locator('.lgn-sb-cell[data-qname$="hoverEndurance"]'), settle_ms=BEAT_SHORT)
    # the dblclick word-selects whatever text sits under the pointer
    # (tooltip included) -- drop the selection, it reads as a glitch
    page.evaluate("() => window.getSelection().removeAllRanges()")
    cam.glide(page.locator('.lgn-sb-cell[data-qname$="cruiseEndurance"]'), steps=40)
    cam.beat(BEAT_LONG)
    cam.shot("03-scoreboard-zoom")

    # -- outro: hold the zoomed view, then cut ------------------------------
    cam.beat(BEAT_LONG)
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
            # warm take: pays the extension/asset cold start OFF camera
            warm = context.new_page()
            warm.goto(f"{server.base_url}/lab?token={server.token}", wait_until="domcontentloaded")
            warm.wait_for_selector("#jp-main-dock-panel", state="attached", timeout=120_000)
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
