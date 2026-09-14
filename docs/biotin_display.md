# Bound biotin and 5′ biotin-TEG display

Full shows one yellow sphere (0.30 nm radius, a visual symbol rather than a
hydrodynamic radius) at the center of each DNA-occupied biotin ring. The same
markers appear in the conjugation-manager preview. In Full, a small spacer bead
and two cylinders connect each biotin sphere to the actual native 5′ DNA backbone
bead. This is a coarse connection symbol, not an atomistic linker conformation.
The connector shares the marker’s visibility and particle movement; protein deltas
reposition its pocket end while retaining its DNA endpoint. Empty pockets have no DNA
biotin marker. Particle pose, tetramer pose, movement, undo/redo and representation
switching preserve their registration. Full-mode simulation deltas are applied
per tetramer rather than applying tetramer 0's delta to the entire coating.

VDW, Ball & Stick, Stick and the native molecular surface use bound biotin plus
a 5′ biotin-TEG heavy-atom spacer. Chemistry defaults to `biotin_teg`; older records
without a chemical identity receive this explicit default when read. This is an
assumption about their modification, not identification of an experimental sample.
The manager's linker tooltip identifies the chemistry. No new runtime dependency
or network fetch is required.

## Structural sources and coordinate construction

- [PDB 1STP biological assembly](https://www.rcsb.org/structure/1STP): the existing
  bundled PDB supplies the bound BTN ring and initial tail. Protein C-alpha Kabsch
  alignment maps chain A's ligand into chains A–D, followed by the saved tetramer
  and nanoparticle transforms. The shared `biotin_pockets.json` catalog uses the
  same centered protein frame as `streptavidin_asset`.
- [IDT 5′ Biotin-TEG, /5BiotinTEG/](https://www.idtdna.com/Site/Catalog/Modifications/Product/8859),
  [chemical structure](https://www.idtdna.com/site/Catalog/Modifications/GetStructureImage/2100):
  biotin-C(O)-NH-CH2-CH2-O-CH2-CH2-O-CH2-CH2-O-CH2-CH2-O-P(DNA).
  The chemical diagram defines connectivity; ambiguous tri-/tetraethylene naming
  in supplier prose is not used to infer the atom count.

The carboxyl hydroxyl O12 is replaced by the spacer amide N. There are 28 added
heavy atoms and two retained ring closures; the spacer's terminal O bonds to the
existing DNA 5′ phosphate (no duplicate phosphate). The bicyclic ring stays at its
crystallographic coordinates. A deterministic least-squares fit varies the tail
and spacer, restraining bond lengths, bond angles, amide planarity and internal
nonbonded separations. It fixes the terminal oxygen at the phosphate's unoccupied
side, inferred from O5′/OP1/OP2, with a 0.160 nm P–O bond. DNA coordinates do not move.
Fits must meet explicit bond-length and angle residual thresholds.

New manager/API attachments default to 1.8 nm reach: the former 2 nm single-strep
example could not close the TEG spacer while respecting phosphate approach.
Existing saved reach values are unchanged. Reach describes the coarse-grained
anchor-to-backbone separation, not chemical contour length, and remains independently
editable because the oxDNA spring model supports geometries outside this chemistry.

When the finite fit fails, the same 28 atoms show an unconnected, chemically sized
spacer and the atomistic API returns a warning shown in the native atomistic view.
No stretched bond to DNA is emitted. Atom ordering remains stable for coordinate
consumers. Failure means this fitting search failed, not proof no conformer exists.

## Scope and validation

These are illustrative constrained display conformers, not energy-minimized or
experimentally validated equilibrium configurations. Hydrogens, charges and bonded
force-field parameters are not supplied. The fit screens internal spacer contacts;
it is not an all-atom gold/protein/solvent steric or energetic optimization. Existing
NAMD readiness restrictions remain in place; full strep-on-gold NAMD validation is
still technical debt. oxDNA continues to use its prescribed coarse-grained spring;
`linker_chemistry` is excluded from its design-staleness fingerprint.

Native design representations are covered here. Dynamic atomistic reconstruction
retains atom serials, but biotin pocket coordinates still come from design poses;
trajectory-aware protein/ligand/spacer reconstruction requires a separate validation
and must not be interpreted as simulated biotin motion. Full markers do follow the
available per-tetramer simulation deltas.

Tests cover pocket mapping, ring preservation, graph connectivity, bond lengths,
phosphate approach, unreachable endpoints, hidden/excluded DNA, multiple tetramers,
rigid movement, descriptor classification, surface consistency and browser mode
switching/movement/undo. No simulation runs were needed for this display change.

## Atomistic loading performance (2026-09-14)

Profiling isolated the slow operation: iterative biotin-TEG fitting accounted for
more than 99% of the small hybrid design's cold atomistic build. The imported PDB
was not being reconstructed expensively; it was incorrectly left as a C-alpha
trace even in VDW/Ball & Stick/Stick.

The solver now uses a vectorized analytic Jacobian and dense Levenberg–Marquardt
for this small dense problem, replacing a Python loop and iterative sparse LSMR.
The objective, fixed ring/phosphate geometry and final acceptance thresholds are
unchanged. Six A/B fixtures span 1.7–2.0 nm reach and one/three tetramers. Failed-fit
counts match the previous solver; the tested bonded distances remain 0.124–0.184 nm.
Uncached fitting is approximately 4–6× faster for the typical/harder cases.

A bounded memory cache plus a disposable SQLite cache (8,192 entries under the OS
NADOC user-cache directory) retains local conformers, including failed fits.
Keys include the molecular endpoints, solver version and structural catalog hash.
Requests for the same fit share a lock. Changed endpoints or chemistry invalidate
it; rigid particle movements reuse it. Corrupt/unavailable caches fall back to the
solver. No cache field is stored in a design or included in a simulation fingerprint.
Attachment and document loading prepare the cache before the representation switch;
a genuinely new/changed linker still incurs fitting cost at preparation time.

Coated streptavidin now uses the complete imported PDB atom/bond graph for VDW,
Ball & Stick and Stick. One GPU atom/bond prototype is shared across tetramers;
each copy has its own rigid placement, including simulation deltas. Atom and bond
coordinates move together. The Full trace/biotin symbols are hidden in these
atomistic modes. The protein atom data is already in the loaded coating, so mode
changes require no PDB fetch or backend protein reconstruction.
Protein spheres use the existing analytic sphere shader (two triangles per atom,
with spherical normals and depth), avoiding thousands of triangulated spheres.
The coating opts into a shared unit-radius material: physical radii live in the
instance transforms. All elements and both sphere modes reuse the same shader,
avoiding a second shader-compilation pass when first switching to VDW.
The diagnostic `?impostors=0` override still selects the ordinary mesh path.

Two additional browser problems compounded loading: a new part's first native
atomistic switch rebuilt the previous part's retained atom table before fetching
the new one, and autosave responses recreated linked coating meshes even when
their inputs were identical. Native cache misses now clear the stale table before
switching; simulation overlays retain ownership of their own data. Coating rebuilds
compare particle, conjugation, placement and nucleotide geometry inputs, preserving
GPU resources across metadata-only saves while still responding to edits and undo.
Atom-cache invalidation also ignores identity/metadata-only saves; an initial
autosave can no longer cancel the current model's in-flight atom request.

Matched backend measurements (median of five profiled builds after preparation):

| Design | DNA only | DNA + biotin |
| --- | ---: | ---: |
| 1 strand, 1 tetramer | 2.17 ms | 2.39 ms |
| 6 strands, 3 tetramers | 12.76 ms | 14.11 ms |

The former profiled cold builds took 1.21 s and 6.33 s respectively. Protein
rendering is measured separately in the browser because it reuses the loaded PDB.
A matched atom-count DNA control is also required: comparing six short strands
against those strands **plus** roughly 11,000 protein atoms is not equal rendering
work. Browser timings include both the switch operation and the next painted frame.

Final headless Chromium comparison (~11,964 coated-design atoms versus ~11,808
DNA-control atoms), after waiting for the imported Full view to paint:

| Representation | First painted view: DNA | First painted view: coated | Repeat painted view: DNA | Repeat painted view: coated |
| --- | ---: | ---: | ---: | ---: |
| Ball & Stick | 1,504 ms | 956 ms | 901 ms | 710 ms |
| VDW | 1,651 ms | 1,263 ms | 804 ms | 411 ms |
| Stick | 213 ms | 324 ms | 214 ms | 317 ms |

Repeat values are medians of two subsequent passes. Repeat switch setup itself
took 4.1/5.5/15.6 ms for the coated model versus 23.1/17.0/23.7 ms for DNA
(Ball & Stick/VDW/Stick). The coated design's first atomistic HTTP request took
42 ms. Timings through painting include two animation-frame callbacks and any
superseding model request, rather than stopping at fetch completion. First-use
numbers also include browser scheduling, shader work and background application
requests. These small headless samples are a reproducible smoke benchmark, not
a guarantee across GPUs, camera views or model sizes. In particular, Stick's
paint time remains slower for the dense protein/gold scene; loading/setup parity
does not imply equal per-frame rendering cost. The much smaller six-strand DNA
control is naturally faster to paint than those strands plus the full proteins.

Validation: 18 targeted backend tests (two native simulation tests deselected),
95 targeted frontend tests, and both Playwright workflow/benchmark tests passed.
The workflow verifies actual PDB atom/bond counts, transformed coordinates,
biotin connectivity, visibility, representation switching, movement and undo/redo.

Reproducible browser benchmark: `cd frontend && npx playwright test e2e/biotin_loading.spec.js --workers=1`.
It generates its matched fixtures and writes numeric timings under
`workspace/validation/biotin_loading_20260914/`. The independent chemistry A/B
results and initial call profiles are in the same validation directory.
