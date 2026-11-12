# Extrude: a 3×6 square-lattice walkthrough

[All guides](../README.md) · [Coverage ledger](../LEDGER.md)

Desktop Extrude guide using the standard 3×6 square-lattice model (18 helices). Select the cross-section in Step 1, then click Next to set 64 bp in a fitted 3D view. Then edit the recorded length to 72 bp. This draft is being iterated for coverage and visual style before broader guide generation. Straight continuation is demonstrated. Deformed continuation is shown through entry and Cancel only because of a square-lattice implementation gap; coverage remains partial.

This is a tool demonstration, not a validated origami design. Numbered arrows point to
mouse targets while keeping their labels visible. Dashed boxes show drag extents.
Unmarked images show settings or results. This is an editorial draft for style review.

[Download the example](example.nadoc) · [Construction verification](verification.json) ·
[Capture and source metadata](manifest.json) · [UX findings](../UX_LEDGER.md)

## Scope

- Desktop: shared Extrude/Sweep cross-section selection normal to XY/XZ/YZ source planes, then Next for a fitted 3D length preview
- Length in bp/nm, direction, scaffold-size recommendations, strand classes and ligation
- Next/Previous preserves footprint and length; cancel, apply, feature editing and Undo/Redo
- Straight-end continuation with overlap refusal and a recorded result
- Deformed-end entry and Cancel after Bend preparation; square-lattice completion blocked by GUIDE-UX-004

## Contents

- [Create a square-lattice part](#create-a-square-lattice-part)
- [Choose a source plane](#choose-a-source-plane)
- [Select the 3×6 footprint](#select-the-36-footprint)
- [Set length, units and direction](#set-length-units-and-direction)
- [Use scaffold-length recommendations](#use-scaffold-length-recommendations)
- [Choose strands and ligation](#choose-strands-and-ligation)
- [Cancel a preview, then build](#cancel-a-preview-then-build)
- [Edit the recorded extrusion](#edit-the-recorded-extrusion)
- [Continue from an existing end](#continue-from-an-existing-end)
- [Deformed-end continuation: current limitation](#deformed-end-continuation-current-limitation)
- [Save and troubleshoot](#save-and-troubleshoot)

## Create a square-lattice part

The shared guide model is three rows × six columns: 18 helices on a square lattice. This lesson uses 64 bp initially. A painted lattice footprint is not yet a routed origami; scaffold routing and staple design are separate operations.

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

The From control chooses the construction plane, not a camera view. XY extrudes normal to XY, XZ normal to XZ, and YZ normal to YZ. The camera turns smoothly to face the selected plane over 0.5 seconds, and orbit is locked during cross-section selection. Changing the plane clears an in-progress footprint: choose the plane before selecting cells. Tools → Extrude starts a new footprint; end continuation uses a different entry point shown later.

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

## Set length, units and direction

Step 1 selects the cross-section. Click Next for Step 2: the camera transitions over 0.5 seconds to a fitted oblique 3D view, and the lattice cannot be repainted accidentally. The initial length is zero; enter a nonzero length to show the preview. Changing the length or direction refits the preview. Previous returns to the normal cross-section view while retaining the length and selected cells. Square-lattice spinner/arrow steps are 8 bp; you can type a different integer directly. In nm mode the entered distance is rounded to an integer number of base pairs using 0.334 nm/bp. Changing the unit reinterprets the field; enter the corresponding numeric value explicitly. +/− controls the extrusion direction, independently of the grid color.

### Step 12

Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.

![Step 12: Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.](12.png)

### Step 13

With length 0, Extrude refuses to build and asks for a length. The footprint remains available for correction.

![Step 13: With length 0, Extrude refuses to build and asks for a length. The footprint remains available for correction.](13.png)

### Step 14

Enter 64 bp. The readout should show 18 × 64 bp = 1152 bp total.

![Step 14: Enter 64 bp. The readout should show 18 × 64 bp = 1152 bp total.](14.png)

### Step 15

For the same 64 bp length, choose nm and enter 21.376. The total remains 1152 bp.

![Step 15: For the same 64 bp length, choose nm and enter 21.376. The total remains 1152 bp.](15.png)

### Step 16

Click − to preview extrusion on the opposite side of the plane.

![Step 16: Click − to preview extrusion on the opposite side of the plane.](16.png)

### Step 17

The negative-direction readout and preview change together. No DNA has been committed yet.

![Step 17: The negative-direction readout and preview change together. No DNA has been committed yet.](17.png)

### Step 18

Return to + for the main example.

![Step 18: Return to + for the main example.](18.png)

## Use scaffold-length recommendations

The 7249 and 8064 chips propose a per-helix length for the current selection. They reserve 14 nt per helix for end loops: floor(target / selected helices) − 14. They size this extrusion alone, not the entire existing design. They do not route a scaffold, assign its sequence, or certify a scaffold-length fit after later routing.

### Step 19

Click 7249 to fill 388 bp for 18 selected helices.

![Step 19: Click 7249 to fill 388 bp for 18 selected helices.](19.png)

### Step 20

The recommendation sets the field to 388 bp and switches the unit to bp. Restore 64 bp for this lesson.

![Step 20: The recommendation sets the field to 388 bp and switches the unit to bp. Restore 64 bp for this lesson.](20.png)

### Step 21

Click 8064 to fill 434 bp for 18 selected helices.

![Step 21: Click 8064 to fill 434 bp for 18 selected helices.](21.png)

### Step 22

The recommendation sets the field to 434 bp and switches the unit to bp. Restore 64 bp for this lesson.

![Step 22: The recommendation sets the field to 434 bp and switches the unit to bp. Restore 64 bp for this lesson.](22.png)

## Choose strands and ligation

Both, Scaffold and Staples select which strand classes the extrusion creates or extends. These controls do not perform an autoscaffold or autostaple routing operation. Ligate adjacent requests joining compatible neighboring strand ends at the extrusion boundary; leaving it unchecked keeps the new segment unligated. Compatibility depends on the source ends and selected strand classes. In an empty part there are no upstream ends to join.

### Step 23

Click Previous to return to the cross-section and strand choices. The view becomes normal to the source plane again.

![Step 23: Click Previous to return to the cross-section and strand choices. The view becomes normal to the source plane again.](23.png)

### Step 24

Choose Scaffold to restrict the extrusion to scaffold strands.

![Step 24: Choose Scaffold to restrict the extrusion to scaffold strands.](24.png)

### Step 25

Choose Staples to restrict the extrusion to staple strands.

![Step 25: Choose Staples to restrict the extrusion to staple strands.](25.png)

### Step 26

Choose Both for the main example.

![Step 26: Choose Both for the main example.](26.png)

### Step 27

Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.

![Step 27: Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.](27.png)

### Step 28

Restore Ligate adjacent for this example and the later continuation.

![Step 28: Restore Ligate adjacent for this example and the later continuation.](28.png)

### Step 29

Click Next again. The same 18 cells and 64 bp length are retained and shown in 3D.

![Step 29: Click Next again. The same 18 cells and 64 bp length are retained and shown in 3D.](29.png)

## Cancel a preview, then build

Preview changes are not authored structure. Cancel in Step 1, the window close button, or Escape discards the pending operation. Previous in Step 2 returns to selection without discarding inputs. Reopen the tool to start again. When ready, click Extrude (or press Enter in the length field). A successful operation is recorded in feature history. Red overlap feedback means the proposed extrusion intersects existing DNA; change direction/length or remove conflicting cells before applying.

### Step 30

Close the Extrude window to discard this preview and selection.

![Step 30: Close the Extrude window to discard this preview and selection.](30.png)

### Step 31

Open Tools → Extrude to start a new extrusion.

![Step 31: Open Tools → Extrude to start a new extrusion.](31.png)

### Step 32

With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.

![Step 32: With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.](32.png)

### Step 33

The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.

![Step 33: The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.](33.png)

### Step 34

Click Next to set the extrusion length in 3D.

![Step 34: Click Next to set the extrusion length in 3D.](34.png)

### Step 35

With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.

![Step 35: With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.](35.png)

### Step 36

Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.

![Step 36: Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.](36.png)

## Edit the recorded extrusion

The feature log preserves the construction inputs. Editing the feature changes its recorded parameters and rebuilds dependent operations. Cancel abandons the edit; Apply commits it. Undo and Redo operate through Edit → Undo/Redo (Ctrl+Z/Ctrl+Y). Review later dependent features after upstream changes.

### Step 37

Click the edit control on the Extrude feature row.

![Step 37: Click the edit control on the Extrude feature row.](37.png)

### Step 38

The recorded footprint opens in Step 1. Click Next to edit its length in 3D.

![Step 38: The recorded footprint opens in Step 1. Click Next to edit its length in 3D.](38.png)

### Step 39

Change the length to 72 bp. Close the window first to verify that the original 64 bp design is preserved.

![Step 39: Change the length to 72 bp. Close the window first to verify that the original 64 bp design is preserved.](39.png)

### Step 40

Close the window to cancel this trial edit.

![Step 40: Close the window to cancel this trial edit.](40.png)

### Step 41

Reopen the feature edit to make a deliberate change.

![Step 41: Reopen the feature edit to make a deliberate change.](41.png)

### Step 42

Click Next to return to the length controls.

![Step 42: Click Next to return to the length controls.](42.png)

### Step 43

Click Apply to rebuild the recorded extrusion at 72 bp.

![Step 43: Click Apply to rebuild the recorded extrusion at 72 bp.](43.png)

### Step 44

Use Edit → Undo to restore 64 bp.

![Step 44: Use Edit → Undo to restore 64 bp.](44.png)

### Step 45

Use Edit → Redo to restore the 72 bp edit. The saved example retains this demonstrated change.

![Step 45: Use Edit → Redo to restore the 72 bp edit. The saved example retains this demonstrated change.](45.png)

## Continue from an existing end

Use BLUNT end rings to identify the source. Right-click an end → Extrude, or left-click the end and use the Extrude action in Properties. Amber cells represent compatible ends that can be continued. Step 1 faces the inherited source plane; Next opens the length preview in 3D. Existing geometry is shown at 15% opacity while the tool is open, making the new preview easier to see; closing or applying restores its normal display. The plane is inherited from the source; +/− defaults away from the body. Select only the ends you intend to extend. Ligate adjacent controls boundary joining; an unligated segment is a different result, not an equivalent continuation.

### Step 46

Enable BLUNT in the toolbar to show selectable end rings.

![Step 46: Enable BLUNT in the toolbar to show selectable end rings.](46.png)

### Step 47

Right-click the marked far-end ring, then choose Extrude from its menu.

![Step 47: Right-click the marked far-end ring, then choose Extrude from its menu.](47.png)

### Step 48

Choose Extrude to continue from this end.

![Step 48: Choose Extrude to continue from this end.](48.png)

### Step 49

From is locked to the selected source end. The tool chooses the initial direction away from the existing body.

![Step 49: From is locked to the selected source end. The tool chooses the initial direction away from the existing body.](49.png)

### Step 50

Select the amber cell at the chosen end. This focused example extends one helix within the 3×6 model; select more compatible cells to extend a wider footprint.

![Step 50: Select the amber cell at the chosen end. This focused example extends one helix within the 3×6 model; select more compatible cells to extend a wider footprint.](50.png)

### Step 51

Click Next to keep the selected end and inspect the continuation in 3D.

![Step 51: Click Next to keep the selected end and inspect the continuation in 3D.](51.png)

### Step 52

For this far end, − points back into existing DNA. Inspect the red overlap feedback.

![Step 52: For this far end, − points back into existing DNA. Inspect the red overlap feedback.](52.png)

### Step 53

Attempting the overlapping extrusion is refused. Correct the direction rather than forcing the operation.

![Step 53: Attempting the overlapping extrusion is refused. Correct the direction rather than forcing the operation.](53.png)

### Step 54

Restore + to extrude away from this far end. A near-end continuation normally defaults to −.

![Step 54: Restore + to extrude away from this far end. A near-end continuation normally defaults to −.](54.png)

### Step 55

With 8 bp, Both and Ligate adjacent selected, apply the continuation.

![Step 55: With 8 bp, Both and Ligate adjacent selected, apply the continuation.](55.png)

### Step 56

The selected end has been extended and the continuation has its own history entry. Unselected helices retain their previous extent.

![Step 56: The selected end has been extended and the continuation has its own history entry. Unselected helices retain their previous extent.](56.png)

## Deformed-end continuation: current limitation

For a bent or twisted source, show Deformed View, right-click an end and choose Extrude. The tool uses the local deformed frame and locks From to the source. However, the current backend places new cells using honeycomb coordinates even for a square source, and its request does not carry the strand-filter/ligation controls. This square-lattice guide therefore demonstrates entry and Cancel only. Do not treat the square deformed-continuation result as verified. GUIDE-UX-004 tracks the gap; the feature remains partially covered until it is resolved and a successful continuation is demonstrated. We add a small 10° Bend through the normal UI to show the entry point; this is geometric CAD deformation, not physical relaxation.

### Step 57

Right-click the marked far-end ring, then choose Bend from its menu.

![Step 57: Right-click the marked far-end ring, then choose Bend from its menu.](57.png)

### Step 58

Choose Bend to prepare the deformed-end example.

![Step 58: Choose Bend to prepare the deformed-end example.](58.png)

### Step 59

For this preparation step, use a 10° Bend. Review the selected scope and start/end planes.

![Step 59: For this preparation step, use a 10° Bend. Review the selected scope and start/end planes.](59.png)

### Step 60

Apply the Bend before continuing its deformed end.

![Step 60: Apply the Bend before continuing its deformed end.](60.png)

### Step 61

Right-click the marked far-end ring, then choose Extrude from its menu.

![Step 61: Right-click the marked far-end ring, then choose Extrude from its menu.](61.png)

### Step 62

Choose Extrude to continue from this end.

![Step 62: Choose Extrude to continue from this end.](62.png)

### Step 63

The source plane is locked in deformed continuation. This entry point is available, but square-lattice placement is not verified: stop here for this model.

![Step 63: The source plane is locked in deformed continuation. This entry point is available, but square-lattice placement is not verified: stop here for this model.](63.png)

### Step 64

Cancel this deformed-continuation preview. No deformed extrusion is committed in the downloadable example.

![Step 64: Cancel this deformed-continuation preview. No deformed extrusion is committed in the downloadable example.](64.png)

## Save and troubleshoot

The downloaded example includes the full demonstrated construction: the edited 3×6 extrusion, straight continuation and Bend preparation. The deformed-continuation preview is canceled because of the documented square-lattice limitation. Use the feature log to inspect the earlier stages. If a target is covered, drag the tool-window title bar or adjust the camera. If the footprint count is wrong, check full-circle enclosure for left-to-right box selection. If no preview appears, check for a nonzero length. If an overlap or backend error occurs, keep the pending inputs, correct the source/direction/length and retry. Cancel abandons the pending operation. Source-plane changes reset an unfinished footprint. Desktop controls are covered here; headset interactions require a separate VR guide.

### Step 65

Inspect the final geometry and ordered feature log. NADOC autosaves the part; use File → Save As when you need a separately named user copy.

![Step 65: Inspect the final geometry and ordered feature log. NADOC autosaves the part; use File → Save As when you need a separately named user copy.](65.png)
