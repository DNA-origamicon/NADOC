"""Bounded activity decisions from explicit observations, with no I/O or effects.

Acquiring facts is the caller's responsibility. Unknown observations are not false;
these decisions are neither finalization authority nor a public job-status schema.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Assessment:
    action: str
    missing: str | None = None


_FIELDS = frozenset({'running', 'live', 'segment_valid', 'outputs_complete',
    'minimization_missing', 'checkpoint', 'log_exists', 'cached', 'raw_complete'})


def _facts(values):
    # Nine bounded scalar facts: no models, containers, subclass hooks or I/O.
    if type(values) is not dict or len(values) > len(_FIELDS):
        raise ValueError('Activity observations require a bounded exact dictionary')
    for key, value in values.items():
        if type(key) is not str or len(key) > 32 or key not in _FIELDS:
            raise ValueError('Unknown activity observation')
        if value is not None and type(value) is not bool:
            raise ValueError('Activity observations must be boolean or unknown')
    return values


def _choose(values, branches):
    for key, when_true, when_false in branches:
        value = values.get(key)
        if value is None:
            return Assessment('unknown', key)
        selected = when_true if value else when_false
        if selected is not None:
            return Assessment(selected)
    raise AssertionError('Activity decision table has no terminal branch')


def namd_activity(values):
    """Local running-orphan decisions; preparation/remote owners stay separate."""
    return _choose(_facts(values), (
        ('running', None, 'unchanged'),
        ('live', 'live', None),
        ('segment_valid', None, 'finalization_required'),
        ('outputs_complete', 'segment_finalization_required', None),
        ('minimization_missing', 'resume_minimization', None),
        ('checkpoint', 'resume_checkpoint', None),
        ('log_exists', 'failed_without_checkpoint', 'resume_unstarted_segment'),
    ))


def mrdna_activity(values):
    """Preserve original priority: live > display cache > raw finalization > stale."""
    return _choose(_facts(values), (
        ('live', 'live', None),
        ('cached', 'completed_cache', None),
        ('raw_complete', 'finalization_required', None),
        ('running', 'stopped', 'unchanged'),
    ))


def raw_mrdna_complete(fine_steps, progress):
    """The existing completion predicate, shared by observation and reconciliation."""
    # Inputs belong to the existing runner's validated progress calculation.
    # The public assessment seam accepts only the resulting bounded boolean.
    return bool(fine_steps > 0 and progress is not None and progress >= 0.99)
