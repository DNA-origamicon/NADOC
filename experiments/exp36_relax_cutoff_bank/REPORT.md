# exp36 — Relaxation-stage cutoff: reference bank + replay

**Question.** Can we detect when a NAMD ENM-ladder relaxation stage has settled and
cut it short to save compute? What signal is *safe* to cut on?

**Method.** `bank_parser.py` turns any NAMD job tree (`job.json` + `package/.../*.log`
+ `output/health.jsonl`) into per-frame tables (energy on the dense ENERGY-line clock,
WC/C1' joined from health). `cutoff_replay.py` replays two causal stopping rules offline
(no physics change): ENERGY-ONLY (pot+volume plateau) and MULTI (pot+volume AND WC
base-pairing plateau), plus a robust within-stage WC drift GUARD.

Rule: trailing window W=10 frames, patience P=3; thresholds EPS_POT=0.1%, EPS_VOL=0.2%,
EPS_WC=2pts. Guard = |median(last 20%) − median(first 20%)| WC > 0.10.

## Reference bank (parsed, local)

| job | design | size | ladder | frames | source |
|---|---|---|---|---|---|
| acc229c76c42 | 2hb_noT | ~32k atoms | k0.5→0.1→0.01→0 | 1012 | `workspace/md_jobs/` |
| e29d1e5d5ace | **18hb** | **2.98M atoms** | k0.5→0.1→0.01→0 | 1012 | `/media/jojo/Archive/NADOC_archive/` |

Parser validated: WC finals reproduce exp30 REPORT (k0.5→0.95, k0.1→0.88, k0.01→0.81,
k0→0.78); resume-seam dedup handled (18hb k0p5_p10 + resume1 → 26 frames).

## Result

**2hb_noT (pathological small bundle, melts at low k):**
- Energy plateaus by ~10–15% of every stage. WC drift within stages small (≤0.03) but the
  low-k stages don't fully plateau on WC → MULTI self-holds k=0.01 (and half of k=0).
- ENERGY-ONLY aggressive 87.3% / 7.9× · conservative (hold k=0) 66.1% / 3.0× ·
  **MULTI 59.2% / 2.45× (safe).**

**18hb (real target, survives true k=0):**
- Energy AND WC plateau at the window floor (~9%) in *every* stage; within-stage WC drift
  ≤0.011, C1' 99–100% throughout → GUARD OK everywhere.
- **MULTI == aggressive: 91.2% / 11.4×** — the WC condition holds nothing back because the
  structure is genuinely settled within each stage.

## Takeaways

1. **The MULTI (energy+WC) gate is the rule to ship.** It self-adapts: on a fragile design
   it refuses to cut stages where base-pairing is still drifting (2.45×); on a well-built
   large origami it cuts everything (11.4×). No per-design tuning.
2. **Energy-alone is unsafe only at low restraint on fragile designs** — confirmed the
   revised S16 position: with current guards the energy plateau tracks structure for the
   restrained high-k stages (the bulk of compute) and on healthy structures at all k.
3. **Wall-clock:** 18hb ran 6.1 days (19.2 ns @ ~3 ns/day). MULTI cut → ~13 h, saving
   ~5.6 days, at matched endpoint (structure was already at equilibrium in the cut steps).
4. **Deployable with zero architecture change:** the rule fires by the existing p10
   checkpoint — evaluate the plateau test there and skip the p50+p100 chunks.

**Policy knob (domain call):** the k=0 stage is also the production-quality equilibration.
On 18hb it's safe to cut, but one may *choose* to always run the full k=0 hold regardless of
plateau. That's the conservative (hold-k=0) tier: 3.0–3.2× and never touches the melt stage.

## Files
`bank_parser.py`, `cutoff_replay.py`, `bank/` (2hb), `bank_18hb/`. Stdlib only; run:
`python3 cutoff_replay.py --bank bank_18hb`.
