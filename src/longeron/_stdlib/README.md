# Vendored SysML v2 standard library (curated subset)

Source: https://github.com/Systems-Modeling/SysML-v2-Release
Path: sysml.library/ (Systems Library + Quantities and Units domain library)
Pinned commit: de1070ae8e79c21532b8004fc663d47b35d0e9fa
License: LGPL-3.0 (see the source repository)

Contents: all 21 Systems Library files, 11 core Quantities-and-Units
files (the large specialized ISQ extensions are omitted), and 2 Analysis
domain-library files (AnalysisTooling, TradeStudies -- the surfaces
design's tool-binding and objective vocabulary). The KerML Kernel
Libraries are not vendored: KerML is parse-only in this package, so a small
shim (KernelShim.sysml) provides the kernel names user models commonly
reference (ScalarValues, Base, Collections, and the ScalarFunctions /
ControlFunctions package names TradeStudies imports).

The extensions/ directory is different: it holds LONGERON-AUTHORED
libraries (LongeronSurfaces), self-declaring in their doc comments and
never labeled standard.  They ship beside the vendored OMG content so
user models can import them, and scripts/vendor_stdlib.py leaves them
untouched.

Refresh with: python scripts/vendor_stdlib.py
