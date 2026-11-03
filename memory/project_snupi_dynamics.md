---
name: project_snupi_dynamics
description: "Plan + build log — add Langevin structural DYNAMICS (Lee/Koh/Kim, Nat Commun 2023) on top of our static SNUPI mimic. Friction (RPY) + random force + GJF integrator + base-stacking Morse + trajectory analysis. Phase 1 = equilibrium-dynamics validator vs our own NMA."
metadata:
  node_type: memory
  type: project
---

# SNUPI dynamics — Langevin time-integration on top of the static mimic

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
