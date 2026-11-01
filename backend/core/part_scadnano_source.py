"""Admit finite scadnano source work before expanding topology or sequences.

The existing importer owns scientific interpretation. This boundary rejects
opaque declarations and excessive work; it never repairs or rewrites input.
"""

from backend.core.part_cadnano_source import _json
from backend.core.part_input_sources import SourceContractError


MAX_SOURCE_BYTES = 100_000
MAX_HELICES = 32
MAX_HELIX_SPAN = 2_048
MAX_TOTAL_SPAN = 8_192
MAX_NUCLEOTIDES = 16_384
MAX_STRANDS = 128
MAX_DOMAINS = 512
MAX_MODIFICATION_WORK = 65_536
_TOP_KEYS = {"name", "version", "grid", "helices", "strands", "photoproduct_junctions"}
_HELIX_KEYS = {"idx", "grid_position", "min_offset", "max_offset"}
_STRAND_KEYS = {"color", "sequence", "is_scaffold", "circular", "domains"}
_DOMAIN_KEYS = {"helix", "forward", "start", "end", "deletions", "insertions"}


def _fail(source, detail, *, limit=False):
    raise SourceContractError(f"scadnano {detail}", source=source,
                              code="source_limit" if limit else "unsupported_source")


def _record(value, keys, source, label):
    if not isinstance(value, dict) or set(value) - keys:
        _fail(source, f"{label} contains unsupported fields")


def _integer(value, source, label, *, minimum=-1_000_000, maximum=1_000_000):
    if type(value) is not int:
        _fail(source, f"{label} must be an integer")
    if not minimum <= value <= maximum:
        _fail(source, f"{label} exceeds the import work contract", limit=True)
    return value


def parse_source(raw, source):
    if len(raw) > MAX_SOURCE_BYTES:
        _fail(source, "source exceeds the 100 KB contract", limit=True)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceContractError("Pinned scadnano source must be UTF-8 JSON", source=source,
                                  code="unsupported_source") from error
    data = _json(text, source, format_name="scadnano")
    _record(data, _TOP_KEYS, source, "source")
    # NADOC's ordinary exporter includes this empty extension field. Nonempty
    # experimental chemistry remains outside the reproducible import contract.
    if data.get("photoproduct_junctions", []) != []:
        _fail(source, "photoproduct junctions are outside the import contract")
    for key, size in (("name", 1024), ("version", 64)):
        if key in data and (type(data[key]) is not str or len(data[key]) > size):
            _fail(source, f"{key} must be bounded text")
    if data.get("grid", "square") not in ("square", "honeycomb"):
        _fail(source, "import requires a square or honeycomb grid")
    helices, strands = data.get("helices"), data.get("strands")
    if not isinstance(helices, list) or not helices or not isinstance(strands, list) or not strands:
        _fail(source, "source requires nonempty helices and strands arrays")
    if len(helices) > MAX_HELICES or len(strands) > MAX_STRANDS:
        _fail(source, "helix/strand count exceeds the import contract", limit=True)
    indices, addresses, spans = set(), set(), 0
    for ordinal, helix in enumerate(helices):
        _record(helix, _HELIX_KEYS, source, "helix")
        idx = _integer(helix.get("idx", ordinal), source, "helix index", minimum=0)
        if idx in indices:
            _fail(source, "helix indices must be unique")
        indices.add(idx)
        grid = helix.get("grid_position")
        if not isinstance(grid, list) or len(grid) != 2:
            _fail(source, "grid positions require two integers")
        address = tuple(_integer(value, source, "grid coordinate") for value in grid)
        if address in addresses:
            _fail(source, "source grid addresses must be unique")
        addresses.add(address)
        start = _integer(helix.get("min_offset", 0), source, "minimum offset")
        end = _integer(helix.get("max_offset"), source, "maximum offset")
        if end <= start:
            _fail(source, "helix bounds must be increasing")
        if end - start > MAX_HELIX_SPAN:
            _fail(source, "helix span exceeds the import contract", limit=True)
        spans += end - start
    if spans > MAX_TOTAL_SPAN:
        _fail(source, "total helix span exceeds the import contract", limit=True)

    domains = modifications = bases = 0
    used_ranges = {}
    for strand in strands:
        _record(strand, _STRAND_KEYS, source, "strand")
        for key in ("is_scaffold", "circular"):
            if key in strand and type(strand[key]) is not bool:
                _fail(source, f"strand {key} must be boolean")
        if strand.get("color") is not None and (type(strand["color"]) is not str or len(strand["color"]) > 64):
            _fail(source, "strand color must be bounded text")
        if strand.get("sequence") is not None and (
                type(strand["sequence"]) is not str or len(strand["sequence"]) > MAX_NUCLEOTIDES):
            _fail(source, "strand sequence exceeds the import contract", limit=True)
        parts = strand.get("domains")
        if not isinstance(parts, list) or not parts:
            _fail(source, "strand domains must be a nonempty array")
        domains += len(parts)
        if domains + 2 * len(strands) > MAX_DOMAINS:
            _fail(source, "domain fragmentation exceeds the import contract", limit=True)
        for part in parts:
            if not isinstance(part, dict):
                _fail(source, "domain must be an object")
            extra = next((key for key in ("loopout", "extension_num_bases") if key in part), None)
            if extra is not None:
                _record(part, {extra}, source, "unpaired domain")
                bases += _integer(part[extra], source, extra, minimum=1, maximum=MAX_NUCLEOTIDES)
            else:
                _record(part, _DOMAIN_KEYS, source, "helix domain")
                hid = _integer(part.get("helix"), source, "domain helix", minimum=0)
                if hid not in indices or type(part.get("forward")) is not bool:
                    _fail(source, "domain requires a known helix and boolean direction")
                start = _integer(part.get("start"), source, "domain start")
                end = _integer(part.get("end"), source, "domain end")
                if end <= start:
                    _fail(source, "domain bounds must be increasing")
                lower, upper = used_ranges.get(hid, (start, end))
                used_ranges[hid] = min(lower, start), max(upper, end)
                bases += end - start
                deletions, insertions = part.get("deletions", []), part.get("insertions", [])
                if not isinstance(deletions, list) or not isinstance(insertions, list):
                    _fail(source, "modifications require arrays")
                modifications += len(deletions) + len(insertions)
                for bp in deletions:
                    _integer(bp, source, "deletion position")
                for pair in insertions:
                    if not isinstance(pair, list) or len(pair) != 2:
                        _fail(source, "insertion requires a position and positive length")
                    _integer(pair[0], source, "insertion position")
                    bases += _integer(pair[1], source, "insertion length", minimum=1, maximum=MAX_NUCLEOTIDES)
            if bases > MAX_NUCLEOTIDES:
                _fail(source, "declared nucleotide work exceeds the import contract", limit=True)
    actual_spans = [end - start for start, end in used_ranges.values()]
    if max(actual_spans, default=0) > MAX_HELIX_SPAN or sum(actual_spans) > MAX_TOTAL_SPAN:
        _fail(source, "used helix span exceeds the import contract", limit=True)
    if domains * modifications > MAX_MODIFICATION_WORK:
        _fail(source, "domain/modification comparison work exceeds the import contract", limit=True)
    from backend.core.conversion_integrity import validate_scadnano_source
    validate_scadnano_source(data)
    module_scaffolds = sum(strand.get("is_scaffold", False) and len({part["helix"]
        for part in strand["domains"] if "helix" in part}) >= 3 for strand in strands)
    if module_scaffolds > 1:
        _fail(source, "v1 supports at most one module scaffold; multiple-module clustering is unqualified")
    return data, {"helices": len(helices), "strands": len(strands), "domain_bound": domains + 2 * len(strands),
                  "declared_nucleotides": bases, "helix_span": sum(actual_spans),
                  "modification_work": domains * modifications}
