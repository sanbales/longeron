"""The tutorial notebooks must execute cleanly against the current code."""

from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))


def test_notebooks_exist():
    assert len(NOTEBOOKS) >= 5


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebook_executes(path):
    notebook = nbformat.read(path, as_version=4)
    client = nbclient.NotebookClient(
        notebook, timeout=600, kernel_name="python3",
        resources={"metadata": {"path": str(ROOT / "notebooks")}})
    client.execute()  # raises CellExecutionError on any failing cell


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebook_committed_without_outputs(path):
    """Committed notebooks are output-free so reruns never produce diffs.

    Checks the COMMITTED blob, not the working tree: outputs may live in
    the working copy while you explore (the pre-commit hook strips the
    staged blob at commit time -- see scripts/git-hooks/pre-commit).
    """

    import subprocess

    blob = subprocess.run(
        ["git", "show", f"HEAD:notebooks/{path.name}"],
        capture_output=True, cwd=ROOT)
    if blob.returncode != 0:  # not committed yet: fall back to the file
        notebook = nbformat.read(path, as_version=4)
    else:
        notebook = nbformat.reads(blob.stdout.decode("utf-8"), as_version=4)
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type != "code":
            continue
        assert cell.get("outputs") == [], \
            f"{path.name} cell {index} has committed outputs " \
            f"(run scripts/run_notebooks.py --strip-only)"
        assert cell.get("execution_count") is None
        assert "execution" not in cell.get("metadata", {})
    assert "widgets" not in notebook.metadata
    assert "language_info" not in notebook.metadata
