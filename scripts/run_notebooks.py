#!/usr/bin/env python
"""Execute every notebook in notebooks/ in place (refreshing outputs)."""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent.parent


def run(path: Path) -> None:
    notebook = nbformat.read(path, as_version=4)
    client = NotebookClient(notebook, timeout=600, kernel_name="python3",
                            resources={"metadata": {"path": str(ROOT)}})
    client.execute()
    nbformat.write(notebook, path)
    print(f"executed {path.name}")


def main() -> int:
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    if not notebooks:
        print("no notebooks found")
        return 1
    for path in notebooks:
        run(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
