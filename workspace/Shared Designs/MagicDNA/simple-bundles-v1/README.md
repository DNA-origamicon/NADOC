# Simple MagicDNA interchange examples

These are routing-converter test fixtures, not sequence designs for fabrication.
The source files use repeating synthetic ACGT test sequences; reconstructed
returned files have unassigned sequences.

- `6hb/`: honeycomb 6HB package, 1 scaffold + 14 staples, 1,134 nucleotides.
- `3x6/`: square 18HB package, 1 scaffold + 41 staples, 4,032 nucleotides.
- `*-returned.nadoc`: actual native MagicDNA exports reconstructed with recorded
  NADOC editor operations and embedded input/upstream histories.

Each package contains `source.nadoc`, `routing.json`, `manifest.json`, and
`magicdna-HC.json` or `magicdna-SQ.json` from native MATLAB export. All dependencies
needed to restore/replay these parts are portable and included. The returned
parts were guard-published, reopened, independently replayed, and inspected in NADOC.

The exact directed routing matched through NADOC → MagicDNA 2 native objects →
native JSON export → NADOC. This does not assert identical atomic coordinates;
the editors use different native geometric conventions. See
[the converter guide](../../../../docs/magicdna_interchange.md) for commands,
source fixes, limitations, and validation details.
