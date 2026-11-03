# NAMD equivalent (2026-08-01) — supporting detail

[Topic head](../../project_oxdna_occupancy_clouds.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## NAMD equivalent (2026-08-01)

`GET`/`POST /md/jobs/{id}/occupancy` → `md_trajectory.md_occupancy`. Same payload shape as
the oxDNA twin, so the same overlay, controls card and display mode draw it unchanged.

**The engine-agnostic core now lives in `backend/core/occupancy_core.py`** — PCA, k-means,
medoids, the switching/drift/unimodal verdict, `resolve_selection_keys`, `_selection_sig`,
`occupancy_confidence`, `_superpose_on_subset`. Both engines import it; `oxdna_occupancy`
re-exports for compatibility. This is safe because **MD and oxDNA speak the same nucleotide
keys** — `atomistic_to_nadoc.md_pkey` emits the identical tuples including `("__xb__", …)`
and `("__ext_<id>", …)`, so scoping and clustering transfer verbatim.

**What MD does NOT share, and must not:**

- **No `a3`.** MD's per-frame value is the P atom — already the backbone site — where oxDNA
  stores a centre of mass from which the site is *derived* via `oxdna_backbone_sites`.
  Feeding MD data to `occupancy_features` would fabricate an offset. `md_occupancy`
  assembles its own features; pinned by `test_md_does_not_route_through_oxdna_feature_assembly`.
- **No FENE gate.** `FENE_R0_OXDNA2` is an oxDNA potential, not a calibrated NAMD frame
  check. (If one is ever wanted, `md_health.C1_PAIRED_MAX_DEFAULT` is the MD-native cutoff.)

**Only PRODUCTION segments form the ensemble — a POSITIVE match on `"production"`.**
`md_production_segments` / `mdHasProductionRun` keep segments whose stage label contains
that word, and there is no opt-in and **no fallback**: a job with only equilibration
returns *"no production run yet"* rather than clustering its ramp.

Every production builder puts the word in the label, which is why the positive test works:

| builder | label |
|---|---|
| `routes_md` (Run production) | `"<N> ns <fast\|medium\|conservative> production run"` |
| `md_ensemble` | `"<N> ns production replica (seed <n>)"` |
| `md_protocols` | `"310K NPT conservative production <N> ns unrestrained"` |
| `md_shell_reprep` | `"shell NVT production (COM-restrained, HMR 4 fs)"` |

**This replaced a keyword-EXCLUSION filter that was badly wrong.** The first version kept
segments carrying none of `enm`/`fixed`/`minim`, built from the four `SegmentSpec` sites
that happen to spell restraint "ENM". Dumping the distinct stage labels across all 85 MD
jobs on this machine showed protocols that encode restraint as **`k=<value>`** instead —
and the exclusion filter admitted **every one** of:

```
50K / 100K / 200K / 300K NVT k=5.0             heating, restrained
310K NPT k=5.0 → 4.0 → … → 0.01  (11 stages)   restraint ramp
Vacuum ENRG-MD shape relaxation                restrained; "ENRG-MD" is not "ENM"
solvent equilibration (DNA position-restrained, NVT)
310K NPT unrestrained qualification            unrestrained, but a probe not sampling
```

i.e. the whole relaxation schedule. **Never enumerate "restrained" keywords here** — there
is no closed set. Match production positively; unknown labels then fail closed, which for
this feature is the safe direction.

Note `"300K NPT k=0"`, the ENM ladder's terminal unrestrained stage, is also excluded: it
is unrestrained but still equilibration. Consequence on the real job set — **17 of 85 jobs
have a production segment and get occupancy; 15 that stop at the ladder correctly do not.**

**Measured on a real production run** (`6fc87681f9de`, 24hb_0xT, 50 ns production replica,
6720 nt): **18.7 s**, 30 of 30 frames, verdict `drift`, PC1 0.35, n_eff 2.81 (preliminary).
An earlier "36.1 s / 30 frames" figure in this file came from `383f7dcc4a5d`'s terminal
EQUILIBRATION stage, before the filter was corrected — that job has no production run and
now returns not-ready.

**No shareable frame cache, and this is the dominant cost.** Every MD analysis runs through
`md_analysis_runner` in a spawned, killed-on-exit subprocess, so nothing a child computes can
be memoised and there is no `_ALIGNED_CACHE` equivalent to piggyback (oxDNA occupancy is
nearly free after a trajectory scrub; MD is never free). Mitigation is a result-level LRU in
`routes_md._MD_OCC_CACHE`, keyed on per-DCD size+mtime so a growing run self-invalidates: a
re-toggle is free, a parameter change is a full re-read.

**Measured** on `383f7dcc4a5d` (24hb_0xT, 6720 nt, 120 frames): **36.1 s**, sampling stages
`['300K NPT k=0']` → **30 of 120 frames**, verdict `drift` (1 transition, n_eff 2.66,
preliminary). 30 free frames is too few to resolve states — a property of these runs, not of
the feature. A longer unrestrained stage is what would make MD occupancy informative.

**Frontend:** `initOccupancyControls({engine, ids, fetchOccupancy})` is now id-parameterised
(`occupancyIds(prefix)`) and takes an injected fetch, because the two clients have genuinely
different signatures (oxDNA options-object, MD positional `(id, signal, opts)`). One overlay
serves both cards, so whichever activates last claims it and stands the other down via
`nadoc:occupancy-active` — otherwise the loser's list would keep describing states no longer
on screen. `mdViz` needed `onOccupancyClear` (it had none), or toggling off left ghosts.

### Three init-order bugs the NAMD work surfaced (all caught only by e2e)

Adding a second engine's card exposed how brittle the panel/init ordering is. None of these
were visible to 6232 backend + 4356 frontend unit tests:

1. **A toggle added to `_syncVizOffRadio`'s `anyOn` array must be DECLARED with its peers.**
   That function runs during init (via `_updateVizToggles`), so a `const occupancyToggle`
   further down the file is a TDZ that aborts **the whole app's boot** — the symptom is an
   unrelated "`__nadocOccupancy` is undefined", because `main()` never finished. Declare
   beside `flexToggle`/`trajToggle`.
2. **Extracting the shared core silently dropped `_OCCUPANCY_CACHE`.**
   `production_occupancy_cached` declares `global _OCCUPANCY_CACHE`; with the name gone,
   every oxDNA occupancy request died with a `NameError` while the whole unit suite stayed
   green, because nothing there calls the cached wrapper. Pinned now by
   `test_cached_wrapper_resolves_its_module_globals`.
3. **A `bluntEnds` TDZ that was NOT a real bug.** It appeared only while boot was already
   broken; once (1) was fixed the spec passed without touching it. Forward-declaring it was
   reverted — worth remembering that a TDZ deep in `main.js` can be a *symptom* of an
   earlier init failure rather than its own defect.

Order of discovery matters here: each masked the next, and a truncated `tail` of the
Playwright output made me report a fix as working when the spec was still red. Read the
whole failure block.
