.PHONY: check test lint format typecheck parsers demo docs

# Equivalent pixi tasks exist (pixi run check|test|parsers|...): same
# commands in a locked env, with antlr+JDK provided by conda-forge.

VENV ?= .venv/bin

check: lint typecheck test test-vendor  ## lint + mypy + tests

test:
	$(VENV)/pytest -q

test-vendor:  ## vendored ipyelk test suite (incl. ported F1-F6 fixes)
	$(VENV)/pytest -c pyproject.toml -q vendor/ipyelk/tests

coverage:
	$(VENV)/pytest -q --cov=longeron --cov-report=term-missing:skip-covered

lint:
	$(VENV)/ruff format --check src tests examples scripts notebooks docs
	$(VENV)/ruff check src tests examples scripts notebooks docs

format:
	$(VENV)/ruff format src tests examples scripts notebooks docs
	$(VENV)/ruff check --fix src tests examples scripts notebooks docs

typecheck:
	$(VENV)/mypy

parsers:  ## regenerate ANTLR parsers from grammars/*.g4 (needs Java)
	$(VENV)/python scripts/generate_parsers.py

stdlib:  ## rebuild the prebuilt standard-library JSON
	$(VENV)/python scripts/vendor_stdlib.py --prebuilt-only

demo:
	$(VENV)/python examples/demo.py

docs:  ## build the documentation site (needs the [docs] extra; pixi: `pixi run docs`)
	$(VENV)/sphinx-build -W -b html docs build/docs

hooks:  ## enable the repo git hooks (auto-strips staged notebook outputs; blocks >5MB blobs)
	git config core.hooksPath scripts/git-hooks
