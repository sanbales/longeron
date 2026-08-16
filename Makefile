.PHONY: check test lint format typecheck parsers demo

VENV ?= .venv/bin

check: lint typecheck test  ## lint + mypy + tests

test:
	$(VENV)/pytest -q

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
