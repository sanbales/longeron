"""Parsing front-end: SysML v2 and KerML text -> ANTLR parse trees."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from antlr4 import CommonTokenStream, InputStream, Token
from antlr4.error.ErrorListener import ErrorListener

from ._gen.kerml.KerMLLexer import KerMLLexer
from ._gen.kerml.KerMLParser import KerMLParser
from ._gen.sysml.SysMLLexer import SysMLLexer
from ._gen.sysml.SysMLParser import SysMLParser
from .errors import ParseError, SyntaxIssue

#: the two grammars this front-end parses (inferred from the file suffix
#: by :func:`parse_file` when not given explicitly)
Language = Literal["sysml", "kerml"]

# ANTLR's "mismatched input X expecting {...}" / "extraneous input X
# expecting {...}" messages dump the full expected-token set -- 40+ token
# soup for expression positions.  _humanize() rewrites them compactly; the
# verbatim text stays on SyntaxIssue.raw_message.
_EXPECTING = re.compile(
    r"^(?:mismatched|extraneous) input (?P<found>.+?) expecting (?P<expected>\{.*\}|\S+)$"
)

#: lexer token kinds that mark a set as "an expression can start here"
_EXPRESSION_KINDS = {"DECIMAL_VALUE", "STRING_VALUE"}


def _describe_expected(expected: str) -> str:
    if not expected.startswith("{"):
        return f"expected {expected}"
    items = [item.strip() for item in expected.strip("{}").split(", ") if item.strip()]
    if len(items) <= 4:
        return "expected " + " or ".join(items)
    kinds = {item for item in items if not item.startswith("'")}
    if _EXPRESSION_KINDS <= kinds:
        return "expected an expression"
    head = ", ".join(items[:3])
    return f"expected {head} \u2026 ({len(items) - 3} more)"


def _humanize(message: str) -> str:
    """Compact ANTLR error verbiage into a one-line human message."""

    match = _EXPECTING.match(message)
    if match is None:
        return message
    found = match.group("found")
    if found in ("'<EOF>'", "<EOF>"):
        found = "end of input"
    return f"unexpected {found} ({_describe_expected(match.group('expected'))})"


class _CollectingErrorListener(ErrorListener):
    def __init__(self, text: str = "") -> None:
        self.issues: list[SyntaxIssue] = []
        self._lines = text.splitlines()

    def _source_line(self, line: int) -> str | None:
        if 0 < line <= len(self._lines):
            return self._lines[line - 1]
        return None

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.issues.append(
            SyntaxIssue(
                line,
                column,
                _humanize(msg),
                raw_message=msg,
                source_line=self._source_line(line),
            )
        )


class ParseResult:
    """A parse tree plus the machinery needed to interpret it."""

    def __init__(self, tree, parser, tokens, language: Language, source_name: str):
        self.tree = tree
        self.parser = parser
        self.tokens = tokens
        self.language = language
        self.source_name = source_name

    def tree_text(self) -> str:
        """Lisp-style rendering of the parse tree (for debugging)."""

        return str(self.tree.toStringTree(recog=self.parser))


def _run_parser(
    text: str,
    lexer_cls,
    parser_cls,
    source_name: str,
    language: Language,
    rule: str = "rootNamespace",
    require_eof: bool = True,
) -> ParseResult:
    listener = _CollectingErrorListener(text)
    lexer = lexer_cls(InputStream(text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(listener)
    tokens = CommonTokenStream(lexer)
    parser = parser_cls(tokens)
    parser.removeErrorListeners()
    parser.addErrorListener(listener)
    tree = getattr(parser, rule)()
    if require_eof:
        current = parser.getCurrentToken()
        if current is not None and current.type != Token.EOF:
            listener.issues.append(
                SyntaxIssue(
                    current.line,
                    current.column,
                    f"unexpected trailing input starting at {current.text!r}",
                    source_line=listener._source_line(current.line),
                )
            )
    if listener.issues:
        raise ParseError(listener.issues, source_name)
    return ParseResult(tree, parser, tokens, language, source_name)


def parse_sysml_text(text: str, source_name: str = "<text>") -> ParseResult:
    """Parse SysML v2 textual notation; raises :class:`ParseError` on errors."""

    return _run_parser(text, SysMLLexer, SysMLParser, source_name, "sysml")


def parse_kerml_text(text: str, source_name: str = "<text>") -> ParseResult:
    """Parse KerML textual notation; raises :class:`ParseError` on errors.

    KerML support is syntactic: you get a validated parse tree, not a model.
    """

    return _run_parser(text, KerMLLexer, KerMLParser, source_name, "kerml")


def parse_file(path: str | Path, language: Language | None = None) -> ParseResult:
    """Parse a ``.sysml`` or ``.kerml`` file (language inferred from suffix)."""

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if language is None:
        language = "kerml" if path.suffix.lower() == ".kerml" else "sysml"
    if language == "kerml":
        return parse_kerml_text(text, str(path))
    return parse_sysml_text(text, str(path))


def parse_expression_text(text: str, source_name: str = "<expr>") -> ParseResult:
    """Parse a single SysML owned-expression snippet, e.g. ``"2 + x * 3"``."""

    return _run_parser(text, SysMLLexer, SysMLParser, source_name, "sysml", rule="ownedExpression")
