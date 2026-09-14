# Biotinylated DNA occupancy and native placement

Apply the streptavidin coating first, then select an integer DNA count per applied tetramer, sequence, and linker reach. Unsaved coating edits disable DNA attachment. Adsorption permits requests of 1–4 DNA per tetramer; biotin tether permits 1–3 because pocket A anchors the protein. These are requested occupancies, not measured accessible-site counts. Every strand uses the entered sequence. Step 1 coating controls are on the left, the 3D preview is central, and Step 2 DNA controls are on the right. Attaching or removing DNA updates this manager in place. Final Apply finishes the operation; it does not recreate an unchanged coating. Remove coating sits below the coating settings.

Every applied tetramer receives exactly the requested count, or nothing changes. Multiple strands require automatic pocket selection. Remove the DNA set before changing its count or the coating. Attachment/removal each form one feature-log and undo/redo operation. Records identify the tetramer and pocket; old records default to tetramer zero.

## Placement

PDB 1STP chain alignment maps the bound biotin carboxyl-tail exit into each applied protein pose. A geometric linker follows that exit and ends at the first native DNA backbone bead, rather than the helix axis. Each DNA is a single forward strand on a normal NADOC helix with native rise (0.334 nm), twist (34.3 degrees), and radius (1 nm). No complementary strand is added.

The deterministic search ranks pockets by outward direction, then tries rigid helix orientations and phases. The flexible linker permits the straight helix to turn at its attachment; nucleotide spacing is never distorted. Backbone and backbone-to-base segments are sampled at at most 0.15 nm spacing. Candidates require 0.5 nm clearance from particle surfaces and coating heavy atoms; linker paths require 0.25 nm. Different DNA/linker paths require 0.8 nm separation. Other cores, coatings and existing native DNA domains are obstacles too. These are native bead/segment criteria, not an all-atom steric calculation.

The finite search can miss a feasible layout. Failure reports the tetramer and number found, suggesting fewer DNA, longer linkers or lower coverage. Requested occupancy is never silently reduced. The preview uses the scene's native nucleotides and reports actual occupancy. Particle rotation transforms helical phase as well as axis, preserving the DNA relative to its protein pocket.

## Simulation boundary

Ideal B-form is an initial representation, not a prediction of equilibrium ssDNA shape or experimental site accessibility. oxDNA uses a separate extended ssDNA preparation seed with legal backbone spacing. New placements start that seed at the native 5′ attachment and screen its extended path too. Placement version 1 preserves the prior seed convention for saved attachments.

Fixed-core DNANM export expands all tetramers, assigns three prescribed anchors per tetramer and one reciprocal protein–DNA spring per occupied pocket. Gold exclusion is emitted once per core. This extends the existing restraint model; it does not establish adsorption or binding energetics. GPU convergence/sampling and experimental occupancy validation remain open, as does NAMD validation of the original strep-on-gold system (TD-STREP-NAMD).

## Validation (2026-09-14)

- 42 focused backend tests passed, including exact 4-site adsorption and 3-site biotin-tether occupancy, multiple tetramers, independent finer clearance sampling, rigid rotation, atomic failure and undo/redo, and legacy seed behavior.
- Native CPU and CUDA each completed MC, MD relaxation and equilibration for three tetramers with two 16-base DNA strands each (1,548 particles). All saved coordinates were finite; all nine protein anchors and six reciprocal DNA tethers were present. These are short execution checks, not equilibrium validation.
- 69 focused frontend tests passed.
- Four Playwright workflows passed in 3.0 minutes: the original single-strep manager, DNA-only GPU execution/display, single-strep GPU execution/display, and exact two-DNA occupancy across three tetramers with six native preview strands, generation, removal, undo and redo. Test scratch designs and native jobs were cleaned up.

Manager layout follow-up: five UI tests and two Playwright workflows passed, verifying left/right step order, Remove coating placement, in-place DNA attachment/removal and preview refresh, and final Apply without an extra undo entry.
