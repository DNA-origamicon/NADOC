"""Illustrative stress-test presets, never demographic or learned skill labels."""
from .model import Profile

PRESETS = {
    'steady_fast': (.65, Profile(position_sigma_m=.001, rotation_sigma_deg=.2,
        overshoot_fraction=.01, reaction_s=.12)),
    'steady_deliberate': (1.8, Profile(position_sigma_m=.001, rotation_sigma_deg=.2,
        overshoot_fraction=.01, reaction_s=.3)),
    'variable_fast': (.65, Profile(position_sigma_m=.012, rotation_sigma_deg=2,
        overshoot_fraction=.15, reaction_s=.12)),
    'variable_deliberate': (1.8, Profile(position_sigma_m=.012, rotation_sigma_deg=2,
        overshoot_fraction=.15, reaction_s=.3)),
}

INITIAL_PRESET = 'steady_fast'
FINAL_PRESETS = tuple(PRESETS)
