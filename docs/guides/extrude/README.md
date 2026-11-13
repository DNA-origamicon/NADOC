# Extrude: a 3×6 square-lattice walkthrough

[All guides](../README.md) · [Coverage ledger](../LEDGER.md)

Create a 3×6 square-lattice model with Extrude, extend a 2×3 cross-section at one end, and add a separated 3×6 cluster. Follow cross-section selection, length and strand settings, and applying each result.

Numbered arrows point to
mouse targets while keeping their labels visible. Dashed boxes show drag extents.
Unmarked images show settings or results. This is an editorial draft for style review.

[Download the example](example.nadoc) · [Construction verification](verification.json) ·
[Capture and source metadata](manifest.json) · [UX findings](../UX_LEDGER.md)

## Scope

- Desktop: select a 3×6 cross-section normal to XY/XZ/YZ source planes, then Next for a fitted 3D length preview
- Length in bp/nm, forward/reverse direction, scaffold-size recommendations, strand classes and ligation
- Apply a 64 bp extrusion, continue a 2×3 end cross-section by 8 bp, then create a separated 3×6 cluster

## Contents

- [Create a square-lattice part](#create-a-square-lattice-part)
- [Choose a source plane](#choose-a-source-plane)
- [Select the 3×6 footprint](#select-the-36-footprint)
- [Choose strands and ligation](#choose-strands-and-ligation)
- [Set length, units and direction](#set-length-units-and-direction)
- [Use scaffold-length recommendations](#use-scaffold-length-recommendations)
- [Build the extrusion](#build-the-extrusion)
- [Continue from an existing end](#continue-from-an-existing-end)
- [Create a separate cluster](#create-a-separate-cluster)

## Create a square-lattice part

The shared guide model is three rows × six columns: 18 helices on a square lattice. This lesson uses 64 bp initially.

### Step 1

Choose File → New.

![Step 1: Choose File → New.](01.png)

### Step 2

Choose Square for the lattice type. The guide uses a temporary example name; use a meaningful name for your own part.

![Step 2: Choose Square for the lattice type. The guide uses a temporary example name; use a meaningful name for your own part.](02.png)

### Step 3

Click Create to open the empty square-lattice part.

![Step 3: Click Create to open the empty square-lattice part.](03.png)

### Step 4

Use Full representation throughout this guide. Full shows the nucleotide beads and base slabs; it is the standard display for guides.

![Step 4: Use Full representation throughout this guide. Full shows the nucleotide beads and base slabs; it is the standard display for guides.](04.png)

## Choose a source plane

The From control chooses the construction plane. XY extrudes normal to XY, XZ normal to XZ, and YZ normal to YZ. The camera turns smoothly to face the selected plane over 0.5 seconds, and orbit is locked during cross-section selection. Changing the plane clears an in-progress footprint: choose the plane before selecting cells. Tools → Extrude starts a new footprint; end continuation uses a different entry point shown later.

### Step 5

Open Tools → Extrude to start a new extrusion.

![Step 5: Open Tools → Extrude to start a new extrusion.](05.png)

### Step 6

Choose XZ in From. Notice the construction plane changes.

![Step 6: Choose XZ in From. Notice the construction plane changes.](06.png)

### Step 7

Choose YZ in From. Notice the construction plane changes.

![Step 7: Choose YZ in From. Notice the construction plane changes.](07.png)

### Step 8

Choose XY in From. Return to XY for the main example.

![Step 8: Choose XY in From. Return to XY for the main example.](08.png)

## Select the 3×6 footprint

Select three consecutive rows and six consecutive columns. Here the displayed indices are rows 0–2 and columns 1–6, positioned beside the floating tool panel. The offset is only to keep the targets visible; the footprint is still 3×6. Drag the tool-window title bar if it covers your intended cells. Extrude and Sweep share this cross-section picker and normal-view workflow. Grid colors identify strand-direction parity; the +/− extrusion buttons below are a separate choice.

### Step 9

Click a cell to select it. Click the same cell again to deselect it.

![Step 9: Click a cell to select it. Click the same cell again to deselect it.](09.png)

### Step 10

With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.

![Step 10: With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.](10.png)

### Step 11

The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.

![Step 11: The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.](11.png)

## Choose strands and ligation

Both, Scaffold and Staples select which strand classes the extrusion creates or extends. Ligate adjacent requests joining compatible neighboring strand ends at the extrusion boundary; leaving it unchecked keeps the new segment unligated. Compatibility depends on the source ends and selected strand classes.

### Step 12

Choose Scaffold to restrict the extrusion to scaffold strands.

![Step 12: Choose Scaffold to restrict the extrusion to scaffold strands.](12.png)

### Step 13

Choose Staples to restrict the extrusion to staple strands.

![Step 13: Choose Staples to restrict the extrusion to staple strands.](13.png)

### Step 14

Choose Both for the main example.

![Step 14: Choose Both for the main example.](14.png)

### Step 15

Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.

![Step 15: Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.](15.png)

### Step 16

Restore Ligate adjacent for this example and the later continuation.

![Step 16: Restore Ligate adjacent for this example and the later continuation.](16.png)

## Set length, units and direction

Step 1 selects the cross-section. Click Next for Step 2: the camera transitions over 0.5 seconds to a fitted oblique 3D view. The initial length is zero; enter a nonzero length to show the preview. Changing the length or direction refits the preview. Previous returns to the normal cross-section view while retaining the length and selected cells. Square-lattice spinner/arrow steps are 8 bp; you can type a different integer directly. In nm mode the entered distance is rounded to an integer number of base pairs using 0.334 nm/bp. Changing the unit reinterprets the field; enter the corresponding numeric value explicitly. +/− controls the extrusion direction, independently of the grid color.

### Step 17

Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.

![Step 17: Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.](17.png)

### Step 18

Enter 64 bp. The readout should show 18 × 64 bp = 1152 bp total.

![Step 18: Enter 64 bp. The readout should show 18 × 64 bp = 1152 bp total.](18.png)

### Step 19

For the same 64 bp length, choose nm and enter 21.376. The total remains 1152 bp.

![Step 19: For the same 64 bp length, choose nm and enter 21.376. The total remains 1152 bp.](19.png)

### Step 20

Click − to preview extrusion on the opposite side of the plane.

![Step 20: Click − to preview extrusion on the opposite side of the plane.](20.png)

### Step 21

The negative-direction readout and preview change together.

![Step 21: The negative-direction readout and preview change together.](21.png)

### Step 22

Return to + for the main example.

![Step 22: Return to + for the main example.](22.png)

## Use scaffold-length recommendations

The 7249 and 8064 chips propose a per-helix length for the current selection. They reserve 14 nt per helix for end loops: floor(target / selected helices) − 14. The recommendation sizes the selected extrusion.

### Step 23

Click 7249 to fill 388 bp for 18 selected helices.

![Step 23: Click 7249 to fill 388 bp for 18 selected helices.](23.png)

### Step 24

The recommendation sets the field to 388 bp and switches the unit to bp. Restore 64 bp for this lesson.

![Step 24: The recommendation sets the field to 388 bp and switches the unit to bp. Restore 64 bp for this lesson.](24.png)

### Step 25

Click 8064 to fill 434 bp for 18 selected helices.

![Step 25: Click 8064 to fill 434 bp for 18 selected helices.](25.png)

### Step 26

The recommendation sets the field to 434 bp and switches the unit to bp. Restore 64 bp for this lesson.

![Step 26: The recommendation sets the field to 434 bp and switches the unit to bp. Restore 64 bp for this lesson.](26.png)

## Build the extrusion

Review the 18-cell cross-section, 64 bp length and forward direction, then apply the extrusion.

### Step 27

With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.

![Step 27: With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.](27.png)

### Step 28

Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.

![Step 28: Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.](28.png)

## Continue from an existing end

Use BLUNT end rings to identify the source. Right-click an end → Extrude, or left-click the end and use the Extrude action in Properties. Amber cells represent compatible ends that can be continued. Step 1 faces the inherited source plane; Next opens the length preview in 3D. Existing geometry is shown at 15% opacity while the tool is open, making the new preview easier to see; closing or applying restores its normal display. The plane is inherited from the source; +/− defaults away from the body. Select only the ends you intend to extend. Ligate adjacent joins compatible strand ends at the boundary.

### Step 29

Enable BLUNT in the toolbar to show selectable end rings.

![Step 29: Enable BLUNT in the toolbar to show selectable end rings.](29.png)

### Step 30

Right-click the marked far-end ring, then choose Extrude from its menu.

![Step 30: Right-click the marked far-end ring, then choose Extrude from its menu.](30.png)

### Step 31

Choose Extrude to continue from this end.

![Step 31: Choose Extrude to continue from this end.](31.png)

### Step 32

From is locked to the selected source end. The tool chooses the initial direction away from the existing body.

![Step 32: From is locked to the selected source end. The tool chooses the initial direction away from the existing body.](32.png)

### Step 33

Select two rows × three columns of amber cells: six compatible ends for the continuation.

![Step 33: Select two rows × three columns of amber cells: six compatible ends for the continuation.](33.png)

### Step 34

Click Next to keep the selected end and inspect the continuation in 3D.

![Step 34: Click Next to keep the selected end and inspect the continuation in 3D.](34.png)

### Step 35

With 8 bp, Both and Ligate adjacent selected, apply the continuation.

![Step 35: With 8 bp, Both and Ligate adjacent selected, apply the continuation.](35.png)

### Step 36

The selected 2×3 cross-section is now 8 bp longer.

![Step 36: The selected 2×3 cross-section is now 8 bp longer.](36.png)

## Create a separate cluster

Open Tools → Extrude and select another 3×6 footprint a few cells away from the existing geometry. The gap creates a separate cluster that you can select and transform independently.

### Step 37

Open Tools → Extrude to start a new extrusion.

![Step 37: Open Tools → Extrude to start a new extrusion.](37.png)

### Step 38

With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.

![Step 38: With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.](38.png)

### Step 39

The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.

![Step 39: The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.](39.png)

### Step 40

Select another 3×6 footprint a few empty rows away from the existing bundle.

![Step 40: Select another 3×6 footprint a few empty rows away from the existing bundle.](40.png)

### Step 41

Click Next to preview the separate extrusion.

![Step 41: Click Next to preview the separate extrusion.](41.png)

### Step 42

Enter 64 bp and click Extrude to create the second cluster.

![Step 42: Enter 64 bp and click Extrude to create the second cluster.](42.png)

### Step 43

The two separated bundles form two clusters. Each cluster can be selected for its own tools and transformations.

![Step 43: The two separated bundles form two clusters. Each cluster can be selected for its own tools and transformations.](43.png)
