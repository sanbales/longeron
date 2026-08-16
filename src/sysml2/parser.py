"""Parsing front-end: SysML v2 and KerML text -> ANTLR parse trees."""

from __future__ import annotations

from pathlib import Path

from antlr4 import CommonTokenStream, InputStream, Token
from antlr4.error.ErrorListener import ErrorListener

from ._gen.kerml.KerMLLexer import KerMLLexer
from ._gen.kerml.KerMLParser import KerMLParser
from ._gen.sysml.SysMLLexer import SysMLLexer
from ._gen.sysml.SysMLParser import SysMLParser
from .errors import ParseError, SyntaxIssue


class _CollectingErrorListener(ErrorListener):
    def __init__(self) -> None:
        self.issues: list[SyntaxIssue] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.issues.append(SyntaxIssue(line, column, msg))


class ParseResult:
    """A parse tree plus the machinery needed to interpret it."""

    def __init__(self, tree, parser, tokens, language: str, source_name: str):
        self.tree = tree
        self.parser = parser
        self.tokens = tokens
        self.language = language
        self.source_name = source_name

    def tree_text(self) -> str:
        """Lisp-style rendering of the parse tree (for debugging)."""

        return str(self.tree.toStringTree(recog=self.parser))


def _run_parser(text: str, lexer_cls, parser_cls, source_name: str, language: str,
                rule: str = "rootNamespace", require_eof: bool = True) -> ParseResult:
    listener = _CollectingErrorListener()
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
            listener.issues.append(SyntaxIssue(
                current.line, current.column,
                f"unexpected trailing input starting at {current.text!r}"))
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


def parse_file(path, language: str | None = None) -> ParseResult:
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

    return _run_parser(text, SysMLLexer, SysMLParser, source_name, "sysml",
                       rule="ownedExpression")
