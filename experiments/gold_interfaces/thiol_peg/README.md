# Neutral PEG–thiolate–gold interface preparation

2026-09-15. **Not yet an executable PEG–Au model.** The source audit identifies
what can be reused and what is missing. No junction constants or charges have
been invented, and no new dynamics have been run.

## Reproduce the audit

From the repository root, choose a new output filename:

```bash
uv run python -m experiments.gold_interfaces.thiol_peg.audit \
  --output .development-artifacts/gold_peg_thiol_20260915/basis_audit.json
```

The audit reads the active gold model, organic parameter files and pinned ether
assets. It records hashes, parameter observations and the shared interface
contract. Existing output files are never overwritten. `simulation_ready: false`
is an assessment result, not a failed audit execution. The checked-in
[basis audit](basis_audit_20260915.json) records the current findings.

## Existing pieces, and what they actually represent

| Path | Reusable piece | Missing chemistry |
| --- | --- | --- |
| `gold_model`, `gold_geometry`, `namd_gold_package` | Same neutral IFF Au type and lattice geometry for slabs and particles | No Au–S parameters or ligand builder |
| `nanoparticle_atomistic` / `top_np_thiol.rtf` | Explicit organic DNA–C3–thiolate graph | Gold is an implicit sphere; sulfur uses a positional restraint; no PEG |
| `namd_electrode_peg` / pinned ether release | CHARMM ether repeats | Methyl-capped chain, no sulfur; a mechanical graft is not an Au–S bond |
| `NanoparticleConjugation.peg_thiol` | Authored scheme and coverage intent | NAMD molecular topology is explicitly unsupported |

The existing `S CT2 198.000 1.8180` parameter is an **organic S–C** interaction.
It is not a gold bond, despite being available in the same force-field load set.
Both pinned ether files match their existing SHA-256 identities.

## Shared basis to implement

Use a single chemistry/parameter record for both planar and nanoparticle builders:

- Explicit precursor and bound-product atom graphs, end groups, spacer and repeat
  count convention. The bound sulfur's retained hydrogen count must follow the
  selected adsorption model; do not attach an intact thiol while labeling it thiolate.
- Versioned Au–S interface model with complete parameter sources and conventions.
  Include every junction bond, angle, torsion, improper and nonbonded exception.
- Separate declared ligand, gold and complete-cell charge balances. No applied
  voltage/excess charge does not imply that all interfacial partial charges vanish.
  Do not remove an S–H atom and silently discard its partial charge.
- Immutable atom mapping to real Au sites. Surface shape supplies geometry and
  local coordination; it must not silently select another force field.
- Binding motif is explicit. A flat-surface site and a nanoparticle staple are not
  interchangeable merely because both contain Au and S.
- Retain the established solvent and gold parameters where supported; any model
  replacement or junction transfer must be recorded and separately assessed.

Initially target a preassembled, fixed-connectivity ligand layer without DNA,
using physical masses and small slab/particle fixtures. This can establish local
structure and hydration. It cannot establish spontaneous chemisorption, ligand
exchange, reconstruction or rupture strength.

## Literature decisions

1. **GolP-CHARMM Au–S extension (2019), DOI 10.1021/acs.jctc.8b00992.**
   The inspected manuscript changes local surface types and adds a hollow-site
   dummy anchor. Table 2's bonded terms supplement that modified surface model.
   They are not standalone bonds between sulfur and an arbitrary real IFF Au atom.
   Its harmonic curvature is expressed as `k = 2 α² D`; CHARMM's `K(r-r0)²`
   coefficient requires the corresponding factor-of-two convention check.
   [Author manuscript](https://discovery.ucl.ac.uk/10065982/1/golp-paper-r1-ms-zf.pdf)
2. **Thiolated PEG on planar and spherical gold (2024), DOI 10.1021/acs.jpcb.3c05238.**
   Useful evidence for a shared slab/particle treatment, but it uses OpenMD,
   EAM/DR-EAM gold, a largely united-atom ligand model and SPC/E water. It is a
   reference model to reproduce, not a drop-in CHARMM/IFF parameter bundle.
   [Paper](https://arxiv.org/html/2312.05689)
3. **ALK–PEG-coated IFF nanoparticles (2025), DOI 10.3390/jcs9060294.**
   Uses GAFF/RESP organic parameters with a C11 spacer and terminal carboxylate.
   That charged, chemically different ligand does not establish neutral
   methoxy-/hydroxy-PEG-thiol parameters for our builder.
   [Author-hosted paper](https://boa.unimib.it/retrieve/ee7f2d17-916b-4496-a911-ff9c483741e0/Siani%20et%20al-2025-J.%20Compos.%20Sci-VoR.pdf)

Downloaded source PDFs/text are in `.development-artifacts/gold_peg_thiol_20260915/`.
These findings rule out simply joining the existing sulfur endpoint to the
nearest gold atom and borrowing a published spring constant.

## Next executable milestones

1. Resolve the exact PEG-thiol chemistry. The user was asked to distinguish
   methoxy-PEG-thiol, hydroxy-PEG-thiol and a specific purchased product. No
   answer or final chemical structure has been recorded in this audit.
2. Obtain or parameterize a complete interface model for that graph. Use the
   selected gold model's reference energy/force curves, not an unrelated Au–S
   bond constant. Preserve source-specific binding motifs and charge accounting.
3. Build isolated small slab and particle candidates using the same ligand
   topology and interface parameters. Review atom graphs, geometry and charge
   accounting before enabling ordinary simulation/export paths.
4. Verify complete parameter coverage and exclusions, native energy/force
   agreement and timestep/restart behavior, then solvent/PEG structure and
   model-specific Au–S binding geometry against external evidence.

A stable tethered trajectory is not evidence that an Au–S force field is correct.
