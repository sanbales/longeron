"""Deprecated alias: :mod:`longeron.explorer` moved to :mod:`longeron.widgets.explorer`."""

from __future__ import annotations

import warnings
from typing import Any

from .widgets import explorer as _home
from .widgets.explorer import *  # noqa: F403  # the home module re-exported

warnings.warn(
    "longeron.explorer moved to longeron.widgets.explorer; "
    "this alias will be removed in a future release",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_home.__all__)


def __getattr__(name: str) -> Any:
    return getattr(_home, name)
