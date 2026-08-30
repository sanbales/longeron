# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
from typing import Tuple

import ipywidgets as W
import traitlets as T
from ipywidgets.widgets.trait_types import TypedTuple

from ..elements import (
    BaseElement,
    ElementIndex,
    HierarchicalElement,
    Node,
    Registry,
    elk_serialization,
)
from ..exceptions import NotFoundError


class MarkIndex(W.DOMWidget):
    elements: ElementIndex = T.Instance(ElementIndex, allow_none=True)
    context: Registry = T.Instance(Registry, kw={})

    _root: Node = None

    def to_id(self, element: BaseElement):
        return element.get_id()

    def from_id(self, key) -> HierarchicalElement:
        return self.elements.get(key)

    @property
    def root(self) -> Node:
        if self._root is None:
            self._update_root()
        return self._root

    @T.observe("elements")
    def _update_root(self, change=None):
        self._root = None
        if self.elements:
            self._root = self.elements.root()


class MarkElementWidget(W.DOMWidget):
    value: Node = T.Instance(Node, allow_none=True).tag(sync=True, **elk_serialization)
    index: MarkIndex = T.Instance(MarkIndex, kw={}).tag(
        sync=True, **W.widget_serialization
    )
    flow: Tuple[str] = TypedTuple(T.Unicode(), kw={}).tag(sync=True)

    def persist(self):
        if self.index.elements is None:
            self.build_index()
        else:
            try:
                self.index.elements.update(ElementIndex.from_els(self.value))
            except NotFoundError:
                # LOCAL PATCH 14 (sysml2-experiments): an endpoint whose VALUE
                # was replaced wholesale (longeron's per-node collapse rebuilds
                # the whole source tree; a cancelled run's late browser reply
                # can also land a different tree generation than the one the
                # pipeline's shared index was built from) must not crash the
                # pipeline over the stale index -- rebuild it from the current
                # value instead, exactly what first use does.
                self.build_index()
        return self

    def build_index(self) -> MarkIndex:
        if self.value is None:
            index = ElementIndex()
        else:
            with self.index.context:
                index = ElementIndex.from_els(self.value)
        self.index.elements = index
        return self.index

    def _repr_mimebundle_(self, **kwargs):
        from IPython.display import JSON, display

        display(JSON(self.value.dict()))
