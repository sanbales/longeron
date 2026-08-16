"""sysml2 -- define, export, and execute SysML v2 models in Python.

Powered by ANTLR4 grammars for SysML v2 and KerML.

Quick start::

    import sysml2

    model = sysml2.loads('''
        package Demo {
            part def Vehicle {
                attribute mass : Real = 1200.0;
            }
            calc def Double { in x : Real; return : Real = 2 * x; }
        }
    ''')

    print(sysml2.to_sysml(model))          # textual export
    print(sysml2.to_json(model))           # JSON export

    interp = sysml2.Interpreter(model)
    car = interp.instantiate("Demo::Vehicle")
    print(car.slots["mass"])               # 1200.0
    print(interp.call("Demo::Double", 21)) # 42
"""

from . import ast, model
from .builder import build_model, loads, parse_expression
from .errors import (
                     BuildError,
                     EvaluationError,
                     ExecutionError,
                     ParseError,
                     ResolutionError,
                     SyntaxIssue,
                     SysMLError,
)
from .export import save, to_dict, to_json, to_sysml
from .importer import from_dict, from_json
from .interpreter import (
                     ActionResult,
                     ConstraintResult,
                     EnumValue,
                     Instance,
                     Interpreter,
                     RequirementResult,
                     SentEvent,
                     SimulationResult,
                     TransitionFired,
)
from .kerml import to_kerml
from .model import *
from .parser import (
                     ParseResult,
                     parse_expression_text,
                     parse_file,
                     parse_kerml_text,
                     parse_sysml_text,
)
from .validation import Diagnostic, validate
from .workspace import cache_dir, clear_cache, load, load_dir, load_file, load_many, merge_models

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # parsing
    "parse_sysml_text", "parse_kerml_text", "parse_file",
    "parse_expression_text", "ParseResult",
    # building / importing
    "build_model", "loads", "load", "parse_expression",
    "from_dict", "from_json",
    "load_dir", "load_file", "load_many", "merge_models",
    "cache_dir", "clear_cache",
    # exporting
    "to_dict", "to_json", "to_sysml", "to_kerml", "save",
    # validating
    "validate", "Diagnostic",
    # executing
    "Interpreter", "Instance", "EnumValue", "ConstraintResult",
    "RequirementResult", "ActionResult", "SimulationResult", "SentEvent",
    "TransitionFired",
    # errors
    "SysMLError", "ParseError", "SyntaxIssue", "BuildError",
    "ResolutionError", "EvaluationError", "ExecutionError",
    # modules
    "ast", "model",
    *model.__all__,
]
