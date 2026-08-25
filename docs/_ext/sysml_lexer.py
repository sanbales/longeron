"""A minimal Pygments lexer for SysML v2 textual notation.

Registered by ``conf.py`` so fenced ``sysml`` code blocks (used in the
tutorial notebooks and the README) highlight instead of tripping
``misc.highlighting_failure`` under ``sphinx-build -W``.
"""

from typing import ClassVar

from pygments.lexer import RegexLexer, words
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Whitespace,
)

_KEYWORDS = (
    "about", "abstract", "accept", "action", "actor", "after", "alias",
    "all", "allocate", "allocation", "analysis", "and", "as", "assert",
    "assign", "assume", "at", "attribute", "bind", "by", "calc", "case",
    "comment", "concern", "connect", "connection", "constraint", "decide",
    "def", "default", "defined", "dependency", "derived", "do", "doc",
    "else", "end", "entry", "enum", "event", "exhibit", "exit", "expose",
    "filter", "first", "flow", "for", "fork", "frame", "from", "hastype",
    "if", "implies", "import", "in", "include", "individual", "inout",
    "interface", "istype", "item", "join", "language", "library", "loop",
    "merge", "message", "meta", "metadata", "nonunique", "not", "objective",
    "occurrence", "of", "or", "ordered", "out", "package", "parallel",
    "part", "perform", "port", "private", "protected", "public", "readonly",
    "redefines", "ref", "references", "rendering", "require", "requirement",
    "return", "satisfy", "send", "snapshot", "specializes", "stakeholder",
    "standard", "state", "subject", "subsets", "succession", "then",
    "timeslice", "to", "transition", "until", "use", "variant", "variation",
    "verification", "verify", "via", "view", "viewpoint", "when", "while",
    "xor",
)  # fmt: skip


class SysMLLexer(RegexLexer):
    """Lex enough SysML v2 to color keywords, literals, and comments."""

    name = "SysML v2"
    aliases: ClassVar = ["sysml", "kerml"]
    filenames: ClassVar = ["*.sysml", "*.kerml"]

    tokens: ClassVar = {
        "root": [
            (r"\s+", Whitespace),
            (r"//\*", Comment.Multiline, "note"),
            (r"/\*", Comment.Multiline, "note"),
            (r"//[^\n]*", Comment.Single),
            (r'"', String, "string"),
            (r"'[^']*'", Name),  # quoted (unrestricted) names
            (words(("true", "false", "null"), suffix=r"\b"), Keyword.Constant),
            (words(_KEYWORDS, suffix=r"\b"), Keyword),
            (r"[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?", Number.Float),
            (r"[0-9]+", Number.Integer),
            (r"::|\.\.|->|=>|:=|:>>|:>|\?\?|[=<>!+\-*/%^?@#&|~]", Operator),
            (r"[{}()\[\];,.:]", Punctuation),
            (r"[A-Za-z_][A-Za-z0-9_]*", Name),
        ],
        "note": [
            (r"[^*]+", Comment.Multiline),
            (r"\*/", Comment.Multiline, "#pop"),
            (r"\*", Comment.Multiline),
        ],
        "string": [
            (r'[^"\\]+', String),
            (r"\\.", String.Escape),
            (r'"', String, "#pop"),
        ],
    }
