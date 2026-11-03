# Provisional TT-CPD numerical models

These four isolated external CGenFF-derived parameter packages passed the finite
numerical admission panel documented in
[the scope audit](../../../docs/audits/cpd_mvp_final_scope_audit_20261017.json).
They are not installed in production and do not replace the legacy cis-syn model.
See USAGE.txt for loading and scope restrictions. Each model directory includes
the patch, parameter overlay, chemical definition and transfer provenance.

Manifest absolute paths identify archived provenance and reproducible historical
runs; they are not dependencies of ordinary tests or the application. Loading a
candidate requires separately installed CHARMM DNA/CGenFF parent libraries matching
the recorded hashes. Those libraries and bulk simulations are not redistributed.
Do not combine packages in one system: their isolated atom-type and patch names
collide. Coordinates must independently satisfy the selected isomer's chemistry.

Physical accuracy, equilibrium populations and parameter equivalence remain
insufficiently established. No additional fitting follows from numerical stability.
