"""One-based inclusive frame selection for interactive NAMD flexibility maps."""


class FlexFrameRangeError(ValueError):
    pass


def flex_frame_indices(n_frames, selection):
    if selection is None:
        return range(n_frames)
    interval = selection.get('interval', 1)
    end = selection.get('end')
    end = n_frames if end is None else end
    start = selection.get('start')
    start = max(1, end - 199) if start is None else start
    if any(type(value) is not int for value in (start, end, interval)):
        raise FlexFrameRangeError('Frame start, end, and interval must be integers')
    if interval < 1 or start < 1 or end < start or end > n_frames:
        raise FlexFrameRangeError(f'Choose 1 ≤ start ≤ end ≤ {n_frames} and interval ≥ 1')
    return range(start - 1, end, interval)
