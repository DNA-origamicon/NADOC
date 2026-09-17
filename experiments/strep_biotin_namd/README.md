# Streptavidin–biotin–DNA development evidence

The [DNA junction implementation and latest GPU results](../../docs/biotin_dna_junction.md)
supersede the earlier "missing BTE/BTE5" preparation state. `build_dna_junction.py`
generates the isolated candidate; `build_junction_complex.py` applies it to a
gold-free design; `check_junction_gpu.py` runs bounded local GPU validation;
`analyze_junction_gpu.py` extracts the junction time series and reduced trajectory.
The candidate passes native mapping/charge/coverage and a 20 ps GPU-resident
check; production qualification remains separate.

These tools operate in isolated research directories. They do not change
application geometry or remove export guards. Only the explicit GPU-check
command launches a simulation.

## Parameter reuse and unmatched chemistry

`prepare_parameterization.py` copies the existing CHARMM36m protein and CHARMM
DNA files unchanged, with SHA-256 provenance. It also copies the official
CGenFF reference library and extracts its NMA, DME, DMEP and UREA definitions
for amide, ether, phosphate and ureido comparison. Those complete reference
residues retain their published types and charges. Their charges are **not**
silently transferred onto biotin or the modified junction.

The ligand-specific files used by Comer (2012) and Sedlak (2020) have not been
recovered from the public sources inspected. A fresh audit of the complete
February 2026 CHARMM archive also found no files mentioning biotin; see
`ws/references/biotin_archive_audit.json`. The historical 1997 assignment was
not adopted: a [CGenFF developer's methodological assessment](https://www.ks.uiuc.edu/Research/namd/mailing_list/namd-l.2012-2013/3619.html)
specifically recommends a modern CGenFF starting point instead.

## Build the assignment package

RDKit is an isolated development dependency; the application environment and
dependency lock remain unchanged:

```bash
uv pip install --python .venv/bin/python --target experiments/strep_biotin_namd/ws/tool_dependencies --no-deps rdkit==2025.9.6
PYTHONPATH=experiments/strep_biotin_namd/ws/tool_dependencies .venv/bin/python experiments/strep_biotin_namd/prepare_parameterization.py --output experiments/strep_biotin_namd/ws/parameterization_new
PYTHONPATH=experiments/strep_biotin_namd/ws/tool_dependencies .venv/bin/python experiments/strep_biotin_namd/validate_parameterization.py experiments/strep_biotin_namd/ws/parameterization_new
```

The reference files must exist in `ws/references/`; they came from the
[official distribution](https://mackerell.umaryland.edu/charmm_ff.shtml).
`--references` can select another directory. Always use a fresh output path.

Outputs:

- `BTMP.mol2` / `BTMP.sdf`: all hydrogens, original biotin stereochemistry,
  Biotin-TEG attached to a methyl-capped phosphate diester; net charge −1.
  MOL2 and SDF roundtrip to the same molecular graph. ETKDG coordinates are
  starting research conformers, not minimized geometries.
- `atom_mapping.json`: explicit names, hydrogen parents, ligand/phosphate/cap
  ownership. O5C/C5C and their cap hydrogens must never enter the final patch.
- `reference_forcefield.json`: exact files, source paths, roles and hashes.
- `parameterization_tasks.json`: unresolved chemistry, reference analogues and
  every modeled bond/angle/proper dihedral crossing O4T–P (1/4/7 terms).
- `qm_targets.json`: six named 24-point relaxed torsion scan definitions,
  atom indices, charge/spin and additional charge/bond-angle targets. These
  define work; no QM calculations or fitted values are implied.
- `validation.json`: chemical and native psfgen/reference coverage checks.

## Obtain and qualify assignments

With a licensed CGenFF executable, run inside the generated package:

```bash
cgenff BTMP.mol2 -a > BTMP.str 2> BTMP.log
```

Alternatively use an existing CGenFF account to submit the MOL2. No account
was created and no external submission was made by this workflow. A local
licensed executable was not found in the inspected application installations.
The [CGenFF CLI documentation](https://docs.silcsbio.com/2024/cgenff/usage.html)
describes assignment and output flags.

The user confirmed website access. Submit `ws/parameterization_final/BTMP.mol2`
through that existing account and retain the original downloaded `.str` and
assignment warnings. The current reference library is CGenFF 5.0; if the server
returns another version, obtain that matching library before auditing.

```bash
.venv/bin/python experiments/strep_biotin_namd/audit_assignment.py experiments/strep_biotin_namd/ws/parameterization_final /path/to/BTMP.str --output experiments/strep_biotin_namd/ws/parameterization_final/assignment_audit.json
```

The auditor checks reference hashes, library version, atom names, total charge,
connectivity and native PSF parameter coverage. Its report retains warning and
penalty summary lines for review; it never promotes the model to simulation-ready.
Five tests exercise the importer using real DMEP reference parameters, including
rejection of incompatible versions, incorrect charge and changed connectivity.

### Returned assignment (2026-09-16)

The user supplied `ws/parameterization_final/BTMP.str`, generated by CGenFF
program 4.0 for library 5.0. Its unchanged SHA-256 is
`ccfd4c2d4c0f3b4178ad4f6e4f64e1e55f72a3a49fdfdf4ff6a77d972e0e6bef`.
`assignment_audit.json` verifies the 68 atom identities, graph and −1 charge;
native PSF construction resolves 69 bonds, 129 angles, 171 proper dihedrals
and two impropers. The importer now recognizes the current server's version
header as well as the older form. The five importer tests passed.

Maximum bonded penalty is 26; maximum charge penalty is 16.547. No reported
penalty exceeds 50. Seven biotin ring atoms have charge penalties between 10
and 50. These are analogy diagnostics, not estimated physical errors. The
assignment is accepted as an **unvalidated parameter seed**, preserving all
values and torsion multiplicities. `assignment_qualification_plan.json` records
the specific moderate-penalty terms and prioritizes ring/pocket validation and
the actual DNA boundary. Coupled ring torsions must not be scanned as independent
full rotations through closed rings. The ligand fragment charge is −0.465 e;
its noninteger charge is not an error or a reason to renormalize it. Removing
the charged methyl cap and grafting the actual DNA requires a charge audit.

The original stream remains unchanged. No full DNA patch or MD validation is
claimed. The ParmEd checks warn about unsupported COLINEAR lone-pair definitions
elsewhere in the reference library; BTMP contains no such sites.

The MOL2 charge column contains **formal-charge placeholders**, not partial
force-field charges. Never use `-z` to retain them. Check the assigned total
charge and all warnings, preserve the complete returned stream, record its
program/library versions and review all penalties. An assignment is a seed,
not a validation result. Recovering compatible literature files would provide
an alternative seed; preserve their provenance and explicitly map their graph.

Refine only uncertain terms against compatible QM targets. The methyl cap
captures phosphate ester chemistry but cannot establish deoxyribose torsions:
the actual DNA sugar context remains required before constructing the BTE/BTE5
patch. Audit phosphate charge redistribution and all mixed CGenFF/CHARMM DNA
terms, including improper and multi-term torsion conventions. The recipe in
`scripts/prepare_strep_biotin_namd.py` must remain blocked until that package is
qualified.

Before any remote validation, qualify a GPU-capable engine/protocol and check
throughput. Every RunPod simulation attempt must use GPU acceleration, with
no CPU fallback; the cumulative budget is $5. No remote jobs were attempted.

`ws/parameterization_final/` retains the final input package and validation.
`ws/tool_dependencies/` supports reproducing it; `ws/literature/` retains source
texts. Temporary reference PSFs are deleted automatically after checking.

2026-09-16 update: Alpine GPU continuation **32611941** is submitted (the earlier
"no remote jobs" statement predates it). `ws/junction_alpine_5ns/` retains the
exact 5 ns continuation config/batch, upload archive, SHA-256 ledger, submission
receipt and extension validation evidence. These are reproducibility/monitoring
artifacts, not workspace designs. `submit_alpine_junction.py` rejects duplicate
submission; do not rerun it to monitor. `check_extension_app.cjs` performs a
browser-only bound-extension review, blocks backend writes and closes its browser
in `finally`; the checked-in application frontend is unchanged.
