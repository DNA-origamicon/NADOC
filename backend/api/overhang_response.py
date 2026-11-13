"""Atomic geometry responses for sequence edits, with conservative pose fallback."""
def sequence_response(before, after, report):
    from backend.api.crud import _design_response, _design_response_with_geometry, _has_effective_display_pose
    from backend.core.render_diff import _local_changed_helices, _strand_occupancy

    changed = None
    if (not _has_effective_display_pose(after) and not after.flexible_connections
            and not after.nucleotide_transforms
            and before.atomistic_reference == after.atomistic_reference):
        # Ordinary helix geometry contains topology/site frames, not sequence
        # letters. Prove every other authored field identical before reusing it.
        excluded = {"feature_log": True, "feature_log_cursor": True,
                    "strands": {"__all__": {"sequence"}},
                    "overhangs": {"__all__": {"sequence"}}}
        if before.model_dump(exclude=excluded) == after.model_dump(exclude=excluded):
            return {**_design_response(after, report), "geometry_unchanged": True}
        old, new = _strand_occupancy(before), _strand_occupancy(after)
        changed = _local_changed_helices(old, new)
        if changed is None and old == new and before.helices == after.helices and before.overhang_connections == after.overhang_connections:
            # Same-length edits still refresh sequence-derived nucleotide metadata
            # on all dependent strands, without rebuilding unrelated helices.
            previous = {s.id: s for s in before.strands}
            old_specs = {o.id: o for o in before.overhangs}
            changed = sorted({o.helix_id for o in after.overhangs if old_specs.get(o.id) != o} | {d.helix_id for s in after.strands
                              if s.id in previous and s.sequence != previous[s.id].sequence
                              for d in s.domains}) or None
    return _design_response_with_geometry(
        after, report, changed_helix_ids=changed,
        compact_deformed=True, partial_axes=bool(changed),
    )
