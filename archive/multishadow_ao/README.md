# Multishadow ambient occlusion — RETIRED 2026-07-28

A faithful port of ChimeraX's `lighting soft` / `full` ambient shadows: N
uniformly distributed directions, an orthographic depth render along each into
one tiled atlas, cached view-independent world→shadow matrices, and a
cosine-weighted `max(dot(N,-L),0) * lit` accumulation normalised by
`0.25 * count`. Two consumption paths — a screen-space composer pass, and an
in-material patch of three's `<aomap_fragment>` so occlusion multiplied only
`reflectedLight.indirectDiffuse` (ChimeraX's `Iamb *= mshadow`).

It worked. It was removed anyway, for a reason that is arithmetic rather than
implementation:

**A cast shadow can only subtract the KEY light; ambient occlusion can only
modulate the AMBIENT term. They compete for the same image.**

| lighting | key/fill/ambient | AO can affect | cast shadow removes |
|---|---|---|---|
| ChimeraX `full` | 0.7 / 0.3 / 0.8 | 44% of the light | 39% |
| what we shipped | 2.0 / 0.0 / 0.15 | **7%** | **93%** |

On DNA origami the deep directional shadow read far better than the soft
occlusion, so the lighting settled at ambient 0.15 — at which point AO is
mathematically almost a no-op and toggling it changed nothing on screen.

A second, independent reason it underdelivered: **shadow-map resolution in
nm/texel**. At 64 directions a 1024 atlas gives each direction only 128 px,
which on a 150 nm structure is ~2.3 nm/texel — coarser than a 2.0 nm duplex, so
the occlusion could not resolve a single helix. ChimeraX's defaults are sized
for a ~5 nm protein. 4096+ fixes the resolution but not the competition above.

**What was kept in the live tree** (`frontend/src/scene/photo_renderer/`):
- `shadow_bounds.js` — frustum fitting, the depthWrite/overlay exclusion list,
  outlier rejection, and the geometry fingerprint. All of it is load-bearing for
  the key-light shadow, and all of it was written for this.

**If you revive it:** it depends on `shadow_bounds.js` (still present) and needs
an ambient level worth modulating — i.e. it belongs with an ambient-dominant rig
(`lighting soft`), never with max-contrast key lighting.

Full findings: `photo_mode_ao_and_lowpoly_spec.md` Part B.
