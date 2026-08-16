"""Exception types for the sysml2 package."""

from __future__ import annotations

from dataclasses import dataclass


class SysMLError(Exception):
    """Base class for all sysml2 errors."""


@dataclass
class SyntaxIssue:
    """A single syntax error reported by the ANTLR parser."""

    line: int
    column: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.line}:{self.column}: {self.message}"


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
