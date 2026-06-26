---
name: REFERENCE_DNA_TOPOLOGY
description: DNA topology rules — scaffold circularity, ask-first policy for strand polarity questions
type: project
---

## Ask-First Policy (CRITICAL)

When encountering ANY confusion, apparent contradiction, or uncertainty about:
- Strand polarity (5′→3′ direction, FORWARD vs REVERSE)
- Helix orientation and handedness
- Loop/skip topology
- Domain traversal order
- Scaffold path direction through a structure
- Any spatial relationship that would normally be shown in a figure

**STOP and ask the user for clarification before writing any implementation code.**

**Why:** DNA origami literature almost universally relies on visual aids. Text descriptions alone are frequently ambiguous or seem contradictory without the accompanying diagrams. Attempting to resolve these ambiguities by guessing leads to incorrect implementations that are hard to debug.

## Scaffold Circularity Model
The scaffold is physically a circular plasmid (M13mp18, 7249 nt). In NADOC it is modeled as a **linear strand with 5′ and 3′ ends** (the nick position). The nick position marks the sequence assignment start point — it is a placeholder until sequence optimization is implemented. When users refer to the scaffold as "circular", this is biologically accurate even though the NADOC model is linear.

## FORWARD / REVERSE Convention
- FORWARD helix: DNA runs 5′→3′ in the +Z direction (along positive axis)
- REVERSE helix: DNA runs 5′→3′ in the −Z direction
- HC cell rule: `val = (row + col%2) % 3` → 0=FORWARD, 1=REVERSE, 2=HOLE
- SQ cell rule: `(row + col) % 2 == 0` → FORWARD; else → REVERSE
- `start_bp` is always 5′ end, `end_bp` always 3′ end (regardless of direction)

## Multiple Scaffold Strands
DTP-0c: Multiple scaffold strands are supported (MagicDNA style). Validator treats >1 scaffold strand as INFO (not ERROR). The nick position convention only applies to the primary scaffold strand.
