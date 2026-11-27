"""Bound the isolated placement experiment to recorded Corner insert seams.

This is an admission check, not a source-replay certificate or production
placement policy. The diagnostic runner independently proves its source.
"""

import re

from backend.api.part_corner_commands import CornerCommand
from backend.core.part_history_proof import command_rows


def require_corner_only_inserts(design):
    operations = {
        CornerCommand.model_validate(params).operation_id
        for _, kind, params in command_rows(design, 2000) if kind == 'corner'
    }
    links = []
    for link in design.forced_ligations:
        if not link.extra_bases:
            continue
        operation, separator, digest = link.id.rpartition(':seam:')
        if not separator or operation not in operations or re.fullmatch('[0-9a-f]{24}', digest) is None:
            raise ValueError('The isolated Corner candidate cannot move inserts from other ligations; '
                             'a scoped placement adapter is required.')
        links.append(link)
    if any(link.extra_bases for link in design.crossovers):
        raise ValueError('The isolated Corner candidate cannot move ordinary crossover inserts.')
    return tuple(links)
