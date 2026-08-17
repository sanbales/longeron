.PHONY: check test lint format typecheck parsers demo

# Equivalent pixi tasks exist (pixi run check|test|parsers|...): same
# commands in a locked env, with antlr+JDK provided by conda-forge.

VENV ?= .venv/bin

check: lint typecheck test test-vendor  ## lint + mypy + tests

test:
	$(VENV)/pytest -q

test-vendor:  ## vendored ipyelk test suite (incl. ported F1-F6 fixes)
	$(VENV)/pytest -c pyproject.toml -q vendor/ipyelk/tests

coverage:
	$(VENV)/pytest -q --cov=sysml2 --cov-report=term-missing:skip-covered

lint:
	$(VENV)/ruff check src tests examples scripts

format:
	$(VENV)/ruff check --fix src tests examples scripts

typecheck:
	$(VENV)/mypy

parsers:  ## regenerate ANTLR parsers from grammars/*.g4 (needs Java)
	$(VENV)/python scripts/generate_parsers.py

stdlib:  ## rebuild the prebuilt standard-library pickle
	$(VENV)/python scripts/vendor_stdlib.py --prebuilt-only

demo:
	$(VENV)/python examples/demo.py

hooks:  ## enable the repo git hooks (auto-strips staged notebook outputs; blocks >5MB blobs)
	git config core.hooksPath scripts/git-hooks
