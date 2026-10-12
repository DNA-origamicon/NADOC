"""Document-bound desktop simulation controls for the native sidebar."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class Control(BaseModel):
    id: str = Field(pattern=r'^[ejvtc]:[a-z0-9:_-]+$', max_length=100)
    label: str = Field(max_length=4096)
    detail: str = Field(default='', max_length=8192)
    enabled: bool
    active: bool = False
    kind: str = Field(default='', max_length=24)
    group: str = Field(default='', max_length=80)
    value: float = Field(default=0, allow_inf_nan=False)
    minimum: float = Field(default=-1e9, allow_inf_nan=False)
    maximum: float = Field(default=1e9, allow_inf_nan=False)
    step: float = Field(default=1, allow_inf_nan=False)


class Trajectory(BaseModel):
    available: int = Field(ge=0, le=100_000_000)
    first: int = Field(ge=1, le=100_000_000)
    last: int = Field(ge=0, le=100_000_000)
    interval: int = Field(ge=1, le=100_000_000)
    count: int = Field(ge=0, le=100_000_000)
    index: int = Field(ge=0, le=100_000_000)
    phase: str = Field(max_length=24)
    playing: bool
    smooth: bool = False
    progress: float = Field(ge=-1, le=1)
    message: str = Field(max_length=4096)


class Progress(BaseModel):
    label: str = Field(max_length=8192)
    fraction: float = Field(ge=-1, le=1)
    busy: bool = False


class Scale(BaseModel):
    title: str = Field(max_length=250)
    minimum: float
    maximum: float
    low: float
    high: float
    palette: int = Field(ge=0, le=5)


class Snapshot(BaseModel):
    version: int = Field(ge=1, le=2147483647)
    acknowledged: int = Field(ge=0, le=2147483647)
    engine: str = Field(max_length=24)
    selected: str = Field(max_length=256)
    engines: list[Control] = Field(max_length=10)
    jobs: list[Control] = Field(max_length=10000)
    controls: list[Control] = Field(max_length=1000)
    mode: str = Field(default='', max_length=80)
    trajectory: Trajectory | None = None
    progress: list[Progress] = Field(default_factory=list, max_length=16)
    scale: Scale | None = None


def encode(snapshot):
    def quoted(value):
        # Native stroke font is ASCII; preserve readable approximations.
        import unicodedata
        text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
        return json.dumps(' '.join(text.split())[:250])
    lines = [f'NADOC_SIMULATIONS_2 {snapshot.version} {snapshot.acknowledged} {len(snapshot.engines)} {len(snapshot.jobs)} {len(snapshot.controls)} {int(bool(snapshot.selected))} {quoted(snapshot.mode)}']
    for row in [*snapshot.engines, *snapshot.jobs, *snapshot.controls]:
        lines.append(f'{quoted(row.id)} {quoted(row.label)} {quoted(row.detail)} {int(row.enabled)} {int(row.active)} {quoted(row.kind)} {quoted(row.group)} {row.value} {row.minimum} {row.maximum} {row.step}')
    t = snapshot.trajectory
    lines.append(str(int(t is not None)))
    if t:
        lines.append(f'{t.available} {t.first} {t.last} {t.interval} {t.count} {t.index} {quoted(t.phase)} {int(t.playing)} {int(t.smooth)} {t.progress} {quoted(t.message)}')
    lines.append(str(len(snapshot.progress)))
    for progress in snapshot.progress:
        lines.append(f'{quoted(progress.label)} {progress.fraction} {int(progress.busy)}')
    c = snapshot.scale
    lines.append(str(int(c is not None)))
    if c:
        lines.append(f'{quoted(c.title)} {c.minimum} {c.maximum} {c.low} {c.high} {c.palette}')
    return '\n'.join(lines) + '\n'


@router.post('/vr/simulations')
async def publish(body: Snapshot, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != get_current_doc():
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
        path = Path(state['event_path'] + '.simulations')
        temporary = Path(str(path) + '.next')
        temporary.write_text(encode(body))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {'published': True}


def parse_event(value):
    if not isinstance(value, dict):
        return None
    if any(type(value.get(k)) is not int or not 1 <= value[k] <= 2147483647 for k in ('sequence', 'version')):
        return None
    import re
    if not isinstance(value.get('id'), str) or not re.fullmatch(r'[ejvtc]:[a-z0-9:_-]{1,96}', value['id']):
        return None
    result = {k: value[k] for k in ('sequence', 'version', 'id')}
    import math
    for key in ('value', 'first', 'last', 'interval'):
        if key not in value:
            continue
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or abs(number) > 1e9:
            return None
        if key != 'value' and (type(number) is not int or number < 1):
            return None
        result[key] = number
    return result
