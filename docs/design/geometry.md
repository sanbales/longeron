# Geometry as model content (design)

> **Status: adopted 2026-08-28.** All ten decisions below (the
> Decisions section) are settled. Nothing in this document is
> implemented yet; it is the contract for the 0.13 geometry arc.

Goal: let SysML v2 models carry CAD content directly. A model declares
rough geometry -- primitive solids, boolean operations, edge
operations -- from primordial CAD elements: points, coordinate frames,
relative coordinate frames, the bare minimum to define basic solids
with their position and orientation. The vocabulary must also extend
to real engineering surfaces -- wings with proper airfoils,
multisection, twist, dihedral -- as the worked example of extending
the base vocabulary. The target is not high-fidelity CAD; it is
reasonable bounding volumes and shapes, good enough for constraint
evaluation inside SysML v2.

The design also covers articulation: what SysML v2 offers for hinges
and joints, so a model can state a gimballed sensor, an unfolding
solar panel, or a multi-joint robot arm -- from a simple 3-DOF arm to
an underconstrained arm with 11 joints. A James Webb Telescope-class
deployment mechanism is the stretch test; an expanding solar panel is
the working example.

The thesis follows longeron's spine. Today geometry is Python-side: a
builder synthesizes an airframe from catalog attributes, and the model
never states a shape. This design inverts the ownership. Parts carry
their own bounding volumes as model content, grounded in the standard
Geometry Domain Library, and the kernel compiles that content into the
meshes and solids the existing checks and viewers already consume.
Longeron's standing posture applies throughout: model-derived, never
invented. Every primordial below is grounded in standard vocabulary,
and every extension is a clearly labeled longeron library.

All empirical claims were verified against longeron 0.10.0. Library
claims cite the pinned OMG corpus at commit `de1070ae`. JupyterCAD
claims were verified in a scratch venv against jupytercad 3.4.2.
Spec-absence claims were verified by full-text search over the SysML
v2 Part 1 PDF.

## The standards boundary: what the library already ships

SysML v2 already owns the shape-vocabulary problem. The Geometry Domain
Library (spec §9.7, printed p. 582) ships two packages, and the
Quantities and Units library ships the entire coordinate-frame
machinery. Both Geometry files parse and validate with zero
diagnostics against longeron 0.10.0 (verified).

### ShapeItems: 43 shape definitions, parametric where it counts

`ShapeItems.sysml` (898 lines) models shapes as structured boundary
items: faces, edges, and vertices with mating constraints, plus the
scalar parameters a compiler needs. The full inventory, cited to the
corpus file:

| Category | Definitions (file line) |
| --- | --- |
| Planar curves | `PlanarCurve` (25), `Line` (49), `Path` (59, abstract), `ConicSection` (83), `Ellipse` (95), `Circle` (107), `Parabola` (122), `Hyperbola` (133), `Polygon` (143), `Triangle` (159), `RightTriangle` (181), `Quadrilateral` (196), `Rectangle` (215) |
| Surfaces and shells | `PlanarSurface` (37), `Shell` (230, abstract), `Disc` (237), `CircularDisc` (261), `ConicSurface` (278), `Ellipsoid` (291), `Sphere` (304), `Paraboloid` (316), `Hyperboloid` (327), `Toroid` (337), `Torus` (355), `RectangularToroid` (368) |
| Closed solids (as shells) | `ConeOrCylinder` (384), `Cone` (441), `EccentricCone` (455), `CircularCone` (464), `RightCircularCone` (479), `Cylinder` (489), `EccentricCylinder` (504), `CircularCylinder` (513), `RightCircularCylinder` (531), `Polyhedron` (541), `CuboidOrTriangularPrism` (562), `TriangularPrism` (680), `RightTriangularPrism` (710, alias `Wedge` 744), `Cuboid` (746), `RectangularCuboid` (798, alias `Box` 821), `Pyramid` (823), `Tetrahedron` (866), `RectangularPyramid` (883) |

That is 43 item definitions (2 abstract) plus 2 aliases. The usable
core for bounding volumes is immediately visible: `Box` with
`length`/`width`/`height`, `Sphere` with `radius`, `CircularCylinder`
and `CircularCone` with `radius`/`height`/offsets, `Ellipsoid` with
three semiaxes, `Torus` with major/minor radii, `Wedge`, `Tetrahedron`,
and `RectangularPyramid`. Every parameter is a `LengthValue` quantity,
so the units design's machinery applies unchanged. `CircularDisc` even
matches the propeller-disc solids the existing overlap check stamps.

Two facts matter for the compiler. First, the parameters are exactly
sufficient: a `Box` knows its three extents, a `CircularCylinder` its
radius and height, and nothing else is needed to build the primitive.
Second, the boundary structure (the face/edge/vertex items with
`MatesWith` connections and `binding` clauses) is *descriptive*, not
constructive. The compiler reads the scalar parameters and ignores the
boundary bookkeeping.

### SpatialItems: frames, nesting, and the one boolean that exists

`SpatialItems.sysml` (167 lines) supplies the positioning substrate.
`SpatialItem` (line 23) is an item with three-dimensional extent that
is also a frame of reference. Its machinery, closely read:

- **`coordinateFrame : ThreeDCoordinateFrame`** (line 37) defaults to
  the singleton `universalCartesianSpatial3dCoordinateFrame`. This is
  the measurement reference for positions within the item.
- **`originPoint`** (line 46) pins the frame: an asserted constraint
  requires its current position to be the zero vector.
- **`subSpatialItems` / `subSpatialParts`** (lines 62-68) nest spatial
  items and parts recursively.
- **`componentItems`** (line 70) is the composition seam. A
  `SpatialItem` with `componentItems` occurs *only* as the collection
  of those items. Each component's `coordinateFrame` defaults to the
  parent's measurement references with a `nullTransformation` whose
  `source` defaults to the parent frame (lines 79-84). A component
  therefore carries a *relative* frame by default, and overriding its
  `transformation` places and orients it within the parent. This is
  the standard's relative-coordinate-frame mechanism, and it composes
  recursively down the tree.
- **`componentUnion`** (lines 87-95) gives the union semantics: a
  `SpatialItem` with components subsets `unionsOf` over exactly those
  components. **This is the only boolean the standard ships.** There
  is no difference, no intersection, and no cut anywhere in the
  library (verified by search over the corpus). Booleans beyond union
  are a longeron extension by necessity.
- **`PositionOf` / `DisplacementOf`** calcs (lines 102-167) define
  position and displacement vectors of points relative to a
  `SpatialItem`, with clock parameters for time-varying positions.

### The frame machinery longeron already vendors

The coordinate-frame vocabulary lives in
`MeasurementReferences.sysml`, which longeron already ships in
`src/longeron/_stdlib/quantities/`. Verified present, with vendored
file lines:

- `CoordinateFrame` (101) with an optional `transformation`, and
  `'3dCoordinateFrame'` (117, alias `ThreeDCoordinateFrame`).
- `CoordinateTransformation` (126), abstract, with `source` and
  `target` frames.
- `CoordinateFramePlacement` (137): origin vector plus basis
  directions in the source frame.
- `Translation` (165) and `Rotation` (176). A `Rotation` carries
  `axisDirection`, `angle`, and `isIntrinsic` -- the exact parameter
  set of a revolute articulation.
- `TranslationRotationSequence` (194): an ordered list of translations
  and rotations, the human-friendly transformation.
- `AffineTransformationMatrix3d` (209) and `NullTransformation` (243):
  the 4x4 machine form, with the identity singleton
  `nullTransformation`.

The 3D frame *taxonomy* lives in `ISQSpaceTime.sysml`, which longeron
does not vendor yet: `Spatial3dCoordinateFrame` (corpus line 161),
`CartesianSpatial3dCoordinateFrame` (169), the singleton
`universalCartesianSpatial3dCoordinateFrame` (188), cylindrical,
spherical, and planetary frames (208-291), and
`Position3dVector`/`Displacement3dVector` (304, 318). The same file
declares the `width`, `height`, `radius`, `area`, and `volume`
quantities that `ShapeItems` redefines (`length` is in the vendored
`ISQBase`). The units design (decision 1) already vendors
`ISQSpaceTime`. This design turns that decision into a
requirement, because `ShapeItems` and `SpatialItems` import it.

### The kernel gap, and the shim that closes it

The corpus copy ships no KerML Kernel Libraries, and longeron's KerML
is parse-only. `ShapeItems` and `SpatialItems` reference kernel names
that today dangle: `Objects::Point`, `Objects::StructuredSpaceObject`
(with `Curve`, `Surface`, and their face/edge/vertex features),
`SpatialFrames::SpatialFrame`, `Occurrences::MatesWith`, and the
kernel function libraries (`SequenceFunctions`, `ControlFunctions`,
`TrigFunctions`, `VectorFunctions`). Longeron already has the pattern
for this: `KernelShim.sysml` provides resolvable stand-ins for kernel
names (`ScalarValues`, `Base`, `Objects`, `Collections`). The shim
grows the geometry names as stubs: `Point`, `SpatialFrame`,
`MatesWith`, and the handful of function names. Where the shim does
not reach, the posture from the units design applies:
resolution is good where the library ships and dangling where it does
not, and the compiler never depends on the dangling parts.

### What the standard does not ship: kinematics, verified absent

The articulation goal asks what SysML v2 has for hinges, gimbals, and
multi-joint arms. The answer, verified empirically: **nothing named**.
A full-text search of the entire Part 1 specification PDF finds zero
occurrences of "revolute", "prismatic", "kinematic", "hinge",
"gimbal", or "degrees of freedom". A search of the whole
`sysml.library` corpus finds the same absence (the only "joint" hits
are information-theory quantities, and the only "kinematic" hits are
viscosity units). The Analysis library's `StateSpaceRepresentation`
(143 lines, checked) models control-system state vectors and their
dynamics, not articulation. It is a plausible *consumer* of a pose
vector but names no joints.

What the standard ships instead is the substrate: nested
`SpatialItem` frames whose `transformation` is a
`TranslationRotationSequence`, and a `Rotation` that already carries
an axis and an angle. A hinge is a frame relationship with one free
parameter. The joint *vocabulary* -- naming that free parameter as a
degree of freedom, bounding it, and chaining links -- is a longeron
extension over standard parts, and the design below builds exactly
that.

One more standard hook, for completeness: the vendored
`StandardViewDefinitions.sysml` already defines `GeometryView` (line
81), a view definition "to present a visualization of exposed spatial
items in two or three dimensions". The compilation pipeline below is,
in the standard's own terms, an implementation of that view.

## What longeron has today (gap analysis)

Everything below was read from the longeron 0.10.0 source.

- **Python-side parametric builders.** `analysis/geometry.py` (2119
  lines) synthesizes four airframe families from catalog attributes:
  the N-arm multirotor, the teardrop quad, the cruciform VTOL, and the
  interceptor. Lifting surfaces loft real NACA 4-digit sections
  (`naca4_profile`), fuselages are lathed bodies of revolution
  (`_tube`), and sizes come from documented heuristics (motor density,
  battery brick proportions). The model states none of this. The
  builder invents it from scalar attributes.
- **Two check engines, honestly named.** The geometric requirement
  checks (`camera_occlusion`, `disc_overlap`, keyed by
  `geometry_checks` for the scoreboard's `values=` seam) run on
  `engine='cad'` (exact OCC booleans via cadquery, behind the `[cad]`
  extra) or `engine='mesh'` (an in-house, stdlib-only deterministic
  volume quadrature with ray-parity membership tests). There is no
  trimesh anywhere in the package (verified). The mesh engine is
  hand-rolled and dependency-free, and this design keeps it that way.
- **The CAD twin.** `to_cadquery` rebuilds the quad assembly as OCC
  solids from the same sizing recipe the mesh builder stamps on
  `mesh["cad"]`. The booleans run against parametric solids, not
  tessellations.
- **Identity keying.** `tag_parts` stamps mesh parts with model
  identities: qualified names, or M0 individual ids
  (`Drone::QuadCopter#0.motors#2`) whose dotted paths drive linked
  selection (`analysis/link.py`). The viewer renders geometry once per
  configuration (`viewer3d`), and the curriculum's T7 requires that
  selecting a configuration renders *its* geometry.
- **Downstream consumers.** `_glb.py` exports the mesh dict as binary
  glTF (stdlib-only), and `mission3d` flies it on the Cesium globe.
- **The model side is ready.** `item` usages instantiate with
  attribute slots (verified: a part with an
  `item envelope : Box { :>> length = 0.075; ... }` yields an instance
  whose `envelope` slot carries `length`, `width`, `height` values).
  The compiler can read geometry straight off instances and M0
  individuals with no interpreter change.

The gap, stated once: geometry today flows *from* Python heuristics
*to* the screen, and the model is only a source of scalars. This
design inverts the arrow. Geometry becomes model content,
and the Python side becomes a compiler.

## The primordial set

The primordials are the bare minimum to define basic solids, their
orientation, and their position. Each row is grounded in the standard
or marked as a longeron extension.

| Primordial | Grounding | Status |
| --- | --- | --- |
| Point | `Objects::Point` (kernel) | standard; shim stub |
| Coordinate frame | `MeasurementReferences::'3dCoordinateFrame'` | standard; **already vendored** |
| Relative frame (placement) | `CoordinateFramePlacement`, `TranslationRotationSequence`, `AffineTransformationMatrix3d` | standard; **already vendored** |
| Spatial container + union | `SpatialItems::SpatialItem` (`componentItems`) | standard; vendor |
| Solid primitives | `ShapeItems`: `Box`, `Sphere`, `CircularCylinder`, `CircularCone`, `Ellipsoid`, `Torus`, `Wedge`, `Tetrahedron`, `RectangularPyramid`, `CircularDisc`, ... | standard; vendor |
| Boolean difference / intersection | none (verified absent) | **longeron extension** |
| Edge operations (fillet, chamfer) | none | **longeron extension**, bounded (see fidelity ceiling) |
| Revolved / lofted solids | none (`Toroid` revolves a curve, but no general sweep) | **longeron extension** |
| Airfoils, wings | none | **longeron extension** (the worked example) |
| Joints, chains, poses | none (verified absent) | **longeron extension** (the kinematics section) |

The extensions live in longeron-authored library packages, shipped
with the package but never labeled `standard library`. The names,
per decision 2: `LongeronGeometry` (booleans, edge
operations, sweeps), `LongeronAero` (airfoils and wings), and
`LongeronKinematics` (joints and chains).

The boolean extension is deliberately small -- a CSG node is an item
that names its operands:

```sysml
package LongeronGeometry {
    doc /* Longeron extension: boolean solids the standard lacks.
           Union of components is standard (SpatialItems::SpatialItem
           componentItems); these cover the other two operations. */

    item def DifferenceSolid {
        item base [1];         // any ShapeItems solid or CSG node
        item tools [1..*];     // subtracted from base
    }

    item def IntersectionSolid {
        item operands [2..*];
    }
}
```

A part then states its own bounding volume in standard vocabulary,
placed by a standard transformation:

```sysml
part battery : Battery {
    item envelope : Box {
        attribute :>> length = 0.075 [SI::m];
        attribute :>> width  = 0.035 [SI::m];
        attribute :>> height = 0.030 [SI::m];
    }
    attribute placement : TranslationRotationSequence;
}
```

The envelope sketch above (an `item` with redefined extents on a part)
parses, validates cleanly, and instantiates with the extent values in
slots (verified at `cc5d4fd`, modulo the vendoring of `ShapeItems`).

M0 carries the tie to individuals. Envelope attributes are ordinary
attributes, so a configuration's selections set them per configuration
and an interpretation's individuals carry them per individual. The
compiler keys every generated solid by the same identity `tag_parts`
uses today, which makes linked selection automatic rather than
hand-stamped.

## The worked example: wings as a domain extension

The worked test: proper airfoils, multisection, twist,
dihedral. `LongeronAero` extends the primordials the same way any
domain library would, which is the point of the example.

```sysml
package LongeronAero {
    doc /* Longeron extension: parametric lifting surfaces. */

    item def AirfoilSection {
        attribute family : String = "NACA4";  // phase 2 supports NACA4
        attribute code : String;              // "2412"
        attribute chord : LengthValue;
        attribute twist : AngleValue;         // about the quarter chord
    }

    item def LoftedSurface {
        doc /* A solid skinned over ordered sections, each placed by
               its own relative frame (span station, dihedral, sweep
               follow from the frame sequence). */
        item sections : AirfoilSection [2..*] ordered;
    }

    item def WingPanel :> LoftedSurface {
        attribute span : LengthValue;
        attribute dihedral : AngleValue;
        attribute sweep : AngleValue;
        item root :> sections;
        item tip :> sections;
    }
}
```

A two-section panel with root and tip chords gives taper. More
sections give multisection wings. Per-section `twist` gives washout,
and the panel's `dihedral` tilts the span direction. The compiler
already has every ingredient: `naca4_profile` generates the section
polygon, and `_lift_surface`/`_skin` loft it. What changes is where
the numbers come from -- the model, not a builder's argument list.
The existing builders demonstrate the target honestly: today's VTOL
wing is exactly a two-section NACA-2412 loft with taper about a
straight quarter chord, so the extension is a re-homing of proven
machinery, not new geometry code.

The fidelity ceiling applies here too. `LoftedSurface` supports named
section families with ruled (linear) lofts between sections. It is a
bounding-volume-grade wing, not a manufacturing surface.

## Kinematics: joints, chains, and deployment

The standard ships no joint vocabulary (verified above), but its frame
machinery is the correct substrate. A joint is a parameterized frame
relationship: the child link's frame transformation, with one or more
parameters left free.

### Joint definitions

`LongeronKinematics` names the four classical joints as
specializations of the standard transformation vocabulary:

```sysml
package LongeronKinematics {
    doc /* Longeron extension: joints as parameterized frame
           relationships. The standard ships the substrate
           (TranslationRotationSequence, Rotation, Translation) but
           names no joints (verified: zero spec occurrences). */

    attribute def RevoluteJoint {
        attribute axis : Real [3];        // in the parent frame
        attribute angle : AngleValue;     // THE degree of freedom
        attribute lowerLimit : AngleValue;
        attribute upperLimit : AngleValue;
        assert constraint jointLimits {
            lowerLimit <= angle and angle <= upperLimit
        }
    }

    attribute def PrismaticJoint {
        attribute axis : Real [3];
        attribute travel : LengthValue;   // THE degree of freedom
        attribute lowerLimit : LengthValue;
        attribute upperLimit : LengthValue;
        assert constraint jointLimits {
            lowerLimit <= travel and travel <= upperLimit
        }
    }

    attribute def SphericalJoint { /* three angular DOF, cone limit */ }
    attribute def UniversalJoint { /* two orthogonal revolutes */ }
}
```

A reduced form of this sketch parses and validates with zero
diagnostics against longeron 0.10.0 (verified). The semantic grounding is direct:
a `RevoluteJoint` *is* the data of a standard `Rotation`
(`axisDirection`, `angle`) plus limits, and a gimbal is two nested
revolutes -- the child frame of the outer joint is the parent frame
of the inner one. The gimballed sensor is therefore
two `RevoluteJoint`s and one camera envelope, and the existing
occlusion check runs per pose.

Joint limits are ordinary asserted constraints. This is the payoff of
staying in the model: `verify` can hunt them. A pose that violates a
limit, or a pose sweep that finds an interference, is a
requirement-violation search over attributes -- exactly the machinery
`hunt`/`prove` already applies to other model attributes, with
shrinking producing the *simplest* violating pose.

### Kinematic chains: the 3-DOF arm, and the 11-joint scale test

A serial arm is a nested chain of `SpatialItem` links, each child
placed by a joint-parameterized transformation:

```sysml
part arm3dof : SpatialItem {
    attribute q1 : RevoluteJoint;   // base yaw
    attribute q2 : RevoluteJoint;   // shoulder pitch
    attribute q3 : RevoluteJoint;   // elbow pitch
    part base : SpatialItem :> componentParts {
        item envelope : CircularCylinder;
        part upper : SpatialItem { /* frame driven by q1, q2 */
            item envelope : CircularCylinder;
            part fore : SpatialItem { /* frame driven by q3 */
                item envelope : CircularCylinder;
            }
        }
    }
}
```

Forward kinematics is frame composition, and the standard already
defines the composition: each nested frame's `transformation` chains
to its parent (the `componentItems` default machinery), and the
compiler multiplies the resulting 4x4 affine matrices. No solver is
involved. A pose (a value for each joint parameter) determines every
link's world placement, and the compiled solids feed the same checks
as static geometry.

The 11-joint underconstrained serial arm is the scale test, and the
model expresses the redundancy honestly. The chain declares eleven
joint parameters, so the configuration space has eleven degrees of
freedom. A task ("reach point X") constrains at most six. The model
does not hide this: the joint parameters are ordinary attributes, the
task is an ordinary constraint over the composed tip frame, and the
gap between eleven and six *is* the redundancy. Nothing in this
design solves inverse kinematics -- the design deliberately stops at
forward composition plus constraint checking (see the fidelity
ceiling). What the model buys at eleven joints is exactly what it
buys at three: pose-parameterized envelopes, limit constraints that
`verify` can hunt, and interference checks per sampled pose.

### Deployment mechanisms: the expanding solar panel

The deployable panel ties kinematics to the machinery longeron
already ships: state machines. A panel array is N petals, each hinged
to its neighbor by a `RevoluteJoint` with limits `[0°, 180°]`.
Deployment is a state machine (`stowed` -> `deploying` -> `deployed`),
and each named state corresponds to a named *pose* -- a binding of
every hinge angle (`stowed`: all 0°, `deployed`: all 180°). The
existing replay recorder (`record_timeline`) already turns state
machines into timelines, so an animated deployment on the 3D viewer is
a timeline of poses driving the same compiled geometry. The James Webb
Telescope deployment sequence is the aspirational test for this
pattern. The expanding solar panel is the deliverable example, and it
exercises every piece: hinges, poses as states, per-pose interference
("does the deploying petal sweep through the hull?"), and limits.

### Articulated geometry feeds the same constraint story

Articulation multiplies configurations. It does not change the check
architecture. The honest capability at bounding-volume fidelity:

- **Per-pose checks, exact.** For any given pose, the chain compiles
  to placed solids and every existing check runs unchanged: occlusion,
  overlap, interference between named `SpatialItem`s, keep-out zones.
- **Range checks, sampled.** "Does the panel hit the hull anywhere in
  deployment?" is answered by sweeping the joint range: grid or
  Latin-hypercube samples over the DOF box (the trades machinery), or
  `hunt` searching for a violating pose and shrinking it. Sampling can
  miss a sliver between samples, and the report says so -- the same
  accuracy contract the mesh quadrature engine already documents.
- **Not offered: continuous swept volumes.** Exact swept-volume
  computation needs a real kinematics/collision engine (FCL-class
  software) and is above the fidelity ceiling. If a program needs
  certified continuous clearance, longeron's job is to export the
  compiled solids and the chain parameters, not to become that engine.

### The M0 tie: a pose is an interpretation-level fact

The M1 chain declares the possibility space: joints, limits, link
envelopes. A *pose* -- the vector of joint parameter values -- is a
fact about individuals, which is exactly what M0 interpretations
carry. A deployed panel and a stowed panel are the same M1 model with
different M0 slot values, and two arm individuals in one scene can
hold two different poses. Trade studies sweep pose spaces the way they
sweep any attribute space today, `verify` hunts them, and the compiled
scene keys each solid by the individual id, so linked selection works
per individual per pose. The floats-only invariant from the units
design survives untouched: a pose is a handful of float slots.

## The compilation pipeline

The kernel compiles model geometry to the two engines that already
exist. No third engine is added.

```text
model (SpatialItem tree, ShapeItems primitives, Longeron* extensions)
  -> instantiate / m0.interpret        (slots carry the numbers)
  -> geometry compiler                 (new, kernel-side)
       - walks part/item trees for envelope items + placements
       - composes frames: 4x4 affine products (stdlib math, ~100 lines)
       - keys every solid: qualified name or M0 individual id
  -> mesh dict            (stdlib tessellation: existing _box/_cylinder/
     |                     _tube/_skin/naca4_profile helpers; feeds
     |                     viewer3d, _glb/mission3d, mesh-engine checks)
  -> OCC solids ([cad])   (cadquery primitives + exact booleans; feeds
                           cad-engine checks, STEP export, JCAD export)
```

Design decisions inside the pipeline:

- **The compiler pattern-matches definitions, not magic names.** An
  item typed by a known primitive (`ShapeItems::Box`,
  `LongeronGeometry::DifferenceSolid`, `LongeronAero::WingPanel`)
  compiles, and anything else is ignored. Placement reads the standard
  transformation attributes (`Translation.translationVector`,
  `Rotation.axisDirection`/`angle`, or a raw
  `AffineTransformationMatrix3d`) off the slots.
- **CSG membership composes without mesh booleans.** The mesh engine's
  checks integrate point membership, and membership distributes over
  CSG: inside a union is inside any operand, inside an intersection is
  inside all, inside a difference is inside the base and no tool. The
  stdlib engine therefore evaluates booleans *exactly for checking
  purposes* with zero new dependencies. Rendering a cut solid as a
  mesh is different: true boolean meshes need the `[cad]` engine, and
  without it the viewer draws the base with tools ghosted translucent
  (an honest visual, documented).
- **Volume and mass properties become computable measures.** Primitive
  volumes are closed-form, CSG volumes come from the cad engine or the
  existing quadrature, and a density or mass attribute on the owning
  part yields center-of-gravity roll-ups over the placed solids. These
  feed requirements through the same `values=` seam `geometry_checks`
  uses today ("the CG shall stay within this box" becomes writable).
- **Checks gain model-defined subjects.** Occlusion and overlap keep
  their signatures. New model-driven checks become writable:
  interference volume between two *named* spatial items, keep-out
  zones (an envelope item marked as forbidden volume plus an exempt
  list), and the per-configuration checks the T7 contract needs. Each
  is the existing boolean/quadrature machinery pointed at
  model-declared solids instead of builder-stamped ones.
- **M0 keying is native.** The compiler emits `tag_parts`-style keys
  as it builds, per configuration and per individual. The mapping
  argument of `tag_parts` becomes unnecessary for compiled scenes.

## JupyterCAD, assessed honestly

Should JupyterCAD replace cadquery? The
question decomposes into three roles -- engine, document format, and
viewer -- and the honest answer differs per role. Facts first, all
verified against jupytercad 3.4.2 in a scratch venv:

- **License:** BSD-3-Clause across `jupytercad`, `jupytercad-core`,
  `jupytercad-lab`, `jupytercad-app`. cadquery is Apache-2.0 (verified
  2.8.0 metadata). No license obstacle either way.
- **There is no Python-side geometry kernel.** `jupytercad_core` is
  212 KB of pydantic schemas and server handlers. The OCC kernel is an
  8.2 MB WebAssembly binary shipped as a *browser* labextension asset
  (`jupytercad.opencascade.wasm`). Booleans, fillets, and the shape
  metadata (mass, center of mass, inertia matrix) are computed by the
  browser worker for display. The Python `CadDocument` API is a
  collaborative-document client (pycrdt/Yjs over a Jupyter comm) that
  *records operations*. It computes nothing.
- **The meta-package is heavy.** `pip install jupytercad` brings
  jupyterlab plus the jupyter-collaboration stack: 115 packages,
  247 MB (measured in the scratch venv).
- **The JCAD document format is small and public.** A `.jcad` file is
  JSON (schemaVersion 3.0.0): a list of objects, each with a `shape`
  from a closed enum -- `Part::Box`, `Part::Cylinder`, `Part::Sphere`,
  `Part::Cone`, `Part::Torus`, `Part::Cut`, `Part::MultiFuse` (union),
  `Part::MultiCommon` (intersection), `Part::Extrusion`,
  `Part::Chamfer`, `Part::Fillet`, `Sketcher::SketchObject`, and
  `Part::Any` (inline BREP/STEP content) -- plus parameters and a
  placement (`Position`, `Axis`, `Angle`). Fillet and chamfer
  reference edges *by integer index*, a fragile identity this design
  declines to adopt (see the fidelity ceiling).

The verdict, per role:

1. **Engine: no.** JupyterCAD cannot fill the engine role from Python
   at all -- its kernel lives in the browser. The exact-boolean engine
   stays cadquery/OCC behind the explicit `[cad]` extra (conda-forge,
   ~1 GB, opt-in as today), and the stdlib mesh engine stays the
   dependency-free fallback. cadquery is irreplaceable
   in the one role JupyterCAD cannot play.
2. **Document format: yes, as an export target.** The primordial set
   maps nearly one-to-one onto JCAD: primitives to `Part::*`, the
   union to `MultiFuse`, `DifferenceSolid` to `Cut`,
   `IntersectionSolid` to `MultiCommon`, placements to
   Position/Axis/Angle. A `to_jcad()` exporter is plain JSON
   construction -- zero new dependencies, no OCC required. Lofted
   wings and lathed bodies do not map parametrically. They export as
   `Part::Any` BREP payloads when `[cad]` is present and are omitted
   (with a warning) when it is not. What export buys: any longeron
   model's geometry opens in JupyterCAD's editor beside the notebooks,
   collaboratively, without longeron depending on JupyterCAD at all.
3. **Viewer: keep ours.** Longeron's viewer is not a generic CAD
   viewer. It is the linked-selection surface (tree, diagram, plot,
   3D, one selection seam) and the per-configuration scene the
   curriculum's T7 mandates. JupyterCAD's viewer knows nothing of
   model identities or M0 individuals. Users who want a CAD-editing
   surface open the exported `.jcad` in JupyterCAD themselves.

Import (JCAD to model) is deliberately out of the first slice: the
useful direction for a source-of-truth tool is model-outward, and
round-tripping edits made in a free-form editor back into model
content is a provenance problem this design does not open.

## Migration path: from builders to compiler

The existing builders are not deleted, and the migration is honest
about what they contain that the model does not.

1. **The heuristics migrate into the model as catalog content.** Motor
   can sizes today come from `_MOTOR_DENSITY` and `_MOTOR_ASPECT` in
   Python. Those numbers become attributes with defaults in the parts
   catalog (a motor part *states* its can diameter and height, or
   derives them from mass by a calc the model owns). This is the
   model-derived posture applied to geometry: a documented heuristic
   is model content wearing a Python costume.
2. **The example models grow envelopes.** `drone.sysml`'s parts gain
   envelope items and placements (battery box, ESC board, motor
   cylinders, prop discs, camera body with its boresight). The
   builders' output is byte-comparable against the compiled output
   during the transition, which is the correctness gate.
3. **The builders become fallback, then compiler targets.**
   `drone_geometry` and its siblings keep working for models without
   declared geometry (nothing breaks). Once the curriculum models
   carry geometry, the builders' role shrinks to synthesizing
   *derived* layouts (the N-arm frame derivation from prop spacing is
   genuinely parametric layout logic, and it can stay as the calc
   behind a model default). Deprecation of the public builder surface
   is not scheduled in this design. It follows only after the
   curriculum ships on compiled geometry.
4. **`to_cadquery` generalizes.** Its job (parametric solids from a
   recipe) becomes the cad-engine backend of the compiler. The
   `mesh["cad"]` recipe stamp survives as a compiler artifact.
5. **Checks keep their contracts.** `occlusion_report`,
   `overlap_report`, and `geometry_checks` keep signatures and engine
   semantics. They gain the ability to take compiled scenes, and the
   drone's `installation` requirement (examples/drone.sysml lines
   739-780) is re-measured from model geometry as the acceptance test.

## The fidelity ceiling, stated explicitly

The purpose is bounded: reasonable bounding volumes and shapes for
constraint evaluation in SysML v2. Not hi-fi CAD. The ceiling, drawn
as design commitments:

- **Primitives, CSG over primitives, and named-family lofts.** No
  free-form BREP modeling, no NURBS surfaces, no constraint-based
  sketcher.
- **No topological naming.** Edge operations (fillet, chamfer) apply
  only to *named* primitive features ("all edges of the base face"),
  never to computed intermediate topology. Persistent edge identity
  through boolean rebuilds is the classic hard problem of feature CAD,
  JCAD's edge-by-index is the cautionary example, and bounding volumes
  do not need it. Fillet/chamfer are accepted as decorative extensions
  with this ceiling named in their docs, and they compile only on the
  `[cad]` engine.
- **Tessellation and quadrature accuracy as today.** Segment counts
  and resolutions stay explicit parameters with the existing accuracy
  contract (nonzero readings are real, zeros mean "nothing
  grid-cell-sized").
- **Kinematics: rigid links, ideal joints, forward composition only.**
  No compliance, no dynamics, no friction, no inverse-kinematics
  solver in core (a program that needs IK can drive the joint
  attributes through the OpenMDAO bridge as an optimization, which
  already exists). Range checks are sampled, not continuous, and swept
  volumes are approximated by pose sampling and reported as such.
- **Mass properties at uniform-density envelope grade.** Good for CG
  envelopes and roll-up sanity, not for certified mass accounting.

## What we deliberately do not build

- **No trimesh, and no mesh-boolean library.** CSG membership
  composes analytically in the existing quadrature engine, and exact
  booleans belong to the `[cad]` engine. A mesh-boolean dependency
  would buy only prettier fallback rendering of cut solids.
- **No JupyterCAD dependency.** Export is plain JSON. The
  collaboration stack (115 packages) never enters longeron's tree.
- **No STEP/BREP import.** Model-outward only, per the JupyterCAD
  verdict.
- **No IK, no physics, no collision engine.** Forward kinematics and
  sampled checks only, per the fidelity ceiling.
- **No geometry in the interpreter's hot path.** Compilation runs per
  configuration/interpretation, like the builders today (baked once,
  milliseconds, no CAD kernel in the render loop). The floats-only
  invariant of instance and M0 slots is untouched.
- **No `standard library` labeling of longeron extensions.** The
  `Longeron*` packages ship as longeron-authored libraries, visibly
  distinct from the vendored OMG content.

## Phasing

The finish-then-tag decision (2026-08-28) holds: v0.11.0 waits
for the unification arc, and nothing in this design lands in 0.11.
The 0.12 headline is the curriculum rebuild. Geometry as model content
is the arc after it, sized in slices:

- **Phase 1 -- static primordials (the smallest honest slice).**
  Vendor `ShapeItems` + `SpatialItems` + `ISQSpaceTime` (piggybacking
  the units design's vendoring question), extend `KernelShim`, ship
  `LongeronGeometry` (booleans only), build the compiler to the mesh
  engine, key by configuration/individual, and re-measure the drone's
  `installation` requirement from model geometry. Deliverable: the
  drone example carries its own envelopes, and the existing checks
  read them.
- **Phase 2 -- the cad engine and the wing.** Compiler backend to
  cadquery solids, exact CSG, `LongeronAero` with the multisection
  wing as the documented domain-extension example, JCAD export, and
  volume/CG measures through the `values=` seam.
- **Phase 3 -- kinematics.** `LongeronKinematics`, frame-chain
  composition, poses as M0 facts, the deployable solar panel with
  states driving poses, the 3-DOF arm as the worked example, the
  11-joint underconstrained arm as the scale test, and pose-sweep
  interference through trades/verify.
- **Phase 4 (unscheduled) -- surfaces that ride later.** JCAD import,
  `GeometryView` as a longeron view kind, swept-envelope upgrades, and
  builder deprecation decisions.

Each phase is independently shippable, and phase 1 alone delivers the
core goal: primordial CAD elements, position and orientation, and
constraint evaluation over model-owned bounding volumes.

## Decisions

All ten were adopted on 2026-08-28.

1. **Booleans: standard union plus labeled extensions.** Union rides
   `SpatialItem` `componentItems` wherever composition is "this
   thing is made of these things"; `LongeronGeometry` adds
   `DifferenceSolid`/`IntersectionSolid` (and an explicit `UnionSolid`
   for closed CSG trees) as clearly labeled extensions. They map
   one-to-one onto JCAD's `Cut`/`MultiCommon`/`MultiFuse`, and the
   grounded union stays grounded.
2. **Extension packages: three longeron-authored library files** --
   `LongeronGeometry`, `LongeronAero`, `LongeronKinematics` -- shipped
   in the package beside the vendored stdlib but in a separate
   directory (the `analysis_conventions.sysml` precedent, promoted to
   an importable library location), never labeled `standard library`,
   each opening with a doc comment naming itself an extension.
3. **JupyterCAD: document format only.** Longeron ships a
   zero-dependency `.jcad` exporter (primitives
   and booleans parametrically, lofts as BREP payloads when `[cad]` is
   present), takes no dependency on any jupytercad package, keeps the
   in-house viewer as the linked-selection surface, and defers import
   indefinitely.
4. **cadquery stays**, unchanged
   in role and packaging -- the exact-boolean engine behind the
   explicit `[cad]` extra (conda-forge). JupyterCAD cannot replace it
   (no Python-side kernel, verified), and the stdlib mesh engine
   remains the no-extra fallback. Revisit only if a lighter OCC
   binding with cp313 wheels changes the packaging calculus.
5. **Landing: phase 1 opens the 0.13 arc.**
   Nothing lands in 0.11 (the tag waits only for the unification arc), and
   nothing in 0.12 (the curriculum owns it). The curriculum's T7 gains
   a model-geometry epilogue
   when phase 1 ships. Adopting this design now lets the 0.12 model
   authoring leave attribute names ready for envelopes.
6. **The fidelity ceiling stands as stated**:
   primitives + CSG + named-family lofts, no
   topological naming (edge operations on named primitive features
   only, `[cad]`-engine only), rigid ideal kinematics with sampled
   range checks, uniform-density mass properties. Every check's report
   names its engine and its accuracy contract, as the existing checks
   already do.
7. **Joints are grounded in the standard as
   parameterized specializations over the vendored transformation
   vocabulary** -- a `RevoluteJoint` is semantically a `Rotation` with
   limits and a named degree of freedom, a `PrismaticJoint` a
   `Translation`, composed through the `SpatialItem` frame chain the
   standard already defines. No new frame algebra, no competing
   placement mechanism, and the joint defs live in
   `LongeronKinematics` marked as extensions (the spec ships no joint
   vocabulary -- verified, zero occurrences).
8. **Poses are layered across all three levels.** Joint parameters are ordinary
   M1 attributes (the possibility space). Named poses (stowed,
   deployed) are attribute-binding sets that states reference, so the
   state machine drives deployment and `record_timeline` animates it.
   A concrete pose is an M0/interpretation-level fact carried in
   individual slots, swept by trades and hunted by verify. The
   interpreter stays floats-only.
9. **Articulation envelopes come from
   the existing two engines over sampled poses** -- grid/LHS sweeps
   through the trades machinery for coverage, `hunt` for adversarial
   pose search with shrinking, exact per-pose booleans on `[cad]`.
   No kinematics/collision dependency (FCL-class engines are above
   the ceiling), and every range verdict is reported as sampled, not
   continuous.
10. **Kinematics waits for the static slice.**
    Static bounding volumes (phase 1) are the smallest honest
    slice and prove the compiler, the keying, and the check plumbing.
    Kinematics (phase 3) reuses all of it and adds only the frame
    chain and pose machinery. The solar panel is the deliverable
    example, the 3-DOF arm the worked chain, the 11-joint arm the
    scale test, and the James Webb deployment stays the aspirational
    benchmark, not a scheduled deliverable.

## References

- OMG Systems Modeling Language (SysML) v2.0, Part 1: §9.7 Geometry
  Domain Library (printed pp. 582-586: Spatial Items pp. 582-585,
  Shape Items p. 586), §9.2.20.2.4 `GeometryView` (printed p. 548),
  §9.8 Quantities and Units (frames: `Spatial3dCoordinateFrame`
  family, printed pp. 638-646).
- Pinned corpus at `de1070ae`: `Domain Libraries/Geometry/
  {ShapeItems,SpatialItems}.sysml`, `Domain Libraries/Quantities and
  Units/{ISQSpaceTime,ISQBase,MeasurementReferences}.sysml`,
  `Systems Library/StandardViewDefinitions.sysml`.
- Longeron surfaces: {mod}`longeron.analysis.geometry`,
  {mod}`longeron.analysis.viewer3d`, {mod}`longeron.analysis.link`,
  {mod}`longeron.analysis.mission3d`, {mod}`longeron.m0`,
  {mod}`longeron.analysis.verify`, `src/longeron/_stdlib/`
  (vendored subset + `KernelShim.sysml`).
- Sibling designs: [units](units.md) (vendoring decision 1, the
  floats-only invariant, model-derived posture),
  [M0 interpretations](m0-interpretations.md) (individuals and slots),
  [the notebooks rebuild](notebooks.md) (finish-then-tag, T7's
  per-configuration geometry contract).
- Verified versions: longeron 0.10.0, jupytercad 3.4.2
  (scratch venv, 247 MB / 115 packages measured), cadquery 2.8.0
  (Apache-2.0), pydantic 2.13.5.
