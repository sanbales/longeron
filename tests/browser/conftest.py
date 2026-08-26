"""Browser-truth infrastructure: real JupyterLab + headless Chromium.

Everything here runs behind ``@pytest.mark.browser`` (deselected from plain
``pytest -q``; opt in with ``pixi run test-browser``).  The session boots
one JupyterLab server (random free port, fresh token, temp root dir) from
the current interpreter and drives it with Playwright.  Three rules keep
this importable everywhere:

* no top-level ``playwright`` import -- default envs do not carry a
  browser, and collection imports this file even when the tier is
  deselected;
* the served jupyter-elk labextension is synced from the vendored build
  before the server boots (the stale-bundle trap: JupyterLab serves the
  copy that ``pixi install`` made, not ``vendor/ipyelk/src/_d``);
* ``PYTHONHASHSEED=0`` and ``PYTHONPATH=<repo>/src`` pin the kernel
  environment exactly like the pixi ``lab`` task.

On failure, a full-page screenshot plus the console/page-error log land in
``build/test-artifacts/`` (uploaded by CI).
"""

from __future__ import annotations

import itertools
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "build" / "test-artifacts"
_LABEXT_REL = Path("share/jupyter/labextensions/@jupyrdf/jupyter-elk")
_VENDOR_BUILD = REPO / "vendor/ipyelk/src/_d" / _LABEXT_REL

#: console error texts to ignore (currently none; grow this ONLY for noise
#: that is provably unrelated to the widgets under test, and say why)
CONSOLE_ERROR_ALLOWLIST: tuple[str, ...] = ()

_PHASE_REPORTS: pytest.StashKey[dict[str, pytest.TestReport]] = pytest.StashKey()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test under tests/browser/ carries the browser marker."""

    here = Path(__file__).resolve().parent
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and Path(path).resolve().is_relative_to(here):
            item.add_marker(pytest.mark.browser)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    """Stash phase reports so fixtures can react to test outcome."""

    report = yield
    item.stash.setdefault(_PHASE_REPORTS, {})[report.when] = report
    return report


# ---------------------------------------------------------------------------
# the JupyterLab server
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _manifest(root: Path) -> dict[str, int]:
    """Relative path -> size for every file (bundle chunks are content-
    hashed filenames, so name+size equality means content equality)."""

    return {
        p.relative_to(root).as_posix(): p.stat().st_size for p in root.rglob("*") if p.is_file()
    }


def _sync_labextension() -> None:
    """Copy the vendored jupyter-elk build over the served copy.

    JupyterLab serves ``{sys.prefix}/share/jupyter/labextensions/...`` --
    a copy made at install time -- so a rebuilt vendor bundle silently
    keeps serving stale code unless synced (see the ``sync-labextension``
    pixi task, which this mirrors for the interpreter running the tests).
    """

    if not _VENDOR_BUILD.is_dir():
        pytest.fail(f"vendored labextension build missing: {_VENDOR_BUILD}")
    served = Path(sys.prefix) / _LABEXT_REL
    if served.is_dir() and _manifest(served) == _manifest(_VENDOR_BUILD):
        return
    if served.is_dir():
        sys.stderr.write(f"WARNING: {served} was serving a STALE jupyter-elk build; syncing\n")
        shutil.rmtree(served)
    shutil.copytree(_VENDOR_BUILD, served)


@dataclass
class LabServer:
    """A booted JupyterLab: address, token, root dir, process handle."""

    base_url: str
    token: str
    root: Path
    process: subprocess.Popen[bytes]
    log_path: Path

    def url_for(self, notebook: str, workspace: str) -> str:
        # a PRIVATE workspace per open: the server-side "default" workspace
        # is shared across pages, so a later test would restore the earlier
        # test's notebook over its own tab, detaching live sprotty widgets
        # ("element not in DOM" console errors). &reset drops any restored
        # layout inside that workspace on top.
        return (
            f"{self.base_url}/lab/workspaces/{workspace}/tree/{notebook}?token={self.token}&reset"
        )


def _wait_http_ready(server: LabServer, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"{server.base_url}/api/status?token={server.token}"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            pytest.fail(
                f"jupyter lab exited with {server.process.returncode}; see {server.log_path}"
            )
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError) as err:
            last_error = err
        time.sleep(0.5)
    pytest.fail(f"jupyter lab not ready after {timeout}s ({last_error}); see {server.log_path}")


@pytest.fixture(scope="session")
def lab_server(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """One headless JupyterLab for the whole session."""

    from ._notebooks import SCENARIO_NOTEBOOKS  # lazy: only the browser tier needs it

    _sync_labextension()
    root = tmp_path_factory.mktemp("lab-root")
    # Hermetic copy: strip every code cell's outputs/execution_count.  The
    # working-tree NB11 accumulates autosaved outputs (capture runs, live Lab
    # sessions); stale widget-view outputs open as "widget model not found"
    # console-error storms on a fresh kernel and poison the gallery test.
    gallery = json.loads(
        (REPO / "notebooks" / "11_notation_gallery.ipynb").read_text(encoding="utf-8")
    )
    for cell in gallery.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    (root / "11_notation_gallery.ipynb").write_text(json.dumps(gallery, indent=1), encoding="utf-8")
    for name, build in SCENARIO_NOTEBOOKS.items():
        (root / name).write_text(json.dumps(build(), indent=1), encoding="utf-8")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    token = secrets.token_hex(16)
    log_path = ARTIFACTS / "lab-server.log"
    # a pristine home (CI runners) makes JupyterLab pop the "Select Kernel"
    # dialog on every notebook open -- a modal that blocks all pointer
    # interaction and stalled the whole tier (found via the artifact
    # screenshot). A temp user-settings dir opts into auto-starting the
    # notebook's preferred kernel, exactly what a developer machine has
    # remembered from its first click.
    settings = tmp_path_factory.mktemp("lab-user-settings")
    tracker = settings / "@jupyterlab" / "notebook-extension"
    tracker.mkdir(parents=True)
    (tracker / "tracker.jupyterlab-settings").write_text(
        json.dumps(
            {
                "autoStartDefaultKernel": True,
                # windowed notebooks detach offscreen cells from the DOM;
                # sprotty then updates detached diagram roots ('element not
                # in DOM: sprotty_N' console-error storms) and rendered-
                # widget counts depend on scroll position. Tests need every
                # cell attached and deterministic.
                "windowingMode": "none",
            }
        ),
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        # deterministic kernel hashing, exactly like the pixi `lab` task
        PYTHONHASHSEED="0",
        # kernels inherit this: shared CI runners can take minutes to push
        # two dozen gallery layouts through one elkjs worker, and a tripped
        # roundtrip timeout is a final, visible layout failure (by design)
        LONGERON_BROWSER_TIMEOUT="600",
        JUPYTERLAB_SETTINGS_DIR=str(settings),
        # workspace layouts persist in ~/.jupyter/lab/workspaces and are
        # restored on open -- state leaking BETWEEN test sessions (and
        # from crashed runs). Isolate per session.
        JUPYTERLAB_WORKSPACES_DIR=str(settings / "workspaces"),
        # the kernel must import THIS tree's sources even when the editable
        # install resolves elsewhere (worktree runs against the main venv)
        PYTHONPATH=os.pathsep.join(
            p for p in (str(REPO / "src"), os.environ.get("PYTHONPATH", "")) if p
        ),
    )
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "jupyterlab",
                "--no-browser",
                # expose window.jupyterlab so tests can drive the command
                # registry (notebook:run-all-cells etc.) instead of the menus
                "--LabApp.expose_app_in_browser=True",
                f"--port={port}",
                "--ServerApp.port_retries=0",
                f"--ServerApp.token={token}",
                "--ServerApp.password=",
                f"--ServerApp.root_dir={root}",
                "--ServerApp.disable_check_xsrf=True",
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    server = LabServer(f"http://127.0.0.1:{port}", token, root, process, log_path)
    try:
        _wait_http_ready(server)
        yield server
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


# ---------------------------------------------------------------------------
# playwright
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _playwright() -> Any:
    sync_api = pytest.importorskip(
        "playwright.sync_api",
        reason="the browser tier needs the browser-test extra (pip install -e '.[browser-test]')",
    )
    manager = sync_api.sync_playwright().start()
    yield manager
    manager.stop()


@pytest.fixture(scope="session")
def browser(_playwright: Any) -> Any:
    """Headless Chromium (`playwright install chromium` provides the binary)."""

    # --disable-dev-shm-usage: CI runners give Chromium a tiny /dev/shm and
    # it hangs/crashes silently on memory-heavy pages (a full gallery
    # notebook qualifies); the flag moves shared memory to /tmp. Harmless
    # on developer machines.
    chromium = _playwright.chromium.launch(args=["--disable-dev-shm-usage"])
    yield chromium
    chromium.close()


# ---------------------------------------------------------------------------
# the page driver
# ---------------------------------------------------------------------------

#: one DOM snapshot for settle-polling: rendered diagram cells, busy
#: prompts, visible progress bars, auto-fitted viewports (transform moved
#: off the identity -- the AutoFitTool's browser-visible effect)
_SNAPSHOT_JS = """() => {
    const rendered = [...document.querySelectorAll('.jp-Cell')].filter(
        (cell) => cell.querySelectorAll('.sprotty svg .elknode').length).length;
    const busy = [...document.querySelectorAll('.jp-InputArea-prompt')].filter(
        (el) => el.textContent.includes('*')).length;
    const bars = [...document.querySelectorAll(
        '.jp-OutputArea .widget-hprogress, .jp-OutputArea .widget-vprogress'
    )].filter(
        (bar) => getComputedStyle(bar).visibility === 'visible'
    ).map((bar) => {
        const inner = bar.querySelector('.progress-bar');
        return {
            width: inner ? inner.style.width || inner.style.height || '' : '',
            warning: Boolean(inner && inner.classList.contains('progress-bar-warning')),
        };
    });
    const fitted = [...document.querySelectorAll('.sprotty svg > g')].filter((g) => {
        const t = g.getAttribute('transform') || '';
        return t && t !== 'scale(1) translate(0,0)' && t !== 'translate(0, 0) scale(1)';
    }).length;
    const elknodes = document.querySelectorAll('.sprotty svg .elknode').length;
    const loading = [...document.querySelectorAll('.jp-OutputArea-output')].filter(
        (el) => el.textContent.trim() === 'Loading widget...').length;
    const kernel = document.querySelector('.jp-Notebook-ExecutionIndicator')
        ?.getAttribute('data-status') || 'missing';
    return {rendered, busy, bars, fitted, elknodes, loading, kernel};
}"""

_CELL_STATE_JS = """(index) => {
    const cells = [...document.querySelectorAll('.jp-Notebook .jp-Cell')];
    const cell = cells.at(index);
    if (!cell) return null;
    const prompt = cell.querySelector('.jp-InputArea-prompt');
    const out = [...cell.querySelectorAll('.jp-OutputArea-output')]
        .map((el) => el.textContent).join('\\n');
    return {prompt: prompt ? prompt.textContent.trim() : '', out};
}"""


class LabPage:
    """Drive one notebook document; collect console + page errors."""

    _workspace_ids = itertools.count()

    def __init__(self, page: Page, server: LabServer) -> None:
        self.page = page
        self.server = server
        self.console: list[str] = []
        self.page_errors: list[str] = []
        page.on("console", lambda message: self.console.append(f"[{message.type}] {message.text}"))
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    # -- lifecycle -----------------------------------------------------------

    def open_notebook(self, name: str, timeout: float = 120.0) -> None:
        """Open the notebook (in its own workspace) and wait for the Lab app."""

        workspace = f"{re.sub(r'[^a-z0-9]+', '-', name.lower())}-{next(self._workspace_ids)}"
        self.page.goto(self.server.url_for(name, workspace), wait_until="domcontentloaded")
        self.page.wait_for_selector(".jp-Notebook", state="attached", timeout=timeout * 1000)
        # belt to the settings suspenders: DISMISS any modal dialog whenever
        # one appears (a visible jp-Dialog blocks every click). Reject, not
        # accept: the kernel picker cannot appear (autoStartDefaultKernel)
        # and accepting e.g. 'Build Recommended' would start a rebuild.
        self.page.add_locator_handler(
            self.page.locator(".jp-Dialog .jp-mod-reject"),
            lambda button: button.click(),
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.page.evaluate("() => !!(window.jupyterapp || window.jupyterlab)"):
                return
            time.sleep(1)
        raise TimeoutError(f"JupyterLab app handle never appeared for {name}")

    def wait_kernel_idle(self, timeout: float = 120.0) -> None:
        """Block until the notebook's kernel connection is established + idle.

        Run-all must not fire before the kernel websocket is up: widget
        comm_open messages sent while the frontend is still connecting are
        lost, and every widget output then shows 'Loading widget...'
        forever (the CI failure mode after the kernel-picker fix; dev
        machines always win that race, 2-core runners always lose it).
        """

        self.page.wait_for_selector(
            '.jp-Notebook-ExecutionIndicator[data-status="idle"]',
            state="attached",
            timeout=timeout * 1000,
        )

    def run_all(self, attempts: int = 5) -> None:
        """Run all cells via the command registry; confirm execution started."""

        self.wait_kernel_idle()
        for _attempt in range(attempts):
            # fire-and-forget: commands.execute returns a promise that only
            # resolves when the WHOLE run finishes, and page.evaluate awaits
            # returned promises -- an unbounded hang if any cell stalls (the
            # CI eaten-clock signature). The bounded wait_settled below owns
            # the waiting and reports last-known state on timeout.
            self.page.evaluate(
                "() => { void (window.jupyterapp || window.jupyterlab)"
                ".commands.execute('notebook:run-all-cells'); return true; }"
            )
            time.sleep(4)
            started = self.page.evaluate(
                "() => [...document.querySelectorAll('.jp-InputArea-prompt')]"
                ".some((el) => el.textContent.includes('[*]') || /\\[\\d+\\]/.test(el.textContent))"
            )
            if started:
                return
        raise TimeoutError(f"run-all never started after {attempts} attempts")

    # -- settle polling ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return dict(self.page.evaluate(_SNAPSHOT_JS))

    def wait_until(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 300.0,
        poll_s: float = 2.0,
        stable_polls: int = 2,
        label: str = "condition",
    ) -> dict[str, Any]:
        """Poll snapshots until the predicate holds ``stable_polls`` in a row."""

        deadline = time.monotonic() + timeout
        streak = 0
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = self.snapshot()
            streak = streak + 1 if predicate(state) else 0
            if streak >= stable_polls:
                return state
            time.sleep(poll_s)
        raise TimeoutError(f"{label} not reached within {timeout}s; last state: {state}")

    def wait_settled(
        self,
        *,
        min_widgets: int = 0,
        min_fitted: int = 0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Settled: nothing busy, no progress bars or stuck widgets, all rendered."""

        return self.wait_until(
            lambda s: (
                s["busy"] == 0
                and not s["bars"]
                and s["loading"] == 0
                and s["rendered"] >= min_widgets
                and s["fitted"] >= min_fitted
            ),
            timeout=timeout,
            label=f"settle (min_widgets={min_widgets}, min_fitted={min_fitted})",
        )

    # -- kernel round trips ---------------------------------------------------

    def cell_output(self, index: int = -1) -> str:
        """The current output text of a cell (no re-run)."""

        state = self.page.evaluate(_CELL_STATE_JS, index)
        assert state is not None, f"no cell at index {index}"
        return str(state["out"])

    def run_cell(self, index: int = -1, timeout: float = 60.0) -> str:
        """Re-run one cell (activate + notebook:run-cell); return its output.

        The command is fired-and-forgotten and RE-FIRED while the cell
        shows no sign of running: ``notebook:run-cell``'s promise resolves
        only when the cell's execution completes, and ``page.evaluate``
        awaits returned promises -- awaiting it hung CI (and local runs
        under load) FOREVER when the execute request was swallowed by a
        just-restarted kernel's half-rewired session (the docking test's
        post-restart checker; the same eaten-clock class ``run_all``
        documents). The bounded poll below owns the waiting; every caller
        re-runs an idempotent print-only checker cell, so an occasional
        double execution is harmless.
        """

        before = self.page.evaluate(_CELL_STATE_JS, index)
        assert before is not None, f"no cell at index {index}"
        self.page.evaluate(
            """(index) => {
                const cells = [...document.querySelectorAll('.jp-Notebook .jp-Cell')];
                const cell = cells.at(index);
                cell.scrollIntoView();
                cell.querySelector('.jp-InputArea').dispatchEvent(
                    new MouseEvent('mousedown', {bubbles: true}));
            }""",
            index,
        )
        time.sleep(0.5)
        deadline = time.monotonic() + timeout
        refire_at = time.monotonic()  # first fire happens immediately
        while time.monotonic() < deadline:
            state = self.page.evaluate(_CELL_STATE_JS, index)
            if (
                state is not None
                and state["prompt"] != before["prompt"]
                and "*" not in state["prompt"]
                and re.search(r"\[\d+\]", state["prompt"])
            ):
                return str(state["out"])
            running = state is not None and "*" in state["prompt"]
            if not running and time.monotonic() >= refire_at:
                self.page.evaluate(
                    "() => { void (window.jupyterapp || window.jupyterlab)"
                    ".commands.execute('notebook:run-cell'); return true; }"
                )
                refire_at = time.monotonic() + 15.0
            time.sleep(0.5)
        raise TimeoutError(f"cell {index} did not finish re-running within {timeout}s")

    def run_cell_json(self, index: int = -1, timeout: float = 60.0) -> dict[str, Any]:
        """Re-run a checker cell and parse the JSON line it prints."""

        return self._extract_json(self.run_cell(index, timeout))

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        for line in reversed(text.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return dict(json.loads(line))
        raise AssertionError(f"no JSON line in cell output: {text!r}")

    # -- error accounting ------------------------------------------------------

    def console_errors(self) -> list[str]:
        return [
            message
            for message in self.console
            if message.startswith("[error]")
            and not any(allowed in message for allowed in CONSOLE_ERROR_ALLOWLIST)
        ]

    def assert_no_errors(self, allow_page_errors: tuple[str, ...] = ()) -> None:
        """Zero page/console errors, minus explicitly documented allowances."""

        unexpected = [
            error
            for error in self.page_errors
            if not any(allowed in error for allowed in allow_page_errors)
        ]
        assert unexpected == [], f"page errors: {unexpected}"
        assert self.console_errors() == [], f"console errors: {self.console_errors()}"

    # -- failure artifacts ------------------------------------------------------

    def save_artifacts(self, directory: Path, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(directory / f"{name}.png"), full_page=True)
        except Exception as err:  # the page may already be unusable
            sys.stderr.write(f"screenshot failed for {name}: {err}\n")
        log = directory / f"{name}.console.txt"
        log.write_text(
            "\n".join(["== page errors ==", *self.page_errors, "== console ==", *self.console]),
            encoding="utf-8",
        )


@pytest.fixture()
def lab(browser: Browser, lab_server: LabServer, request: pytest.FixtureRequest) -> Any:
    """A fresh page (and console/error collectors) per test."""

    page = browser.new_page(viewport={"width": 1500, "height": 1100})
    # a crashed renderer must fail fast, never masquerade as a hang: a
    # pending page.evaluate on a crashed page waits forever (the CI
    # eaten-clock failure mode; small /dev/shm kills renderers silently)
    page.on(
        "crash",
        lambda _page: pytest.fail("chromium renderer crashed (see the /dev/shm note in conftest)"),
    )
    driver = LabPage(page, lab_server)
    yield driver
    try:
        reports = request.node.stash.get(_PHASE_REPORTS, {})
        if any(report.failed for report in reports.values()):
            driver.save_artifacts(ARTIFACTS, request.node.name)
    finally:
        page.close()
