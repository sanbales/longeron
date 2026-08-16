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
def test_notebook_committed_with_outputs(path):
    """Committed notebooks should be readable on GitHub (outputs included)."""

    notebook = nbformat.read(path, as_version=4)
    code_cells = [c for c in notebook.cells if c.cell_type == "code"]
    assert code_cells
    executed = [c for c in code_cells if c.get("outputs") or
                c.get("execution_count")]
    assert executed, f"{path.name} has no executed cells"
