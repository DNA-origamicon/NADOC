# scaffold-and-loops — diagnostics runbook
Loaded on demand from the `scaffold-and-loops` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

## Symptoms
- Auto-scaffold runs but no scaffold strand created
- "Autoscaffold silent" — no visible change, no error
- Scaffold strand disconnected / multiple scaffold strands unexpectedly
- Tests fail with "scaffold strand not found"

## First-Check Invariants

1. **Even helix count required** — `auto_scaffold` raises `ValueError` if helix count is odd. Design must have an even number of helices for seam-line routing.

2. **Test design minimum size** — Scaffold/staple routing tests are only valid for 6HB+ designs. A 2HB design gives degenerate results. Use `CELLS_6HB` or `CELLS_18HB`.

3. **Nick is domain boundary adjustment, not make_nick** — The scaffold nick is implemented by setting domain `start_bp`/`end_bp` at the nick position. It is NOT a call to `make_nick()`.

## Diagnosis Tree

### No scaffold strand after auto-scaffold
1. Check `auto_scaffold` return value — does it raise ValueError? Check server logs.
2. Check helix count is even
3. Check `_helix_adjacency_graph(design)` returns a connected graph (helices must have XY neighbors)
4. Check that `_greedy_hamiltonian_path` succeeds (needs ≥2 helices)

### Scaffold routing test failing
1. First check: is design at least 6HB?
2. Scaffold routing tests only in `tests/test_lattice.py` and `tests/test_scaffold_geometry.py`
3. If 2HB or 4HB → test is invalid by design; switch to 6HB

### Auto-scaffold inserts wrong sequences
1. Check `sequences.py` — `assign_scaffold_sequence(design, name)` where name = 'M13mp18' | 'p7560' | 'p8064'
2. If design is longer than scaffold → remaining positions get 'N' padding
3. `assign_staple_sequences(design)` fills Watson-Crick complements; unpaired positions get 'N'
