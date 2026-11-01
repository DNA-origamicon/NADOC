"""Bound original PDB conversion work without interpreting molecular geometry."""

from math import isfinite

from backend.core.part_input_sources import SourceContractError


MAX_SOURCE_BYTES = 200_000
MAX_ATOMS = 2_000
MAX_RESIDUES = 128
MAX_CHAINS = 8
MAX_RECORDS = 3_000
MAX_LINE = 256
MAX_BONDS = 8_000


def _fail(source, detail, *, limit=False):
    raise SourceContractError(f"DNA PDB {detail}", source=source,
        code="source_limit" if limit else "unsupported_source")


def parse_source(raw, source):
    if len(raw) > MAX_SOURCE_BYTES:
        _fail(source, "source exceeds 200,000 bytes", limit=True)
    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceContractError("DNA PDB source must be UTF-8", source=source,
                                  code="unsupported_source") from error
    if "\0" in content:
        _fail(source, "source contains a null byte")
    lines = content.splitlines()
    if len(lines) > MAX_RECORDS:
        _fail(source, "record count exceeds the conversion allowance", limit=True)
    from backend.core.pdb_to_design import _DNA_RESNAME
    serials, atom_keys, residues, chains = set(), set(), {}, set()
    bonds = 0
    for line in lines:
        if len(line) > MAX_LINE:
            _fail(source, "record width exceeds 256 characters", limit=True)
        record = line[:6].strip()
        if record in {"MODEL", "ENDMDL"}:
            _fail(source, "multiple-model containers need a separately declared model selection")
        if record == "CONECT":
            fields = [line[i:i + 5].strip() for i in range(6, len(line), 5)]
            if not fields or any(value and not value.isdecimal() for value in fields):
                _fail(source, "CONECT requires decimal atom serials")
            bonds += max(0, sum(bool(value) for value in fields) - 1)
            if bonds > MAX_BONDS:
                _fail(source, "explicit bond work exceeds the conversion allowance", limit=True)
        if record not in {"ATOM", "HETATM"}:
            continue  # Non-coordinate metadata is retained verbatim in the source.
        if len(line) < 54:
            _fail(source, "atom record has truncated coordinates")
        if line[16].strip() or line[26].strip():
            _fail(source, "alternate locations and insertion codes need explicit conversion choices")
        try:
            serial, residue = int(line[6:11]), int(line[22:26])
            coordinates = [float(line[i:i + 8]) for i in (30, 38, 46)]
        except ValueError as error:
            raise SourceContractError("DNA PDB requires decimal serial/residue IDs and numeric coordinates",
                                      source=source, code="unsupported_source") from error
        if not all(isfinite(value) for value in coordinates):
            _fail(source, "coordinates must be finite")
        if serial in serials:
            _fail(source, "atom serials must be unique")
        serials.add(serial)
        if len(serials) > MAX_ATOMS:
            _fail(source, "atom count exceeds 2,000 records", limit=True)
        name, chain, atom = line[17:20].strip(), line[21], line[12:16].strip()
        if name not in _DNA_RESNAME:
            continue
        key = chain, residue
        if not atom or (key, atom) in atom_keys or (key in residues and residues[key] != name):
            _fail(source, "DNA residue/atom identities are ambiguous")
        atom_keys.add((key, atom))
        residues[key] = name
        chains.add(chain)
        if len(residues) > MAX_RESIDUES or len(chains) > MAX_CHAINS:
            _fail(source, "DNA residue/chain count exceeds the conversion allowance", limit=True)
    if not residues:
        _fail(source, "source has no supported DNA residues")
    return content, {"atoms": len(serials), "residues": len(residues), "chains": len(chains), "bonds": bonds}
