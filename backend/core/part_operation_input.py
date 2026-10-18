"""Small JSON operation envelopes; reject excess work before copying/spawning."""

from math import isfinite


MAX_OPERATION_BYTES = 256_000
MAX_OPERATION_NODES = 10_000


def validate_operation_input(value):
    pending = [(value, 0)]
    nodes, size = 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        size += 16
        if nodes > MAX_OPERATION_NODES or depth > 64:
            raise ValueError("Part operation input exceeds the structural budget")
        if type(item) is str:
            size += 4 * len(item)
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if item.bit_length() > 64:
                raise ValueError("Part operation integer exceeds the supported range")
        elif type(item) is float:
            if not isfinite(item):
                raise ValueError("Part operation numbers must be finite")
        elif type(item) in {dict, list}:
            if nodes + len(pending) + len(item) > MAX_OPERATION_NODES:
                raise ValueError("Part operation input exceeds the structural budget")
            if type(item) is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("Part operation object keys must be strings")
                    size += 4 * len(key)
                    pending.append((child, depth + 1))
            else:
                pending.extend((child, depth + 1) for child in item)
        else:
            raise ValueError("Part operation accepts JSON values only")
        if size > MAX_OPERATION_BYTES:
            raise ValueError("Part operation input exceeds the byte budget")
