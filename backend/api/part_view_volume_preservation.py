"""Bounded exact presentation projection for sealed geometry, never batch authority."""
from math import isfinite

from backend.core.models import ViewVolume
from backend.core.part_command_errors import CommandContractError

MAX_VOLUMES = 128
MAX_STRING = 1024
_FIELDS = frozenset({'id', 'name', 'shape', 'min_corner', 'max_corner', 'rotation',
    'representation', 'opacity', 'coloring', 'outline_visible', 'enabled'})
_ENUMS = {'shape': {'box', 'hexagonal'},
    'representation': {'full', 'beads', 'cylinders', 'surface', 'vdw', 'ballstick', 'stick'},
    'coloring': {'strand', 'base', 'cluster', 'overhang-only', 'cpk'}}


def _reject():
    raise CommandContractError('Sealed view volumes require bounded exact finite records',
                               code='unsupported_revision_preservation')


def projection(volumes):
    # Fixed lengths and exact types precede traversal, validation and hashing.
    # At most 128 records, 2048 string characters and 11 numeric values each;
    # this fits the existing 30k-node/8MiB metadata bounds without raising either.
    if type(volumes) is not list or len(volumes) > MAX_VOLUMES or set(ViewVolume.model_fields) != _FIELDS:
        _reject()
    result = []
    for volume in volumes:
        if (type(volume) is not ViewVolume or type(volume.__dict__) is not dict
                or len(volume.__dict__) != len(_FIELDS) or set(volume.__dict__) != _FIELDS or getattr(volume, '__pydantic_extra__', None)):
            _reject()
        row = volume.__dict__
        for name in ('id', 'name'):
            if type(row[name]) is not str or len(row[name]) > MAX_STRING:
                _reject()
        for name, choices in _ENUMS.items():
            if type(row[name]) is not str or row[name] not in choices:
                _reject()
        for name in ('enabled', 'outline_visible'):
            if type(row[name]) is not bool:
                _reject()
        for name, length in (('min_corner', 3), ('max_corner', 3), ('rotation', 4)):
            value = row[name]
            if type(value) is not tuple or len(value) != length:
                _reject()
            if any(type(number) is not float or not isfinite(number) for number in value):
                _reject()
        if type(row['opacity']) is not float or not isfinite(row['opacity']):
            _reject()
        # Recheck ordinary bounds/quaternion/opacity rules after bounded shape
        # admission: model_copy/model_construct can otherwise bypass validation.
        try:
            ViewVolume.model_validate(dict(row))
        except ValueError:
            _reject()
        result.append(dict(row))
    return result
