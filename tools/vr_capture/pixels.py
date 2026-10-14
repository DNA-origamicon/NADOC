"""Bounded, lossless decoding of recorded panel images; no optical processing."""
from __future__ import annotations

import ctypes
from functools import lru_cache
import os
from pathlib import Path
import stat
import zlib


@lru_cache(maxsize=1)
def zstd_library():
    library = ctypes.CDLL('libzstd.so.1')
    library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    return library


def decode_frame(directory, row):
    directory = Path(directory).resolve(strict=True)
    name = row['file']
    path = (directory / name).resolve(strict=True)
    if path.parent != directory or Path(name).name != name:
        raise ValueError('image must be directly inside capture directory')
    expected = row['width'] * row['height'] * 4
    if not 0 < expected <= 512 * 1024 * 1024:
        raise ValueError('invalid or excessive image size')
    if row.get('raw_bytes', expected) != expected:
        raise ValueError('raw byte count disagrees with dimensions')
    with path.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('pixel storage must be a regular file')
        if 'file_offset' in row:
            offset, size = row['file_offset'], row.get('compressed_bytes')
            if (type(offset) is not int or type(size) is not int or offset < 0
                    or not 0 < size <= expected * 2 + 1024
                    or info.st_size > 2 * 1024 * 1024 * 1024 or offset + size > info.st_size):
                raise ValueError('invalid or excessive packed-frame range')
            stream.seek(offset)
        else:
            size = info.st_size
            if not 0 < size <= expected * 2 + 1024:
                raise ValueError('excessive compressed payload size')
        compressed = stream.read(size)
        if len(compressed) != size:
            raise ValueError('pixel file was truncated during read')
    codec = row.get('codec', 'zlib')
    if codec == 'zlib':
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected + 1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data:
            raise ValueError('lossless payload size/stream mismatch')
        return raw
    if codec == 'zstd':
        library = zstd_library()
        size = library.ZSTD_findFrameCompressedSize(compressed, len(compressed))
        if library.ZSTD_isError(size) or size != len(compressed):
            raise ValueError('invalid or concatenated Zstandard frame')
        output = ctypes.create_string_buffer(expected)
        decoded = library.ZSTD_decompress(output, expected, compressed, len(compressed))
        if library.ZSTD_isError(decoded) or decoded != expected:
            raise ValueError('Zstandard payload size/stream mismatch')
        return output.raw
    raise ValueError(f'Unsupported pixel codec: {codec}')
