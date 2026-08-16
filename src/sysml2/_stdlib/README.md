# Vendored SysML v2 standard library (curated subset)

Source: https://github.com/Systems-Modeling/SysML-v2-Release
Path: sysml.library/ (Systems Library + Quantities and Units domain library)
Pinned commit: de1070ae8e79c21532b8004fc663d47b35d0e9fa
License: LGPL-3.0 (see the source repository)

Contents: all 21 Systems Library files and 11 core Quantities-and-Units
files (the large specialized ISQ extensions are omitted). The KerML Kernel
Libraries are not vendored: KerML is parse-only in this package, so a small
shim (KernelShim.sysml) provides the kernel names user models commonly
reference (ScalarValues, Base, Collections).

Refresh with: python scripts/vendor_stdlib.py
