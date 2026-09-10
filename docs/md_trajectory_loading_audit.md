# NAMD trajectory and solvent loading

Verified against `small_plate.nadoc`, P1 Alpine (`a5e2cf157a76`). Its downloaded
production DCD contains **5,597 complete frames**. At the default interval of 20,
the trajectory contains 280 display frames.

## Frame count and loading feedback

The panel cached raw frame counts by job ID. A count obtained when only a live
frame or partial download existed could remain at one after the download
finished. Loading now awaits a fresh metadata count before confirming the frame
budget or reading coordinates. Concurrent older metadata replies cannot overwrite
that count. A circular spinner beside View trajectory stays visible through
counting, coordinate loading, and atom preparation, and clears on failure too.

## Solvent bottleneck and changes

A local cProfile comparison of two P1 frames (raw frames 0 and 25), requesting ions
and the periodic box, measured **54.46 seconds before / 28.44 seconds after**.
These are profiled backend extraction times, not browser wall-clock guarantees.
Both outputs were 1,249,176 bytes. All metadata and all 308,826 coordinate floats
were identical, including the 6,799 ions and 44,664 graphene atoms per frame.

The initial profile spent about 37 seconds parsing the full PSF and about 10
seconds building the DNA reference model twice. The package contains 2,977,603
atoms, mostly water. Solvent display does not consume PSF bonds, angles,
dihedrals, or impropers, but previously parsed and constructed all of them.

The solvent path now:

- Uses MDAnalysis' existing PSF atom parser and stops before bonded sections.
  The resulting Universe stays separate from the full-topology viewer cache.
- Reuses the existing model's phosphate coordinates for centroid alignment,
  avoiding a second model build while preserving the original reference.
- Skips unused DNA atom metadata and per-frame display dictionaries while retaining
  the same heavy-atom periodic imaging and alignment.
- Fetches the requested solvent frame first, displays it, then prepares nearby
  frames in batches. Previously the first display waited for up to 32 frames.

The PSF atom table remains the largest setup cost (about 16.8 profiled seconds),
followed by the reference model and nucleotide index construction. Each killable
analysis subprocess pays setup independently. Water additionally requires the
existing hydration-shell neighbour search; ions remain uncapped and use the same
periodic imaging as before. Binary coordinate transport was already in use.

## Validation

DOM regressions cover recounting a stale single-frame download, loading feedback,
count failures, and displaying ions before their background batch finishes.
A real PSF/DCD test compares the reduced topology's atom order, residues,
coordinates, and solvent selections against MDAnalysis' full parser. Existing
solvent transform, binary transport, route, atom identity, and rendering tests
also pass. The P1 comparison read local results without altering the job.

## Follow-up: water disabled for trajectory playback

Full-trajectory viewing now disables and unchecks Water, hides its shell controls,
and sends no water requests even when water was enabled in saved settings. Live
Display MD retains its water option and preference.

The ions-only path additionally skips water triplet construction, DNA heavy-atom
layout and base-ring indexing, and the ion-to-DNA neighbour query. Ion imaging
still uses the same phosphate-derived alignment: DNA anchor shifts are integer
box vectors, so the final primary-cell fold makes the neighbour search redundant.
Coordinates are selected from the trajectory reader buffer without first copying
the full solvated AtomGroup. Changing bead/VDW/ball-and-stick representation reuses
the existing ion coordinates rather than requesting another extraction.

The same P1 two-frame profile measured **24.19 seconds**, versus 28.44 seconds
before this follow-up (about 15% less). Metadata and atom counts were unchanged;
the largest coordinate difference was 0.00000191 nm, from floating-point rounding
when redundant periodic translations were omitted. Randomized periodic-image
tests independently compare both imaging paths. The atom table and alignment
reference remain the principal initial loading costs.

## Follow-up: preserve the loaded trajectory while browsing

The MD panel now tracks the loaded trajectory's job separately from the job
selected in the list. Deselection, selection of a different completed job or draft,
and subsequent status refreshes retain the loaded frames, atom preparation,
playback controls, and ion companions. Selecting the original job again reuses
them. Selecting another job does not launch trajectory extraction or Alpine
prewarming; View trajectory must be chosen explicitly to replace the loaded job.

A pending load retains its original job and interval if selection changes, so its
completion cannot attach ions from the newly selected job. Explicit Off, another
visualization mode, or opening another design still tears down the active view.
DOM tests exercise selection, deselection, polling, reuse, explicit replacement,
and selection changes during loading.
