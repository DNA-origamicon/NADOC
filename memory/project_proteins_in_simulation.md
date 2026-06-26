---
name: project-proteins-in-simulation
description: Including imported PDB proteins in oxDNA + MD simulations — plan + Phase 1 (ANM-oxDNA fork) done
metadata: 
  node_type: memory
  type: project
  originSessionId: b1b2781c-6b84-4312-8107-fb51b6b00637
---

# Proteins in oxDNA + MD simulations

Goal: make imported-PDB proteins (`ProteinAsset`/`ProteinAttachment`, today display-only — see
[[project-protein-attachment]]) participate in oxDNA + NAMD/GROMACS as **near-rigid bodies with
excluded-volume surface repulsion**, tethered to DNA only where conjugated, and conformationally inert
across any salt (we don't care about protein dynamics). Sibling of [[project-oxdna-relaxation]].

**Authoritative plan + as-built log:** `~/.claude/plans/proteins-in-oxdna-and-md.md` (read it first).

## Locked decisions (user, 2026-06-19)
- oxDNA: adopt the **ANM-oxDNA fork** (`sulcgroup/anm-oxdna`, `interaction_type=DNANM`); per-residue Cα ANM,
  **stiff** (near-rigid); DNA↔protein = excluded volume; conjugation = `mutual_trap` spring (prot bead ↔
  handle nt). Mainline oxDNA has NO DNANM → genuine 2nd binary.
- MD: all-atom CHARMM36 (reuse psfgen pipeline) + **Cα elastic-network restraints** (extraBonds) so it holds
  its fold at any salt; click linker = harmonic bond to handle terminus.
- Scope: **ALL attachments** (conjugated → tether to its real OH_BINDER strand terminus; free/overhang → a
  positional anchor trap so they don't drift).

## PART B (MD) DONE (2026-06-19) — all-atom NAMD/GROMACS protein inclusion ✅ (suite 2727/55, ruff clean)
Imported PDB proteins now participate in all-atom NAMD/GROMACS as near-rigid bodies (Cα ENM holds
the fold at any salt; click linker tethers to the DNA handle). Real psfgen (installed at
`~/Applications/NAMD_3.0.2_*/psfgen`) builds a combined DNA+protein PSF that passes the charge audit.
Live multi-ns run = **MV-MD-PROT** (PENDING). Plan: `~/.claude/plans/proteins-in-oxdna-and-md.md`.
- **B1** `atomistic.build_atomistic_model(..., include_proteins=False)` (opt-in, default OFF → live
  3D view + all existing callers byte-identical, no double-render) + new
  `protein.build_protein_attachment_atoms`: world-places each visible attachment's atoms via the
  SAME `compose_protein_world_transform` (nm), distinct chain id `PA`/`PB`…, `__protein__{att.id}`
  sentinel, distance-inferred bonds. Applied at BOTH return paths. `pdb_export` iterates
  `model.atoms` → proteins flow through. The MD package builders pass `include_proteins=True`.
- **B2** CHARMM36m protein FF added to `backend/data/forcefield/` (`top_all36_prot.rtf`,
  `par_all36m_prot.prm`). `namd_topology`: protein-aware segids (`P000`)/resnames (HIS→HSD)/pdbaliases
  (ILE CD1→CD, OXT→OT2) + `topology top_all36_prot.rtf`; protein segments use `first NTER/last CTER`,
  NO DNA DEO5/DEOX. `namd_helpers._render_namd_conf(name, has_protein)` adds
  `parameters par_all36m_prot.prm` + `extraBonds on`; `namd_package` bundles the FF + writes
  `extrabonds.txt` when proteins present; `complete_psf(design, model)` threads the protein model.
- **B3** NEW `backend/core/protein_enm.py` (pure, tested): `enm_extra_bonds` (Cα–Cα within 12 Å,
  stiff k=10, ref=current sep) + `linker_extra_bonds` (one click bond per conjugated attachment,
  conj atom ↔ handle terminus via the SHARED `oxdna_protein.binder_terminus_nuc_key`). NAMD order
  `bond i j k b0` (0-based; note legacy `export_dry_implicit_restraints` writes b0 then k — untouched).
- **B4** `namd_solvate` full-topology (psfgen) path carries proteins → TIP3P+ions pack around them
  (salt-robustness from the ENM, not ion tuning). Legacy heavy-atom solvate stays DNA-only.
- **B5** `gromacs_package._pick_ff(require_protein=)` blocks AMBER for protein jobs (CHARMM36 only);
  `build_gromacs_package` threads `include_proteins=True` into the pdb2gmx input.
- **B6** `tests/test_protein_md.py` (13): atoms/chains/world-pose/default-exclude, ENM
  cutoff/symmetry/ref-lengths/text-order, click linker, FF files, namd.conf, psfgen segment + a
  REAL combined DNA+protein psfgen build (audit passes).
- **Units gotcha:** atomistic model is nm, NAMD/PDB is Å (×10) — matched in `protein_enm._dist_ang`.

## Phase 1 DONE (2026-06-19) — fork builds (CPU+CUDA), GPU-validated, FULL feature parity ✅
- Clone at `~/anm-oxdna` (source `~/anm-oxdna/oxDNA`). **Both binaries built + run:
  CPU `~/anm-oxdna/oxDNA/build/bin/oxDNA`, CUDA `~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA`** (set
  `OXDNA_ANM_BIN` to the CUDA one). CUDA ran a real hybrid DNANM sim on the RTX 2080 Super (sm_75), OK.
- **Repro DONE:** `NADOC/scripts/build-anm-oxdna.sh` + `scripts/anm-oxdna-cuda13.patch` (clone→patch→
  regenerate CUB shadow→build CPU+CUDA; idempotent; `OXDNA_CUDA_ARCH`/`ANM_OXDNA_DIR` knobs). Clean-room verified.
- The ~2021 fork needed CUDA-13/g++-13 fixes (all in the patch): `<cstdint>` includes; removed
  `cudaThread*`→`cudaDevice*`; `helper_cuda` computeMode/clockRate stub; texture→`__ldg` migration in the
  simple-verlet list; **CUB `block_load_to_shared` `data()/size()` ambiguity** (CCCL13+libstdc++13, root-owned
  header → local `cuda_compat` shadow with calls qualified to `::cuda::std::`, prepended via `-I`); `-rdc`
  separable compilation for cross-TU `__global__` launches + **`static` on all header `__constant__`/`__device__`
  globals** (same names collide under `-rdc`); `-gencode` token-split + `OXDNA_CUDA_ARCH` knob. `std::ptr_fun`/
  `not1` are warnings only under g++13.
- **Phase-2 wiring TODO:** add `oxdna_runner.find_oxdna_anm()` resolving `OXDNA_ANM_BIN`→build_cuda→build,
  mirroring `find_oxdna()`/`find_dnanalysis()`.
- A real hybrid DNANM run (the fork's `ANMUtils/examples/Cage`) confirmed EVERY pipeline feature is honored:
  `DNANM` + `DNANM_relax` (capped relax), MC & MD, `max_backbone_force[_far]`, `max_io`, `mutual_trap`
  (prot↔DNA), `repulsion_plane` (surface), Debye-Hückel salt. So NO feature-degradation fallback needed.
- **Fork quirk:** several keys mainline makes optional are MANDATORY here (`restart_step_counter`,
  `time_scale`, `refresh_vel`) — the stage-input renderer must always emit them.
- **CUDA build deferred** (bounded CUDA-13 port: `cudaThreadSynchronize`×22, `computeMode`/`clockRate`
  already patched, a `std::data` ambiguity, removed texture-refs in one Verlet list). CPU fully unblocks dev
  (protocol is backend-agnostic). ~1–2 h follow-up when GPU throughput matters.

## Phase 2 DONE (2026-06-19) — pure oxDNA geometry/file core ✅ (full suite 2695 pass / 55 skip, ruff clean)
- `backend/core/protein_cg.py` — `protein_beads(asset, attachment, tip, outward)` = one Cα bead/residue in
  WORLD nm (via the renderer's `compose_protein_world_transform`; centroid fallback; `prev_index` resets at
  chain boundary; `is_conjugation` flag); `anm_springs(beads, cutoff=1.5nm)` (pairs i<j within cutoff);
  `AA_3TO1`/`aa_one_letter` (unknown→'G'); consts `ANM_CUTOFF_NM=1.5`, `ANM_SPRING_K_STIFF=50.0` (tunable).
  Tests `test_protein_cg.py` (9).
- `backend/physics/oxdna_protein.py` — `hybrid_topology_text` (5-field header, protein lines FIRST/neg strand,
  DNA n3/n5 shifted +N_prot), `protein_conf_lines` (15-float oxDNA-unit), `anm_par_text` (`i j r0 s k`),
  `dna_index_offset` + `dna_particle_index` (THE protein-first index map). Tests `test_oxdna_protein.py` (8).
- `oxdna_interface.py` — extracted `topology_rows()` from `write_topology` (behavior-preserving) so the hybrid
  reuses DNA topology logic. Format authority = fork's `ANMUtils/examples/Cage`.

## Phase 4b DONE (2026-06-19) — display + health pair, Kabsch-verified ✅ (suite 2714/55, frontend OK, vite build OK)
- **Keystone:** `_protein_lead_offset(data, order)=max(0,len-len(order))` auto-skips leading protein lines in
  ALL conf readers (`read_configuration`/`_full`/`read_trajectory_frames_full`) → DNA display + health +
  per-frame RMSD hybrid-correct, DNA-only byte-identical. `read_protein_bead_positions(conf, n_dna)`.
- **Health:** protein jobs → `dnanalysis_bin=None` (mainline DNAnalysis can't parse DNANM) → geometric
  `base_pair_retention` (now hybrid-correct). Gate stays 0 pending HBList threshold validation.
- **Display:** `unwrap_align_to_reference(..., extra_points=)` carries protein beads through the same
  unwrap+align (opt-in tuple return); `oxdna_protein.protein_display_transforms(conf,ref,design,geom)` →
  per-attachment rigid 4×4 (design→relaxed) via Kabsch; `/display` returns `proteins:[{attachment_id,
  transform[16 row-major]}]`. Verified by KABSCH RECOVERY test (90°+trans→1e-4).
- **Frontend:** `atomistic_renderer.applyOxdnaTransforms({id:[16]})`/`clearOxdnaTransforms()` (per
  `__protein__{id}` sentinel); `oxdna_display.proteinTransformMap` (pure) applied on display/cleared on stop;
  main.js passes `proteinRenderer` into `initOxdnaDisplay`. Tests in `oxdna_display.test.js`.
- **MV-OX-PROT (PENDING):** live GPU hybrid relax + on-screen protein-follows-DNA visual. Smoke
  env-blocked this session (needs separate FastAPI; --reload WSL2 wedge) — relied on vite build + unit tests.
- `test_oxdna_protein.py` now 27.

## Phase 4 DONE (2026-06-19, backend) — hybrid jobs through the live runner, REAL-FORK validated ✅ (suite 2710/55)
- `build_relaxation_stages(protein=True)`: parfile=anm.par all stages; mc/md_relax=DNANM_relax, equil=DNANM;
  absolute_forces (anchor traps) → fix_diffusion off; equil keeps equil_forces.txt (protein tethers persist);
  bp gate 0 for protein.
- `prepare_oxdna_job` branches on `has_proteins`: writes hybrid top/conf + anm.par; forces.txt =
  `write_mutual_traps(particle_offset=N_prot)` + `protein_forces_text`. `build_protein_blocks(design,geometry)`
  bridges attachments→blocks. `run_job` picks `find_oxdna_anm()` when any stage has parfile; resolves
  parfile/forces to abs paths. `render_stage_input` += parfile_name; `write_mutual_traps` += particle_offset.
  `routes_oxdna` create detects proteins. DNA-only path unchanged.
- REAL-FORK integration test: 6hb+5-bead-protein design through real prepare→render→fork run (MC stage, rc0,
  DNANM loaded). `test_oxdna_protein.py` now 24.
- **NOT DONE (frontend + polish, app-exercise needed):** (1) display overlay for relaxed protein beads
  (`oxdna_display`/`applyFemPositions` is DNA-only; need hybrid-aware `read_configuration` skipping leading
  N_prot lines + a protein overlay, e.g. Kabsch-fit asset→relaxed beads). (2) hybrid-aware health metric (A7:
  +N_prot offset on bp-retention/HBList — today mis-reads, gates 0 so jobs complete). (3) live MV-OX-PROT gesture.

## Phase 3 DONE (2026-06-19) — traps + protocol + binary-select + file-assembly, REAL-FORK validated ✅ (suite 2707/55)
- `oxdna_protein.py` += `conjugation_trap_text` (symmetric mutual_trap, stiff=1.424/r0=1.071),
  `protein_anchor_trap_text` (centroid-bead trap), `binder_terminus_nuc_key` (geometric nearest-end via
  `resolve_overhang_anchor`+`binds_overhang_id`), `protein_forces_text`, `hybrid_configuration_text`
  (protein-first + shared box). Extracted `resolved_nuc_map`/`box_nm_for_positions`/`nuc_conf_line` from
  `write_configuration`.
- `oxdna_protocol.py`: `OxdnaStageSpec` += `interaction`/`parfile`/`relax_type`; render emits
  `interaction_type=DNANM[_relax]`+`parfile`+`relax_type`+MC `refresh_vel` (fork-mandatory). DNA-only unchanged.
- `oxdna_runner.find_oxdna_anm()`: `$OXDNA_ANM_BIN`→build_cuda→build (protein jobs only).
- **REAL-FORK e2e:** assembled hybrid top/dat/par/forces (6hb+6-bead protein, 510 particles) RAN on the fork
  CPU binary — DNANM_relax loaded, anchor trap on particle 2 (centroid, protein-first index), OK.
- Tests `test_oxdna_protein.py` now 20.
- **Next (Phase 4 = runner+UI wiring):** `prepare_oxdna_job` protein branch (build blocks, write hybrid
  files+par+forces, pick find_oxdna_anm, dt=0.002), protein `build_relaxation_stages`, routes detect proteins,
  display overlay for protein beads.

## CRITICAL format finding (corrects the plan's first draft)
Hybrid topology lists **PROTEIN particles FIRST (idx 0..N_prot−1), DNA AFTER**. So our existing
`_strand_nucleotide_order` DNA indices need **`+N_prot` offset** in ALL traps/anchors/WC-pairs for protein
jobs. Concrete `.top`/`.par`/`.dat`/trap formats are in the plan file (captured from the fork's own examples).
