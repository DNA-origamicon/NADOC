"""Resolve the viewer's baseline/candidate comparison without reviving legacy geometry.

The 2026-09-20 native placement is the starting point for BOTH comparison states.
The public ``measured_positioning`` flag/header is retained for existing clients,
but False now selects this baseline, not the retired legacy viewer projection.
Raw helical-site projections used by builders/seeds remain a separate API.
"""


def measured_display_placement(comparison_enabled: bool | None = None) -> bool:
    """Both comparison slots currently use the accepted measured placement.

    Future candidate experiments must be dispatched here explicitly and tested
    against the baseline. Changing the debug switch alone cannot change geometry.
    """
    return True
