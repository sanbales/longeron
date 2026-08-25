#!/usr/bin/env python
"""Capture PNG snapshots of the tutorial notebooks' widget outputs.

The docs site cannot run live widgets (ipyelk diagrams, anywidget
viewers), so the tutorial pages embed *static PNG snapshots* instead
(see ``docs/_ext/widget_snapshots.py``).  This script regenerates them:

    pixi run capture-widgets              # all of tutorials 01..11 + 13
    pixi run capture-widgets 06 11        # just those two (manifest merge)

It boots one real JupyterLab server (root: ``notebooks/``, so relative
data paths resolve against THIS checkout) and drives it with headless
Chromium, mirroring the battle-tested browser test tier
(``tests/browser/conftest.py``) -- the server/settle/dialog techniques
here are deliberately kept in lockstep with that file, duplicated rather
than imported so the pytest tier stays self-contained.  For each
notebook it runs all cells, waits for the widgets to settle (nothing
busy, no visible progress bars, DOM state stable), then screenshots the
top-level DOM element of every rendered widget output into
``docs/_static/widget-snapshots/<stem>/cell-<code-cell-index>.png`` and
rewrites ``manifest.json`` mapping each snapshot back to its notebook
cell.  Notebooks with no widget outputs contribute nothing.  Tutorial 12
(the model explorer docks into the Lab shell itself, there is no
meaningful in-cell snapshot) is excluded.

The PNGs and manifest are COMMITTED artifacts: docs builds stay
deterministic and Chromium-free, and this script is re-run manually when
a widget-bearing tutorial cell changes.  Determinism knobs: fixed
viewport, ``PYTHONHASHSEED=0`` for the kernel, no timestamps in the
manifest.  The notebooks themselves are never saved -- the repo copies
stay output-free.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
NOTEBOOK_DIR = REPO / "notebooks"
SNAPSHOT_DIR = REPO / "docs" / "_static" / "widget-snapshots"
MANIFEST_PATH = SNAPSHOT_DIR / "manifest.json"
#: durable scratch (server log, Lab user settings) -- inspectable after a run
SCRATCH = REPO / "build" / "widget-capture"
#: the vendored jupyter-elk labextension build; passed as an EXTRA
#: labextensions path so the served bundle is always THIS checkout's build,
#: even when the interpreter's own env carries a stale copy (extra paths
#: take precedence: jupyterlab_server keeps the first occurrence of a name)
VENDOR_LABEXTENSIONS = REPO / "vendor/ipyelk/src/_d/share/jupyter/labextensions"

WIDGET_VIEW_MIMETYPE = "application/vnd.jupyter.widget-view+json"
VIEWPORT = {"width": 1500, "height": 1100}  # matches tests/browser/conftest.py
DEVICE_SCALE_FACTOR = 2  # crisp diagram text on high-DPI displays
#: tutorials 01..11 and 13; 12 is excluded by design (see module docstring)
TUTORIAL_NUMBERS = tuple(f"{n:02d}" for n in (*range(1, 12), 13))

# -- DOM snapshots (adapted from tests/browser/conftest.py) ------------------

#: busy prompts, visible progress bars, and layout state for settle-polling
_SNAPSHOT_JS = """() => {
    const busy = [...document.querySelectorAll('.jp-InputArea-prompt')].filter(
        (el) => el.textContent.includes('*')).length;
    const bars = [...document.querySelectorAll(
        '.jp-OutputArea .widget-hprogress, .jp-OutputArea .widget-vprogress'
    )].filter(
        (bar) => getComputedStyle(bar).visibility === 'visible'
    ).map((bar) => {
        const inner = bar.querySelector('.progress-bar');
        return inner ? inner.style.width || inner.style.height || '' : '';
    });
    const elknodes = document.querySelectorAll('.sprotty svg .elknode').length;
    const fitted = [...document.querySelectorAll('.sprotty svg > g')].filter((g) => {
        const t = g.getAttribute('transform') || '';
        return t && t !== 'scale(1) translate(0,0)' && t !== 'translate(0, 0) scale(1)';
    }).length;
    const widgets = document.querySelectorAll(
        '.jp-Cell-outputWrapper .jupyter-widgets').length;
    return {busy, bars, elknodes, fitted, widgets};
}"""

#: kernel-side truth: per-code-cell execution counts (run-all completion)
_PROGRESS_JS = """() => {
    const app = window.jupyterapp || window.jupyterlab;
    const panel = app && app.shell ? app.shell.currentWidget : null;
    if (!panel || !panel.content || !panel.content.model) return null;
    const nb = panel.content.model.toJSON();
    let code = 0, executed = 0;
    for (const cell of nb.cells) {
        if (cell.cell_type !== 'code') continue;
        code += 1;
        const src = Array.isArray(cell.source) ? cell.source.join('') : cell.source;
        if (!src.trim() || cell.execution_count !== null) executed += 1;
    }
    return {code, executed};
}"""

#: the full notebook model (with outputs) -- NOT saved to disk, read from
#: the browser-side document model so the repo notebooks stay output-free
_MODEL_JS = """() => {
    const app = window.jupyterapp || window.jupyterlab;
    return app.shell.currentWidget.content.model.toJSON();
}"""

#: tag the rendered view of each expected widget output with
#: data-lgn-snap="<cellIndex>-<k>".  ``expected`` maps nb-cell-index ->
#: [output indices]: JupyterLab renders exactly one .jp-OutputArea-child
#: per output model item, so DOM children align with model output indices
#: (ipywidgets views carry .jupyter-widgets; anywidget views only their own
#: class, so fall back to the renderer's first element child).  Returns the
#: DOM cell count plus any alignment problems for the caller to report.
_TAG_WIDGETS_JS = """(expected) => {
    const WIDGET_MIME = 'application/vnd.jupyter.widget-view+json';
    const cells = [...document.querySelectorAll('.jp-Notebook .jp-Cell')];
    const problems = [];
    for (const [cellIndex, outputIndices] of Object.entries(expected)) {
        const cell = cells[Number(cellIndex)];
        if (!cell) {
            problems.push(`cell ${cellIndex} not in the DOM`);
            continue;
        }
        const children = cell.querySelectorAll(
            ':scope > .jp-Cell-outputWrapper > .jp-OutputArea > .jp-OutputArea-child');
        outputIndices.forEach((outputIndex, k) => {
            const child = children[outputIndex];
            const out = child ? child.querySelector('.jp-OutputArea-output') : null;
            if (!out) {
                problems.push(`cell ${cellIndex} output ${outputIndex} not in the DOM`);
                return;
            }
            const mime = out.dataset.mimeType || '';
            if (mime && mime !== WIDGET_MIME) {
                problems.push(
                    `cell ${cellIndex} output ${outputIndex} rendered as ${mime},` +
                    ' not as a widget');
                return;
            }
            const target = out.querySelector('.jupyter-widgets') || out.firstElementChild || out;
            target.setAttribute('data-lgn-snap', `${cellIndex}-${k}`);
        });
    }
    return {cells: cells.length, problems};
}"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class LabServer:
    """A booted JupyterLab: address, token, process handle."""

    base_url: str
    token: str
    process: subprocess.Popen[bytes]
    log_path: Path

    def url_for(self, notebook: str, workspace: str) -> str:
        # a private workspace per open + &reset: no restored layout ever
        # steals the tab (same rationale as tests/browser/conftest.py)
        return (
            f"{self.base_url}/lab/workspaces/{workspace}/tree/{notebook}?token={self.token}&reset"
        )

    def api(self, path: str, method: str = "GET") -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/{path}",
            method=method,
            headers={"Authorization": f"token {self.token}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
        return json.loads(body) if body else None

    def shutdown_sessions(self, notebook: str) -> None:
        """Free the notebook's kernel (the heavy tutorials add up)."""

        try:
            for session in self.api("sessions"):
                if session.get("path") == notebook:
                    self.api(f"sessions/{session['id']}", method="DELETE")
        except (urllib.error.URLError, OSError) as err:
            print(f"  WARNING: session cleanup for {notebook} failed: {err}")


def start_lab_server() -> LabServer:
    """Boot JupyterLab on ``notebooks/`` (mirrors tests/browser/conftest.py)."""

    SCRATCH.mkdir(parents=True, exist_ok=True)
    # autoStartDefaultKernel: without it a pristine home pops the modal
    # "Select Kernel" dialog on every open (the browser tier's CI blocker)
    settings = SCRATCH / "lab-user-settings"
    tracker = settings / "@jupyterlab" / "notebook-extension"
    tracker.mkdir(parents=True, exist_ok=True)
    (tracker / "tracker.jupyterlab-settings").write_text(
        json.dumps({"autoStartDefaultKernel": True}), encoding="utf-8"
    )
    # no news toast / update banner: they overlay the page bottom-right and
    # photobomb any widget snapshot whose bounding box reaches that corner
    apputils = settings / "@jupyterlab" / "apputils-extension"
    apputils.mkdir(parents=True, exist_ok=True)
    (apputils / "notification.jupyterlab-settings").write_text(
        json.dumps({"fetchNews": "false", "checkForUpdates": False, "doNotDisturbMode": True}),
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        PYTHONHASHSEED="0",  # deterministic kernel hashing, like the `lab` task
        JUPYTERLAB_SETTINGS_DIR=str(settings),
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
    log_path = SCRATCH / "lab-server.log"
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
                f"--ServerApp.root_dir={NOTEBOOK_DIR}",
                "--ServerApp.disable_check_xsrf=True",
            ],
            cwd=NOTEBOOK_DIR,
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


# -- driving one notebook -----------------------------------------------------


def open_notebook(page: Any, server: LabServer, name: str, index: int, timeout: float) -> None:
    workspace = f"{re.sub(r'[^a-z0-9]+', '-', name.lower())}-{index}"
    page.goto(server.url_for(name, workspace), wait_until="domcontentloaded")
    page.wait_for_selector(".jp-Notebook", state="attached", timeout=timeout * 1000)
    # dismiss any modal dialog (reject, never accept -- same rationale as
    # tests/browser/conftest.py: 'Build Recommended' etc. must not run)
    page.add_locator_handler(
        page.locator(".jp-Dialog .jp-mod-reject"), lambda button: button.click()
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate("() => !!(window.jupyterapp || window.jupyterlab)"):
            return
        time.sleep(1)
    raise TimeoutError(f"JupyterLab app handle never appeared for {name}")


def run_all(page: Any, attempts: int = 5) -> None:
    """Fire-and-forget run-all (bounded settle-polling owns the waiting)."""

    for _attempt in range(attempts):
        page.evaluate(
            "() => { void (window.jupyterapp || window.jupyterlab)"
            ".commands.execute('notebook:run-all-cells'); return true; }"
        )
        time.sleep(4)
        started = page.evaluate(
            "() => [...document.querySelectorAll('.jp-InputArea-prompt')]"
            ".some((el) => el.textContent.includes('[*]') || /\\[\\d+\\]/.test(el.textContent))"
        )
        if started:
            return
    raise TimeoutError(f"run-all never started after {attempts} attempts")


def wait_settled(page: Any, *, timeout: float, poll_s: float = 2.0, stable_polls: int = 3) -> None:
    """Settled: every code cell executed, nothing busy, DOM state stable.

    Unlike the test tier there is no per-notebook expected widget count, so
    stability (identical snapshot ``stable_polls`` times in a row, progress
    bars included) stands in for the explicit thresholds.
    """

    deadline = time.monotonic() + timeout
    streak = 0
    previous: dict[str, Any] | None = None
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = dict(page.evaluate(_SNAPSHOT_JS))
        progress = page.evaluate(_PROGRESS_JS)
        done = (
            progress is not None and progress["executed"] >= progress["code"] and state["busy"] == 0
        )
        streak = streak + 1 if (done and state == previous) else 0
        previous = state
        if streak >= stable_polls:
            return
        time.sleep(poll_s)
    raise TimeoutError(f"notebook never settled within {timeout}s; last state: {state}")


def widget_outputs_by_cell(model: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """nb-cell-index -> manifest entries (sans image path) for widget outputs."""

    outputs_by_cell: dict[int, list[dict[str, Any]]] = {}
    code_cell_index = -1
    for nb_cell_index, cell in enumerate(model["cells"]):
        if cell["cell_type"] != "code":
            continue
        code_cell_index += 1
        for output_index, output in enumerate(cell.get("outputs", [])):
            data = output.get("data", {})
            if WIDGET_VIEW_MIMETYPE not in data:
                continue
            text = data.get("text/plain", "")
            if isinstance(text, list):
                text = "".join(text)
            # just the repr's (possibly dotted) class name: full reprs embed
            # run-varying ids and memory addresses
            match = re.match(r"<?([A-Za-z_][\w.]*)", text.strip())
            outputs_by_cell.setdefault(nb_cell_index, []).append(
                {
                    "nb_cell_index": nb_cell_index,
                    "code_cell_index": code_cell_index,
                    "output_index": output_index,
                    "alt": match.group(1).rstrip(".") if match else "widget",
                }
            )
    return outputs_by_cell


def capture_notebook(
    page: Any, server: LabServer, name: str, index: int, timeout: float
) -> list[dict[str, Any]]:
    """Run one notebook and screenshot its widget outputs; return manifest rows."""

    stem = Path(name).stem
    open_notebook(page, server, name, index, timeout=120)
    run_all(page)
    wait_settled(page, timeout=timeout)
    time.sleep(3)  # grace: late auto-fit animation frames
    model = page.evaluate(_MODEL_JS)
    expected = widget_outputs_by_cell(model)
    tag_result = page.evaluate(
        _TAG_WIDGETS_JS,
        {
            str(cell_index): [entry["output_index"] for entry in entries]
            for cell_index, entries in expected.items()
        },
    )
    if tag_result["cells"] != len(model["cells"]):
        raise RuntimeError(
            f"{name}: DOM shows {tag_result['cells']} cells, model has {len(model['cells'])}"
        )
    if tag_result["problems"]:
        raise RuntimeError(f"{name}: widget outputs did not render: {tag_result['problems']}")
    out_dir = SNAPSHOT_DIR / stem
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rows: list[dict[str, Any]] = []
    for cell_index, entries in sorted(expected.items()):
        for k, entry in enumerate(entries):
            suffix = "" if len(entries) == 1 else f"-{k + 1}"
            image = f"{stem}/cell-{entry['code_cell_index']:02d}{suffix}.png"
            out_dir.mkdir(parents=True, exist_ok=True)
            _shoot(page, f'[data-lgn-snap="{cell_index}-{k}"]', SNAPSHOT_DIR / image)
            rows.append({**entry, "image": image})
            print(f"  {image}  (nb cell {cell_index}, output {entry['output_index']})")
    return rows


def _shoot(page: Any, selector: str, path: Path) -> None:
    """Screenshot one element, growing the viewport for oversized widgets.

    JupyterLab scrolls notebooks in an inner container, so Playwright's
    capture-beyond-viewport cannot reach the parts of an element that do
    not fit: a taller-than-viewport widget (tutorial 7's dashboard) would
    come back collaged with Lab chrome.  Temporarily growing the page
    viewport to the element's height keeps the whole widget visible at
    capture time; the viewport is restored afterwards.
    """

    locator = page.locator(selector)
    locator.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    box = locator.bounding_box() or {"height": 0}
    needed = int(box["height"]) + 400  # widget + Lab toolbars/margins
    resized = needed > VIEWPORT["height"]
    if resized:
        page.set_viewport_size({"width": VIEWPORT["width"], "height": min(needed, 6000)})
        page.wait_for_timeout(500)  # relayout + canvas redraw
        locator.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
    try:
        locator.screenshot(path=str(path), animations="disabled")
    finally:
        if resized:
            page.set_viewport_size(VIEWPORT)
            page.wait_for_timeout(250)


# -- manifest -----------------------------------------------------------------


def write_manifest(captured: dict[str, list[dict[str, Any]]], full_run: bool) -> None:
    """Rewrite (full run) or merge (filtered run) the snapshot manifest."""

    notebooks: dict[str, list[dict[str, Any]]] = {}
    if not full_run and MANIFEST_PATH.exists():
        notebooks = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["notebooks"]
    for stem, rows in captured.items():
        if rows:
            notebooks[stem] = rows
        else:
            notebooks.pop(stem, None)
    manifest = {
        "viewport": {**VIEWPORT, "device_scale_factor": DEVICE_SCALE_FACTOR},
        "notebooks": dict(sorted(notebooks.items())),
    }
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "only",
        nargs="*",
        help="capture only notebooks whose filename contains one of these "
        "substrings (e.g. '06'); the manifest is merged, not rewritten",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="per-notebook settle timeout in seconds (default: 600, "
        "matching nb_execution_timeout in docs/conf.py)",
    )
    args = parser.parse_args(argv)

    all_names = sorted(
        path.name for path in NOTEBOOK_DIR.glob("*.ipynb") if path.name[:2] in TUTORIAL_NUMBERS
    )
    names = [name for name in all_names if not args.only or any(sub in name for sub in args.only)]
    if not names:
        print(f"no tutorial notebooks match {args.only!r}")
        return 2

    from playwright.sync_api import sync_playwright  # needs the browser env

    captured: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []
    server = start_lab_server()
    try:
        with sync_playwright() as playwright:
            # --disable-dev-shm-usage: tiny /dev/shm hangs Chromium on CI
            browser = playwright.chromium.launch(args=["--disable-dev-shm-usage"])
            for index, name in enumerate(names):
                print(f"== {name}")
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR)
                page.on("crash", lambda _page, name=name: failures.append(f"{name}: crash"))
                try:
                    captured[Path(name).stem] = capture_notebook(
                        page, server, name, index, args.timeout
                    )
                except Exception as err:  # keep capturing the other notebooks
                    failures.append(f"{name}: {err}")
                    print(f"  FAILED: {err}")
                finally:
                    page.close()
                    server.shutdown_sessions(name)
            browser.close()
    finally:
        server.process.terminate()
        try:
            server.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.process.kill()
            server.process.wait()

    write_manifest(captured, full_run=not args.only)
    total = sum(len(rows) for rows in captured.values())
    print(f"\ncaptured {total} widget snapshot(s) across {len(captured)} notebook(s)")
    for stem, rows in sorted(captured.items()):
        print(f"  {stem}: {len(rows)}")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
