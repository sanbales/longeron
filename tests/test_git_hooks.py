"""The pre-commit hook auto-strips staged notebook state, index-only."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "git-hooks" / "pre-commit"

#: inherit the real environment (the pixi env provides git on every
#: platform) but isolate git config so the hook behaves identically on
#: any machine; os.devnull keeps it Windows-portable
_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def _run_notebooks_module():
    spec = importlib.util.spec_from_file_location(
        "run_notebooks", ROOT / "scripts" / "run_notebooks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dirty_notebook_text() -> str:
    """A notebook carrying every kind of state the hook must strip."""

    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3 (ipykernel)",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.13.1"}
    nb.metadata["widgets"] = {"state": {"abc": {}}}
    nb.cells.append(nbformat.v4.new_markdown_cell("héllo — unicode"))
    cell = nbformat.v4.new_code_cell("print('hi')")
    cell.execution_count = 3
    cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="hi\n")]
    cell.metadata["execution"] = {"iopub.execute_input": "2026-01-01T00:00:00Z"}
    cell.metadata["collapsed"] = False
    nb.cells.append(cell)
    return nbformat.writes(nb) + "\n"


def git(repo: Path, *args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        text=True,
        check=kwargs.pop("check", True),
        **kwargs,
    )


def run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)], cwd=repo, env=_ENV, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def stage(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "--", rel)


def staged(repo: Path, rel: str) -> bytes:
    return subprocess.run(
        ["git", "show", f":{rel}"], cwd=repo, env=_ENV, capture_output=True, check=True
    ).stdout


def test_strips_tutorial_notebook_index_only(repo):
    original = dirty_notebook_text()
    stage(repo, "notebooks/tour.ipynb", original)

    result = run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert "stripped" in result.stdout
    # working tree keeps the outputs the user was looking at
    assert (repo / "notebooks/tour.ipynb").read_text(encoding="utf-8") == original
    committed = json.loads(staged(repo, "notebooks/tour.ipynb"))
    for cell in committed["cells"]:
        if cell["cell_type"] != "code":
            continue
        assert cell["outputs"] == []
        assert cell["execution_count"] is None
        assert "execution" not in cell["metadata"]
        assert "collapsed" not in cell["metadata"]
    assert "widgets" not in committed["metadata"]
    assert "language_info" not in committed["metadata"]
    assert committed["metadata"]["kernelspec"]["display_name"] == "Python 3"


def test_hook_strip_matches_run_notebooks_strip(repo):
    """Hook-stripped commits are byte-identical to script-stripped ones."""

    original = dirty_notebook_text()
    stage(repo, "notebooks/tour.ipynb", original)
    run_hook(repo)

    notebook = nbformat.reads(original, as_version=4)
    _run_notebooks_module().strip(notebook)
    expected = nbformat.writes(notebook)
    if not expected.endswith("\n"):
        expected += "\n"
    assert staged(repo, "notebooks/tour.ipynb") == expected.encode("utf-8")


def test_vendored_notebook_keeps_upstream_metadata(repo):
    stage(repo, "vendor/example/demo.ipynb", dirty_notebook_text())

    result = run_hook(repo)

    assert result.returncode == 0, result.stderr
    committed = json.loads(staged(repo, "vendor/example/demo.ipynb"))
    code = [c for c in committed["cells"] if c["cell_type"] == "code"]
    assert all(c["outputs"] == [] for c in code)
    assert all(c["execution_count"] is None for c in code)
    assert "widgets" not in committed["metadata"]
    # upstream-pristine bits survive
    assert committed["metadata"]["language_info"]["name"] == "python"
    assert committed["metadata"]["kernelspec"]["display_name"] == "Python 3 (ipykernel)"
    assert code[0]["metadata"]["collapsed"] is False


def test_clean_notebook_left_byte_identical(repo):
    notebook = nbformat.reads(dirty_notebook_text(), as_version=4)
    _run_notebooks_module().strip(notebook)
    clean = nbformat.writes(notebook) + "\n"
    stage(repo, "notebooks/clean.ipynb", clean)
    before = git(repo, "ls-files", "--stage").stdout

    result = run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert "stripped" not in result.stdout
    assert git(repo, "ls-files", "--stage").stdout == before


def test_refuses_oversized_blob(repo):
    stage(repo, "big.bin", "x" * (5 * 1024 * 1024 + 1))

    result = run_hook(repo)

    assert result.returncode == 1
    assert "REFUSING" in result.stderr
    assert "big.bin" in result.stderr


def test_refuses_unparseable_notebook(repo):
    stage(repo, "notebooks/broken.ipynb", "{not json")

    result = run_hook(repo)

    assert result.returncode == 1
    assert "could not parse/strip" in result.stderr


def test_symlinked_notebook_ignored(repo):
    (repo / "real.ipynb").write_text("{}", encoding="utf-8")
    (repo / "link.ipynb").symlink_to("real.ipynb")
    git(repo, "add", "--", "link.ipynb")

    result = run_hook(repo)

    assert result.returncode == 0, result.stderr  # symlinks pass through


# --- pre-push: the gate hook must still upload LFS objects -----------------

PRE_PUSH = ROOT / "scripts" / "git-hooks" / "pre-push"


def _pre_push(tmp_path: Path, stdin: str, *, lfs: bool) -> subprocess.CompletedProcess[str]:
    """Run the hook ungated with a stub ``git-lfs`` on PATH (or none at all).

    The stub prints its arguments and echoes its stdin, so the test sees
    exactly what ``git lfs pre-push`` would have received. PATH holds ONLY
    the temp bin dir: the hook's other needs (``bash``, ``git``, ``cat``)
    are linked into it, so a real ``git-lfs`` on the machine (GitHub's
    runners ship one in /usr/bin) can neither answer for the stub nor
    contact the fake remote.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # the git binary itself, not a PATH wrapper around it (a wrapper's own
    # helpers would be missing from the isolated PATH)
    exec_path = subprocess.check_output(["git", "--exec-path"], text=True).strip()
    (bin_dir / "git").symlink_to(Path(exec_path) / "git")
    for tool in ("bash", "cat"):
        real = shutil.which(tool)
        assert real, tool
        (bin_dir / tool).symlink_to(real)
    if lfs:
        stub = bin_dir / "git-lfs"
        stub.write_text('#!/bin/sh\necho "stub git-lfs $*"\ncat\n')
        stub.chmod(0o755)
    env = {**_ENV, "LONGERON_PUSH_UNGATED": "1", "PATH": str(bin_dir)}
    return subprocess.run(
        ["bash", str(PRE_PUSH), "origin", "git@example.invalid:x/y.git"],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook")
def test_pre_push_forwards_the_refs_to_git_lfs(tmp_path):
    """The refs git hands the hook on stdin reach ``git lfs pre-push`` unchanged."""
    refs = "refs/heads/main 0123 refs/heads/main 4567\n"
    done = _pre_push(tmp_path, refs, lfs=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"stub git-lfs pre-push origin git@example.invalid:x/y.git\n{refs}"


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook")
def test_pre_push_with_nothing_to_push_skips_lfs(tmp_path):
    done = _pre_push(tmp_path, "", lfs=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""


@pytest.mark.skipif(sys.platform == "win32", reason="bash hook")
def test_pre_push_refuses_to_run_without_git_lfs(tmp_path):
    done = _pre_push(tmp_path, "refs/heads/main 0123 refs/heads/main 4567\n", lfs=False)
    assert done.returncode == 2
    assert "git-lfs is not installed" in done.stderr
