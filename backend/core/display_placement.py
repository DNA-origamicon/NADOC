"""Reject the removed viewer placement switch at every display boundary."""


def measured_display_placement(comparison_enabled: bool | None = None) -> bool:
    """The only supported native Full placement is its canonical O5′ projection."""
    from backend.core.native_full_placement import require_native_full_option

    require_native_full_option(comparison_enabled)
    return True
