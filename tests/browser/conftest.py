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

import contextlib
import itertools
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
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


#: opt-in harness tracing (LONGERON_HARNESS_TRACE=1): per-wait poll stats
#: and slow-evaluate lines on stderr -- the flake-triage view of a run
_TRACE = os.environ.get("LONGERON_HARNESS_TRACE", "") not in ("", "0")

#: flake-triage bisect knob (LONGERON_HARNESS_DISABLE=evalnet,loopnet,
#: testnet,probe): switch individual hang-net components off to A/B a
#: suspected harness/product interaction without editing this file
_DISABLED = {
    part.strip()
    for part in os.environ.get("LONGERON_HARNESS_DISABLE", "").split(",")
    if part.strip()
}


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    """Stash phase reports so fixtures can react to test outcome."""

    report = yield
    item.stash.setdefault(_PHASE_REPORTS, {})[report.when] = report
    return report


# ---------------------------------------------------------------------------
# the page watchdog: a hang must become a visible failure
# ---------------------------------------------------------------------------
#
# The one wedge this tier has actually produced (three landings' gates)
# was NOT fixture poisoning: a renderer-main-thread freeze (the LATENT
# SelectAction microtask oscillation defused in 6aa1f76) parks every
# timeout-less playwright call FOREVER -- ``page.evaluate`` and
# ``locator.count()`` carry no driver-side deadline, so the sync greenlet
# waits in ``run_until_complete`` until pytest-timeout's thread method
# dumps the stacks and ``os._exit(1)``s the WHOLE run: no rerun, no
# artifacts, no summary, every later test unrun (and the session-scoped
# lab server orphaned).  The watchdog inverts that: when a bounded block
# overruns its budget, the renderers belonging to THIS pytest process are
# SIGKILLed, the parked call raises (Target crashed -- verified live
# against an injected renderer freeze), and the block reports a loud,
# labeled test failure.  The browser process and the JupyterLab server
# survive; the rerun gets a fresh renderer and a fresh kernel session.


def _our_renderer_pids() -> list[int]:
    """Chromium renderer PIDs that are DESCENDANTS of this process.

    Ancestry-scoped on purpose: this box runs other sessions' browsers
    and kernels; only processes under our own pid (python -> playwright
    node driver -> chromium -> renderers) are ever candidates.
    """

    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=False
    ).stdout
    children: dict[int, list[int]] = {}
    commands: dict[int, str] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
        commands[pid] = parts[2]
    found: list[int] = []
    stack = [os.getpid()]
    while stack:
        for kid in children.get(stack.pop(), []):
            stack.append(kid)
            if "--type=renderer" in commands.get(kid, ""):
                found.append(kid)
    return found


def _kill_wedged_renderers() -> list[int]:
    """SIGKILL this run's renderers; return the pids actually signalled."""

    killed: list[int] = []
    for pid in _our_renderer_pids():
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except OSError as err:  # already gone: the goal state
            sys.stderr.write(f"watchdog: kill({pid}) failed (non-fatal): {err}\n")
    return killed


@contextlib.contextmanager
def _page_watchdog(budget_s: float, label: str) -> Iterator[None]:
    """Bound a block of playwright work: overrun -> renderer kill -> loud fail.

    Budgets sit ABOVE every legitimate deadline inside the block, so a
    healthy-but-slow page always fails through its own labeled timeout
    first; the watchdog only ever fires on a page that can no longer
    answer anything (at which point killing its renderer is the only way
    to unstick the parked greenlet -- no Python-side timeout can).
    """

    fired = threading.Event()

    def _fire() -> None:
        fired.set()
        sys.stderr.write(
            f"PAGE WATCHDOG [{label}]: no progress within {budget_s:.0f}s; "
            "presuming a wedged renderer and SIGKILLing this run's "
            f"chromium renderers: {_kill_wedged_renderers()}\n"
        )

    timer = threading.Timer(budget_s, _fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    except Exception as err:
        if fired.is_set():
            raise AssertionError(
                f"page unresponsive: {label!r} overran its {budget_s:.0f}s watchdog "
                "budget; the wedged renderer was killed so this failure could "
                f"surface (the unstuck call raised {err!r})"
            ) from err
        raise
    finally:
        timer.cancel()


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


def _interrupt_kernels(server: LabServer) -> None:
    """Interrupt every live kernel (best effort): the stuck-kernel unstick.

    A kernel that stops answering execute probes on EVERY connection --
    fresh cloned ones included, websocket reconnected, status stale at
    'idle' (live-observed; the server-side view showed a restored, live
    connection) -- is blocked inside a handler, waiting on a browser
    reply that a dropped comm message means will never come.  No
    browser-side action can heal that; interrupt_request rides the
    kernel's CONTROL channel (its own thread), raises KeyboardInterrupt
    in the blocked handler, and the loop resumes.  Widget comms survive
    an interrupt (unlike a restart, which orphans every saved output
    into 'Error displaying widget').
    """

    try:
        with urllib.request.urlopen(
            f"{server.base_url}/api/sessions?token={server.token}", timeout=10
        ) as response:
            sessions = json.loads(response.read().decode("utf-8"))
        for session in sessions:
            kernel_id = (session.get("kernel") or {}).get("id")
            if not kernel_id:
                continue
            request = urllib.request.Request(
                f"{server.base_url}/api/kernels/{kernel_id}/interrupt?token={server.token}",
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10):
                pass
            sys.stderr.write(f"interrupted kernel {kernel_id}\n")
    except (urllib.error.URLError, OSError, ValueError) as err:
        sys.stderr.write(f"kernel interrupt failed (non-fatal): {err}\n")


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
    # working-tree gallery accumulates autosaved outputs (capture runs, live
    # Lab sessions); stale widget-view outputs open as "widget model not found"
    # console-error storms on a fresh kernel and poison the gallery test.
    gallery = json.loads(
        (REPO / "notebooks" / "notation_gallery.ipynb").read_text(encoding="utf-8")
    )
    for cell in gallery.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    (root / "notation_gallery.ipynb").write_text(json.dumps(gallery, indent=1), encoding="utf-8")
    # NB03 VERBATIM (maintainer QA: the app/inspector findings were all
    # reported from live tutorial sessions, so the tier drives the REAL
    # tutorial, not a paraphrase).  Served from a notebooks/ subdir
    # with examples/ beside it so the notebook's relative
    # "../examples/deepscout" resolves exactly like in the repo; outputs
    # stripped for the same autosave-poisoning reasons as the gallery.
    tutorial = json.loads(
        (REPO / "notebooks" / "03_views_for_review.ipynb").read_text(encoding="utf-8")
    )
    for cell in tutorial.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    (root / "notebooks").mkdir()
    (root / "notebooks" / "03_views_for_review.ipynb").write_text(
        json.dumps(tutorial, indent=1), encoding="utf-8"
    )
    (root / "examples").mkdir()
    # the app scenario loads the program; the dashboard scenario bakes
    # the real crossed mission catalog from the same workspace
    shutil.copytree(REPO / "examples" / "deepscout", root / "examples" / "deepscout")
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
    # news prompt OFF: the announcements plugin emits 'Would you like to
    # get notified about official Jupyter news?' whenever the notification
    # setting `fetchNews` composites to its default 'none' (= never asked)
    # -- on CI's pristine runners that toast overlays the bottom-right
    # viewport mid-test (all four failure screenshots of the 770117c run
    # wear it; dev machines answered it once, long ago, in ~/.jupyter).
    # 'false' is the supported never-fetch answer, settled at the config
    # level so no dismissal race exists; checkForUpdates off too -- the
    # update toast rides the same pipe and depends on network truth.
    notification = settings / "@jupyterlab" / "apputils-extension"
    notification.mkdir(parents=True)
    (notification / "notification.jupyterlab-settings").write_text(
        json.dumps({"fetchNews": "false", "checkForUpdates": False}), encoding="utf-8"
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
                # NEVER rate-limit iopub: jupyter-server's limiter silently
                # DROPS comm_msg (widget state updates + custom messages;
                # status/comm_open are exempt) whenever a burst outruns the
                # window, and the widget protocol has no retransmit -- one
                # dropped inlet-value update wedges an ipyelk pipe forever
                # (the ad27a8b gallery CI failure: 20 bars frozen at exactly
                # the text-sizer stage, kernel idle, zero errors; mechanism
                # proven by dropping 60% of comm_msg locally, which froze
                # the same 20-at-37.5%-plus-one-at-87.5% signature).  A
                # run-all creating two dozen diagram widgets is exactly such
                # a burst on a slow 2-core runner (the limiter is rate-based,
                # and a starved server drains its zmq backlog in bursts).
                # The limiter protects human browsers from runaway stream
                # output; this tier wants correctness -- unlimited buffering
                # of a finite storm costs a few MB and zero drops.
                "--ZMQChannelsWebsocketConnection.limit_rate=False",
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


def scroll_into_view(locator: Any, *, attempts: int = 3, timeout_ms: int = 10_000) -> None:
    """Stale-safe ``scroll_into_view_if_needed`` for re-rendering widgets.

    Playwright resolves the locator to ONE element, then waits for it to
    be stable -- but a widget re-render (a re-bake swapping an svg, a
    layout pass moving a card) detaches that element mid-wait and the
    call dies with 'Element is not attached to the DOM ... element is
    not stable' (the 770117c CI dashboard failure).  Locators re-resolve
    on every call, so a bounded retry rides out the re-render; any other
    error (or a persistently detaching element) still raises.
    """

    for attempt in range(1, attempts + 1):
        try:
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
            return
        except Exception as err:
            stale = "not attached" in str(err) or "not stable" in str(err)
            if attempt == attempts or not stale:
                raise
            sys.stderr.write(
                f"scroll_into_view: attempt {attempt} crossed a re-render "
                f"({str(err).splitlines()[0]}); re-resolving and retrying\n"
            )
            time.sleep(1.0)


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
    const empty = [...document.querySelectorAll('.sprotty svg')].filter(
        (svg) => svg.querySelectorAll('.elknode').length === 0).length;
    const loading = [...document.querySelectorAll('.jp-OutputArea-output')].filter(
        (el) => el.textContent.trim() === 'Loading widget...').length;
    const werrors = [...document.querySelectorAll('.jp-OutputArea-output')].filter(
        (el) => (el.textContent || '').includes('Error displaying widget')).length;
    const kernel = document.querySelector('.jp-Notebook-ExecutionIndicator')
        ?.getAttribute('data-status') || 'missing';
    return {rendered, busy, bars, fitted, elknodes, empty, loading, werrors, kernel};
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
        #: set when chromium reports the renderer gone (spontaneous crash
        #: or a watchdog kill); read by error messages, never re-raised
        #: here -- raising inside a playwright event listener poisons the
        #: dispatcher (observed: a Failed-in-listener plus a teardown ERROR)
        self.crashed: str | None = None
        page.on("console", lambda message: self.console.append(f"[{message.type}] {message.text}"))
        page.on("crash", self._on_crash)
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

    def _on_crash(self, _page: Page) -> None:
        self.crashed = "chromium renderer crashed (or was killed by the page watchdog)"
        sys.stderr.write(
            "page crash event: renderer gone (spontaneous chromium crash -- see "
            "the /dev/shm note on the browser fixture -- or a watchdog kill); "
            "pending calls on this page will now raise\n"
        )

    # -- bounded evaluate ------------------------------------------------------

    def evaluate(
        self,
        expression: str,
        arg: Any = None,
        *,
        timeout: float = 45.0,
        label: str = "page.evaluate",
    ) -> Any:
        """``page.evaluate`` with a REAL deadline.

        Playwright gives evaluate no timeout at all: on a renderer whose
        main thread is pegged (the proven wedge class) it parks the sync
        greenlet forever.  Every harness evaluate goes through here so a
        frozen page becomes a labeled failure within ``timeout`` seconds
        instead of an eternal park that only pytest-timeout's run-killing
        os._exit can end.
        """

        start = time.monotonic()
        if "evalnet" in _DISABLED:  # bisect knob: raw, timeout-less evaluate
            result = self.page.evaluate(expression, arg)
        else:
            with _page_watchdog(timeout, label):
                result = self.page.evaluate(expression, arg)
        elapsed = time.monotonic() - start
        if _TRACE and elapsed > 1.0:
            sys.stderr.write(f"trace: evaluate[{label}] took {elapsed:.2f}s\n")
        return result

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
            if self.evaluate(
                "() => !!(window.jupyterapp || window.jupyterlab)",
                timeout=30.0,
                label=f"open_notebook({name}): app handle poll",
            ):
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
        After three, the KERNEL is interrupted: probes that die on a
        reconnected socket AND on fresh cloned connections mean the
        kernel itself is blocked in a handler (see _interrupt_kernels).
        """

        deadline = time.monotonic() + timeout
        attempt = 0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            attempt += 1
            budget_ms = int(max(min(15.0, deadline - time.monotonic()), 3.0) * 1000)
            last = dict(
                self.evaluate(
                    _CHANNEL_PROBE_JS,
                    {"timeoutMs": budget_ms},
                    timeout=budget_ms / 1000 + 25.0,
                    label="execute-channel probe",
                )
            )
            if last.get("ok"):
                if attempt > 1:
                    sys.stderr.write(f"execute channel proven alive on probe attempt {attempt}\n")
                return
            sys.stderr.write(
                f"execute-channel probe {attempt} found a dead channel: {last.get('why')}\n"
            )
            if attempt == 2:
                sys.stderr.write("escalating: reconnecting the notebook kernel's websocket\n")
                self.evaluate(_RECONNECT_JS, timeout=30.0, label="kernel websocket reconnect")
            elif attempt == 3:
                sys.stderr.write("escalating: interrupting the stuck kernel\n")
                _interrupt_kernels(self.server)
            time.sleep(1.0)
        raise TimeoutError(
            f"the notebook kernel never answered an execute probe within {timeout}s "
            f"(even after a websocket reconnect and a kernel interrupt); last probe: {last}"
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
        before = list(self.evaluate(_PROMPTS_JS, timeout=30.0, label="run_all: prompts snapshot"))
        for _attempt in range(attempts):
            # fire-and-forget: commands.execute returns a promise that only
            # resolves when the WHOLE run finishes, and page.evaluate awaits
            # returned promises -- an unbounded hang if any cell stalls (the
            # CI eaten-clock signature). The bounded wait_settled below owns
            # the waiting and reports last-known state on timeout.
            self.evaluate(
                "() => { void (window.jupyterapp || window.jupyterlab)"
                ".commands.execute('notebook:run-all-cells'); return true; }",
                timeout=30.0,
                label="run_all: fire notebook:run-all-cells",
            )
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                prompts = list(
                    self.evaluate(_PROMPTS_JS, timeout=30.0, label="run_all: prompts poll")
                )
                if any("*" in prompt for prompt in prompts) or prompts != before:
                    return
                time.sleep(0.25)
        raise TimeoutError(f"run-all never started after {attempts} attempts; prompts: {before}")

    # -- settle polling ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return dict(self.evaluate(_SNAPSHOT_JS, timeout=45.0, label="settle snapshot"))

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

        The same flag recovers PARKED PIPES: progress bars frozen at the
        same widths (37.5%/87.5% -- the text-size/layout stages) with no
        busy cell and an idle kernel means one widget comm message was
        lost mid-burst and the layout pipeline will wait forever (the
        ad27a8b class; mechanism proven by dropping comm_msg locally.
        Reproduced isolated at 2bc9b4d BASE with every harness net
        disabled, so it is a product/timing marginality, not a harness
        artifact -- the kernel-side stale re-sync loop visibly churns in
        the server log without healing it).  A parked pipeline never
        heals by waiting either: after ~30s frozen, run-all is re-fired
        on the same bounded budget, rebuilding the widgets on fresh
        comms in-test instead of burning the wait and a whole rerun.
        """

        started = time.monotonic()
        deadline = started + timeout
        streak = 0
        state: dict[str, Any] = {}
        stalled_since: float | None = None
        parked_bars: Any = None
        parked_since: float | None = None
        refires = 0
        polls = 0
        snap_total = 0.0
        snap_max = 0.0
        # the loop's own deadline raises a labeled TimeoutError on a SLOW
        # page; the watchdog (deadline + slack) only fires on a WEDGED one
        # -- it also nets the caller-supplied predicate, whose locator
        # calls (count(), input_value()) can park forever on a frozen page
        with (
            contextlib.nullcontext()
            if "loopnet" in _DISABLED
            else _page_watchdog(timeout + 60.0, f"wait_until({label})")
        ):
            while time.monotonic() < deadline:
                snap_start = time.monotonic()
                state = self.snapshot()
                snap_elapsed = time.monotonic() - snap_start
                polls += 1
                snap_total += snap_elapsed
                snap_max = max(snap_max, snap_elapsed)
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
                    refire_why: str | None = None
                    if not (state["busy"] > 0 and state["kernel"] == "idle"):
                        stalled_since = None
                    elif stalled_since is None:
                        stalled_since = now
                    elif now - stalled_since >= 12.0:
                        refire_why = (
                            f"dead run ({state['busy']} cell(s) pinned at [*] with an idle kernel)"
                        )
                    if not (
                        state["busy"] == 0
                        and state["kernel"] == "idle"
                        and state["bars"]
                        and state["bars"] == parked_bars
                    ):
                        parked_bars = state["bars"] if state["busy"] == 0 else None
                        parked_since = now
                    elif parked_since is not None and now - parked_since >= 30.0:
                        refire_why = (
                            f"parked pipelines ({len(state['bars'])} progress bar(s) "
                            "frozen with an idle kernel: a widget comm message was "
                            "lost mid-burst)"
                        )
                    if refire_why and refires < 3:
                        refires += 1
                        stalled_since = None
                        parked_bars = None
                        parked_since = None
                        sys.stderr.write(
                            f"{label}: {refire_why}; re-firing run-all ({refires}/3)\n"
                        )
                        # cells pinned at [*] with an idle kernel (and a
                        # parked pipeline alike) mean messages are being
                        # swallowed somewhere between the notebook's SHARED
                        # kernel connection and the kernel (the post-restart
                        # session class; live-observed: a re-fire down the
                        # same dead pipe just pinned 16 cells at [*]) -- so
                        # escalate exactly like wait_execute_channel_ready
                        # and run_cell: reconnect the websocket, then re-fire
                        if refires >= 2:
                            # a refire that didn't take means the kernel
                            # itself may be blocked (see _interrupt_kernels)
                            sys.stderr.write(f"{label}: escalating -- interrupting the kernel\n")
                            _interrupt_kernels(self.server)
                            time.sleep(1.0)
                        self.evaluate(
                            _RECONNECT_JS,
                            timeout=30.0,
                            label=f"{label}: kernel websocket reconnect",
                        )
                        time.sleep(1.0)  # let the socket re-establish
                        self.evaluate(
                            "() => { void (window.jupyterapp || window.jupyterlab)"
                            ".commands.execute('notebook:run-all-cells'); return true; }",
                            timeout=30.0,
                            label=f"{label}: run-all re-fire",
                        )
                streak = streak + 1 if predicate(state) else 0
                if streak >= stable_polls:
                    if _TRACE:
                        sys.stderr.write(
                            f"trace: wait_until({label}): ok in "
                            f"{time.monotonic() - started:.1f}s, {polls} polls "
                            f"(snapshot avg {snap_total / polls:.2f}s, max {snap_max:.2f}s); "
                            f"state: {state}\n"
                        )
                    return state
                time.sleep(poll_s)
        raise TimeoutError(
            f"{label} not reached within {timeout}s ({polls} polls, snapshot "
            f"avg {snap_total / max(polls, 1):.2f}s, max {snap_max:.2f}s, "
            f"{refires} refires); last state: {state}"
        )

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

        state = self.evaluate(_CELL_STATE_JS, index, timeout=30.0, label=f"cell_output({index})")
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
                self.evaluate(
                    _DIRECT_EXECUTE_JS,
                    {"index": index, "timeoutMs": budget_ms},
                    timeout=budget_ms / 1000 + 25.0,
                    label=f"run_cell({index}): direct kernel execute",
                )
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
                self.evaluate(
                    _RECONNECT_JS,
                    timeout=30.0,
                    label=f"run_cell({index}): kernel websocket reconnect",
                )
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


def _lab_page(
    browser: Browser,
    lab_server: LabServer,
    request: pytest.FixtureRequest,
    viewport: dict[str, int],
) -> Any:
    """The shared body of every page fixture (lab, lab1080, labtall).

    Rerun-safe by construction: pytest-rerunfailures re-executes this
    function-scoped generator on every attempt, so each attempt gets a
    page PROVEN responsive before the test starts (a mid-test abort or a
    watchdog renderer-kill in the previous attempt cannot leak a poisoned
    page forward -- the one unresponsive-page retry recycles it), a
    per-test hang net around the body, and a server with no live kernel
    sessions left behind by teardown.
    """

    page: Page | None = None
    for attempt in (1, 2):
        if "probe" in _DISABLED:  # bisect knob: pre-patch fixture setup
            page = browser.new_page(viewport=viewport)
            break
        with _page_watchdog(60.0, "fixture setup: browser.new_page"):
            page = browser.new_page(viewport=viewport)
        try:
            # the page must PROVABLY answer an evaluate before the test
            # starts -- a wedged/half-dead renderer here would otherwise
            # spend the whole test budget masquerading as a slow app
            with _page_watchdog(30.0, "fixture setup: fresh-page responsiveness probe"):
                assert page.evaluate("() => 1 + 1") == 2
            break
        except Exception:
            with contextlib.suppress(Exception):
                page.close()
            if attempt == 2:
                raise
            sys.stderr.write("fresh page unresponsive; recycling it once\n")
    assert page is not None
    # repro aid for slow-CI timing bugs: LONGERON_BROWSER_CPU_THROTTLE=<rate>
    # slows the RENDERER by that factor via CDP (e.g. 8 approximates a
    # loaded 2-core runner on a fast dev machine). Off by default.
    throttle = float(os.environ.get("LONGERON_BROWSER_CPU_THROTTLE", "0") or 0)
    if throttle > 1:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
    driver = LabPage(page, lab_server)
    # the per-test net: ANY timeout-less playwright call a test makes
    # (raw evaluates, locator.count()) parks forever on a frozen page;
    # this net unsticks it minutes BEFORE pytest-timeout's thread method
    # would os._exit the whole run (700s), so the test fails, artifacts
    # save, teardown runs, and --reruns retries on a fresh page
    with (
        contextlib.nullcontext()
        if "testnet" in _DISABLED
        else _page_watchdog(600.0, f"test net: {request.node.name}")
    ):
        yield driver
    try:
        reports = request.node.stash.get(_PHASE_REPORTS, {})
        if any(report.failed for report in reports.values()):
            with _page_watchdog(90.0, "fixture teardown: failure artifacts"):
                driver.save_artifacts(ARTIFACTS, request.node.name)
    finally:
        with contextlib.suppress(Exception):  # a crashed page may refuse the close
            page.close()
        # hermetic teardown: every test (and every rerun attempt) hands the
        # next one a server with NO live kernel sessions -- see
        # _shutdown_sessions for the CI evidence this encodes
        _shutdown_sessions(lab_server)


@pytest.fixture()
def lab(browser: Browser, lab_server: LabServer, request: pytest.FixtureRequest) -> Any:
    """A fresh, probed-responsive page (and console/error collectors) per test."""

    yield from _lab_page(browser, lab_server, request, {"width": 1500, "height": 1100})
