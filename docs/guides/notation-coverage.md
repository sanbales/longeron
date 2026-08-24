# SysML v2 notation coverage

This page states which parts of the SysML v2 graphical notation longeron
draws, and which parts it does not. The reference is the OMG *Systems
Modeling Language v2.0* specification: its per-clause notation tables and
the clause 8.2.3 graphical-notation BNF. Every implemented glyph was
verified against rendered spec figures, and the
[notation gallery](../tutorials/11_notation_gallery.ipynb) shows each one
beside its spec figure with a self-verifying assertion. The browser test
tier re-checks the gallery on every CI run.

Legend: ✔ implemented per the spec figure · ◐ implemented with a stated
approximation · ✖ not implemented (reason given).

## Relationship edges and endpoints

| Notation | Spec form | Status |
|---|---|---|
| Subclassification `:>` (def→def) | solid line, hollow triangle | ✔ |
| Subsetting `:>` (usage→usage) | solid line, hollow triangle | ✔ |
| Feature typing `:` | solid line, hollow triangle, colon dots on the shaft | ✔ |
| Redefinition `:>>` | solid line, hollow triangle, bar tick on the shaft | ✔ |
| Reference subsetting `::>` | solid line, hollow triangle, 2×2 dots | ✔ |
| Composite membership | filled diamond at the whole end, end multiplicities | ✔ (`composition="defs"`) |
| Referential membership (`ref`) | hollow diamond at the whole end | ✔ |
| Owned membership edge | circle-plus at the owning end | ✔ (`membership="edges"`; nesting stays the default presentation) |
| Alias membership | hollow circle at the referencing end, alias name | ✔ |
| Connection (undirected) | solid line, no endpoint | ✔ |
| Connection with direction | open-V head at the target end | ✔ (direction comes from `sourceEnd`/`targetEnd` def-end names, the spec's own model signal) |
| N-ary connection / dependency | junction dot, radiating links | ✔ (links meet at the dot center) |
| Proxy connection (nested ends) | ball on the shallowest drawn ancestor, residual-path label | ✔ |
| Binding connection | `=` riding the line | ✔ |
| Dependency | dashed open-V, optional name label | ✔ |
| Satisfy requirement (longhand) | «satisfy requirement» box + reference-subsetting edge | ✔ (printed p.133 form) |
| Satisfy (shorthand `by`) | keyword edge | ✔ |
| Allocation | «allocate» keyword edge + «allocation» box forms | ✔ |
| Flow connection | border pins, filled head at the target pin, payload labels | ◐ pins are edge-end decorations, not ELK ports, to keep packed layouts stable; port-attached flows use the real port squares |
| Portion membership | notched ball at the whole-occurrence end | ✔ |
| Conjugation `~` | textual only (no edge glyph in the spec) | ✔ as text |
| Succession (action views) | dashed open-V | ✔ |
| Transition (state views) | solid open-V, trigger/guard/effect label | ✔ |
| Message/event lines | sequence view | ✖ longeron has no sequence view |

All arrowheads share the spec's slender (~27°) geometry, derived from one
set of constants in both render pipelines.

## Nodes and adornments

| Notation | Spec form | Status |
|---|---|---|
| Definition / usage boxes | square corners for defs, rounded for usages | ✔ |
| Package | folder tab | ✔ (tab selects and hovers with the box) |
| Ports | boundary squares, direction arrows inside, `~` label for conjugates | ✔ (direction derives from the port definition's directed features; arrows point relative to the node interior) |
| Actor | stick figure, name below (default); «actor» keyword box | ✔ (`actor_style="box"` for the alternative) |
| Stakeholder | «stakeholder» keyword box | ✔ |
| Compartments | left-aligned rows, «keyword» stereotypes | ✔ |
| Comment / documentation | folded-corner note, dashed anchor | ✔ (`annotations=True`) |
| Metadata | «@Type» / «#keyword» adornments | ✔ (`annotations=True`) |
| Individual / timeslice / snapshot | keyword adornments | ✔ |

## Behavior views

| Notation | Spec form | Status |
|---|---|---|
| Start | filled circle | ✔ |
| Done / final | bullseye | ✔ |
| Terminate | circle with inscribed X | ✔ |
| Fork / join | filled bar | ✔ |
| Decision / merge | hollow rhombus | ✔ (in/out links meet at single anchors) |
| Accept action | rounded box, notched-banner badge at top left | ✔ |
| Send action | rounded box, pointed-tag badge at top left | ✔ |
| Swim lanes | dashed «performer» lanes | ◐ content-sized lane containers ordered by ELK partitioning, not full-height columns (`lanes=`) |
| Typed submachines | expanded in place | ✔ (`submachine_depth`, cycle-protected) |
| State entry/exit points | border circles | ✖ the language model has no border connection-point element to render; tracked as a model-layer gap |

## Interaction

Selection and hover treat a node and its adornments (tab, badges, ports)
as one shape. Diagrams open fitted and centered. The toolbar provides
search-that-highlights, edge-routing and layout-direction toggles, and
fit/center/collapse controls. Edge routing offers orthogonal (default),
polyline, and splines; endpoint symbols stay correctly oriented in all
three.

## How this page stays honest

The gallery notebook asserts every ✔ above against the built diagram, and
executes on every CI run, headless and in a real browser. When a glyph
changes, the gallery fails before this page can drift. Deferred items keep
their reasons next to them; when a deferral lands, its row moves up and
the gallery gains a section.
