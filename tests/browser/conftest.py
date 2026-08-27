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
_LONGERON_EXT_REL = Path("share/jupyter/labextensions/longeron")
_LONGERON_EXT_BUILD = REPO / "npm/_d" / _LONGERON_EXT_REL

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
    """Copy the repo's labextension builds over the served copies.

    JupyterLab serves ``{sys.prefix}/share/jupyter/labextensions/...`` --
    a copy made at install time -- so a rebuilt bundle silently keeps
    serving stale code unless synced (see the ``sync-labextension``
    pixi task, which this mirrors for the interpreter running the tests).
    Two builds ride this: the vendored jupyter-elk and the longeron
    launcher tile (npm/_d; editable installs never place data files, so
    without this sync the tile tier would test NOTHING).
    """

    for build, rel in ((_VENDOR_BUILD, _LABEXT_REL), (_LONGERON_EXT_BUILD, _LONGERON_EXT_REL)):
        if not build.is_dir():
            pytest.fail(f"labextension build missing: {build}")
        served = Path(sys.prefix) / rel
        if served.is_dir() and _manifest(served) == _manifest(build):
            continue
        if served.is_dir():
            sys.stderr.write(f"WARNING: {served} was serving a STALE build; syncing\n")
            shutil.rmtree(served)
        shutil.copytree(build, served)


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


def _shutdown_sessions(server: LabServer) -> None:
    """Close every kernel session (best effort) so the NEXT test's open
    starts a fresh kernel exactly like a first open.

    Reopening a notebook whose session still holds a live kernel makes
    JupyterLab REPLACE that kernel during page init (the 5ee3aee CI
    server log shows a started/shutdown pair on every rerun's reopen) --
    a moving target for the page's widget manager wiring.  Left alone,
    kernels also ACCUMULATE for the whole session (8 live ipykernels by
    suite end in the CI artifacts), pure memory pressure on a 2-core
    runner.  Best effort: cleanup failure must never mask a test result.
    """

    base = f"{server.base_url}/api/sessions"
    try:
        with urllib.request.urlopen(f"{base}?token={server.token}", timeout=10) as response:
            sessions = json.loads(response.read().decode("utf-8"))
        for session in sessions:
            request = urllib.request.Request(
                f"{base}/{session['id']}?token={server.token}", method="DELETE"
            )
            with urllib.request.urlopen(request, timeout=10):
                pass
    except (urllib.error.URLError, OSError, ValueError) as err:
        sys.stderr.write(f"session cleanup failed (non-fatal): {err}\n")


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
    # NB14 VERBATIM (maintainer QA: the app/inspector/scoreboard findings
    # were all reported from live NB14 sessions, so the tier drives the
    # REAL tutorial, not a paraphrase).  Served from a notebooks/ subdir
    # with examples/ beside it so cell 3's relative
    # "../examples/drone.sysml" resolves exactly like in the repo; outputs
    # stripped for the same autosave-poisoning reasons as the gallery.
    tutorial = json.loads((REPO / "notebooks" / "14_model_app.ipynb").read_text(encoding="utf-8"))
    for cell in tutorial.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    (root / "notebooks").mkdir()
    (root / "notebooks" / "14_model_app.ipynb").write_text(
        json.dumps(tutorial, indent=1), encoding="utf-8"
    )
    (root / "examples").mkdir()
    shutil.copyfile(REPO / "examples" / "drone.sysml", root / "examples" / "drone.sysml")
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
    # autosave OFF: the tier shares one lab root across tests and rerun
    # attempts.  On a slow CI runner a single test can outlive JupyterLab's
    # 120s autosave interval, which then writes that run's OUTPUTS into the
    # shared notebook file; every later open of the file replays the stale
    # widget-view outputs ('Error displaying widget: model not found'
    # console storms) and shows stale [n] prompts.  That poisoning turned
    # ONE slow first attempt into deterministic 3-minute failures for every
    # rerun and follow-up test of the same notebook (the 5ee3aee CI run's
    # artifact anatomy: 'Saving file at /explorer_scenario.ipynb' at t+120s,
    # then model-not-found on all three later opens of that file).  Tests
    # never need the file mutated -- reruns WANT the pristine copy.
    docmanager = settings / "@jupyterlab" / "docmanager-extension"
    docmanager.mkdir(parents=True)
    (docmanager / "plugin.jupyterlab-settings").write_text(
        json.dumps({"autosave": False}), encoding="utf-8"
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
        # install resolves elsewhere (worktree runs against the main venv);
        # the vendored ipyelk rides along for the same reason
        PYTHONPATH=os.pathsep.join(
            p
            for p in (
                str(REPO / "src"),
                str(REPO / "vendor/ipyelk/src"),
                os.environ.get("PYTHONPATH", ""),
            )
            if p
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
                # skip jupyter_lsp's language-server detection sweep (a ~20s
                # background probe of ~19 servers in the 5ee3aee CI log,
                # right under the first test's cold start); no test uses LSP
                "--LanguageServerManager.autodetect=False",
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


@pytest.fixture(scope="session", autouse=True)
def _warm_lab(browser: Browser, lab_server: LabServer) -> None:
    """One throwaway page load before the first test runs.

    The first Lab page of a fresh server pays every cold-start cost at
    once: federated extension asset serving, jupyter_lsp's server
    detection sweep, chromium's first paint.  On a 2-core CI runner that
    bill otherwise lands on the first TEST's clock -- and on its widget
    comm traffic (the 5ee3aee CI run failed ONLY the first scenario's
    attempts; every later widget test in the same session passed).
    Costs a few seconds locally; buys the first test the same warm
    server every other test gets.
    """

    page = browser.new_page()
    try:
        page.goto(
            f"{lab_server.base_url}/lab?token={lab_server.token}",
            wait_until="domcontentloaded",
        )
        page.wait_for_selector("#jp-main-dock-panel", state="attached", timeout=120_000)
    finally:
        page.close()


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
    const werrors = [...document.querySelectorAll('.jp-OutputArea-output')].filter(
        (el) => (el.textContent || '').includes('Error displaying widget')).length;
    const kernel = document.querySelector('.jp-Notebook-ExecutionIndicator')
        ?.getAttribute('data-status') || 'missing';
    return {rendered, busy, bars, fitted, elknodes, loading, werrors, kernel};
}"""

_CELL_STATE_JS = """(index) => {
    const cells = [...document.querySelectorAll('.jp-Notebook .jp-Cell')];
    const cell = cells.at(index);
    if (!cell) return null;
    const prompt = cell.querySelector('.jp-InputArea-prompt');
    const out = [...cell.querySelectorAll('.jp-OutputArea-output')]
        .map((el) => el.textContent).join('\\n');
    const kernel = document.querySelector('.jp-Notebook-ExecutionIndicator')
        ?.getAttribute('data-status') || 'missing';
    return {prompt: prompt ? prompt.textContent.trim() : '', out, kernel};
}"""

#: every input prompt's text, in document order (run_all's started check)
_PROMPTS_JS = """() => [...document.querySelectorAll('.jp-InputArea-prompt')]
    .map((el) => el.textContent.trim())"""

#: find the (single) notebook panel among the main-area widgets and hand
#: back {panel, kernel}; every miss is a self-naming string instead
_FIND_NOTEBOOK_JS = """
    const app = window.jupyterapp || window.jupyterlab;
    if (!app) return {why: 'no JupyterLab app handle on window'};
    const panel = [...app.shell.widgets('main')].find(
        (w) => w.sessionContext && w.content && w.content.model
            && w.content.model.cells);
    if (!panel) return {why: 'no notebook panel among the main-area widgets'};
    const session = panel.sessionContext.session;
    const kernel = session ? session.kernel : null;
    if (!kernel) return {
        why: 'notebook sessionContext has no kernel yet'
            + ' (isReady=' + panel.sessionContext.isReady + ')',
    };
"""

#: prove the notebook's OWN kernel connection can round-trip an execute:
#: an empty silent execute must come back with an execute_reply.  This is
#: the signal the execution indicator CANNOT give (artifact-verified: the
#: indicator said Idle while every execute vanished): a reply proves
#: websocket send -> kernel -> reply -> the connection's serial incoming
#: message chain, end to end -- exactly the path run-all and cell prompts
#: depend on.  Bounded by our own race; never hangs page.evaluate.
_CHANNEL_PROBE_JS = (
    """async ({timeoutMs}) => {"""
    + _FIND_NOTEBOOK_JS
    + """
    const state = () => ' (connectionStatus=' + kernel.connectionStatus
        + ', kernelStatus=' + kernel.status
        + ', isReady=' + panel.sessionContext.isReady + ')';
    try {
        const future = kernel.requestExecute(
            {code: '', silent: true, store_history: false}, false);
        const reply = await Promise.race([
            future.done,
            new Promise((resolve) => setTimeout(
                () => resolve('__probe_timeout__'), timeoutMs)),
        ]);
        future.dispose();
        if (reply === '__probe_timeout__') return {
            why: 'no execute_reply to the probe within ' + timeoutMs + 'ms'
                + state(),
        };
        return {ok: true};
    } catch (err) {
        return {why: 'probe requestExecute threw: ' + err + state()};
    }
}"""
)

#: reconnect the notebook kernel's websocket (fire-and-forget: the next
#: probe is the arbiter of whether it helped)
_RECONNECT_JS = (
    """() => {"""
    + _FIND_NOTEBOOK_JS
    + """
    void kernel.reconnect();
    return {ok: true};
}"""
)

#: run one cell's SOURCE directly on the kernel over a FRESH cloned
#: connection, bypassing the notebook command machinery AND the shared
#: kernel connection (see LabPage.run_cell for why both must be bypassed).
#: Returns the concatenated stream/error/result text; bounded by our own
#: race so page.evaluate can never hang on a swallowed request.
_DIRECT_EXECUTE_JS = (
    """async ({index, timeoutMs}) => {"""
    + _FIND_NOTEBOOK_JS
    + """
    const cells = panel.content.model.cells;
    const at = index < 0 ? cells.length + index : index;
    if (at < 0 || at >= cells.length) return {
        why: 'no cell at index ' + index + ' (notebook has ' + cells.length + ')',
    };
    const code = cells.get(at).sharedModel.getSource();
    // a fresh KernelConnection: its own websocket and its own serial
    // incoming-message chain, so neither a silently-queued send nor a
    // wedged chain on the notebook's shared connection can eat this
    // execute or its reply. handleComms=false: widget traffic stays on
    // the shared connection.
    const clone = kernel.clone();
    try {
        let out = '';
        const future = clone.requestExecute(
            {code, store_history: false, allow_stdin: false, stop_on_error: false},
            false);
        future.onIOPub = (msg) => {
            const kind = msg.header.msg_type;
            if (kind === 'stream') out += msg.content.text;
            else if (kind === 'execute_result') {
                out += (msg.content.data || {})['text/plain'] || '';
            } else if (kind === 'error') {
                out += '\\n' + msg.content.ename + ': ' + msg.content.evalue;
            }
        };
        const reply = await Promise.race([
            future.done,
            new Promise((resolve) => setTimeout(
                () => resolve('__execute_timeout__'), timeoutMs)),
        ]);
        if (reply === '__execute_timeout__') return {
            why: 'no execute_reply within ' + timeoutMs + 'ms over a FRESH '
                + 'kernel connection (clone connectionStatus='
                + clone.connectionStatus + ', kernel status=' + clone.status
                + '): the kernel/service side is not answering',
        };
        return {ok: true, status: reply.content.status, out};
    } catch (err) {
        return {why: 'direct requestExecute threw: ' + err};
    } finally {
        clone.dispose();
    }
}"""
)


class LabPage:
    """Drive one notebook document; collect console + page errors."""

    _workspace_ids = itertools.count()

    def __init__(self, page: Page, server: LabServer) -> None:
        self.page = page
        self.server = server
        self.console: list[str] = []
        self.page_errors: list[str] = []
        page.on("console", lambda message: self.console.append(f"[{message.type}] {message.text}"))
        # page errors KEEP their JS stack: a bare 'Host is not attached.'
        # is unactionable, while the throwing frame named the vendored
        # overlay-attach race outright (QA-3); allowance matching is
        # substring-based, so the suffix costs nothing
        page.on(
            "pageerror",
            lambda error: self.page_errors.append(
                str(error) + " | STACK: " + str(getattr(error, "stack", ""))
            ),
        )

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

    def wait_execute_channel_ready(self, timeout: float = 120.0) -> None:
        """Block until the notebook kernel PROVABLY answers an execute.

        The execution indicator is not that proof: the CI artifacts show
        it pinned at Idle while every execute request vanished for 120s+
        (the kernel connection either silently queues sends -- non-empty
        ``_pendingMessages``, ``connectionStatus !== 'connected'``, or
        ``_isRestarting`` -- or its serial incoming-message chain is
        wedged behind one never-resolving comm_open handler, so replies
        arrive but are never processed).  The only signal that the
        channel WORKS is a completed round trip, so this fires an empty
        silent execute and waits (bounded) for its execute_reply.

        After two dead probes the kernel websocket is reconnected (a
        reconnect flushes a stuck send queue; it cannot unwedge the
        incoming chain -- ``_clearKernelState`` only runs on restart --
        but then the LOUD failure below names exactly what is broken).
        """

        deadline = time.monotonic() + timeout
        attempt = 0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            attempt += 1
            budget_ms = int(max(min(15.0, deadline - time.monotonic()), 3.0) * 1000)
            last = dict(self.page.evaluate(_CHANNEL_PROBE_JS, {"timeoutMs": budget_ms}))
            if last.get("ok"):
                if attempt > 1:
                    sys.stderr.write(f"execute channel proven alive on probe attempt {attempt}\n")
                return
            sys.stderr.write(
                f"execute-channel probe {attempt} found a dead channel: {last.get('why')}\n"
            )
            if attempt == 2:
                sys.stderr.write("escalating: reconnecting the notebook kernel's websocket\n")
                self.page.evaluate(_RECONNECT_JS)
            time.sleep(1.0)
        raise TimeoutError(
            f"the notebook kernel never answered an execute probe within {timeout}s "
            f"(even after a websocket reconnect); last probe: {last}"
        )

    def run_all(self, attempts: int = 5) -> None:
        """Run all cells via the command registry; confirm execution started.

        Started means BROWSER-VISIBLE evidence relative to a pre-fire
        snapshot: a live ``[*]`` marker, or any prompt text that CHANGED.
        Comparing against the snapshot (rather than accepting any ``[n]``)
        keeps prompts restored from a previously-saved copy of the file
        from faking a start -- the 5ee3aee CI reruns opened an
        autosave-poisoned notebook whose stale ``[1]`` prompts satisfied
        the old check, so a swallowed run-all was never re-fired.
        """

        self.wait_kernel_idle()
        # idle indicator != working channel (see wait_execute_channel_ready):
        # prove the execute channel BEFORE the first run-all, so a slow
        # runner's half-wired session costs one bounded probe instead of a
        # swallowed run + re-fire cycle
        self.wait_execute_channel_ready()
        before = list(self.page.evaluate(_PROMPTS_JS))
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
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                prompts = list(self.page.evaluate(_PROMPTS_JS))
                if any("*" in prompt for prompt in prompts) or prompts != before:
                    return
                time.sleep(0.25)
        raise TimeoutError(f"run-all never started after {attempts} attempts; prompts: {before}")

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
        refire_run_on_stall: bool = False,
    ) -> dict[str, Any]:
        """Poll snapshots until the predicate holds ``stable_polls`` in a row.

        ``refire_run_on_stall`` (used by :meth:`wait_settled`, whose callers
        just ran the whole notebook) recovers a DEAD RUN: cells pinned at
        ``[*]`` while the kernel reports idle means the execute requests
        were swallowed by a half-rewired session -- JupyterLab can replace
        a session's kernel during page init (double kernel start in the
        server log) and a post-restart session drops requests; both were
        artifact-verified (gallery cells at ``[ ]``/``[*]`` + kernel idle
        for the full 480s budget).  A dead run never heals by waiting, so
        after ~12s of that state run-all is re-fired (bounded) -- safe
        because every scenario notebook in this tier is idempotent by
        convention (the docking test refires on the same contract).
        """

        deadline = time.monotonic() + timeout
        streak = 0
        state: dict[str, Any] = {}
        stalled_since: float | None = None
        refires = 0
        while time.monotonic() < deadline:
            state = self.snapshot()
            # a widget output rendering as 'Error displaying widget' NEVER
            # self-heals -- the frontend widget manager has no model for it
            # (a lost comm_open, or a dead kernel's saved output).  Waiting
            # out the full timeout on it burned 3 minutes per CI attempt;
            # fail fast and NAME it so --reruns 1 retries on fresh state.
            if state.get("werrors"):
                raise AssertionError(
                    f"{label}: {state['werrors']} widget output(s) render as "
                    "'Error displaying widget' (frontend widget manager has no "
                    "model: lost comm_open or a dead kernel's saved output); "
                    f"this never self-heals, failing fast. Last state: {state}"
                )
            if refire_run_on_stall:
                now = time.monotonic()
                if not (state["busy"] > 0 and state["kernel"] == "idle"):
                    stalled_since = None
                elif stalled_since is None:
                    stalled_since = now
                elif now - stalled_since >= 12.0 and refires < 3:
                    refires += 1
                    stalled_since = None
                    sys.stderr.write(
                        f"{label}: dead run detected ({state['busy']} cell(s) pinned "
                        f"at [*] with an idle kernel); re-firing run-all "
                        f"({refires}/3)\n"
                    )
                    self.page.evaluate(
                        "() => { void (window.jupyterapp || window.jupyterlab)"
                        ".commands.execute('notebook:run-all-cells'); return true; }"
                    )
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
            # wait_settled's callers just ran the notebook: recover a dead
            # run (cells pinned at [*], kernel idle) instead of timing out
            refire_run_on_stall=True,
        )

    # -- kernel round trips ---------------------------------------------------

    def cell_output(self, index: int = -1) -> str:
        """The current output text of a cell (no re-run)."""

        state = self.page.evaluate(_CELL_STATE_JS, index)
        assert state is not None, f"no cell at index {index}"
        return str(state["out"])

    def run_cell(self, index: int = -1, timeout: float = 60.0) -> str:
        """Run one cell's source DIRECTLY on the kernel; return its output.

        Not ``notebook:run-cell``: every checker cell here is a print-only
        kernel-state read, and the notebook path proved unrecoverable on
        loaded runners.  The CI artifacts (checker pinned at ``[*]``,
        indicator Idle, no websocket drop, 12 re-fires all swallowed,
        including runs with NO restart) match the two silent failure modes
        of the notebook's SHARED kernel connection in Lab 4.6's own code:

        * ``_sendMessage`` silently queues an execute whenever pending
          messages exist, the socket is not 'connected', or the client is
          mid-restart -- and the queue only flushes on a later
          connected-transition, so a re-fired command just queues behind
          the dead one;
        * all incoming messages are chained through one serial promise
          (``_msgChain``); a single never-resolving comm_open handler (the
          widget manager, during the post-run-all comm storm) freezes
          every later reply/status/stream FOREVER while sends still work
          -- the kernel executes, and nothing in the DOM ever shows it.
          ``kernel.reconnect()`` does not reset that chain; only a
          restart/dispose does.

        So the checker read must not depend on that connection at all:
        run the cell's SOURCE over a fresh ``kernel.clone()`` connection
        (own websocket, own message chain, same kernel process and
        namespace) and collect the reply's stream text ourselves, bounded
        by our own timeout.  ``store_history=False`` keeps the kernel's
        execution counter untouched; the DOM cell is not involved (its
        prompt/output are irrelevant to what the callers assert).  After
        two dead attempts the shared connection is reconnected too (it
        may be what broke, and later DOM-level waits depend on it).
        """

        deadline = time.monotonic() + timeout
        attempt = 0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            attempt += 1
            budget_ms = int(max(min(20.0, deadline - time.monotonic()), 3.0) * 1000)
            result = dict(
                self.page.evaluate(_DIRECT_EXECUTE_JS, {"index": index, "timeoutMs": budget_ms})
            )
            if result.get("ok"):
                if result.get("status") != "ok":
                    raise AssertionError(
                        f"cell {index} direct execute replied "
                        f"{result.get('status')!r}: {result.get('out')}"
                    )
                return str(result.get("out", ""))
            last = result
            sys.stderr.write(
                f"run_cell({index}): direct kernel execute attempt {attempt} "
                f"got no reply ({result.get('why')}); retrying on a fresh clone\n"
            )
            if attempt == 2:
                sys.stderr.write(
                    f"run_cell({index}): escalating -- reconnecting the notebook "
                    "kernel's shared websocket\n"
                )
                self.page.evaluate(_RECONNECT_JS)
            time.sleep(1.0)
        raise TimeoutError(
            f"cell {index} did not finish re-running within {timeout}s: every direct "
            f"kernel execute over a fresh connection went unanswered; last: {last}"
        )

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
    # repro aid for slow-CI timing bugs: LONGERON_BROWSER_CPU_THROTTLE=<rate>
    # slows the RENDERER by that factor via CDP (e.g. 8 approximates a
    # loaded 2-core runner on a fast dev machine). Off by default.
    throttle = float(os.environ.get("LONGERON_BROWSER_CPU_THROTTLE", "0") or 0)
    if throttle > 1:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
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
        # hermetic teardown: every test (and every rerun attempt) hands the
        # next one a server with NO live kernel sessions -- see
        # _shutdown_sessions for the CI evidence this encodes
        _shutdown_sessions(lab_server)
