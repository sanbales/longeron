# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
"""LOCAL PATCH 14 (sysml2-experiments): a wholesale-replaced endpoint value
must not crash ``persist()`` over the pipeline's stale shared index.

Longeron's per-node collapse rebuilds the whole diagram source tree (new
synthetic ids), and a cancelled run's late browser reply can likewise land
a different tree generation than the one the shared ``MarkIndex`` was built
from.  ``MarkElementWidget.persist`` used to raise ``NotFoundError`` from
``ElementIndex.update`` in that case -- erroring the pipeline forever; it
now rebuilds the index from the current value, exactly what first use does.
"""

from ipyelk.elements import Label, Node
from ipyelk.pipes import MarkElementWidget


def _tree(prefix: str) -> Node:
    return Node(
        id=f"{prefix}-root",
        children=[Node(id=f"{prefix}-child", labels=[Label(id=f"{prefix}-label", text="x")])],
    )


def test_persist_updates_in_place_for_the_same_generation() -> None:
    mark = MarkElementWidget(value=_tree("a"))
    mark.persist()  # builds the index
    assert mark.index.elements is not None
    before = mark.index.elements
    mark.persist()  # same ids: the in-place update path
    assert mark.index.elements is before


def test_persist_self_heals_after_a_wholesale_value_swap() -> None:
    mark = MarkElementWidget(value=_tree("a"))
    mark.persist()
    mark.value = _tree("b")  # a rebuilt tree: entirely new ids
    mark.persist()  # used to raise NotFoundError('a-... not in index')
    assert mark.index.elements is not None
    assert mark.index.elements.get("b-child").id == "b-child"
