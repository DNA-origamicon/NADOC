"""The pinned import admits ordinary origami work while retaining hard bounds."""

import asyncio
import json

from fastapi import HTTPException
import pytest

from backend.api import routes_part_cadnano_import as routes
from backend.core import part_cadnano_source as limits
from backend.core.part_input_sources import SourceContractError, describe
from tests.test_part_cadnano_commands import path_into, source
from tests.test_part_cadnano_routes import StreamRequest


def parse(data=None, *, raw=None):
    if raw is None:
        raw = json.dumps(data, separators=(",", ":")).encode()
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    return limits.parse_source(raw, descriptor)


def blank_source(helices, width):
    data = source(helices=helices, width=width)
    for helix in data["vstrands"]:
        helix["scaf"] = [[-1] * 4 for _ in range(width)]
        helix["stap"] = [[-1] * 4 for _ in range(width)]
        helix["loop"] = helix["skip"] = []
    return data


def long_single_module_source():
    """Sparse long arrays with one scaffold and 166 fragmented staple paths."""
    data = blank_source(10, 1302)
    scaffold = [(num, bp) for num in range(6)
                for bp in (range(1260) if num % 2 == 0 else range(1259, -1, -1))]
    path_into(data, "scaf", scaffold)
    # Source-site bookkeeping only: synthetic crossover locations are not a
    # molecular-geometry qualification fixture or a deliverable structure.
    staples = [(num, bp) for tile in range(60) for num in (1, 0, 3, 2, 5, 4)
               for bp in (range(21 * tile, 21 * tile + 21) if num % 2
                          else range(21 * tile + 20, 21 * tile - 1, -1))]
    for index in range(166):
        path_into(data, "stap", staples[len(staples) * index // 166:
                                       len(staples) * (index + 1) // 166])
    return data


def test_long_single_module_source_counts_without_changing_declarations():
    data = long_single_module_source()
    raw = json.dumps(data, separators=(",", ":")).encode()
    admitted, counts = parse(raw=raw)
    assert 100_000 < len(raw) < limits.MAX_SOURCE_BYTES
    assert admitted == data
    assert counts["helices"] == 10 and counts["array_slots"] == 13020
    assert counts["active_bases"] == counts["declared_nucleotides"] == 15120
    assert counts["strands"] == 167
    assert 512 < counts["domain_bound"] <= limits.MAX_DOMAINS


def test_long_source_still_rejects_nonreciprocal_routing():
    data = long_single_module_source()
    data["vstrands"][0]["scaf"][1][:2] = [-1, -1]
    with pytest.raises(ValueError, match="Nonreciprocal"):
        parse(data)


def test_exact_source_byte_boundary_and_next_byte():
    raw = json.dumps(source()).encode()
    raw += b" " * (limits.MAX_SOURCE_BYTES - len(raw))
    assert parse(raw=raw)[1]["strands"] == 4
    with pytest.raises(SourceContractError, match=f"{limits.MAX_SOURCE_BYTES:,}-byte") as error:
        parse(raw=raw + b" ")
    assert error.value.code == "source_limit"


def test_sparse_array_work_remains_bounded_independently_of_occupancy():
    data = blank_source(12, 2048)
    assert parse(data)[1]["array_slots"] == limits.MAX_ARRAY_SLOTS
    # Common-width arrays just over the limit, still below the byte limit.
    with pytest.raises(SourceContractError, match="array work") as error:
        parse(blank_source(13, 1891))
    assert error.value.code == "source_limit"


def test_pointer_envelope_helix_limit_and_next_helix():
    assert parse(blank_source(limits.MAX_HELICES, 1))[1]['helices'] == limits.MAX_HELICES
    with pytest.raises(SourceContractError, match='helix count'):
        parse(blank_source(limits.MAX_HELICES + 1, 1))


def test_declared_nucleotide_limit_is_unchanged():
    data = source(helices=4, width=2048)
    assert parse(data)[1]["declared_nucleotides"] == limits.MAX_NUCLEOTIDES
    data["vstrands"][0]["loop"][0] = 1
    with pytest.raises(SourceContractError, match="nucleotide work"):
        parse(data)


def fragmented_source(count):
    data = blank_source(1, 2 * count)
    for index in range(count):
        path_into(data, "scaf", [(0, 2 * index), (0, 2 * index + 1)])
    return data


def test_exact_strand_fragmentation_limit_and_next_strand():
    assert parse(fragmented_source(limits.MAX_STRANDS))[1]["strands"] == limits.MAX_STRANDS
    with pytest.raises(SourceContractError, match="fragmentation"):
        parse(fragmented_source(limits.MAX_STRANDS + 1))


def domain_source(count):
    # Sparse positions on one path isolate domain work from strand count;
    # spread the path across helices to retain the independent width bound.
    per_helix = limits.MAX_ARRAY_WIDTH // 2
    data = blank_source((count + per_helix - 1) // per_helix,
                        min(count, per_helix) * 2)
    path_into(data, "scaf", [(index // per_helix, 2 * (index % per_helix))
                             for index in range(count)])
    return data


def test_exact_domain_work_limit_and_next_domain():
    assert parse(domain_source(limits.MAX_DOMAINS - 2))[1]["domain_bound"] == limits.MAX_DOMAINS
    with pytest.raises(SourceContractError, match="fragmentation"):
        parse(domain_source(limits.MAX_DOMAINS - 1))


@pytest.mark.parametrize("headers", [{}, {"content-length": "100001"}])
def test_shared_scadnano_transport_keeps_its_original_limit(headers):
    request = StreamRequest([b" " * 100001], {"content-type": "application/json", **headers})
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes._read_source(request, format_name="scadnano"))
    assert error.value.status_code == 413
    assert "100,000 bytes" in error.value.detail["detail"]
