"""Deprecated alias: :mod:`longeron.inspector` moved to :mod:`longeron.widgets.inspector`."""

from __future__ import annotations

import warnings
from typing import Any

from .widgets import inspector as _home
from .widgets.inspector import *  # noqa: F403  # the home module re-exported

warnings.warn(
    "longeron.inspector moved to longeron.widgets.inspector; "
    "this alias will be removed in a future release",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_home.__all__)


def __getattr__(name: str) -> Any:
    return getattr(_home, name)
