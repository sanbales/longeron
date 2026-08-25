# Saving diagrams as SysML v2 views (design)

Goal: let a user click "Save view" on an explorer diagram and get the
diagram back later -- in longeron, in any conformant SysML v2 tool, and
across the Systems Modeling API. This document records the design for
longeron 0.10.0 (tranche 2 groundwork). It records design intent; no
persistence code exists yet. All empirical claims below were verified
against longeron 0.9.1 at commit `499c75b`.

## The standards boundary

SysML v2 has no diagram-interchange standard. The specification defines
no geometry, no node positions, and no diagram file format. What it does
define is §7.26 "Views and Viewpoints": a standard vocabulary for diagram
*configuration*. A `ViewUsage` with `expose` relationships and `filter`
conditions says what a diagram shows. A `RenderingUsage` names how the
exposed content is rendered (spec §7.26.1, printed p. 149). That is
exactly the information a diagram needs to be reconstructed, and it lives
*in the model*, so it travels through `.sysml` text, the Systems Modeling
API, Flexo, and every conformant tool.

The design therefore has two tiers:

- **Standard tier.** Saving a diagram writes a `ViewUsage` into the model
  itself: the exposed elements, any filter conditions, and a rendering
  reference. This tier round-trips through every standard channel and is
  legible to other tools.
- **Sidecar tier.** A small versioned JSON file, owned by longeron,
  carries what the standard cannot: layout direction, edge routing,
  collapse state, and the longeron diagram kind. It is keyed by the view
  usage's qualified name, so it degrades gracefully -- a model without
  the sidecar still restores correctly with default presentation.

Geometry is deliberately in neither tier. Longeron's diagrams are laid
out by ELK, and ELK layout is deterministic given the same element set
and layout options. Persisting the *inputs* (exposed elements, direction,
routing) reproduces the picture; persisting pixel coordinates would only
record one layout engine's output and rot on the first model edit. This
matches the standards-boundary stance of the
[OpenMBEE integration design](openmbee-integration.md): meet other tools
at the standard, keep tool-specific state small and honest.

## What the standard provides

### View definitions and usages

A view definition declares filter conditions and a view rendering; a view
usage adds `expose` relationships that select the model content (spec
§7.26.2, printed pp. 152-153). The textual notation (spec §8.2.2.26.1-2,
printed pp. 190-191):

```text
ViewDefinition   = OccurrenceDefinitionPrefix 'view' 'def'
                   DefinitionDeclaration ViewDefinitionBody
ViewUsage        = OccurrenceUsagePrefix 'view'
                   UsageDeclaration? ValuePart? ViewBody
ViewBodyItem     = DefinitionBodyItem
                 | ElementFilterMember | ViewRenderingMember | Expose
```

The spec's own example pair (§7.26.2, printed p. 152):

```sysml
view def 'Part Structure View' {
    import Views::*;
    filter @SysML::PartUsage;
    render asTreeDiagram;
}
view 'vehicle parts view' : 'Part Structure View' {
    expose VehicleDesignModel::**;
    filter not @SysML::ConnectionUsage;
    render asMyTreeDiagram;
}
```

A view usage inherits filter conditions from its definition and may add
its own. A `render` clause that names an existing rendering usage creates
a reference subsetting to it; declaring one redefines the definition's
rendering (spec §7.26.2, printed p. 152).

### Expose

`Expose` is a kind of `Import` whose owner must be a `ViewUsage` (spec
§8.3.26.2, printed pp. 383-384). It comes in two forms, mirroring the two
import forms (spec §8.2.2.26.2, printed p. 191):

- `expose a::b;` -- a **MembershipExpose** of one membership;
  `expose a::b::**;` recursively exposes memberships beneath it.
- `expose Pkg::*;` -- a **NamespaceExpose** of a namespace's memberships;
  `Pkg::**` recurses.
- Either form takes the filtered-import bracket:
  `expose Pkg::**[not @SysML::ConnectionUsage];` (spec §7.26.2, printed
  p. 153).

Two abstract-syntax constraints matter for persistence. An `Expose`
always has `isImportAll = true` -- visibility is ignored -- and always
has *protected* visibility, so exposed elements do not leak out of the
view's namespace (spec §8.3.26.2 `validateExposeIsImportAll` /
`validateExposeVisibility`). The derived `exposedElement` set is the
imported memberships filtered by the owned and inherited view conditions
(`deriveViewUsageExposedElement`, spec §8.3.26.11, printed p. 392).

### Viewpoints

A viewpoint is a requirement whose subject is a view (spec §7.26.3,
printed p. 153). A composite viewpoint usage nested in a view definition
or usage is implicitly asserted to be satisfied by that view; an explicit
`satisfy` usage does the same across namespaces (spec §8.4.22.4, printed
p. 458). Viewpoints are stakeholder-analysis machinery, not diagram
state; this design parses and preserves them but never evaluates them
(see the scope fences).

### Renderings and the standard libraries

The `Views` library package supplies the base types (`View`, `views`,
`Rendering`, `renderings`) and four standard rendering usages:
`asInterconnectionDiagram`, `asTreeDiagram`, `asElementTable`,
`asTextualNotation` (spec §9.2.19, printed pp. 507-513). The
`StandardViewDefinitions` package defines the normative diagram kinds --
`GeneralView` (gv), `InterconnectionView` (iv), `ActionFlowView` (afv),
`StateTransitionView` (stv), `SequenceView` (sv), and others (spec
§9.2.20, Table 34, printed p. 513). Both packages ship in longeron's
bundled standard library (`src/longeron/_stdlib/systems/Views.sysml` and
`StandardViewDefinitions.sysml`), so saved views resolve without network
access -- verified below.

## What a saved diagram writes

Longeron's diagram kinds map onto the standard vocabulary directly:

| longeron diagram              | view definition (typing)                  | rendering reference             |
| ----------------------------- | ----------------------------------------- | ------------------------------- |
| `structure_diagram`           | `StandardViewDefinitions::InterconnectionView` | `Views::asInterconnectionDiagram` |
| `state_diagram`               | `StandardViewDefinitions::StateTransitionView` | `Views::asInterconnectionDiagram` |
| `action_diagram`              | `StandardViewDefinitions::ActionFlowView`      | `Views::asInterconnectionDiagram` |
| `explorer.requirements_view`  | `StandardViewDefinitions::GeneralView`         | `Views::asInterconnectionDiagram` |

The `GeneralView` row follows the spec's own recipe: its description
names a "requirement view" as a `GeneralView` specialization selected by
filters on requirement metaclasses (spec §9.2.20.2.3, printed p. 515).

Clicking "Save view" on the explorer's structure diagram of `Rig::axle`
(which the explorer scopes to the nearest owning package, `Rig`) writes
this view usage into the model:

```sysml
package Rig {
    part def Axle {
        part hub : Hub [2];
    }
    part def Hub;
    part axle : Axle;

    view 'axle structure' : StandardViewDefinitions::InterconnectionView {
        expose Rig::**;
        render Views::asInterconnectionDiagram;
    }
}
```

This exact text parses, round-trips through `to_sysml` at a fixpoint, and
passes `longeron.validate` with the standard library attached (verified
0.9.1). Restoring it reverses each line: the typing picks the structure
builder, the expose closure yields the diagram scope, and the sidecar
entry keyed by `Rig::axle structure` re-applies direction, routing, and
collapse state. A conformant tool that has never heard of longeron reads
the same text and knows what to draw and how the spec says to render it.

## What longeron supports today (gap analysis)

Every row below was established empirically: spec-shaped samples were
parsed with `longeron.loads()`, walked, exported, and projected. The
probe sample exercised `view def` with `satisfy`/`render`, `viewpoint`
with `frame`/`require`, `rendering`, and a `view` usage with all three
expose forms, a `filter`, and a `render` reference.

| surface | view | viewpoint | expose | rendering / render |
| --- | --- | --- | --- | --- |
| grammar (`SysML.g4` §8.2.2.26 rules; collapsed into `KerML.g4` ~l. 2487) | full | full | full, incl. bracket filters | full |
| model layer (`model.py` kinds; `Expose` dataclass) | full | full | full (`target`, `is_namespace`, `is_recursive`, `filters`) | full (`render` = reference-subsetting usage) |
| `to_sysml` export | fixpoint | fixpoint | fixpoint, incl. `X::**[expr]` | fixpoint |
| longeron JSON (`to_json`/`from_json`) | lossless | lossless | lossless | lossless |
| stdlib resolution + `validate` | typing by `StandardViewDefinitions::*` resolves, no diagnostics | resolves | **dangling expose target: no diagnostic** | `render` target resolves; dangling target flagged (`unresolved-reference`) |
| API projection (`to_api_records`) | `ViewDefinition`/`ViewUsage` records | `ViewpointUsage` record | **dropped -- no record at all** | `RenderingUsage` record; membership degrades |
| API inverse (`model_from_api_json`) | survives, retyped | degrades (`frame`/`require` flatten) | **gone** | degrades to `rendering :> ...` |
| diagrams (`diagrams.py`) | `view def` draws as a generic «view def» box; **`view` usages are not drawn** (not in `_StructureBuilder._visit`'s kind list) | drawn as generic box | ignored | ignored |
| explorer | view usages appear in the tree (kind badge); no view-aware behavior | same | n/a | n/a |

Observed API projection for the probe (`@type` histogram): `ViewDefinition`,
`ViewUsage`, `ViewpointUsage`, `RenderingUsage`, and `SatisfyRequirementUsage`
records all appear -- but no `MembershipExpose`, `NamespaceExpose`, or
`ElementFilterMembership` record exists anywhere in the output. Pushing the
example above through `to_api_records` and back yields:

```sysml
view axleView : Rig::AxleStructure {
    rendering :> Rig::asTreeDiagram;
}
```

The exposes and the filter are simply gone.

The five most consequential findings:

1. **The textual tier already works end to end.** Grammar, model layer,
   `to_sysml`, and longeron's lossless JSON all carry views, viewpoints,
   exposes (all three forms, with bracket filters), and renderings at a
   verified round-trip fixpoint. The standard tier of this design needs
   *no parser or exporter work*.
2. **The API projection silently deletes the point of a view.**
   `to_api_records` keeps the `ViewUsage` shell but drops every `Expose`
   and `ElementFilter`. A view pushed through longeron's own server (or
   any API consumer) arrives empty. Fixing the `ecore.py`/`api.py`
   projection is a hard precondition for tier-1 round-trip.
3. **View usages are invisible in diagrams.** `_StructureBuilder._visit`
   draws `view def` boxes (any `M.Definition` draws) but skips `view`
   usages entirely. Restore work starts from zero on the rendering side;
   nothing conflicts with it.
4. **Element UUIDs are index-path derived, not name derived.**
   `ecore.py` assigns `elementId = uuid5(ns, "$root/0/3/...")` -- stable
   only while sibling *positions* are stable. Inserting a member shifts
   every later sibling's id. Qualified names are the reliable join key;
   the sidecar treats UUIDs as hints only.
5. **Dangling exposes are undiagnosed.** `validate` flags a dangling
   `render` target through subsetting resolution, but an `expose` naming
   a nonexistent element produces no diagnostic today. Restore needs a
   defined behavior (below) and validation needs a new code.

## The sidecar

The sidecar carries only what the standard cannot express and what the
layout engine cannot re-derive: presentation intent. One JSON file per
workspace, `.longeron/views.json`, next to the `.sysml` sources:

```json
{
  "schema": "longeron/views",
  "version": 1,
  "views": {
    "Rig::axle structure": {
      "elementId": "9e60018a-0d60-59e9-833f-46718a42c19c",
      "kind": "structure",
      "direction": "right",
      "routing": "orthogonal",
      "collapsed": ["Rig::Axle"],
      "options": {"membership": "nested", "show_attributes": true}
    }
  }
}
```

Schema rules:

- **Keys are view qualified names.** These are the ids the explorer and
  diagrams already use for every node, and they survive text round-trips.
  `elementId` records the API projection's UUID as a cross-reference
  hint, but it is never the join key (finding 4).
- **Versioned and forward-compatible.** Readers accept any `version` >= 1,
  keep unknown per-view keys intact on rewrite, and ignore what they do
  not understand. A future version bump is only for incompatible key
  *reinterpretation*, never for additions.
- **Values mirror existing constructor kwargs.** `kind` is one of
  `explorer.DIAGRAM_KINDS`; `direction`/`routing` are the toolbar traits
  (`right`/`down`; `orthogonal`/`polyline`/`splines`); `collapsed` lists
  qualified names of collapsed nodes; `options` holds the diagram-kind
  specific kwargs (`membership`, `submachine_depth`, `lanes`, ...). No
  new vocabulary is invented.
- **Small enough to review.** One view is a handful of lines; a sidecar
  diff in a code review reads as "this view changed direction", not as
  an opaque blob. Absent entries mean defaults, so the file only grows
  when a user actually deviates from them.

## Save flow

The explorer gains a "Save view" toolbar button next to the kind
switcher. Saving proceeds in three steps:

1. **Model edit.** Build a `ViewUsage` named by the user (default:
   `"<element> <kind>"`), typed per the mapping table, with one recursive
   expose of the diagram's scope root and a `render` reference to the
   matching `Views::` rendering. Append it to the scope package's
   members. Appending -- never inserting -- keeps existing index-path
   UUIDs stable (finding 4).
2. **Sidecar write.** Read the live toolbar traits (`direction`,
   `routing`), the collapse tool's state, and the builder kwargs; write
   or replace the sidecar entry under the view's qualified name.
3. **Workspace write.** Regenerate the owning `.sysml` file with
   `to_sysml`, exactly as the server's `apply_commit` already does for
   API-pushed changes: only the touched file is rewritten, the result is
   left uncommitted, and the user reviews the diff. For API-backed
   workspaces, `Client.push_commit` sends the same change -- once the
   projection gap (finding 2) is fixed; until then, save over the API is
   fenced off with an explicit error.

Collision and rename semantics are by qualified name. Saving under an
existing view name *replaces* that view usage's body (exposes, filters,
render) and its sidecar entry -- save is idempotent. Renaming a view is a
save-under-new-name plus an explicit delete; the sidecar entry moves with
it. Sidecar entries whose qualified name no longer resolves in the model
are ignored on load and pruned on the next sidecar write, so a view
deleted by another tool cannot wedge the explorer.

## Restore flow

Selecting a view usage in the explorer tree (where views already appear)
restores the diagram:

1. **Resolve the recipe.** The view's typing (or, if untyped, its
   `render` reference; or, failing both, the sidecar `kind`) selects the
   diagram builder. Unknown view definitions fall back to the structure
   builder with a warning.
2. **Compute the expose closure.** Each `Expose` resolves through the
   existing `Resolver`: membership exposes yield the named element (plus
   its subtree when recursive), namespace exposes yield the namespace's
   members. Filter conditions restrict the closure. Metaclass filters
   (`@SysML::PartUsage`, the dominant spec idiom) evaluate against
   longeron's kind vocabulary; general model-level expressions are
   deferred (scope fence below).
3. **Build and decorate.** The builder runs over the closure; the sidecar
   entry (if any) supplies `direction`, `routing`, `options`, and the
   collapsed-node set. No sidecar means spec content with default
   presentation -- the degraded mode *is* the standard mode.

A dangling expose (target deleted or renamed by another tool) resolves to
nothing: restore warns, skips that expose, and draws the rest. A view
whose every expose dangles restores to an empty diagram with the warning,
never an exception. A new validation diagnostic (`dangling-expose`,
warning severity) surfaces the same condition in `longeron.validate`,
closing finding 5.

## Round-trip implications

**Other tools editing the model.** The standard tier is plain model text.
Another tool can rename the view, retarget an expose, or change the
rendering, and longeron restores what the text now says. The sidecar is
keyed by qualified name, so a rename made elsewhere orphans the sidecar
entry -- the view still restores, with default presentation, and the
orphan is pruned. This failure mode is deliberate: presentation is the
cheap half.

**Deleted elements.** Views referencing deleted elements are the
dangling-expose case above: warn, skip, keep going. The spec places no
well-formedness constraint on an import target's continued existence, so
longeron treats it as a diagnostic, not an error.

**Merges.** View usages merge as ordinary model text -- one view per
block, so concurrent edits to different views never conflict. The sidecar
is one JSON object per view under stable keys; git merges entries from
different views cleanly, and a conflict inside one entry is a few
readable lines. The append-only save discipline keeps model-file diffs
minimal.

**The API.** Once exposes project (finding 2), a view survives
`push_commit` / `fetch_model` and the same flows work against Flexo or
the OMG pilot servers. The sidecar never crosses the API: it is not
model content, and inventing a nonstandard element for it would poison
the record stream for other consumers -- the same reasoning that kept M0
interpretations out of the API projection
([M0 design, decision 3](m0-interpretations.md)).

## What we deliberately do not build

- **No viewpoint conformance checking.** Viewpoints, `frame`, and
  satisfaction assertions parse, round-trip, and are preserved verbatim.
  Longeron does not evaluate `ViewpointCheck` requirements (spec
  §9.2.19.2.11) or report viewpoint conformance. That is requirements
  analysis, not diagram persistence.
- **No rendering engine work beyond the four diagram kinds.**
  `asElementTable` and `asTextualNotation` views restore through the
  structure fallback with a warning. Tabular and textual renderers are
  separate features if ever wanted.
- **No geometry, ever.** No node positions, no sizes, no waypoints --
  neither in the model nor in the sidecar. ELK re-derives layout from
  persisted intent.
- **No composite view artifacts.** The spec sketches nested views as
  document sections (§7.26.1, printed p. 149). Longeron restores one
  diagram per view usage; document generation is out of scope.
- **No general filter-expression evaluation at restore (initially).**
  Metaclass filters evaluate; arbitrary model-level expressions in
  filters are preserved and exported but not applied to the closure until
  the expression evaluator grows metadata-aware checking.

## Open questions for the maintainer

1. **Where does a new view usage land in multi-file workspaces?**
   Options: append to the file owning the scope package, or collect views
   in a dedicated `views.sysml`. *Recommendation:* append to the owning
   file. It keeps the view next to what it shows, matches the spec's
   examples, and the server's per-file rewrite already localizes the
   diff. Revisit if users object to tools touching their source files.
2. **Type saved views by `StandardViewDefinitions`, or leave them untyped
   with only a `render` reference?** *Recommendation:* type them. The
   standard library ships with every conformant tool, the typing is the
   machine-readable statement of diagram kind, and it is what makes the
   saved view legible outside longeron. The sidecar `kind` remains as the
   fallback for untyped views authored by hand.
3. **Fix the API expose projection in this tranche or a later one?**
   *Recommendation:* this tranche. Without it, longeron's own server
   erases saved views on the first push, which contradicts the feature's
   headline. The exporter work is bounded: `MembershipExpose`,
   `NamespaceExpose`, and `ElementFilterMembership` records plus their
   inverse.
4. **Stabilize element UUIDs by seeding from qualified names instead of
   index paths?** *Recommendation:* not now. Changing the seed changes
   every derived `@id` across releases (the `ecore.py` comment already
   guards this), and qualified-name keys make the sidecar independent of
   the answer. Reconsider only if a cross-tool consumer needs stable ids
   under reordering.
5. **Should "Save view" also record the explorer's selection?**
   *Recommendation:* no. Selection is transient focus, not diagram
   configuration; persisting it adds sidecar churn on every save for no
   restore value.

## References

- OMG Systems Modeling Language (SysML) v2.0, Part 1: §7.26 (printed
  pp. 149-157), §8.2.2.26 (printed pp. 190-192), §8.3.26 (printed
  pp. 381-392), §8.4.22 (printed pp. 457-458), §9.2.19-9.2.20 (printed
  pp. 507-518).
- Longeron surfaces: {mod}`longeron.diagrams`, {mod}`longeron.explorer`,
  {mod}`longeron.workspace`, {mod}`longeron.client`,
  [validation guide](../guides/validation.md).
- Sibling designs: [OpenMBEE integration paths](openmbee-integration.md),
  [M0 interpretations](m0-interpretations.md).
