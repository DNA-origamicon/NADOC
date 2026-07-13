---
name: project_snupi_reference_compare
description: "The autonomous NADOC→SNUPI→mimic comparator loop — BUILT 2026-07-12. Runs the REAL SNUPI software as ground truth; mimic reproduces SNUPI's RMSF (r 0.96–0.99) + correlation (0.97–0.997) near-exactly, but its 3 SOFTEST modes differ (MAC≈0)."
metadata:
  node_type: memory
  type: project
---

# SNUPI reference comparator — run the REAL SNUPI on NADOC designs, compare to our mimic

## ✅ BUILT + validated end-to-end (2026-07-12)

**Deliverables:**
- `backend/physics/snupi_reference.py` — pure, CI-safe: JSON shim, PDB/xyz/`.mat`(h5py) parsers,
  **node-matcher** (topological + spatial + boundary salvage), observable math (RMSD/RMSF/MAC/corr).
- `scripts/snupi_reference_compare.py` — machine-local orchestrator (env `SNUPI_HOME`/`SNUPI_MCR`;
  subprocess run; 3 mimic variants; optional 3-way NAMD). CLI `--only`, `--no-nma`, `--parse-only`.
- `tests/test_snupi_reference.py` — 15 CI-safe pins (parsers, shim, matcher: scramble/flip/salvage/reject).
- `backend/core/cadnano.py` — added `export_cadnano_with_labels()` (+ extracted `_export_layout`); the
  topological node-identity map. Export byte-identical (24 export tests green; test-smart FULL 4843 pass).
- Results: `experiments/exp42_snupi_cross_compare/reference.json`.

**The crux (node correspondence) — SOLVED cleanly.** SNUPI's chain `H{k+1}` == the k-th exported vstrand;
resSeq j == that vstrand's j-th duplex bp → topological map to NADOC `(helix_id, global_bp)`. Validated
spatially (Kabsch INIT residual: 6HB 0.015 nm, SQ 0.021 nm; 630/630 & 488/488). Key insight: nodes ALONG
a helix are 0.34 nm apart → pure NN can't disambiguate; matching is ORDER-based per helix, geometry only a
global gate + per-helix flip auto-resolve. SQ had a **2-bp H7↔H8 crossover-boundary swap** (SNUPI attributes
2 bp to the adjacent helix vs NADOC's duplex convention) — recovered by transform+capped mutual-NN salvage
(true partner ~0.02 nm ≪ 0.34 nm neighbour). Gate refuses (`ok=False`) below 98% coverage.

**Findings (mimic vs REAL SNUPI):**
| observable | 6HB (HC) | 3x4SQ | verdict |
|---|---|---|---|
| RMSF Pearson/Spearman | **0.986 / 0.991** | 0.962 / 0.942 | mimic reproduces SNUPI flexibility near-exactly (mag +12% on HC) |
| Corr Pearson / Generalized | **0.997 / 0.988** | 0.973 / 0.971 | DCCM matrices match |
| Shape RMSD (mimic ES-free vs SNUPI _STT) | 0.37 nm | 0.55 nm | close; corotational OVER-deforms (1.8 / 2.5 nm) — ES-magnitude gap, as [[project_snupi_gaps]] G-tables say |
| MAC (elastic only) | axial SNUPI-5↔mimic-23 **0.83**; bending SNUPI-7↔mimic-2 0.44 | SNUPI-7↔mimic-2 0.66 | elastic modes match; ranked differently (see below) |
| L_p bend (mimic) | 2430 nm | 71 nm | SNUPI eigenvalues in `.mat` (units TBD for a matched L_p) |

### ✅ RESOLVED: the "MAC≈0 for SNUPI's 3 softest modes" was an ARTIFACT, not a physical gap
SNUPI's free-free NMA **does NOT project out the 6 zero-frequency rigid-body modes** — its lowest saved
modes are rigid-body RESIDUALS (`rigid_body_fraction` = 1.000 for modes 1–3, 0.913 for mode 4; PR=1.0;
eigval ~1e7 ≪ the ~1e11 elastic modes). The mimic's `_nma_modes` drops all 6 rigid modes cleanly (rigid_frac
0.000), so it has no counterparts → MAC≈0. **Fix in the comparator**: `rigid_body_fraction(field, positions)`
annotates each SNUPI mode; the MAC now compares only elastic (`rigid_frac<0.5`) modes. After filtering, the
mimic DOES reproduce SNUPI's elastic mode SHAPES (axial 0.83, bending 0.44–0.66). **The genuine finding**:
the two models RANK the soft deformations differently — SNUPI's global axial-stretch is its *softest* elastic
mode (#5), the mimic's is #23 → **the mimic is much stiffer in axial stretch relative to bending than SNUPI**
(consistent with the corotational-ES over-stretch and the shape-gap story; ties to G10/ES calibration).

### ✅ RESOLVED: SQ 3-way NAMD (was 0.017 nm / r 0.079)
The DCD glob `*k0*.dcd` matched the **restrained annealing** run `k0p5` (k=0.5) — the `_p10/_p50/_p100`
suffix is trajectory PERCENTAGE, not restraint; only `k0` as a whole token (`_k0_`/`_k0.`) is unrestrained.
Fixed by `_pick_free_k0_dcd` (regex `_k0(?=[._])`, prefer production+longest-ns+`_p100`) **+ Kabsch-aligning
each frame** before RMSF. Now **SQ SNUPI-vs-MD RMSF r 0.71 / ρ 0.57** (matches exp42 ~0.74); 6HB r 0.55.
The genuinely-free 5 ns SQ run is `3x4SQ_18_production_5ns_k0_p100.dcd`.

### ✅ RESOLVED: L_p apples-to-apples (was "units TBD")
SNUPI's `.mat` eigenvalues/eigenvectors are in a different internal unit system than the mimic's (raw λ ~1e11
vs ~1e23) AND its coordinate frame is rigidly rotated ~90° from the mimic's. So L_p is computed **unit-free**
via `bending_amplitude_variance`: project each engine's physical NMA displacement covariance onto the analytic
free-free Euler–Bernoulli fundamental bending shape (⟨a₁²⟩, nm²), **each engine in its OWN geometry frame**
(mixing frames corrupts it — the bug that first gave a spurious 2.2×), then `L_p_snupi = L_p_mimic·⟨a₁²⟩_m/⟨a₁²⟩_s`.
**Result: 6HB mimic 2430 / SNUPI 2847 nm (1.18×); SQ 71.5 / 74.5 nm (1.006×).** L_p agrees to 1–18% — good,
NOT the factor-2 first feared. (The MAC axial-rank difference stands as a mode-ordering observation, but L_p
itself — the integrated bending stiffness — matches well.)

## ✅ Comprehensive metric audit (2026-07-12) — two bars, both met
The comparator now runs a **per-run self-consistency guard** (`sr.self_consistency` in the report; `ok=False`
if it fails): reconstruct every derived NMA output SNUPI stores from its OWN raw eigenvalues+eigenvectors and
match SNUPI's stored value. Verified SNUPI runs its NMA at **300 K (kBT=4.142)** and **drops the first 6 modes**
(reconstruction only matches with these). Full audit of every SNUPI output:

**A. Parse-fidelity (self-consistency, target <0.1% — ALL PASS at ~machine precision):**
| SNUPI output | our reconstruction | agreement |
|---|---|---|
| `NMA_RMSF` | kBT(300K)·Σφ²/λ from eigs, skip 6 | **5.1e-5 %** |
| `NMA_CORR_PEARSON` | DCCM from eigs | **1.7e-16** (machine) |
| `NMA_CORR_GENERAL` | Lange–Grubmüller MI from eigs | **3.4e-11** (machine) |
| PDB node coords | node-match to design geom (Kabsch) | 0.015 nm residual |
| `_NMA_MODE_*` xyz | vs `NMA_EIG_VEC` translational | \|cos\| 0.996 |
| node count / helix | duplex-bp topology | exact (630, 488) |

**B. Mimic-vs-SNUPI modeling (different models by design — bar is defensible noise, NOT 0.1%):**
| observable | 6HB | SQ |
|---|---|---|
| RMSF pattern Pearson/Spearman | 0.986 / 0.991 | 0.962 / 0.942 |
| RMSF magnitude (mimic/SNUPI mean) | 1.12× | 1.06× |
| Pearson / Generalized DCCM | 0.997 / 0.988 | 0.973 / 0.971 |
| Shape RMSD (ES-free) | 0.37 nm | 0.55 nm |
| **L_p bending** | 2430 / 2847 nm (**1.18×**) | 71.5 / 74.5 nm (**1.01×**) |
| MAC (elastic best) | axial 0.83, bend 0.44 | bend 0.66 |

**C. SNUPI outputs with NO comparable mimic quantity (not scored):** `STRUCT_ENERGY` (per-element strain
energy), `ELEC_ENERGY` (per-pair Debye–Hückel energy), `STACK_ENERGY`, `TRIAD_NODE` (nodal triads),
`NODE_*.mat` (redundant coords, rows ≠ plain xyz — PDB is the validated coordinate source), oxDNA/`.stl`/traj
geometry files.

**Quantified systematic:** the mimic's NMA uses **298 K (kBT=4.11)**, SNUPI **300 K (4.142)** → a **0.39 %**
RMSF-magnitude systematic (RMSF ∝ √kBT). Not fixed globally (KBT is shared with cando/exp42); flagged. The
remaining ~12 % RMSF-magnitude gap (6HB) is the model (mimic slightly softer), consistent with L_p 1.18×.

**Verdict:** within <0.1 % (machine precision) on every SNUPI output we can reconstruct from its raw data
(proves faithful parsing); on the genuine modeling comparison the mimic tracks real SNUPI tightly — RMSF/corr
0.96–0.997, L_p 1–18 %, shape sub-nm — with the elastic-mode MAC (0.4–0.8) the loosest channel.
New module fns: `reconstruct_rmsf`, `reconstruct_pearson_correlation`, `self_consistency`,
`bending_amplitude_variance`, `rigid_body_fraction` (pins in `tests/test_snupi_reference.py`, 20 total).

## ⚠ Environment note (machine-local)
- SNUPI `.mat` is **MATLAB v7.3 (HDF5)** → needs **h5py** (installed into the VENV only, `uv pip install h5py`,
  NOT in pyproject — the module soft-imports it; CI never sees a `.mat`). Re-install on the other computer if
  running there. Full-precision RMSF/corr/eigvecs are in `*_STT.mat` keys `NMA_RMSF`, `NMA_CORR_{PEARSON,GENERAL}`,
  `NMA_EIG_{VAL,VEC}` (eigvec layout per node = `[tx,ty,tz,rx,ry,rz]`, translational-first, matches mimic).
- **Do NOT use the PDB occupancy column for RMSF** — it is 1-decimal AND a DIFFERENT quantity (not NMA_RMSF).
- `.snp`: patch `Default.snp` (keeps every key). NMA runs WITHOUT a sequence CSV. SNUPI is FAST (NMA 0.4 s).

## Original plan (below, retained for reference)

**Goal:** close the loop the whole [[snupi-mimic]] project needs — validate our FEM mimic against the
*actual* SNUPI software (not just against NAMD). NADOC exports caDNAno JSON → real SNUPI predicts the
shape + NMA → parse its output → run our mimic on the same design → quantify per-observable agreement.
This is the tool that then drives closing the shape gaps (G10 canonical init config + electrostatics
calibration; see [[project_snupi_gaps]]).

## SNUPI is installed (2026-07-12, machine-local — THIS computer only)
- **App:** `~/SNUPI/` — the compiled `SNUPI` binary + `run_SNUPI.sh` + `EXAMPLE/` + `Input.txt` +
  `Default.snp` + `README.txt`. v3.10 linux (from `github.com/SSDL-SNU/SNUPI`, files live directly in
  the repo tree — download via `raw.githubusercontent.com/SSDL-SNU/SNUPI/master/SNUPI_v3_10_linux.zip`;
  the web "Download" button returns a rate-limit HTML page, hence the earlier corrupt download).
- **Runtime:** MATLAB Runtime **R2022b (9.13)** at `~/MATLAB_Runtime/R2022b` (silent-installed, no sudo).
- **Run:** `cd ~/SNUPI && ./run_SNUPI.sh /home/jojo/MATLAB_Runtime/R2022b` (headless OK; first launch
  extracts the CTF, ~1 min). Verified working on the bundled NMA example (converged + NMA + modes + corr).
- **NOT on the work computer, NOT in CI.** The comparator is a LOCAL analysis tool (like exp42/DCDs).

## SNUPI I/O
- **Input:** `Input.txt` lines = `<H|S>  <design_basename>` (H=honeycomb, S=square); per-design options
  in `<basename>.snp`; caDNAno **json** (+ **csv** for sequence). The `.snp` for our comparison wants:
  `DO_STT 1` (static shape) · `DO_ES 1 ES_TEMP 300 ES_MG 20 ES_R_CUT 2.5 ES_ITER_NUM 3` (electrostatics —
  identical params to our mimic) · `DO_NMA 1 NMA_MODE_NUM 200 DO_NMA_RMSF 1 DO_NMA_CORR 1 NMA_SAVE_NUM 5`.
  Start from `Default.snp` / the `EXAMPLE/*.snp`.
- **Output** → `~/SNUPI/OUTPUT/<name>_[YYMMDD_HHMMSS]/` (timestamped — glob it). Key files:
  - `_STT_STRCT.pdb` — **equilibrium shape** (also `_STT_oxDNA.conf/.top`, `_STT.mat`/`_STT_RES.mat`).
  - `_INIT_STRCT.pdb` — SNUPI's **canonical initial config** (the G10 reference — the 2.25 nm CO / twist).
  - `_NMA_MODE_1..5_{m,p}.{pdb,xyz}` — the **5 lowest mode shapes** (mode vector ≈ `p − m` or `p − REF`;
    `_NMA_MODE_REF.{pdb,xyz}` is the reference config).
  - RMSF (in the `.mat`, plus `_NMA_RMSF.fig`); `_NMA_CORR_{P,G}.png` — **Pearson + Generalized**
    correlation (data in the `.mat`).
  - `.mat`/`_RES.mat` parse in Python: `scipy.io.loadmat(f, squeeze_me=True, struct_as_record=False)`.
    `_STT_RES.mat` keys: `NODE` (node coords), `V`, `TR`/`CR` (triads), `PROP`, `E_CONN` (connectivity),
    `ES_DATA`. Prefer the `.mat` for numeric modes/RMSF/K; `.pdb/.xyz` for coordinates.

## What already exists on our side
- caDNAno export: `backend.core.cadnano.export_cadnano(design) → dict` (+ route `/design/export/cadnano`).
  **Confirmed SNUPI-compatible** (`{name, vstrands:[{num,scaf,stap,skip,loop,row,col,…}]}`). ⚠ CAVEAT:
  SNUPI's JSON has `scafLoop`/`stapLoop` arrays; NADOC emits `scaf_colors`/`loop` instead — the converter
  must add empty `scafLoop`/`stapLoop` and emit the **sequence CSV** SNUPI needs. Diff against a working
  `~/SNUPI/EXAMPLE/*.json` first.
- Mimic: `predict_shape(material="snupi")`, `_nma_modes`, `compute_rmsf_nma`,
  `compute_correlation_matrix`, `compute_generalized_correlation_matrix`, `persistence_length_from_nma`.
  Mimic FEM node keys = `(helix_id, global_bp)`.
- Comparison harness: `scripts/snupi_visual_compare.py` (mimic vs NAMD per-visual) — **add SNUPI as a
  third reference column here** rather than a parallel stack. Also `snupi_cross_compare.py`,
  `snupi_dccm_compare.py`, `experiments/exp42_snupi_cross_compare/`.

## Comparison plan (per observable: mimic vs SNUPI, ideally 3-way with NAMD)
- **Shape:** per-bp RMSD (Kabsch) to SNUPI's `_STT_STRCT.pdb` + twist/bend/span deltas. Expect a GAP —
  our default shape drops electrostatics (the 2× stretch fix) and lacks the twisted init config; SNUPI
  has both. Quantifying it is the point (drives G10 + ES calibration).
- **RMSF:** per-bp pattern Pearson/Spearman (SNUPI RMSF from the `.mat`).
- **Mode shapes (the new one):** MAC (Modal Assurance Criterion) between SNUPI's 5 modes and ours —
  `MAC = (φ_s·φ_m)² / (|φ_s|²|φ_m|²)` on matched translational DOFs. Answers the "lowest bending/torsion
  mode" question directly against ground truth.
- **Correlation:** off-diagonal correlation of the bp-bp Pearson + Generalized matrices vs SNUPI's.
- **Persistence length:** ours (G8) vs whatever SNUPI reports.

## HARD PARTS the implementer must solve
1. **Node correspondence** — SNUPI's PDB/`.mat` nodes ↔ our `(helix, bp)` nodes. Match by the caDNAno
   base index the export carries, or spatially (Kabsch-align then nearest-neighbour). Without a solid
   matching, RMSD/RMSF/MAC are meaningless. This is the crux.
2. **caDNAno format** — the scafLoop/stapLoop + sequence-CSV caveat above; verify SNUPI actually parses
   the NADOC-exported JSON (round-trip one design first, eyeball the loaded structure in SNUPI's log).
3. **Subprocess orchestration** — write Input.txt + `<basename>.snp` + json/csv into a scratch design
   dir, run `run_SNUPI.sh`, wait (slow; timeout), glob the timestamped OUTPUT dir, parse. Idempotent,
   one design at a time; battery mode loops.
4. **Expected shape mismatch is a FEATURE** — don't "fix" the mimic to match SNUPI's shape blindly; the
   comparator exists to MEASURE the gap so G10 + the electrostatic balance can be calibrated against
   ground truth.

## Related
[[snupi-mimic]] · [[project_snupi_gaps]] (G10 canonical init config; the deferred shape gaps) ·
`scripts/snupi_visual_compare.py` · exp42.
