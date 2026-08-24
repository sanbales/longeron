# Longeron and OpenMBEE: integration paths (design)

Longeron and the OpenMBEE ecosystem solve different problems, and they meet at
open standards. This document describes the integration paths between longeron
and OpenMBEE's Flexo MMS, in order of maturity. It records design intent; no
adapter code exists yet.

## What each project provides

Longeron is a Python toolchain for SysML v2 models. It parses, validates,
executes, renders, and analyzes models, primarily inside notebooks. Longeron
includes a small git-backed server that implements the OMG Systems Modeling
API for local development. That server is a single-workspace convenience. It
is not a model-management system.

OpenMBEE is a NumFOCUS-sponsored open-source community for model-based
engineering environments. Its Flexo MMS is a graph-native version-control
system for structured data. Flexo stores models as RDF in a SPARQL 1.1
quadstore, with git-like organizations, repositories, branches, locks, and
commits. On top of Flexo, the `flexo-mms-sysmlv2` service implements the OMG
Systems Modeling API and Services specification (beta, Apache-2.0). OpenMBEE
also maintains a Python client, a web modeler, command-line tooling, and MCP
servers for the same API.

## Why the Systems Modeling API is the seam

Both projects implement the same OMG standard from opposite sides. Longeron's
`longeron.client` consumes the Systems Modeling API and fetches any project
and commit into an executable model. The `flexo-mms-sysmlv2` service produces
that API over Flexo's version store. When the two meet at the standard, each
project keeps its own scope: Flexo manages and versions models at
organizational scale, and longeron executes and analyzes them.

Integration at the standard boundary also stays portable. An adapter written
against the Systems Modeling API works with any conformant server, including
the OMG pilot implementation and future OpenMBEE releases.

## Path 1: longeron as a Systems Modeling API client of Flexo (near-term)

This path needs the least new code. `Client` already speaks the standard
projects, commits, and elements resources. Three known deltas remain:

1. **Authentication.** Flexo uses Bearer JWT everywhere. `Client` needs an
   `Authorization` header option. Flexo's SSO service supports OIDC login,
   API keys, and RFC 8693 token exchange designed for JupyterHub. That
   token-exchange flow fits longeron's notebook usage directly.
2. **Organization bootstrap.** The sysmlv2 service maps projects into a
   configured Flexo organization (default `sysmlv2`). A first-run helper
   should surface a missing organization as an actionable message.
3. **Conformance drift.** The sysmlv2 service is beta, and the OpenMBEE team
   tracks its specification gaps openly (pagination, `previousCommit`, error
   shapes). An adapter should tolerate these gaps, and interoperability
   findings should be reported upstream as issues. Longeron's client-side
   experience is useful test coverage for their conformance work.

Success for this path is one demonstration: `longeron.client` fetches a
project from a Flexo deployment, executes it, and pushes a change back as a
commit.

## Path 2: RDF interchange with Flexo layer 1 (near-term, read-mostly)

Flexo's native layer accepts RDF in standard serializations through the Graph
Store Protocol, with SPARQL query per branch, lock, or diff. Longeron's
`longeron.rdf` module already projects models to RDF triples. Publishing a
longeron-derived graph to a Flexo branch is therefore a small mapping
exercise: choose a vocabulary, then `PUT` the graph. Each accepted update
becomes a Flexo commit.

This path suits derived artifacts rather than round-trip model authoring. For
example, longeron can publish M0 interpretation populations, analysis
results, or requirement-verdict graphs next to the model they describe.
SPARQL users then query model and results together.

## Path 3: a Flexo-backed project store (longer-term)

Longeron's server reads models through a `ProjectStore` interface, which the
git-backed store implements today. A `FlexoProjectStore` implementing the
same interface would let longeron tooling browse Flexo-managed projects
without a local checkout. Flexo's refs and commits map naturally onto the
store's branch and commit semantics.

Two design constraints are known up front. First, merge-conflict resolution
is an open research area in Flexo, so an adapter must treat merges as a
client-side concern. Second, large models should flow through Flexo's bulk
load path rather than element-by-element writes. This path is worth
prototyping only after Path 1 proves the API-level round trip.

## What longeron can contribute back

Integration should benefit both communities. Three concrete contributions:

- **Conformance feedback.** Longeron's client and server both exercise the
  Systems Modeling API, so interoperability testing against the sysmlv2
  service produces actionable upstream issue reports.
- **Textual-notation coverage.** Longeron parses the full KerML and SysML v2
  grammars, with a reproducible sweep of the OMG training corpus. Tools in
  the OpenMBEE ecosystem that accept textual SysML v2 may find that corpus
  and parser useful for validation.
- **Executable-model demos.** Notebook demonstrations that fetch from Flexo,
  execute, and publish results make the combined workflow visible to both
  communities.

## Non-goals

- Longeron does not provide multi-user model management, access control, or
  organizational versioning. Those concerns belong to model-management
  systems such as Flexo MMS.
- Longeron's built-in server remains a local development convenience. It is
  not proposed as a deployment alternative to any OpenMBEE service.
- No OpenMBEE code is vendored or forked. Integration happens through
  published APIs and upstream contributions.

## References

- Flexo MMS overview: <https://www.openmbee.org/flexo.html>
- Layer 1 service: <https://github.com/Open-MBEE/flexo-mms-layer1-service>
- Systems Modeling API service:
  <https://github.com/Open-MBEE/flexo-mms-sysmlv2>
- OpenMBEE Python client:
  <https://github.com/Open-MBEE/sysmlv2-python-client>
- Deployment guide:
  <https://flexo-mms-deployment-guide.readthedocs.io/en/latest/>
- Longeron API server and client: [the API server guide](../guides/api-server.md)
