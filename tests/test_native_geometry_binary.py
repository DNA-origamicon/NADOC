"""NDGB preserves native coordinates, identities, sparse fields, and copy order."""

import json
import struct

import numpy as np
import orjson
import pytest

from backend.core.native_geometry_binary import pack_geometry_binary, unpack_geometry_binary


def test_lossless_compact_native_payload_and_indexed_design_arrays():
    values = np.nextafter(np.arange(36, dtype=float).reshape(12, 3) / 7, np.inf).tolist()
    bucket = {"bp": [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "bb": values,
              "sp": values, "sq": [[0.1, 0.2, 0.3, 0.4]] * 12,
              "pv": ["native-full-o5-v1"] * 12,
              "sid": ["strand-a", "strand-b", None] * 4,
              "is5": [True] + [False] * 11, "is3": [False] * 11 + [True],
              "ohid": [None] * 12, "base": [None, "A", "T"] * 4,
              "extid": [None, "tail"] * 6, "ismod": [True, False] * 6}
    payload = {"sources": {"source": {"nucleotides_compact": {"h": {"FORWARD": bucket}},
        "helix_axes": [], "design": {"deformations": [{"params": {
            "bp_positions_nm": values, "bp_frames": [np.eye(3).ravel().tolist()] * 12}}]}}},
        "instances": {"a": "source", "b": "source"}, "errors": {}}
    actual = unpack_geometry_binary(pack_geometry_binary(payload))
    assert actual == payload
    assert orjson.dumps(actual) == orjson.dumps(payload)
    out = actual["sources"]["source"]["nucleotides_compact"]["h"]["FORWARD"]
    assert np.asarray(out["bb"]).tobytes() == np.asarray(values).tobytes()
    out["sq"][0][0] = 9
    assert out["sq"][1][0] == 0.1  # decoded repetition must not alias mutable rows


def test_mixed_json_values_reserved_marker_large_integers_and_signed_zero():
    value = {"mixed": [False, 0, True, 1, None, "a", {}, []],
             "reserved": {"$nadoc": "array", "custom": list(range(9))},
             "large": [2**60 + i for i in range(10)],
             "zeros": [[-0.0 if i % 2 else 0.0, 1.0] for i in range(10)]}
    actual = unpack_geometry_binary(pack_geometry_binary(value))
    assert orjson.dumps(actual) == orjson.dumps(value)
    assert np.asarray(actual["zeros"]).tobytes() == np.asarray(value["zeros"]).tobytes()


@pytest.mark.parametrize("change", ["magic", "version", "truncated", "offset", "size"])
def test_rejects_malformed_binary_packet(change):
    packet = pack_geometry_binary({"xyz": np.arange(36).reshape(12, 3).tolist()})
    if change == "magic":
        packet = b"FAIL" + packet[4:]
    elif change == "version":
        packet = packet[:4] + struct.pack("<I", 99) + packet[8:]
    elif change == "truncated":
        packet = packet[:-1]
    else:
        magic, version, size, data_size = struct.unpack_from("<4sIII", packet)
        header = orjson.loads(packet[16:16 + size])
        header["payload"]["xyz"]["offset" if change == "offset" else "nbytes"] = 2**30
        encoded = orjson.dumps(header)
        data_start = (16 + size + 7) // 8 * 8
        packet = struct.pack("<4sIII", magic, version, len(encoded), data_size) + encoded
        packet += b"\0" * (-len(packet) % 8) + pack_geometry_binary({"xyz": np.arange(36).reshape(12, 3).tolist()})[data_start:]
    with pytest.raises(ValueError):
        unpack_geometry_binary(packet)


def test_nonfinite_native_arrays_are_not_silently_encoded_as_null():
    with pytest.raises(ValueError, match="finite"):
        pack_geometry_binary({"bb": [[float("nan"), 0, 0]] * 12})


def test_numpy_columns_keep_exact_values_types_signed_zero_and_noncontiguous_rows():
    payload = {"f": np.arange(180, dtype=float).reshape(30, 6)[::2, ::2] / 7,
               "i": np.arange(15, dtype=np.int64), "b": np.arange(15) % 2 == 0,
               "repeated": np.full((15, 3), -0.0), "small": np.array([1., 2.]),
               "mixed": [[0, .1]] * 15, "bool_numeric": [[True, 1.]] * 15}
    expected = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in payload.items()}
    actual = unpack_geometry_binary(pack_geometry_binary(payload))
    assert orjson.dumps(actual) == orjson.dumps(expected)
    assert np.asarray(actual['repeated']).tobytes() == payload['repeated'].tobytes()


def _descriptor_packet(payload):
    header = orjson.dumps({'format': 'ndgb1', 'payload': payload})
    packet = struct.pack('<4sIII', b'NDGB', 1, len(header), 0) + header
    return packet + b'\0' * (-len(packet) % 8)


@pytest.mark.parametrize('descriptor', [
    {'$nadoc': 'array', 'dtype': 'f8', 'shape': [4294967295, 0], 'offset': 0, 'nbytes': 0},
    {'$nadoc': 'repeat', 'count': 4294967295, 'value': None},
    {'$nadoc': 'repeat', 'count': 10000, 'value': {'$nadoc': 'repeat', 'count': 10000, 'value': None}},
])
def test_rejects_descriptor_expansion_before_numpy_or_copy_allocation(descriptor, monkeypatch):
    from backend.core import native_geometry_binary as codec

    def forbidden(*args, **kwargs):
        pytest.fail('Descriptor expansion must be rejected before allocation')

    monkeypatch.setattr(codec.np, 'frombuffer', forbidden)
    monkeypatch.setattr(codec, 'deepcopy', forbidden)
    with pytest.raises(ValueError, match='element budget exceeded'):
        unpack_geometry_binary(_descriptor_packet({'bad': descriptor}))


def test_decoded_budget_is_cumulative_and_counts_repeated_nested_entries():
    packet = _descriptor_packet({'a': {'$nadoc': 'repeat', 'count': 3, 'value': [0, 0]}})
    # One object entry, two template positions, three outer rows, six copied positions.
    assert unpack_geometry_binary(packet, max_elements=12) == {'a': [[0, 0]] * 3}
    with pytest.raises(ValueError, match='element budget exceeded'):
        unpack_geometry_binary(packet, max_elements=11)
    packet = _descriptor_packet({'a': [1, 2], 'b': [3, 4]})
    assert unpack_geometry_binary(packet, max_elements=6) == {'a': [1, 2], 'b': [3, 4]}
    with pytest.raises(ValueError, match='element budget exceeded'):
        unpack_geometry_binary(packet, max_elements=5)


def test_decoded_budget_counts_numeric_array_rows_and_literal_dictionary_entries():
    packet = pack_geometry_binary({'a': np.arange(24).reshape(8, 3)})
    assert unpack_geometry_binary(packet, max_elements=33)['a'] == np.arange(24).reshape(8, 3).tolist()
    with pytest.raises(ValueError, match='element budget exceeded'):
        unpack_geometry_binary(packet, max_elements=32)
    packet = pack_geometry_binary({'$nadoc': 'custom', 'value': [1, 2]})
    assert unpack_geometry_binary(packet, max_elements=4) == {'$nadoc': 'custom', 'value': [1, 2]}
    with pytest.raises(ValueError, match='element budget exceeded'):
        unpack_geometry_binary(packet, max_elements=3)


@pytest.mark.parametrize('limit', [-1, 1.5, True, None, 2**53])
def test_rejects_invalid_decoded_budget(limit):
    with pytest.raises(ValueError, match='Invalid NDGB decoded element budget'):
        unpack_geometry_binary(_descriptor_packet({}), max_elements=limit)


def test_rejects_excessive_nested_template_depth_before_copying(monkeypatch):
    from backend.core import native_geometry_binary as codec

    descriptor = None
    for _ in range(257):
        descriptor = {'$nadoc': 'repeat', 'count': 1, 'value': descriptor}
    monkeypatch.setattr(codec, 'deepcopy', lambda _: pytest.fail('Depth must be checked before copying'))
    # orjson's encoder has a smaller nesting limit than the decoder under test.
    header = json.dumps({'format': 'ndgb1', 'payload': descriptor}).encode()
    packet = struct.pack('<4sIII', b'NDGB', 1, len(header), 0) + header
    packet += b'\0' * (-len(packet) % 8)
    with pytest.raises(ValueError, match='nesting depth'):
        unpack_geometry_binary(packet)
