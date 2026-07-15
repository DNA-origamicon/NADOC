> ⚠️ **SUPERSEDED — read this first (2026-07-15).** This report concluded there is an
> *extensive, equilibrium* ~3.0 fs ceiling for extra-base designs and floated "accept 3 fs and
> match it." **That conclusion is wrong / obsolete.** A later session found the real cause is a
> **bad INITIAL guess**, not an equilibrium property: the geometric build stacks neighbouring
> extra-base sugars (159 clash pairs, C4'–C4' to 0.29 Å) and the declash minimiser relieves the
> overlap by stretching a C4'–C5' bond to ~3.1 Å — fatal to a 4 fs rigid-bonds RATTLE step.
> The fix is to **oxDNA-seed the design so the extra bases start declashed** (`oxdna_seed.py`,
> `prep_24hb_seeded.py`, the `pre_declashed` path in `md_protocols.prepare_mgh_slow_release`),
> after which **4 fs runs**. **4 fs is the ONLY sanctioned production timestep** — lowering
> production dt is disallowed (`memory/feedback_namd_4fs_production_only.md`). The mechanism study
> below is kept for its measured data; ignore every "match/accept 3 fs" recommendation in it
> (§4e, §6, §8.3–8.4). See `NEXT_SESSION_24hb_LAUNCH.md` and `NAMD_4FS_RATTLE_RESEARCH.md`.

# Why does 4 fs destabilize NAMD MD of DNA-origami with extra crossover bases?

**A research handoff.** Self-contained: the reader is assumed to know atomistic MD and DNA
nanotech but to have none of the originating session's context.

**The question.** With an HMR + `rigidBonds all` + 4 fs protocol that runs a duplex DNA-origami
bundle stably, adding **unpaired single-stranded "extra" bases at crossovers** collapses the
maximum stable timestep from 4.0 fs to ~3.0 fs. We want the *mechanism* — and, ideally, a
protocol change that recovers 4 fs without biasing the equilibrium ensemble.

Everything below is measured, not inferred, unless explicitly flagged as hypothesis.

---

## 1. System and protocol

- **Construct:** `24hb_1xT` — a 24-helix-bundle DNA origami, 147 bp/helix, **1,322,736 atoms**
  solvated (TIP3P, 12.5 mM Mg²⁺, screening ions), CHARMM36 nucleic acid FF.
- **Extra bases:** 384 crossovers; **338 carry a single unpaired `T`** inserted at the
  crossover, 46 carry none. These T's are **single-stranded, unpaired** — dangling nucleotides
  at the crossover junctions. This is the *only* topological difference from the control.
- **Control:** `24hb_0xT` — byte-identical topology with **all `extra_bases → None`** (verified:
  identical helix/strand/crossover-half graph; SHA-256 of the topology matches; only the
  `extra_bases` field differs). 1,320,174 atoms.
- **Also built:** `24hb_2xT` (`T → TT`, 338 sites), and a tiny 2-helix analog family
  (`2hb_noT`/`2hb_1xT`/`2hb_2xT`, ~31.7k atoms).
- **Production integrator (NAMD 3.0.2):** `rigidBonds all`, HMR PSF (non-water H ×3.0),
  `timestep 4.0`, `langevin on` / `langevinHydrogen off` / `langevinDamping 5`,
  `langevinPiston on` (NPT, 1 atm, 300 K), PME, `fullElectFrequency 2`, `stepspercycle 20`.
- **HMR detail:** `write_hmr_psf(factor=3.0)` — each non-water H: 1.008 → 3.024 amu; the donated
  2.016 amu is subtracted from its single bonded heavy partner (mass-conserving). A CH₂ carbon
  (e.g. sugar **C5′**) donates to *two* H → loses ~4 amu (12 → ~8); a CH carbon (C1′/C2′/C3′)
  loses ~2 amu (→ ~10).

**Why this matters scientifically:** the campaign measures **equilibrium inter-helix 6-DOF
stiffness by crossover context** from fluctuations. HMR mass and (for a stable, thermostatted
integrator) timestep do **not** enter the Boltzmann factor, so any of these knobs is
thermodynamically free *if* it yields a stable, accurate trajectory. The blocker is purely
integrator stability.

---

## 2. The core observation

| system | extra-base sites | max stable dt (HMR ×3.0, `rigidBonds all`) |
|---|---|---|
| `24hb_0xT` (control) | 0 | **≥ 4.0 fs** (2500 steps clean, TOTAL finite/neg, 300 K) |
| `24hb_1xT` | 338 | **3.0 fs** (4.0 and 3.5 fs both die) |
| `2hb_1xT` (tiny) | 2 | **≥ 4.5 fs** |
| `2hb_noT` (tiny control) | 0 | **≥ 4.5 fs** |

The control runs 4 fs. Adding unpaired T's drops the ceiling — **and the drop scales with the
number of sites** (2 sites: no measurable drop; 338 sites: 4.0 → 3.0 fs). See §5.

---

## 3. The failure signature (this is the crux — study it)

The failure is **not** a gradual heating or energy drift. It is an **instantaneous,
single-atom, step-0 blow-up**:

- Fails at **step 0** of a fresh 4 fs start, even from a **fully equilibrated** structure
  (50 ps of prior 1 fs soft dynamics + equilibrated velocities read from the restart).
- **One atom** at a time; a **different** atom on each run (draw from a distribution).
- Presents as either `Constraint failure in RATTLE algorithm for atom N` **or**
  `Atoms moving too fast` (NAMD velocity limiter) depending on dt/HMR — the same underlying
  event, caught by whichever guard trips first.
- The runaway velocities are enormous and single-step: at HMR ×3.5, dt 4.0 fs, one atom's
  velocity component hit **595,127 / −141,377 / 1,097,010** (NAMD internal units) against a
  limit of 2,500 — i.e. **~240× the limit in a single step**. At dt 3.5 fs the same atom was
  **3,234 vs limit 2,857 — only 13% over** (a near-miss; the ceiling is right there).

### The failing atoms — every one is a thymine **sugar carbon**

Mapped from NAMD's 1-based atom index back through the PDB:

| atom | name | residue | seg | note |
|---|---|---|---|---|
| 130981 | **C5′** | THY | D00D | CH₂ (lightest after HMR, ~8 amu) |
| 142858 | **C5′** | THY | D00M | CH₂ |
| 181792 | **C5′** | THY | D01A | CH₂ |
| 172490 | C3′ | THY | D013 | CH |
| 172977 | C1′ | THY | D013 | CH |
| 180575 | C2′ | THY | D019 | CH |

- **Every failing atom is a thymine sugar carbon.** Since the control (`0xT`, which also
  contains sequence thymines throughout its duplex) runs 4 fs cleanly, the failures are caused
  specifically by the **unpaired extra-base T's**, not thymine per se.
- **Half (3/6) are C5′.** C5′ is the *only* CH₂ among the sugar carbons and therefore the atom
  **HMR lightens most** (loses ~4 amu vs ~2). This overrepresentation is the strongest
  mechanistic clue we have (see §6).

---

## 4. What we tried (all negative for reaching 4 fs)

All on the real 1.32M-atom `24hb_1xT`, from the equilibrated 50 ps checkpoint,
`rigidBonds all`, durability = 25,000-step runs unless noted.

### 4a. Soft annealing — NO effect on the ceiling
Ran 0 / 25 / 50 ps of soft dynamics (1 fs, `rigidBonds none`, ENM restraints, i.e. the
"declash" relaxation), then measured max-stable-dt after each:

| soft anneal | 1.5 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 fs |
|---|---|---|---|---|---|---|
| 0 ps (from minimized) | ✅ | ✅ | ✅ | ✅ | ✅ | ✗ |
| 25 ps | ✅ | ✅ | ✅ | ✅ | ✗ | ✗ |
| 50 ps | ✅ | ✅ | ✅ | ✅ | ✗ | ✗ |

Ceiling is **flat (≈3.0 fs), if anything lower once equilibrated** (the 0 ps "3.5 fs pass" is a
cold-start artifact: freshly assigned 300 K velocities on a minimized structure hadn't yet
developed the thermal tail). **Conclusion: this is not residual build strain that relaxes out —
it is a steady-state property of the equilibrium ensemble.**

### 4b. HMR factor sweep — 3.0 is optimal; MORE repartitioning is WORSE
On the tiny `2hb_1xT` (fast grid) and confirmed on the real `24hb_1xT`:

- HMR factor is **capped at ~3.5** by NAMD itself: at factor 4.0 the H mass (4.03 amu) exceeds
  NAMD's hydrogen-grouping threshold → `FATAL: Atom N has bad hydrogen group size` (a topology
  rejection, not a physics result). Factor 5.0 additionally drives 29 atoms to **negative mass**
  (over-donation from CH₂/CH₃).
- Within the legal 3.0–3.5 window, **3.0 is better than 3.5.** On real `24hb_1xT`, HMR ×3.5:
  dt 4.0 and 3.5 die at step 0; **dt 3.0 died at step 21,000** — whereas HMR ×3.0 dt 3.0
  survived the full 25,000. Raising HMR *lowers* the ceiling.
- **This is a key mechanistic constraint (§6):** more HMR → lighter heavy atoms → *worse*
  stability, opposite to the usual "HMR buys timestep" intuition. It says the limiting motion
  is a **heavy-atom** motion, not an X–H stretch.

### 4c. Langevin-on-hydrogen — NO effect
`langevinHydrogen on` (thermostat friction applied directly to H, clipping their velocity
tails), at `langevinDamping` 5 and 50, HMR ×3.0, dt 4.0: **both die at step 0 (RATTLE).**
Confirmed the knobs were actually written (not a silent no-op). Langevin preserves the canonical
ensemble at any damping, so this would have been free — it simply doesn't move the ceiling.

### 4d. Tiny-system reproducer — does NOT reproduce (this is a positive finding)
`2hb_1xT` (2 extra-base sites, 31.7k atoms) survives **4.5 fs** at HMR ×3.0; `24hb_1xT` (338
sites) fails **4.0 fs**. Same protocol, same motif, same FF. The tiny system is far more
forgiving → the ceiling is **extensive in the number of unpaired-base sites** (§5).

### 4e. Durability confirmed at the ceiling
HMR ×3.0: dt 3.0 fs survived 25,000 steps (75 ps) with zero constraint errors; dt 2.5 fs clean
through 24,000 (interrupted, not failed). So 3.0 fs is genuinely durable at short scale — but
50 ns is 16.7M steps, ~670× longer, and the failure is a rare per-step tail event, so 3.0 fs is
*at* the ceiling and a 50 ns run would be expected to trip occasionally (NAMD restarts from the
last checkpoint, so recoverable but wall-clock-wasteful).

---

## 5. Established: the ceiling is EXTENSIVE in unpaired-site count

2 sites → no measurable drop; 338 sites → 4.0→3.0 fs. Combined with the step-0, single-atom,
different-atom-each-time signature, this says the failure is an **independent per-site,
per-step tail event**: each unpaired base has some small probability per step of drawing a
configuration/velocity that a 4 fs step cannot integrate; with N sites you sample that tail ~N×
harder. **Practical consequence for a multi-design campaign: there is no single "safe" timestep —
larger / more-crossover designs have lower ceilings. Max-stable-dt must be measured per design
(cheap: the failure is at step 0, so a probe costs ~30 s).**

---

## 6. Leading mechanistic hypothesis (for the researcher to confirm or kill)

**"HMR-lightened, under-caged sugar carbons on dangling nucleotides."**

The limiting fast motion under `rigidBonds all` is a **heavy-atom** motion (proven by 4b: more
HMR = lighter heavy atoms = worse). The failing atoms are thymine **sugar carbons**, half of
them **C5′** — the CH₂ that HMR lightens most (to ~8 amu). In a **duplex**, these carbons are
caged by base-pairing + stacking, so even lightened they stay stable at 4 fs (the `0xT` control).
On an **unpaired, dangling** extra base, the same lightened carbon is poorly caged and free to
sample large-amplitude, close-approach configurations; a 4 fs step overshoots into a steep
repulsive wall → near-singular force → single-step velocity blow-up. This simultaneously explains:

1. **Why sugar carbons specifically** fail (they're the lightened heavy atoms).
2. **Why C5′ is overrepresented** (CH₂ → lightest; ~8 amu).
3. **Why only the extra-base (unpaired) versions** fail (duplex caging vs dangling freedom).
4. **Why higher HMR is worse** (lighter carbon → larger acceleration per unit force).
5. **Why it's a step-0 / instantaneous event** and **annealing doesn't help** (dynamic
   under-caging, not static strain).
6. **Why it's extensive** (independent per-dangling-site).

### Predictions this hypothesis makes (cheap to test)
- **Selective / reduced HMR on the extra-base residues** (don't lighten the dangling sugars, or
  lighten them less) should raise the ceiling — directly opposite to global higher HMR.
  *(Requires a per-residue HMR PSF writer; not yet built.)*
- Failures should **correlate with the lightest carbons** (C5′ > C1′/C2′/C3′) — partially seen
  (3/6). More statistics would confirm.
- The instantaneous pre-failure force on the failing atom should show a **steep VDW/electrostatic
  close-contact**, not a bonded-term explosion. (Dump forces the step before failure.)
- Running the extra-base system **without HMR** (`rigidBonds all`, no mass repartition) should
  push the ceiling for the dangling sugars back up, at the cost of the global dt (a controlled
  way to separate "HMR lightening" from "unpaired floppiness").

### Alternative / additional mechanisms to weigh
- **Under-constrained fast bending of a terminal residue** independent of HMR (dangling ends
  have well-known short-period librations). Test: does the ceiling drop for extra bases even at
  HMR ×1.0 (no lightening)? If yes, HMR-lightening is not the whole story.
- **A specific bad rotamer / stacking geometry** at a subset of crossovers that a coarse relax
  can't escape. Argues against: annealing 50 ps didn't help, and failures spread across many
  distinct segments.
- **Multiple-timestep (r-RESPA) resonance** with the fast dangling-base mode
  (`fullElectFrequency 2` = PME every 8 fs at 4 fs dt). Test: `fullElectFrequency 1` at 4 fs.

---

## 7. What we already know it's NOT
- Not build strain / bad minimization (survives long soft anneal; fails from equilibrated state).
- Not fixable by more HMR (worse), by H-thermostatting (no effect), or by longer relaxation.
- Not a starting-configuration problem → **seeding from a coarser engine (oxDNA/mrDNA/FEM) cannot
  help**: those engines don't represent H, sugar carbons, or the failing DOF at all, and any seed
  must still be equilibrated in CHARMM (which we did, to no effect). The ceiling is a property of
  the equilibrium *dynamics* of unpaired-ssDNA sugars, not of the frame.
- Not specific to the small/large system — the motif reproduces; only the site-count (and thus
  the tail sampling) differs.

---

## 8. Concrete asks for the deep-research session
1. **Literature:** timestep/`rigidBonds`-RATTLE stability limits for **terminal/dangling/unpaired
   nucleotides** under **HMR**; known HMR failure modes on residues with multiple exchangeable /
   CH₂ hydrogens; Aksimentiev-lab and CHARMM HMR practice for ssDNA overhangs.
2. **Adjudicate the §6 hypothesis** (HMR-lightened under-caged C5′) vs the alternatives.
3. **Best free lever to recover 4 fs**, ranked, given the equilibrium measurement makes mass /
   dt / damping thermodynamically free: e.g. per-residue HMR, selective heavier mass on dangling
   sugars, `settle`/rigid treatment of the dangling base, `rigidBonds all` without HMR at 3.5 fs,
   or accept the 3.0 fs ceiling and match it.
4. **Whether a matched timestep is even required** for an *equilibrium* stiffness comparison, or
   whether `0xT`@4 fs vs T-variants@3 fs samples the same canonical ensemble to within the
   fluctuation-measurement error (this is the open decision that stopped the campaign).

---

## Appendix: exact configs / reproduction
- Package: `24hb_1xT` at `/media/jojo/Archive/nadoc_jobs/ba552fac051a/package/24hb_1xT_namd_solvated/`
  (PSF/PDB, HMR PSF, `_hmr3.5.psf`, ENM restraint files, forcefield).
- Base production conf template: `*_01_300K_NPT_ENM_k0p5_p10.conf` (edited per test: structure→HMR
  PSF, `rigidBonds all`, `timestep`, langevin knobs; ENM `extraBondsFile` removed for unrestrained
  production; `binCoordinates/Velocities/extendedSystem` ← equilibrated 50 ps checkpoint).
- Test harnesses (this session, in scratch): `dt_ladder.sh` (max-stable-dt bisection),
  `landscape.sh` (2hb HMR×dt grid), `durability.sh`, `f35_test.sh`, `langevin_test.sh`.
- All failures reproduced on a local RTX 3080 Ti (`namd3 +p8 +devices 0`, offload mode — the
  ceiling is arch-independent, it's an integrator property).
- The declash auto-routing in code (`design_has_extra_bases → soft_ladder → fast=False`) is why
  extra-base designs default to 1 fs; that is over-conservative — the real ceiling is 3.0 fs, not
  1.0 — and is a separate finding from *why* 4 fs specifically fails.
