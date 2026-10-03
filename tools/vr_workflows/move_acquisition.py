"""Require the existing remote-grab contract throughout acquisition feedback."""
import math


def remote_target(state):
    end = state.get('move_beam_end')
    return bool(state.get('move_nearby') and end is not None
                and math.dist(state['hands'][1]['position'], end) > .15)
