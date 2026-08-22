"""Exception types for the longeron package."""

from __future__ import annotations

from dataclasses import dataclass


class SysMLError(Exception):
    """Base class for all longeron errors."""


@dataclass
class SyntaxIssue:
    """A single syntax error reported by the ANTLR parser."""

    line: int
    column: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.line}:{self.column}: {self.message}"


@dataclass(frozen=True)
class SourceLocation:
    """Where a model element was declared: source (file path or label),
    1-based line, 1-based column.

    Stamped on elements by the builder (as a plain ``source_location``
    attribute) and carried by lint diagnostics.  Models rebuilt from JSON
    -- including model-cache hits -- carry no source locations.
    """

    source_name: str
    line: int
    column: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.source_name}:{self.line}:{self.column}"


class ParseError(SysMLError):
    """Raised when source text does not conform to the grammar."""

    def __init__(self, issues: list[SyntaxIssue], source_name: str = "<text>"):
        self.issues = issues
        self.source_name = source_name
        listing = "\n".join(f"  {issue}" for issue in issues)
        super().__init__(f"{len(issues)} syntax error(s) in {source_name}:\n{listing}")


class BuildError(SysMLError):
    """Raised when a parse tree cannot be transformed into a model."""


class ResolutionError(SysMLError):
    """Raised when a qualified name cannot be resolved."""


class EvaluationError(SysMLError):
    """Raised when an expression cannot be evaluated."""


class ExecutionError(SysMLError):
    """Raised when an action or state machine cannot be executed."""
