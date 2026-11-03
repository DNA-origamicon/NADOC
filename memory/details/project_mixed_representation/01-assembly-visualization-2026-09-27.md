# Assembly visualization (2026-09-27) — supporting detail

[Topic head](../../project_mixed_representation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Assembly visualization (2026-09-27)

Assembly comparison panes/layers own independent renderer resources and use placed
assembly bounds. View volumes persist in `Assembly.view_volumes` via
`/api/assembly/view-volumes`; membership namespaces each instance's columns and
uses transformed backbone/skip samples. The part CG/atom/surface layer renderer
is reused through source-specific adapters. Unaffected copies keep shared GPU
instancing; enabled volumes also carry into comparison scenes. Native geometry
and authored representations are preserved when comparison tools close.
See `docs/audits/assembly_visualization_20260927.md` for scope and validation.
