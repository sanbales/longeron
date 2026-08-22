"""Exception types for the longeron package."""

from __future__ import annotations

from dataclasses import dataclass


class SysMLError(Exception):
    """Base class for all longeron errors."""


class MissingExtraError(SysMLError, ImportError):
    """An optional dependency of this feature is not installed.

    Every optional-import guard in the package raises this one type -- it
    is both a :class:`SysMLError` and an :class:`ImportError`, so handlers
    written against either keep working -- with a uniform message carrying
    the exact install command (``pip install "longeron[extra]"``).
    """

    def __init__(
        self,
        feature: str,
        package: str,
        extra: str | None = None,
        *,
        command: str | None = None,
    ):
        #: what was being attempted, e.g. ``"the replay widget"``
        self.feature = feature
        #: the missing distribution/module, e.g. ``"anywidget"``
        self.package = package
        #: the pip extra that provides it (``None`` for non-extra installs)
        self.extra = extra
        #: the exact command that fixes it
        self.command = command or f'pip install "longeron[{extra}]"'
        super().__init__(f"{feature} needs {package}; install it with: {self.command}")


@dataclass
class SyntaxIssue:
    """A single syntax error reported by the ANTLR parser.

    ``message`` is the humanized text shown to users; ``raw_message``
    preserves the verbatim ANTLR wording (expected-token sets and all) for
    anyone debugging the grammar.  ``source_line`` carries the offending
    line of source when the parser had it in hand.
    """

    line: int
    column: int
    message: str
    raw_message: str | None = None
    source_line: str | None = None

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
        lines: list[str] = []
        for issue in issues:
            lines.append(f"  {issue}")
            # echo the offending line with a caret under the column
            excerpt = issue.source_line
            if excerpt is not None:
                excerpt = excerpt.replace("\t", " ")  # keep the caret aligned
            if excerpt and len(excerpt) <= 120 and 0 <= issue.column <= len(excerpt):
                lines.append(f"    | {excerpt}")
                lines.append(f"    | {' ' * issue.column}^")
        listing = "\n".join(lines)
        super().__init__(f"{len(issues)} syntax error(s) in {source_name}:\n{listing}")


class BuildError(SysMLError):
    """Raised when a parse tree cannot be transformed into a model."""


class ResolutionError(SysMLError):
    """Raised when a qualified name cannot be resolved."""


class EvaluationError(SysMLError):
    """Raised when an expression cannot be evaluated."""


class ExecutionError(SysMLError):
    """Raised when an action or state machine cannot be executed."""
