"""Recorded thermostat setpoints for trajectory segments (not measured temperatures)."""
import math
import re
from pathlib import Path


def input_temperature_c(stage_dir, filename="input.txt"):
    """Read the executed input, never infer a historical temperature from a new schedule."""
    try:
        text = (Path(stage_dir) / filename).read_text()
    except OSError:
        return None
    match = re.search(r'^\s*T\s*=\s*([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*([kKcC]?)\s*(?:#.*)?$', text, re.M)
    if not match:
        return None
    try:
        value = float(match[1])
    except ValueError:
        return None
    unit = match[2].upper()
    celsius = value if unit == 'C' else value * (1 if unit == 'K' else 3000) - 273.15
    return round(celsius, 6) if math.isfinite(celsius) and celsius > -273.15 else None


def temperature_metadata(item, seed=False):
    if len(item) <= 7 or item[7] is None:
        return {}
    return {'temperature_c': item[7], 'temperature_start': int(seed)}


def temperature_markers(stages, markers):
    """Enrich real output-frame boundaries, including the first physical frame.

    The optional design-reference seed has no simulation temperature. Empty stages
    and future plateaus have no frames and therefore receive no marker.
    """
    result = [dict(m) for m in markers]
    offset = 0
    for stage in stages:
        count = stage['n_frames']
        start = offset + stage.get('temperature_start', 0)
        if stage.get('temperature_c') is not None and start < offset + count:
            marker = next((m for m in result if m['frame'] == start), None)
            if marker is None:
                marker = {'frame': start, 'label': f"→ {stage['kind']}",
                          'kind': stage['kind'], 'stage_name': stage['name']}
                result.append(marker)
            marker.update(temperature_c=stage['temperature_c'], end_frame=offset + count - 1)
        offset += count
    return sorted(result, key=lambda m: m['frame'])


def trajectory_temperature_c(trajectory):
    """Archived frames must use their own input, not the current attempt's input."""
    trajectory = Path(trajectory)
    match = re.fullmatch(r'trajectory\.r(\d+)\.dat', trajectory.name)
    name = f'input.r{match[1]}.txt' if match else 'input.txt'
    return input_temperature_c(trajectory.parent, name)


def archive_temperature_input(stage_dir, trajectory_archive):
    """Keep an attempt's setpoint alongside its archived frames before input rewrite."""
    from shutil import copyfile
    stage_dir = Path(stage_dir)
    match = re.fullmatch(r'trajectory\.r(\d+)\.dat', trajectory_archive)
    if match and (stage_dir / 'input.txt').exists():
        copyfile(stage_dir / 'input.txt', stage_dir / f'input.r{match[1]}.txt')
