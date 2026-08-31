"""Deprecated alias: :mod:`longeron.app` moved to :mod:`longeron.widgets.app`."""

from __future__ import annotations

import warnings
from typing import Any

from .widgets import app as _home
from .widgets.app import *  # noqa: F403  # the home module re-exported

warnings.warn(
    "longeron.app moved to longeron.widgets.app; this alias will be removed in a future release",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_home.__all__)


def __getattr__(name: str) -> Any:
    return getattr(_home, name)
