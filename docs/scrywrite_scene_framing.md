# ScryWrite scene framing

Status: canonical live-headset framing workflow implemented and validated 2026-08-21.

## Golden path

From the repository root, run:

```bash
just scrywrite-frame
```

This builds the viewer, mirrors the left eye, enables the room grid, waits for 15
stable fully tracked poses, and places the diagnostic origami in front of that exact
mirrored eye using `front`, 1.30 m distance, and 2× scale. No headset coordinates or
quaternions are required.

The operation is ready when the window title contains all of:

```text
SUBMITTED | DESIGN+GRID | O FRONT | TRACKED
```

The console also prints one `ScryWrite placement applied` record. Every subsequent
diagnostic JSONL sample persists the view, orientation, distance, scale, Euler
offsets, and whether placement was actually applied.

## Common variations

The first positional argument is the orientation. The second is the target view; the
third is the mirrored eye.

```bash
# Named orientation, same live mirror target:
just scrywrite-frame top

# Center on the binocular head pose while retaining the left-eye desktop mirror:
just scrywrite-frame front head

# Center on and display the right eye:
just scrywrite-frame front right right

# Use another viewer snapshot:
just scrywrite-frame isometric mirror left path/to/design.nadocvr
```

The orientation presets are:

| Preset | Model rotation relative to its authored/front frame |
|---|---|
| `front` | unchanged |
| `back` | 180° yaw |
| `left` | +90° yaw |
| `right` | −90° yaw |
| `top` | +90° pitch |
| `bottom` | −90° pitch |
| `isometric` | −35° yaw and −20° pitch |

The target views are `mirror`, `head`, `left`, and `right`. `mirror` follows the eye
selected for the desktop companion and is the safest default when the desktop image
is the test oracle. `head` uses the midpoint of both eyes for binocular presentation.

## Fine adjustment

Only use numeric adjustment after choosing the nearest named preset. The full recipe
argument order is:

```text
ORIENT VIEW EYE SCENE GRID DISTANCE SCALE YAW PITCH ROLL DIAGNOSTICS
```

For example, this starts from `top`, adds 15° yaw, and uses the remaining safe
defaults explicitly:

```bash
just scrywrite-frame top mirror left \
  native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr \
  room 1.30 2.0 15 0 0 /tmp/scrywrite_mirror_diagnostics.jsonl
```

Distance is constrained to 0.20–10 m, scale to 0.05–20, and each Euler offset to
±360°. Invalid, non-finite, unknown-view, and unknown-preset input fails before the
VR scene starts.

## Bounded interpretation

Placement means the normalized design center was transformed onto the chosen view's
forward ray at the requested distance, with the requested orientation and scale. It
does not prove that the expected design identity loaded, that the whole design is in
frame, or that its apparent size is comfortable. `DESIGN+GRID` establishes coarse
design-class coverage; exact identity, projected bounds, and depth remain separate
gates.

If the result says `GRID ONLY`, do not hand-adjust world coordinates. First retry the
same command and confirm the placement-applied record. Then choose a named orientation
or change only distance/scale. This keeps runs reproducible and their configuration
recoverable from JSONL.
