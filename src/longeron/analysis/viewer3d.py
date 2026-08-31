"""Deprecated alias: :mod:`longeron.analysis.viewer3d` moved to :mod:`longeron.widgets.viewer3d`."""

from __future__ import annotations

import warnings
from typing import Any

from ..widgets import viewer3d as _home
from ..widgets.viewer3d import *  # noqa: F403  # the home module re-exported

warnings.warn(
    "longeron.analysis.viewer3d moved to longeron.widgets.viewer3d; "
    "this alias will be removed in a future release",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_home.__all__)


def __getattr__(name: str) -> Any:
    return getattr(_home, name)
