#!/usr/bin/env python
"""Execute and/or strip the notebooks in notebooks/.

Committed notebooks are output-free: running this script executes every
notebook (validation) and then writes them back *stripped* of outputs,
execution counts, and volatile metadata, so reruns never produce diffs.

    python scripts/run_notebooks.py               # execute + strip
    python scripts/run_notebooks.py --strip-only  # just normalize (fast)
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent

#: notebook-level metadata keys that churn without carrying information
_VOLATILE_NOTEBOOK_METADATA = ("widgets", "language_info")


def strip(notebook) -> None:
    """Remove outputs, execution counts, and volatile metadata in place."""

    for key in _VOLATILE_NOTEBOOK_METADATA:
        notebook.metadata.pop(key, None)
    kernelspec = notebook.metadata.get("kernelspec")
    if kernelspec is not None:  # normalize the display name churn
        kernelspec["display_name"] = "Python 3"
        kernelspec["name"] = "python3"
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        cell.outputs = []
        cell.execution_count = None
        cell.metadata.pop("execution", None)
        cell.metadata.pop("collapsed", None)
        cell.metadata.pop("scrolled", None)


def process(path: Path, execute: bool) -> None:
    notebook = nbformat.read(path, as_version=4)
    if execute:
        from nbclient import NotebookClient

        client = NotebookClient(
            notebook, timeout=600, kernel_name="python3",
            resources={"metadata": {"path": str(ROOT / "notebooks")}})
        client.execute()
        print(f"executed {path.name}")
    strip(notebook)
    nbformat.write(notebook, path)


def main() -> int:
    execute = "--strip-only" not in sys.argv
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    if not notebooks:
        print("no notebooks found")
        return 1
    for path in notebooks:
        process(path, execute)
    if not execute:
        print(f"stripped {len(notebooks)} notebook(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
