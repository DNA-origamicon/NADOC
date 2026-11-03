# Measured on real data — supporting detail

[Topic head](../../project_oxdna_occupancy_clouds.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Measured on real data

| Job | nt basis | bp basis | Verdict |
|---|---|---|---|
| `exp35_.../14b896dab3c2` (540 nt, 50 prod frames) | PC1 0.78, sil +0.58 | PC1 0.83, sil +0.59 | **drift** — 1 transition, n_eff 2.6 |
| `exp31_.../0cc5368fbfda` (14 494 nt, 108 prod frames) | PC1 0.27, sil +0.23 | PC1 0.29, sil **+0.25** | **switching** — 24 transitions, 12–13 visits/state, n_eff 54, 71 %/29 % |
| **`5ce768ef2acf` VoltronCore · field** (14 774 nt, 50 prod frames) — live `:8000`, via the route | PC1 **0.47**, sil +0.39 | PC1 0.52, sil +0.34 | **switching** — 9 transitions, 5 visits/state, n_eff 24.7 (*preliminary*), **74 %/26 %**, medoids **2.29 nm** apart |

VoltronCore behaves as the user predicted: two distinct configurations, a genuinely dominant
PC1, and enough recurrence to call them states — though `n_eff 24.7` sits just under the
`OCCUPANCY_PRELIM_NEFF = 25` bar, so the UI flags the populations as not yet converged.

The exp31 job straddles the 0.25 floor: `nt` says unimodal, `bp` says switching. The floor
is doing real work, and basis choice matters at the margin — which is why `basis` is a
user-facing control rather than a constant. Default is `nt` (matches RMSF's atom set).

Forcing `n_clusters=3` on VoltronCore correctly flips the verdict to **drift**: the third
cluster is a single frame visited once, and the recurrence guard refuses to call an outlier
a state. Cache behaved as designed — first call 20.8 s, second 0.12 s.

## Verified in the app

`frontend/e2e/occupancy_clouds.spec.js` **passes** on the VoltronCore job (`5ce768ef2acf`,
~1.5 min): job select → radio → request → verdict → legend → **ghosts present in the scene**
→ switch to the flexibility map → ghosts gone → no console errors. Screenshot at
`frontend/e2e/screenshots/occupancy-clouds.png` shows the design in its own colours with a
translucent gold state-2 ghost superposed, legend reading
`74 % ± 9 %` / `26 % ± 9 % · 2.29 nm from state 1`, and the ⚠ under-sampling line.

Note the e2e backend is a throwaway on a dedicated port but resolves the SAME on-disk
workspace, so it sees the real jobs — the run never touches the user's `:8000` process.

**Four e2e-harness traps, all of which cost a full run to find** (they are about the app's
panel chrome, not this feature — expect them in any new oxDNA spec):

1. `#oxdna-jobs-heading` **no longer exists** — engine panels are tab-fronted, oxDNA is the
   selector's default tab, so the panel is already up once Dynamics is open.
2. `#oxdna-jobs-list` is a **hidden legacy node**; the visible list is `#simulate-jobs-list`,
   whose rows are scoped to the active design. Selecting via the hidden list (after setting
   `#oxdna-jobs-show-all` programmatically) is what works.
3. **Load the design THROUGH THE PAGE** (`import('/src/api/client.js').loadDesign`). A bare
   `POST /design/load` sets backend session state the booted page never syncs, leaving
   `currentDesign`/`currentGeometry` null — the ghosts then silently build nothing, and the
   panel still looks fine because it needs no design.
4. The in-progress status is "Clustering **configuration**s…", so a `/configuration/` regex
   races the fetch and passes before any result exists. Match a terminal verdict.
