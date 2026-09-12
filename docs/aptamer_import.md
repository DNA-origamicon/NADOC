# Aptamer import and native representation mapping

Use **Import → Aptamer…** to add a bundled folded motif or a local DNA PDB
(including a NAMD coordinate PDB). Existing designs receive a new movable cluster;
empty sessions receive a new design. Both paths record an undoable Aptamer import
feature; undoing the first import returns to an empty document. Each covalent chain becomes a separately
identified, named oligo in the strand spreadsheet, with its sequence and an editable
domain ordered 5′→3′. The four G-runs of an intramolecular quadruplex are not four
separate oligos.

Resize the strand's 5′ or 3′ end using the existing end tools to add attachment
bases. The G4 sequence and coordinates remain intact; new bases are `N` until
assigned. New terminal coordinates use B-DNA attachment slots fitted to the native end frame.
This is an initial design geometry that needs relaxation, not an atomistically
optimized overhang. Save as `.nadoc` to retain the imported geometry and identities.

## Sources reviewed

Bundled PDB files were downloaded from `https://files.rcsb.org/download/ID.pdb`
on 2026-09-11. Headers are retained; NMR ensembles are reduced to the first model.
The runtime catalog works offline.

| PDB | Strand sequence (5′→3′) | Why included |
| --- | --- | --- |
| [148D](https://www.rcsb.org/structure/148D) | GGTTGGTGTGGTTGG | TBA/HD1, two-quartet antiparallel G4 with three loops; a starting motif for potassium-responsive aptamer designs. |
| [1C35](https://www.rcsb.org/structure/1C35) | GGTTGGTGTGGTTGG | TBA structure from the study of potassium-saturated and intermediate potassium–DNA complexes. Includes deposited K coordinates in the source file. |
| [2HY9](https://www.rcsb.org/structure/2HY9) | AAAGGGTTAGGGTTAGGGTTAGGGAA | Human telomeric hybrid-1 G4 determined in potassium solution. |

[Structure-switching potassium aptamer research](https://pmc.ncbi.nlm.nih.gov/articles/PMC4209343/)
uses alternative hairpin states to tune the response of TBA-derived sequences.
[Origami-bound telomeric G4 experiments](https://pubmed.ncbi.nlm.nih.gov/25413669/)
show that attachment constraints can change ion selectivity. These structures are
building blocks, not calibrated concentration sensors or validated locks for an
arbitrary origami geometry. No universal Kd or switching concentration is assigned.

[NAMD-based G4 modeling work](https://pmc.ncbi.nlm.nih.gov/articles/PMC7545536/)
uses PDB-derived templates (including 2M27 and 3SC8). The research search found
usable deposited PDB coordinates; it did not establish a reusable, validated
NAMD PSF/configuration bundle for the offered motifs. A NAMD coordinate PDB can
use the local-file importer. PSF, DCD and NAMD configuration files are not parsed
by this menu. Force fields, solvent and ion occupancy still require MD preparation.

## Native mapping

`Helix.native_residues` holds typed residue sites: stable `bp_index`, base,
source residue identity, and named atom coordinates in nm. `native_source`
records provenance. Here the helix is a strand-address carrier, not a claim that
the chain forms a duplex. Each native `Strand` has its own UUID and domain; no
protein surrogate, reference-only strand or session-only PDB cache is used.

The importer selects the first model, honors chain/TER/segment boundaries,
preserves insertion codes and file residue order, selects blank/A alternate
locations, and normalizes prime/CHARMM phosphate atom names. Missing frame atoms,
RNA and broken O3′–P connectivity fail explicitly. Protein, water and free-ion
records do not become strands. Arbitrary local DNA is accepted as a candidate;
the importer does not infer G-quartet contacts or prove ion responsiveness.

All representations read the same persisted sites:

- Coarse/full geometry: C1′ backbone landmark, base-ring centroid, glycosidic-side
  direction and base-plane normal. Full uses the standard strand-colored backbone
  cones, with no extra duplex-axis tube over the folded chain.
- Cylinder geometry: a thin curve following the saved backbone, not a straight
  B-DNA axis.
- Atomic geometry (and atom-derived surfaces): source coordinates for matching
  native heavy atoms. Missing terminal atoms use fitted native templates. Edited
  bases use their own base templates fitted to the saved sugar frame.
- Cluster transforms and authored nucleotide transforms apply after native
  placement. Simulation frame overrides retain precedence.

The mapping preserves the deposited syn/anti residue coordinates without making
G–G contacts into Watson–Crick pairs. Atomic connectivity comes from native strand
order and atom templates. Source hydrogens and free ions are not included in the
native rendering/export model. Adding ions and concentration-dependent folding
or mechanical locking constraints is separate simulation work. Lattice-only
exports cannot encode these arbitrary coordinates; use `.nadoc` or PDB for
structural interchange.

## Verification

`tests/test_aptamer_import.py` covers real templates, save/reload, exact matching
atom coordinates, cluster transformations, distinct strand identities,
TER/insertion codes, both terminal resizes, curve projection and API integration.
Frontend tests cover menu/modal import, retry, and duplicate-submit protection.
MD thermodynamics and experimental origami locking are not validated by these tests.

`tests/test_aptamer_history.py` exercises import, move/rotate commits, feature
editing/deletion, dependency-aware import deletion, seek, revert, resize and
undo/redo through the HTTP API, comparing native, coarse and atomic coordinates.
The browser regression covers live movement previews, cancellation, commits,
rotation, undo/redo and representation/timeline round trips.

## Origami attachment and cadnano editing

Resizing either end registers the added bases as ordinary inline overhang domains,
with OverhangSpec IDs, labels and sub-domains. They appear in Overhang Connections
and can pair with regular staple overhangs. Tail binders occupy distinct antiparallel
B-DNA slots while the deposited G4 core retains its coordinates.

The 3D Force Crossover tool accepts G4 3′/5′ ends and opposite-polarity ends on
regular staples. The result is one native multi-domain strand, with concatenated
sequences and an undoable forced ligation. Scaffold sequence reassignment preserves
the authored G4 core.

Cadnano displays the native strand on its ordinary track with a four-guanine
G4 icon above the core. Both native tracks accept ordinary staple painting. Painting
an antiparallel partner auto-assigns the complementary sequence; overlapping the
native core selects ordinary B-DNA geometry for the carrier in all representations.
The icon reads “G4 · duplex” in this state. Tail-only pairing does not select this
state. Partial core overlap also selects the duplex layout for the carrier, with
unoccupied positions remaining single-stranded; this is an authored design layout,
not a predicted partial-folding intermediate or a thermodynamic simulation.
Deleting the partner or undoing the edit restores the deposited fold without losing
source coordinates or strand identity.

Regression coverage: `tests/test_aptamer_connections.py`,
`frontend/src/shared/aptamer.test.js`, and
`frontend/e2e/aptamer_connections.spec.js` cover native tails, direct duplexes,
forced ligation, core complement painting, icon drawing, and history restoration.
