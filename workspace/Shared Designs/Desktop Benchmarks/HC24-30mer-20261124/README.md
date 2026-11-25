# Standard desktop acceptance fixture

Open `HC24-polymerization.nadoc` for the part or `HC24-30mer.nass` for the
straight, open-ended 30-copy assembly. Keep both files in this directory under
the workspace's `Shared Designs` folder; the assembly references the part by
its portable workspace-relative path.

User-selected recipe, November 24, 2026: copy the honeycomb cross-section of an
existing 24HB reference and apply Seamed Autoscaffold, Full Autostaple and Route
for polymerization. Cross-section and initial 126-bp length come from the recorded
bundle input in `24hb_0xT.nadoc` (source hash is embedded in the new part metadata).
No strands or molecular coordinates were copied from that reference.

The saved part records all four native construction commands. Its 24 periodic
seams remain part-owned; the assembly separately records Add Part and Polymerize
(30 copies, forward, 29 joins). The part contains 7,056 nucleotides and the
assembly represents 211,680 nucleotides. No simulation materialization or
strand-extension conversion was performed. Periodic seam closure distances in
an isolated monomer are not ordinary terminal extensions.

Publication used `scripts.agent_structure_guard.publish` for the part and
`scripts.guide_assembly_audit.publish` for the assembly. The saved/reopened part
and upstream assembly process are independently replayed by
`scripts/build_desktop_reference.py --audit-existing`. Development benchmark
reports and screenshots stay local under `.development-artifacts/desktop-milestones`.
See `docs/desktop_install.md` for the installed-app workflow and measurement limits.
