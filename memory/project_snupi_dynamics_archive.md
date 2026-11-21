# SNUPI dynamics — historical campaigns and implementation notes

Moved from the project head on November 20, 2026. Read on demand; dated
CPU-only statements and old handoffs do not override the current CUDA contract.

## Completed BigO 10-mer scaling check (2026-11-18)

User-requested job `3c02b943f1c9` completed on RunPod for
`BigO-poly-10monomer.nass`. Assembly publication and saved/reopened independent
replay verify Add Part + Polymerize Periodic (10 instances, 9 joins), preserving
the audited 70-command `BigO-rebuilt.nadoc` source. Same coarse Langevin options
as two-mer `fe44cad5dfec`: 60,000 steps, 0.13 ps, 7.8 ns, no retries, 40 output
frames. Same RTX PRO 4000 host type and 8 requested CPU cores; RAM request was
24 GiB instead of 16 GiB to meet the 21 GiB guarded minimum. This remains CPU
integration; physical CPU identity across rented hosts is not controlled.

Nodes 14,112 → 70,560 (5×); setup approximately 5 → 20 s (4×), integration
301 → 1,591 s (5.286×), analysis 164.78 → 820.47 s (4.979×), total solver
470.78 → 2,431.47 s (5.165×). Stage timestamps have one-second resolution;
analysis is residual solver time. Pod lifetime 611.406 → 2,882.985 s (4.715×);
compute charge $0.096828 → $0.456503. Near-linear observed runtime, not a
physical equilibration/convergence claim. All trajectory/display values finite;
70,560 RMSF values finite and nonnegative, range 0.128712–0.519886 nm.
Results collected, job listed/viewable, provider confirms no pods remain.
App inspection verified 10 instances, live step percentage, integration timeline,
SNUPI spinner and selected RunPod card. Temporary review documents, screenshots,
browser profiles and download staging removed. No production code changes.
Evidence: `.development-artifacts/snupi-scaling-10mer-20261118/`, particularly
`comparison.json`, `completed-run.json`, `proof.json`, `completion-api-checks.json`.

## Installed experimental timestep/setup optimization (2026-11-18)

The user subsequently requested termination of the before case and installation.
Job `bebad41f65e7` is stopped; RunPod termination succeeded and `/api/runpod/pods`
returned an empty list. The candidate is now installed in `snupi_dynamics.py`,
`snupi_timestep.py` and `snupi_electro_vectorized.py`; 34 installed numerical tests
pass. The remote bundle includes these backend modules. GPU integration remains
an isolated prototype. Evidence lives in
`.development-artifacts/snupi-timestep-20261118/`.

Legacy-source gap repaired through `scripts/rebuild_legacy_part.py`. Today's
automatic end-clearance rule produces 147 bp instead of original BigO's 126 bp,
so reconstruction uses real Helix Extend, Resize Ends, Nick and Place Crossovers
commands for the recorded scaffold layout, then the recorded downstream commands.
No router/clearance rules or phase constants were changed. `BigO-rebuilt.nadoc`
passes publication/reopened independent replay (70 commands), and matches original
molecular topology, sequences, junctions, periodic identities and geometry (float
absolute tolerance 1e-12). `BigO-rebuilt.rebuild.json` retains original history and
source checksum alongside the new command history. Original files stay unchanged.

`BigO-poly-2monomer.nass` uses actual Add Part + Polymerize Periodic(count=2,
forward) operations. Saved/reopened assembly audit passes: 2 instances, 1 joint,
complete upstream 70-command replay. App load/visual check passed, no page errors;
temporary screenshot and browser document removed. RunPod job `fe44cad5dfec`
completed: coarse Langevin, 60000 steps, 20 mM MgCl2, hydrodynamics/tails off,
RTX PRO 4000 Blackwell, 8 CPU / 16 GiB host RAM, $0.57/hour, $1 cap, 60 min limit.
It used the installed CPU optimization, not the GPU integration prototype. Setup
~5 s; timestep selection and first integration report share the same log second.
Completed 60000 steps at 0.13 ps without retry, solver total 470.78 s, 40 finite
trajectory frames / 29008 nucleotide keys, finite RMSF 0.1321–0.5677 nm. Results
downloaded; exact pod terminated and provider inventory empty. Compute cost
$0.09683. Actual frontend job row, RunPod selection, integration timeline and
81.7% measured progress were verified; temporary browser artifacts removed.

Full BigO-poly: 211,680 nodes / 1,270,080 DOFs / 54,084,202 stiffness nonzeros.
Mass-scaled positive-weight absolute row bounds (nine sparse products, fixed work)
select 0.13 ps rounded DOWN, with anchor and tail frequency bounds retained. Setup
kernel took 1.55 s; two local preparations reached the timestep stage in ~45 s.
The original local generalized eigensolve hit a 45 s cutoff; scaled tol=1e-3
converged in 5.63 s (one thread), 6.00 s (eight), suggesting ~0.143 ps. Thus the
bound costs ~10% more steps for an equal physical duration. Explicit dt and
modified-GJF paths stay unchanged in the candidate.

Chunked vectorized electrostatic COO assembly plus CSR retention eliminates large
Python triplet lists/LIL round trips. BigO part full-operator comparison: relative
Frobenius difference 6.4e-21, identical diagonal masses. Full assembly electrostatic
assembly ~11 s; overall assembly ~45 s (81 s with vectorized electrostatics but old
LIL conversions). Original scalar full-assembly probe stopped under 6 GiB memory
throttling; no OOM and no change to desktop safety caps.

RTX 2080 SUPER pilot, float64, same NumPy random impulses: 20 plain linear/Stokes
GJF steps CPU 2.22 s, warm GPU 0.374 s, cold GPU 2.39 s. Relative q/v errors ~1e-16;
GPU allocator peak ~0.96 GiB. This excludes output analysis/hydrodynamics and is
not a production GPU backend. Fifty CPU candidate steps on the full assembly
finished with finite frames/RMSF, no retry, ~53 s including setup. This is a short
numerical sanity check, not physical sampling/convergence validation. Evidence:
`benchmark.json`, `integration-check.json`, `operator-check.json` in that folder.

## GPU exploration (2026-11-17)

No production GPU backend enabled by this exploration. mrDNA dynamics already
runs in CUDA ARBD; NADOC SNUPI solves/integration remain NumPy/SciPy CPU paths.
Float64 RMSF prototypes, 120 synthetic frames × 211,680 nodes: warm CPU/resident
GPU/batched GPU = 2.44/0.50/0.72 s (linear), 2.85/0.92/2.25 s (Kabsch), including
transfers and alignment. GPU startup adds ~3 s. All comparisons satisfy 1e-12
absolute/relative tolerance; largest absolute difference 1.2e-14. CPU BLAS used
one thread; shared desktop GPU, not an exclusive-device benchmark.
A 1,200-frame capacity run completed in 64 s with 228 MiB tensor allocations,
286 MiB CUDA allocator reservation and 6.21 GiB host peak RSS. Input is still
resident on host; no full-size CPU speed comparison or simulation is claimed.
Actual BigO-part K×q: 100 calls CPU 0.139 s, warm GPU 0.011 s; cold GPU 2.48 s.
This supports a persistent-worker, bounded-batch pilot, not automatic offload
or a claim that dense hydrodynamics/NMA now fits VRAM.
Evidence: `.development-artifacts/solver-vram-20261117/review.json`.


## Second memory pass (2026-11-17)

Trajectory RMSF now reuses owned projection/alignment buffers for centering and
squaring. The driver computes mean displacement before releasing the six-DOF
samples and their views, so they no longer overlap RMSF analysis. Public inputs
remain unchanged, including read-only arrays; core/tail output ownership is unchanged.
Bounded 120-frame/30,000-node benchmarks: linear RMSF peak 404→294 MiB,
0.443→0.249 s; Kabsch RMSF 313→230 MiB, 0.370→0.335 s. Both output hashes identical.
Single-run measurements, not full assembly performance guarantees. Verification
status is recorded under `.development-artifacts/solver-memory-round2-20261117/`.
No automatic GPU/disk offload: a 38.4 MB float64 variance probe measured CPU
0.102 s, disk including flush 0.179 s, CUDA cold 0.354 s / warm 0.009 s including
transfers. Warm GPU reduction merits a separate end-to-end pilot; cold overhead,
VRAM capacity, and alignment costs preclude a blanket speed claim.


## Memory pilot (2026-11-17)

All three GJF integrators now allocate their sampled output once instead of retaining
a list and copying it into an ndarray. Sampling indices, force calculations, RNG
draw order and return shapes are preserved; nine old/new seeded comparisons were
bitwise equal. A 160-frame, 100,000-DOF probe reduced process peak RSS from 289 to
167 MiB and time from 1.91 to 1.72 s (single run, not a scaling guarantee).
For BigO's default 1,200 samples this removes one 12.19 GB sample copy; it does not
remove trajectory analysis/display allocations, the NMA workspace, or the slow
timestep eigensolve. Evidence: `.development-artifacts/solver-memory-20261117/`.
Alpine's submitted pilot retains the original source as the baseline.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Source paper: **Lee, Koh & Kim, *Nat Commun* 14:7079 (2023)** — `Literature/SNUPI_dynamics.pdf`
(read in full 2026-07-12). This is the *dynamics engine* bolted onto the SNUPI **ACS Nano 2021**
structural model we already mimic ([[snupi-mimic]], [[project_snupi_gaps]]). It keeps SNUPI's FE
internal-force + mass description verbatim and adds **Langevin time-integration** → trajectories
instead of a single mean structure.

## Linear RMSF audit (2026-09-06)

`simulate_equilibrium` now requests `trajectory_rmsf(linearized=True)` for its linear
force model. The free linear FEM rotations are `omega × X0`, not finite rotations
of X0: Kabsch alignment cannot remove them exactly and spuriously counts their
diffusive growth as internal fluctuation. The readout now projects displacements
off the translational/infinitesimal-rotational subspace before taking variance.
SVD rank selection preserves the five observable rigid modes of collinear nodes.
The default finite-coordinate helper and nonlinear-force path retain Kabsch.
Forces, random noise, trajectories, mean shape, topology and physical constants
are unchanged; other analysis helpers still use their documented finite alignment.

The original 200k-step 42 bp 2HB regression gave Stokes/RPY means 0.354160/0.409694 nm
under finite alignment (15.7% difference); linear projection gives
0.351144/0.402770 nm (14.7%), within the unchanged 15% sampling tolerance. These
finite trajectories are not a claim of complete equilibrium convergence. Analytic
controls add arbitrary linear rigid motion to known uniform dilation and verify
that only the prescribed strain contributes to RMSF, including collinear nodes.

Governing equation (everything scopes off this):

    M V̇ = F − Z V + R ,   U̇ = V

<a id="what-we-already-have-60-of-the-machine"></a>
- [What we already have (≈60% of the machine)](details/project_snupi_dynamics/01-what-we-already-have-60-of-the-machine.md#what-we-already-have-60-of-the-machine)

<a id="whats-missing-the-dynamics-contribution"></a>
- [What's missing (the dynamics contribution)](details/project_snupi_dynamics/01-what-we-already-have-60-of-the-machine.md#whats-missing-the-dynamics-contribution)

<a id="the-load-bearing-insight-why-phase-it-this-way"></a>
- [The load-bearing insight (why phase it this way)](details/project_snupi_dynamics/01-what-we-already-have-60-of-the-machine.md#the-load-bearing-insight-why-phase-it-this-way)

## Units (locked — get this wrong and it silently corrupts)
Integrate in a consistent **nm · pN · ns** system so the assembled K and displacement q keep their
NATURAL units (no per-block SI conversion of K). Derived mass unit = pN·ns²/nm = 1e-21 kg (a bp ≈
1.086e-3 of these) → the G6 mass matrix (SI kg / kg·nm²) is scaled by `MASS_G6_TO_DYN=1e21`. k_BT =
4.142 pN·nm @300 K. Stokes drag on σ=1.1 nm in water η=8.9e-4 Pa·s: `STOKES_TRANS=6πησ` → 18.45
pN·ns/nm (N·s/m ×1e12); `STOKES_ROT=8πησ³` → 29.8 pN·nm·ns (N·m·s ×1e30). Δt in ns (5 ps = 0.005).
(NB `fem_solver.KBT=4.11 pN·nm` is the 298 K NMA value; dynamics uses 300 K 4.142 — keep distinct.)
Implemented exactly this way in `snupi_dynamics.py`; validated by the 1-DOF `⟨x²⟩=k_BT/k` test.

<a id="phases"></a>
- [Phases](details/project_snupi_dynamics/02-phases.md#phases)

- [Phases — continued detail](details/project_snupi_dynamics/02-phases.md)

<a id="visualization-bridge-2026-07-12--dynamics-output-is-toggle-able-like-every-structure-prediction"></a>
- [Visualization bridge (2026-07-12) — dynamics output is toggle-able like every structure prediction](details/project_snupi_dynamics/03-visualization-bridge-2026-07-12--dynamics-output-is-toggle-able-l.md#visualization-bridge-2026-07-12--dynamics-output-is-toggle-able-like-every-structure-prediction)

<a id="hydrodynamics-is-memory-bound--the-on²-wall--the-coarse-blob-model-2026-07-13"></a>
- [Hydrodynamics is MEMORY-BOUND — the O(N²) wall + the coarse blob model (2026-07-13)](details/project_snupi_dynamics/03-visualization-bridge-2026-07-12--dynamics-output-is-toggle-able-l.md#hydrodynamics-is-memory-bound--the-on²-wall--the-coarse-blob-model-2026-07-13)

<a id="e-field-in-the-langevin-loop-2026-07-25--done"></a>
- [E-field in the Langevin loop (2026-07-25) — DONE](details/project_snupi_dynamics/03-visualization-bridge-2026-07-12--dynamics-output-is-toggle-able-l.md#e-field-in-the-langevin-loop-2026-07-25--done)

## Decisions / open
- Frame value proposition honestly: for **static shape + equilibrium flexibility** our NMA already
  matches MD cheaply (the paper itself: NMA↔dynamics RMSF overlap 0.97). Dynamics' unique value =
  **reconfigurable/responsive designs** (switches, rotors), non-equilibrium transients, solvent-damped
  spectra, and actual trajectories/movies. Prioritize Phase 2 only if responsive-device sim is wanted.
- Perf is the elephant for Phase 2 (µs runs). Phase 1 (ns equilibrium, small designs) is fine in Python.
- Three-Layer Law: trajectories are PHYSICAL/display-only, never write topology.

<a id="handoff-2026-07-13-session-2--final-phases"></a>
- [Handoff (2026-07-13, session 2 — "final phases")](details/project_snupi_dynamics/04-handoff-2026-07-13-session-2--final-phases.md#handoff-2026-07-13-session-2--final-phases)

<a id="kickoff-prompt-for-a-fresh-session-continue--drive-the-live-ui"></a>
- [Kickoff prompt for a fresh session (continue + drive the live UI)](details/project_snupi_dynamics/04-handoff-2026-07-13-session-2--final-phases.md#kickoff-prompt-for-a-fresh-session-continue--drive-the-live-ui)

<a id="references"></a>
- [References](details/project_snupi_dynamics/04-handoff-2026-07-13-session-2--final-phases.md#references)
