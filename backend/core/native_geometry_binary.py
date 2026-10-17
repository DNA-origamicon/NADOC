"""Lossless native display transport: JSON metadata and aligned numeric arrays.

NDGB v1 keeps native placements in float64. It does not calculate, simplify,
validate, or otherwise reinterpret molecular geometry. Existing JSON callers
remain unchanged; the matching decoder reconstructs ordinary JSON-shaped data.

Wire: ``<4sIII`` (NDGB, version, header byte count, data byte count), UTF-8
JSON ``{format: 'ndgb1', payload: ...}``, zero padding to 8 bytes, then data.
Array descriptor offsets are relative to the start of data, not the packet.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import chain
import math
import struct

import numpy as np
import orjson

MEDIA_TYPE = "application/vnd.nadoc.geometry+binary"
MAGIC = b"NDGB"
VERSION = 1
_PREFIX = struct.Struct("<4sIII")
_MIN_ARRAY = 8
_DEFAULT_MAX_ELEMENTS = 64 * 1024 * 1024
_DTYPES = {"f8": np.dtype("<f8"), "i4": np.dtype("<i4"),
           "u1": np.dtype("u1"), "u2": np.dtype("<u2"), "u4": np.dtype("<u4")}


def _numeric_type(value, ndim):
    """Prove a rectangular Python numeric array has one exact JSON scalar type.

    ``np.asarray`` has already proved the shape. Flattening iterators and C's
    map/set avoid a Python recursive call for every coordinate, while rejecting
    bool coercion and mixed int/float columns (JSON preserves that distinction).
    """
    leaves = value
    for _ in range(ndim - 1):
        leaves = chain.from_iterable(leaves)
    types = set(map(type, leaves))
    return types == {int} or types == {float}


def pack_geometry_binary(payload: dict) -> bytes:
    """Pack an existing native response without reducing coordinate precision."""
    data = bytearray()

    def array_descriptor(values, dtype, **extra):
        array = np.asarray(values, dtype=_DTYPES[dtype])
        data.extend(b"\0" * (-len(data) % 8))
        descriptor = {"$nadoc": "array", "dtype": dtype, "shape": list(array.shape),
                      "offset": len(data), "nbytes": array.nbytes, **extra}
        data.extend(array.tobytes(order="C"))
        return descriptor

    def encode(value):
        if isinstance(value, dict):
            content = {key: encode(item) for key, item in value.items()}
            return {"$nadoc": "literal", "value": content} if "$nadoc" in value else content
        if isinstance(value, np.generic):
            return encode(value.item())
        if type(value) is float and not math.isfinite(value):
            raise ValueError("Native geometry transport requires finite numeric arrays")
        native_array = isinstance(value, np.ndarray)
        if native_array and value.ndim == 0:
            return encode(value.item())
        if not isinstance(value, (list, tuple, np.ndarray)):
            return value
        if len(value) < _MIN_ARRAY:
            return [encode(item) for item in value]
        if native_array and value.dtype.kind == "b":
            if np.all(value == value[0]):
                return {"$nadoc": "repeat", "count": len(value), "value": encode(value[0])}
            return array_descriptor(value, "u1", kind="bool")
        first = value[0]
        if first is None or type(first) in (str, bool):
            if all(type(item) is type(first) and item == first for item in value):
                return {"$nadoc": "repeat", "count": len(value), "value": first}
            if all(type(item) is bool for item in value):
                return array_descriptor(value, "u1", kind="bool")
            if all(item is None or type(item) is str for item in value):
                table, lookup, indices = [], {}, []
                for item in value:
                    if item not in lookup:
                        lookup[item] = len(table)
                        table.append(item)
                    indices.append(lookup[item])
                dtype = "u1" if len(table) <= 256 else "u2" if len(table) <= 65536 else "u4"
                return array_descriptor(indices, dtype, table=table)
        if native_array or type(first) in (int, float) or isinstance(first, (list, tuple)):
            try:
                array = np.asarray(value)
            except (ValueError, TypeError):
                array = None
            if array is not None and array.size and array.dtype.kind in "fiu" and (native_array or _numeric_type(value, array.ndim)):
                if not np.isfinite(array).all():
                    raise ValueError("Native geometry transport requires finite numeric arrays")
                # Preserve integer metadata outside float64's exact integer range
                # as JSON. All placement arrays are already binary64 numbers.
                if array.dtype.kind in "iu" and (array.min() < -(2**53) or array.max() > 2**53):
                    return [encode(item) for item in value]
                dtype = "i4" if array.dtype.kind in "iu" and array.min() >= -(2**31) and array.max() < 2**31 else "f8"
                array = np.asarray(array, dtype=_DTYPES[dtype])
                rows = array.view(np.uint8).reshape(len(array), -1)
                # Byte equality preserves signed zero as well as exact numbers.
                if rows.shape[1] and np.all(rows == rows[0]):
                    return {"$nadoc": "repeat", "count": len(value), "value": encode(value[0])}
                return array_descriptor(array, dtype)
        return [encode(item) for item in value]

    header = orjson.dumps({"format": "ndgb1", "payload": encode(payload)})
    prefix = _PREFIX.pack(MAGIC, VERSION, len(header), len(data))
    return prefix + header + b"\0" * (-(len(prefix) + len(header)) % 8) + data


def unpack_geometry_binary(packet: bytes, *, max_elements: int = _DEFAULT_MAX_ELEMENTS) -> dict:
    """Exact browser oracle with bounded buffer reads and decoded allocations.

    The budget counts all decoded dictionary/list entries, including outer
    array rows. A tiny zero-byte descriptor or repeated template cannot expand
    into unbounded containers. Preflight completes before reconstruction.
    """
    if type(max_elements) is not int or not 0 <= max_elements <= 2**53 - 1:
        raise ValueError("Invalid NDGB decoded element budget")
    if len(packet) < _PREFIX.size:
        raise ValueError("Incomplete NDGB prefix")
    magic, version, header_size, data_size = _PREFIX.unpack_from(packet)
    if magic != MAGIC or version != VERSION:
        raise ValueError("Unsupported NDGB format")
    start = _PREFIX.size + header_size
    data_start = start + (-start % 8)
    if data_start + data_size != len(packet):
        raise ValueError("Invalid NDGB buffer lengths")
    header = orjson.loads(packet[_PREFIX.size:start])
    if header.get("format") != "ndgb1":
        raise ValueError("Invalid NDGB header")

    def bounded(count):
        if count > max_elements:
            raise ValueError("NDGB decoded element budget exceeded")
        return count

    def object_slots(value, depth):
        slots = allocated = bounded(len(value))
        for item in value.values():
            child_slots, child_allocated = decoded_slots(item, depth + 1)
            slots = bounded(slots + child_slots)
            allocated = bounded(allocated + child_allocated)
        return slots, allocated

    def decoded_slots(value, depth=0):
        if depth > 256:
            raise ValueError("Invalid NDGB nesting depth")
        if isinstance(value, list):
            slots = allocated = bounded(len(value))
            for item in value:
                child_slots, child_allocated = decoded_slots(item, depth + 1)
                slots = bounded(slots + child_slots)
                allocated = bounded(allocated + child_allocated)
            return slots, allocated
        if not isinstance(value, dict):
            return 0, 0
        marker = value.get("$nadoc")
        if marker == "literal":
            content = value.get("value")
            if not isinstance(content, dict):
                raise ValueError("Invalid NDGB literal")
            return object_slots(content, depth)
        if marker == "repeat":
            count = value.get("count")
            if type(count) is not int or not 0 <= count <= 0xffffffff:
                raise ValueError("Invalid NDGB repeat count")
            bounded(count)
            child_slots, child_allocated = decoded_slots(value.get("value"), depth + 1)
            # Match the browser: decoded template allocation plus independent
            # copies. A nested repeat's temporary template is not copied again.
            slots = bounded(count * (1 + child_slots))
            return slots, bounded(child_allocated + slots)
        if marker == "array":
            shape = value.get("shape")
            if (not isinstance(shape, list) or not shape or len(shape) > 256
                    or any(type(n) is not int or not 0 <= n <= 0xffffffff for n in shape)):
                raise ValueError("Invalid NDGB array descriptor")
            total, prefix = 0, 1
            for dimension in shape:
                prefix *= dimension
                total = bounded(total + prefix)
            return total, total
        if marker is not None:
            raise ValueError("Unknown NDGB descriptor")
        return object_slots(value, depth)

    decoded_slots(header["payload"])

    def decode(value):
        if isinstance(value, list):
            return [decode(item) for item in value]
        if not isinstance(value, dict):
            return value
        marker = value.get("$nadoc")
        if marker == "literal":
            return {key: decode(item) for key, item in value["value"].items()}
        if marker == "repeat":
            count = value["count"]
            if type(count) is not int or count < 0:
                raise ValueError("Invalid NDGB repeat count")
            item = decode(value["value"])
            return [deepcopy(item) for _ in range(count)]
        if marker == "array":
            dtype = _DTYPES.get(value["dtype"])
            shape, offset, nbytes = value["shape"], value["offset"], value["nbytes"]
            if (dtype is None or not isinstance(shape, list) or not shape
                    or any(type(n) is not int or n < 0 for n in shape)
                    or type(offset) is not int or offset < 0 or offset % 8
                    or type(nbytes) is not int or nbytes < 0
                    or offset + nbytes > data_size
                    or int(np.prod(shape, dtype=object)) * dtype.itemsize != nbytes):
                raise ValueError("Invalid NDGB array descriptor")
            array = np.frombuffer(packet, dtype=dtype, count=nbytes // dtype.itemsize,
                                  offset=data_start + offset).reshape(shape)
            if "table" in value:
                table = value["table"]
                if array.ndim != 1 or array.dtype.kind != "u" or (array.size and int(array.max()) >= len(table)):
                    raise ValueError("Invalid NDGB dictionary indices")
                return [table[int(i)] for i in array]
            if value.get("kind") == "bool":
                if array.dtype != np.dtype("u1") or np.any(array > 1):
                    raise ValueError("Invalid NDGB boolean array")
                return array.astype(bool).tolist()
            return array.tolist()
        if marker is not None:
            raise ValueError("Unknown NDGB descriptor")
        return {key: decode(item) for key, item in value.items()}

    return decode(header["payload"])
