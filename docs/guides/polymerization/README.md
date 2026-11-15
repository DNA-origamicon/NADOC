# A complete 6HB origami: periodic ends, linear polymers and circles

[All guides](../README.md) · [Coverage ledger](../LEDGER.md)

Build a standard honeycomb 6HB with a fully assigned p7560 scaffold, route periodic staple bridges, inspect the seam in the cadnano editor, and create linear and circular polymer assemblies.

Numbered arrows point to
mouse targets while keeping their labels visible. Dashed boxes show drag extents.
Unmarked images show settings or results. This is an editorial draft for style review.

[Download the example](example.nadoc) · [Construction verification](verification.json) ·
[Capture and source metadata](manifest.json) · [UX findings](../UX_LEDGER.md)

## Scope

- Honeycomb 6HB construction, seamed scaffold routing, standard autostaple and p7560 sequence assignment
- Cadnano inspection, periodic-boundary mirror, sequence and 3D visualization options
- Three-unit linear assembly and a six-unit circular arrangement using Curve to make polymer circle

## Example files

Keep each assembly beside its source part:

- [__e2e__6hb-straight.nadoc](__e2e__6hb-straight.nadoc)
- [__e2e__6hb-circle-unit.nadoc](__e2e__6hb-circle-unit.nadoc)
- [__e2e__6hb-linear-polymer.nass](__e2e__6hb-linear-polymer.nass)
- [__e2e__6hb-circular-polymer.nass](__e2e__6hb-circular-polymer.nass)

## Contents

- [Create a standard honeycomb 6HB](#create-a-standard-honeycomb-6hb)
- [Route scaffold and staples](#route-scaffold-and-staples)
- [Make the ends periodic](#make-the-ends-periodic)
- [Assign the scaffold and staple sequences](#assign-the-scaffold-and-staple-sequences)
- [Inspect topology and sequences in the cadnano editor](#inspect-topology-and-sequences-in-the-cadnano-editor)
- [Use the periodic boundary view](#use-the-periodic-boundary-view)
- [Choose useful 3D visualizations](#choose-useful-3d-visualizations)
- [Create an actual linear polymer assembly](#create-an-actual-linear-polymer-assembly)
- [Bend a repeat for a circular polymer](#bend-a-repeat-for-a-circular-polymer)
- [Build and inspect the circular assembly](#build-and-inspect-the-circular-assembly)

## Create a standard honeycomb 6HB

Build the six-helix ring on a honeycomb lattice. Use your own descriptive filenames; the __e2e__ names shown here identify the isolated guide capture. This lesson uses a 1,236 bp initial extrusion; Seamed Autoscaffold adjusts the terminal turns to produce a single 7,560-nt scaffold matching p7560. Full representation is used for construction; later images explicitly demonstrate visualization choices.

### Step 1

Choose File → New.

![Step 1: Choose File → New.](01.png)

### Step 2

Name the part and choose Honeycomb, then Create.

![Step 2: Name the part and choose Honeycomb, then Create.](02.png)

### Step 3

Open Tools → Extrude. Choose the XY source plane.

![Step 3: Open Tools → Extrude. Choose the XY source plane.](03.png)

### Step 4

Select the six cells of the hexagonal ring: rows 0 and 1, columns 1–3. The count must read 6 helices.

![Step 4: Select the six cells of the hexagonal ring: rows 0 and 1, columns 1–3. The count must read 6 helices.](04.png)

### Step 5

Click Next to set the bundle length.

![Step 5: Click Next to set the bundle length.](05.png)

### Step 6

Set 1236 bp, + direction and Both strands; click Extrude.

![Step 6: Set 1236 bp, + direction and Both strands; click Extrude.](06.png)

## Route scaffold and staples

Run Seamed Autoscaffold to obtain matched end faces, then Standard Full Autostaple to route the interior staples. Autoscaffold can extend individual helix ends; inspect the routed scaffold length rather than assuming it equals six times the initial extrusion length.

### Step 7

Choose Tools → Routing → Autoscaffold.

![Step 7: Choose Tools → Routing → Autoscaffold.](07.png)

### Step 8

Choose Seamed and click Run to route the scaffold with matched ends.

![Step 8: Choose Seamed and click Run to route the scaffold with matched ends.](08.png)

### Step 9

Choose Tools → Routing → Full Autostaple.

![Step 9: Choose Tools → Routing → Full Autostaple.](09.png)

### Step 10

Keep Standard and click OK to route the interior staples.

![Step 10: Keep Standard and click OK to route the interior staples.](10.png)

## Make the ends periodic

Route for Polymerization fills the bare terminal scaffold regions with connector staples and joins their terminal tips across the periodic seam. Each copy retains its own scaffold. The bridging staples join adjacent repeats; in the part they are recorded as periodic seam strands.

### Step 11

Choose Tools → Routing → Route for Polymerization.

![Step 11: Choose Tools → Routing → Route for Polymerization.](11.png)

### Step 12

The 6HB now has six periodic staple bridges, one for each face helix. Inspect their seam routing in the cadnano editor next.

![Step 12: The 6HB now has six periodic staple bridges, one for each face helix. Inspect their seam routing in the cadnano editor next.](12.png)

## Assign the scaffold and staple sequences

Assign p7560 after routing so the entire 7,560-nt scaffold receives the intended sequence. Full Autostaple initially uses M13mp18; this explicit assignment replaces it. Then assign complementary staple sequences, including the periodic bridges. The saved example is checked for undefined bases.

### Step 13

Choose Tools → Sequencing → Assign Scaffold Sequence.

![Step 13: Choose Tools → Sequencing → Assign Scaffold Sequence.](13.png)

### Step 14

Select p7560 (7,560 nt), verify the matching scaffold length, and click Apply.

![Step 14: Select p7560 (7,560 nt), verify the matching scaffold length, and click Apply.](14.png)

### Step 15

Choose Assign Staple Sequences to complement all staples against the assigned scaffold.

![Step 15: Choose Assign Staple Sequences to complement all staples against the assigned scaffold.](15.png)

## Inspect topology and sequences in the cadnano editor

Open Origami Editor to inspect the same saved part as a flat strand diagram. Check scaffold continuity, staple crossovers, terminal connector staples and sequence assignment. The path view preserves base-pair indices even when the 3D part is bent.

### Step 16

Click Origami Editor in the top bar.

![Step 16: Click Origami Editor in the top bar.](16.png)

### Step 17

Press F to fit all six helices. Follow the scaffold route and the staple crossovers between helices.

![Step 17: Press F to fit all six helices. Follow the scaffold route and the staple crossovers between helices.](17.png)

### Step 18

Enable sequence letters and undefined-base highlighting. Zoom into domains to read individual bases; the verified example contains no undefined sequence bases.

![Step 18: Enable sequence letters and undefined-base highlighting. Zoom into domains to read individual bases; the verified example contains no undefined sequence bases.](18.png)

## Use the periodic boundary view

Enable PBC to display translucent copies of the terminal regions beside the opposite ends. The two red boundary sliders define the display period P = far − near. Dashed seam connections pass through that boundary. Dragging a boundary changes this inspection view; editing a mirrored strand changes the real part. The view resets when disabled or reloaded.

### Step 19

Click PBC to show the periodic boundary sliders, repeated end regions and dashed seam connections. Red ruler labels report the original base indices in the mirrored regions.

![Step 19: Click PBC to show the periodic boundary sliders, repeated end regions and dashed seam connections. Red ruler labels report the original base indices in the mirrored regions.](19.png)

### Step 20

Drag the far red ruler handle outward to change the display period. Read the seam-gap indicator and compare the displaced mirror with the real end; this moves the boundary, not the DNA.

![Step 20: Drag the far red ruler handle outward to change the display period. Read the seam-gap indicator and compare the displaced mirror with the real end; this moves the boundary, not the DNA.](20.png)

### Step 21

Toggle PBC off and on to restore the boundaries to the active strand extents before inspecting the seam.

![Step 21: Toggle PBC off and on to restore the boundaries to the active strand extents before inspecting the seam.](21.png)

### Step 22

Right-drag to center the far boundary, then scroll up to inspect the seam and individual sequence bases. Compare the terminal scaffold and bridging staple on the real unit with the translucent neighboring unit; the mirror is an inspection view, not an assembly instance.

![Step 22: Right-drag to center the far boundary, then scroll up to inspect the seam and individual sequence bases. Compare the terminal scaffold and bridging staple on the real unit with the translucent neighboring unit; the mirror is an inspection view, not an assembly instance.](22.png)

### Step 23

For this staggered 6HB, the physical repeat is 1260 bp while the default bounding span is 1267 bp. Move the far boundary 7 bp inward: the “overlap 7 bp” display lets the staggered ends interlock. This changes only the inspection period; assembly placement comes from the recorded seams.

![Step 23: For this staggered 6HB, the physical repeat is 1260 bp while the default bounding span is 1267 bp. Move the far boundary 7 bp inward: the “overlap 7 bp” display lets the staggered ends interlock. This changes only the inspection period; assembly placement comes from the recorded seams.](23.png)

## Choose useful 3D visualizations

Full shows nucleotide geometry; Cylinders simplify the bundle shape. Length coloring helps inspect the staple length distribution. The temperature overlay cycles through domain melting temperature and total staple folding temperature; these estimates support inspection rather than proving assembly yield. Periodic Seam Connections reveals the normally hidden long seam arcs in the single-part view.

### Step 24

Press F2 for Cylinders to inspect the long 6HB shape.

![Step 24: Press F2 for Cylinders to inspect the long 6HB shape.](24.png)

### Step 25

Press F4 for Full, then enable LENGTH to color staples by length.

![Step 25: Press F4 for Full, then enable LENGTH to color staples by length.](25.png)

### Step 26

Click TM to inspect domain melting temperatures with the displayed color scale.

![Step 26: Click TM to inspect domain melting temperatures with the displayed color scale.](26.png)

### Step 27

Click TM again for total staple folding temperatures. Check the legend to distinguish this from the domain view.

![Step 27: Click TM again for total staple folding temperatures. Check the legend to distinguish this from the domain view.](27.png)

### Step 28

View → Periodic Seam Connections shows the long seam arcs on the unit; these are periodic connections, not strands passing through the bundle interior.

![Step 28: View → Periodic Seam Connections shows the long seam arcs on the unit; these are periodic connections, not strands passing through the bundle interior.](28.png)

### Step 29

Inspect the periodic connectors, then turn Periodic Seam Connections off for the polymer overview.

![Step 29: Inspect the periodic connectors, then turn Periodic Seam Connections off for the polymer overview.](29.png)

## Create an actual linear polymer assembly

Create a separate assembly and add the saved periodic part. The “via periodic boundary” option derives repeat placement from its seam strands. Chain length is the total number of units including the seed. Forward, Backward and Both choose where new repeats are placed relative to it.

### Step 30

Choose File → New Assembly and give the assembly a name.

![Step 30: Choose File → New Assembly and give the assembly a name.](30.png)

### Step 31

Choose Assembly → Add Part to insert the saved periodic unit.

![Step 31: Choose Assembly → Add Part to insert the saved periodic unit.](31.png)

### Step 32

Choose __e2e__6hb-straight.nadoc from the library.

![Step 32: Choose __e2e__6hb-straight.nadoc from the library.](32.png)

### Step 33

Choose Assembly → Polymerize Origami.

![Step 33: Choose Assembly → Polymerize Origami.](33.png)

### Step 34

Choose the part’s “via periodic boundary” entry, set Chain length to 3 total, and keep Forward. The seed is included in this count.

![Step 34: Choose the part’s “via periodic boundary” entry, set Chain length to 3 total, and keep Forward. The seed is included in this count.](34.png)

### Step 35

A straight chain reports “Chain does NOT close”; that is expected for a linear polymer.

![Step 35: A straight chain reports “Chain does NOT close”; that is expected for a linear polymer.](35.png)

### Step 36

Click Polymerize to create the repeated part instances and seam mates in this assembly.

![Step 36: Click Polymerize to create the repeated part instances and seam mates in this assembly.](36.png)

### Step 37

The three units now form a real assembly polymer. Press F2 for Cylinders to inspect the overall arrangement; each repeat remains a separate part instance.

![Step 37: The three units now form a real assembly polymer. Press F2 for Cylinders to inspect the overall arrangement; each repeat remains a separate part instance.](37.png)

## Bend a repeat for a circular polymer

Open the straight part and use Save As to create a separate circular unit. Tools → Bend offers Curve to make polymer circle after periodic strands exist. Set six units; the tool derives the curvature from the periodic seam span. Direction rotates the bending plane. This chapter demonstrates CAD curvature and geometric ring placement; it does not apply loop/skip compensation or validate the relaxed physical shape. The repeat is still a part; copies are created later in its assembly.

### Step 38

Choose Save As to preserve the straight unit and create a separate bent unit.

![Step 38: Choose Save As to preserve the straight unit and create a separate bent unit.](38.png)

### Step 39

Save the new part as the circular-unit example.

![Step 39: Save the new part as the circular-unit example.](39.png)

### Step 40

Set Selectable to Cluster before choosing the complete 6HB.

![Step 40: Set Selectable to Cluster before choosing the complete 6HB.](40.png)

### Step 41

Click the 6HB to select the complete unit.

![Step 41: Click the 6HB to select the complete unit.](41.png)

### Step 42

Choose Tools → Bend with the complete unit selected; the planes span that selection.

![Step 42: Choose Tools → Bend with the complete unit selected; the planes span that selection.](42.png)

### Step 43

Enable Curve to make polymer circle and enter 6 units. Review the calculated bend; refine this example’s angle in the next step before Apply.

![Step 43: Enable Curve to make polymer circle and enter 6 units. Review the calculated bend; refine this example’s angle in the next step before Apply.](43.png)

### Step 44

For this exact 6HB, the automatic estimate leaves a 0.515 nm six-unit closure residual. Uncheck Curve to make polymer circle and refine Angle to 60.3229°, keeping Direction 0° and planes −12–1254 bp. The recorded manual setting meets the 0.5 nm closure tolerance; this value is specific to this example.

![Step 44: For this exact 6HB, the automatic estimate leaves a 0.515 nm six-unit closure residual. Uncheck Curve to make polymer circle and refine Angle to 60.3229°, keeping Direction 0° and planes −12–1254 bp. The recorded manual setting meets the 0.5 nm closure tolerance; this value is specific to this example.](44.png)

### Step 45

The bent periodic unit is ready for repetition. Its source construction, routing and sequence assignment remain in its feature history.

![Step 45: The bent periodic unit is ready for repetition. Its source construction, routing and sequence assignment remain in its feature history.](45.png)

## Build and inspect the circular assembly

Create a new assembly using the bent unit and choose six total repeats. Verify both the rotational and translational residuals before polymerizing. A circular arrangement requires the accumulated repeat transform to return to the starting frame; the closure check measures that alignment. Consecutive seam mates remain explicit assembly operations.

### Step 46

Choose File → New Assembly and give the assembly a name.

![Step 46: Choose File → New Assembly and give the assembly a name.](46.png)

### Step 47

Choose Assembly → Add Part to insert the saved periodic unit.

![Step 47: Choose Assembly → Add Part to insert the saved periodic unit.](47.png)

### Step 48

Choose __e2e__6hb-circle-unit.nadoc from the library.

![Step 48: Choose __e2e__6hb-circle-unit.nadoc from the library.](48.png)

### Step 49

Choose Assembly → Polymerize Origami.

![Step 49: Choose Assembly → Polymerize Origami.](49.png)

### Step 50

Choose the part’s “via periodic boundary” entry, set Chain length to 6 total, and keep Forward. The seed is included in this count.

![Step 50: Choose the part’s “via periodic boundary” entry, set Chain length to 6 total, and keep Forward. The seed is included in this count.](50.png)

### Step 51

Wait for the closure calculation to finish after changing the count. Check “Chain closes” and both residuals before creating the ring. This tests the accumulated repeat transform.

![Step 51: Wait for the closure calculation to finish after changing the count. Check “Chain closes” and both residuals before creating the ring. This tests the accumulated repeat transform.](51.png)

### Step 52

Click Polymerize to create the repeated part instances and seam mates in this assembly.

![Step 52: Click Polymerize to create the repeated part instances and seam mates in this assembly.](52.png)

### Step 53

Six bent units form a circular arrangement. Cylinders make the overall shape readable. The closure readout verifies geometric alignment; the feature creates five consecutive seam mates, not a sixth closing mate.

![Step 53: Six bent units form a circular arrangement. Cylinders make the overall shape readable. The closure readout verifies geometric alignment; the feature creates five consecutive seam mates, not a sixth closing mate.](53.png)
