"""Bound caDNAno source work before the unchanged importer constructs models."""

import json
import math

from backend.core.part_input_sources import SourceContractError


# Provisional qualification envelope, separate from document transport limits.
MAX_SOURCE_BYTES = 100_000
MAX_HELICES = 32
MAX_ARRAY_WIDTH = 2_048
MAX_ARRAY_SLOTS = 8_192
MAX_NUCLEOTIDES = 16_384
MAX_STRANDS = 128
MAX_DOMAINS = 512
MAX_JSON_DEPTH = 16
_TOP_KEYS = frozenset({"name", "vstrands"})
_HELIX_KEYS = frozenset({"row", "col", "num", "scaf", "stap", "loop", "skip",
                         "stap_colors", "scaf_colors", "scafLoop", "stapLoop"})


def _fail(source, detail, *, limit=False):
    raise SourceContractError(detail, source=source,
                              code="source_limit" if limit else "unsupported_source")


def _json(text, source):
    # JSON's normal parser may allocate deeply nested containers before a
    # post-parse schema can reject them. This scan only bounds nesting; stdlib
    # remains the syntax/parser authority, including escaping and UTF-8 text.
    quoted, escaped, depth = False, False, 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                _fail(source, "caDNAno JSON nesting exceeds the import contract", limit=True)
        elif char in "]}":
            depth -= 1

    def integer(value):
        if len(value.lstrip("-")) > 10:
            _fail(source, "caDNAno integer exceeds the import work contract", limit=True)
        result = int(value)
        if abs(result) > 2_147_483_647:
            _fail(source, "caDNAno integer exceeds the import work contract", limit=True)
        return result

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            _fail(source, "caDNAno source numbers must be finite")
        return result

    def constant(_value):
        _fail(source, "caDNAno source numbers must be finite")

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail(source, "caDNAno source contains duplicate JSON fields")
            result[key] = value
        return result

    try:
        return json.loads(text, parse_int=integer, parse_float=floating,
                          parse_constant=constant, object_pairs_hook=object_pairs)
    except json.JSONDecodeError as exc:
        _fail(source, f"Invalid caDNAno JSON: {exc.msg}")


def parse_source(raw, source):
    """Return admitted JSON plus work counts; do not alter source declarations."""
    if len(raw) > MAX_SOURCE_BYTES:
        _fail(source, "caDNAno source exceeds the initial 100 KB contract", limit=True)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceContractError("Pinned caDNAno source must be UTF-8 JSON", source=source,
                                  code="unsupported_source") from exc
    data = _json(text, source)
    if not isinstance(data, dict) or set(data) - _TOP_KEYS:
        _fail(source, "caDNAno v1 accepts only the name and vstrands source fields")
    if "name" in data and (not isinstance(data["name"], str) or len(data["name"]) > 1_024):
        _fail(source, "caDNAno source name must be bounded text")
    helices = data.get("vstrands")
    if not isinstance(helices, list) or not helices:
        _fail(source, "caDNAno source needs a nonempty vstrands array")
    if len(helices) > MAX_HELICES:
        _fail(source, "caDNAno helix count exceeds the import contract", limit=True)
    slots, active, inserted, boundaries, starts = 0, 0, 0, 0, []
    addresses = set()
    for helix in helices:
        if not isinstance(helix, dict) or set(helix) - _HELIX_KEYS:
            _fail(source, "caDNAno vstrand contains unsupported fields")
        if any(type(helix.get(key)) is not int for key in ("num", "row", "col")):
            _fail(source, "caDNAno helix numbers and grid addresses must be integers")
        if helix["num"] < 0 or any(abs(helix[key]) > 1_000_000 for key in ("num", "row", "col")):
            _fail(source, "caDNAno helix address exceeds the import contract", limit=True)
        address = helix["row"], helix["col"]
        if address in addresses:
            _fail(source, "caDNAno v1 requires unique source grid addresses")
        addresses.add(address)
        # The importer does not interpret these legacy optional fields. Do not
        # silently certify an opaque alternate loop representation as authored
        # topology. Normal v2 exports include them as empty arrays.
        if any(helix.get(key, []) != [] for key in ("scafLoop", "stapLoop")):
            _fail(source, "caDNAno v1 requires empty legacy scafLoop/stapLoop fields")
        scaffold = helix.get("scaf")
        if not isinstance(scaffold, list) or not 0 < len(scaffold) <= MAX_ARRAY_WIDTH:
            _fail(source, "caDNAno array width exceeds the import contract", limit=True)
        width = len(scaffold)
        slots += width
        if slots > MAX_ARRAY_SLOTS:
            _fail(source, "caDNAno array work exceeds the import contract", limit=True)
        for key in ("scaf", "stap"):
            array = helix.get(key)
            if not isinstance(array, list) or len(array) != width:
                _fail(source, "caDNAno scaffold and staple arrays must have equal widths")
            for bp, entry in enumerate(array):
                if not isinstance(entry, list) or len(entry) != 4 or any(type(item) is not int for item in entry):
                    _fail(source, "caDNAno pointers must contain four integers")
                if entry == [-1, -1, -1, -1]:
                    continue
                active += 1
                previous, previous_bp = entry[:2]
                # Count the unchanged importer's possible domain boundaries,
                # without constructing or modifying a strand path.
                step = 1 if (previous % 2 == 0) == (key == "scaf") else -1
                if previous == -1 or previous != helix["num"] or previous_bp + step != bp:
                    boundaries += 1
                if previous == -1:
                    starts.append((key, helix["num"], bp))
        for key in ("loop", "skip"):
            values = helix.get(key)
            if not isinstance(values, list) or len(values) > width or any(type(value) is not int for value in values):
                _fail(source, "caDNAno loop/skip arrays must be bounded integer lists")
            if key == "loop":
                if any(value < 0 for value in values):
                    _fail(source, "caDNAno loop counts cannot be negative")
                # Each inserted helix base may appear on both strands. Count
                # inactive declarations too rather than relying on later drops.
                inserted += 2 * sum(values)
        for key in ("stap_colors", "scaf_colors"):
            colors = helix.get(key, [])
            if (not isinstance(colors, list) or len(colors) > width
                    or any(not isinstance(row, list) or len(row) != 2
                           or any(type(value) is not int for value in row) for row in colors)):
                _fail(source, "caDNAno colors must be bounded integer pairs")
    if active + inserted > MAX_NUCLEOTIDES:
        _fail(source, "caDNAno declared nucleotide work exceeds the import contract", limit=True)
    # Keep original reciprocal-pointer and molecular declaration validation.
    # Once checked, traversing each source slot once is safe and bounded.
    from backend.core.conversion_integrity import validate_cadnano_source
    validate_cadnano_source(data)
    by_num = {helix["num"]: helix for helix in helices}
    visited = set()

    def visit(key, num, bp):
        while (key, num, bp) not in visited:
            visited.add((key, num, bp))
            next_num, next_bp = by_num[num][key][bp][2:]
            if next_num == -1:
                return
            num, bp = next_num, next_bp

    for start in starts:
        visit(*start)
    cycles = 0
    for helix in helices:
        for key in ("scaf", "stap"):
            for bp, entry in enumerate(helix[key]):
                if entry != [-1, -1, -1, -1] and (key, helix["num"], bp) not in visited:
                    cycles += 1
                    visit(key, helix["num"], bp)
    strands = len(starts) + cycles
    # A circular source origin can add one cut; inline-overhang discovery can
    # split each of two terminal domains once. These are conservative bounds.
    domains = boundaries + cycles + 2 * strands
    if strands > MAX_STRANDS or domains > MAX_DOMAINS:
        _fail(source, "caDNAno strand/domain fragmentation exceeds the import contract", limit=True)
    return data, {"helices": len(helices), "array_slots": slots, "active_bases": active,
                  "declared_nucleotides": active + inserted, "strands": strands,
                  "domain_bound": domains}
