"""Exact display-frame selection, independent of topology and physical analysis."""

def select_composite_range(groups, first=0, last=None, step=1):
    """Select inclusive composite indices with a global (not per-segment) interval."""
    if type(step) is not int or step < 1:
        raise ValueError('frame_step must be a positive integer')
    total = sum(len(group) for group in groups)
    start = min(max(0, first or 0), max(0, total - 1))
    end = min(total, max(start + 1, last + 1)) if last is not None else total
    offset = 0
    selected = []
    for group in groups:
        lo, hi = max(0, start - offset), min(len(group), end - offset)
        lo += (start - offset - lo) % step
        selected.append(group[lo:max(lo, hi):step])
        offset += len(group)
    return selected, start, total
