"""Cache only the molecular inputs used by a conservative native fit scope."""
import hashlib
import orjson

from backend.core.strand_loop_fit_sites import fit_sites

# Authoring/presentation data cannot affect native atom coordinates. Keep every
# other field by default so new molecular model fields invalidate conservatively.
_NON_MOLECULAR = {
    'recipe_root', 'input_sources', 'repair_draft', 'feature_log',
    'feature_log_cursor', 'feature_log_sub_cursor', 'metadata', 'animations',
    'dimensions', 'annotations', 'annotations_enabled', 'visibility_state',
    'representation_overrides', 'view_volumes', 'zoom_volumes',
    'plate_layout', 'tm_settings',
}


def record_key(record):
    return (record['strand_id'], record['helix_id'], record['bp_index'],
            record['direction'], record.get('copy_k', 0))


def fit_key(design, records):
    sites = fit_sites(design, records)
    excluded = set(_NON_MOLECULAR)
    if sites is not None:
        excluded.update(('helices', 'strands'))
    payload = design.model_dump(mode='json', exclude=excluded)
    if sites is None:
        local = records
    else:
        # Recompute the spatial scope on EVERY request, so a formerly distant
        # helix moving into range enters the key before a cached fit is reused.
        local = [r for r in records
                 if (r['helix_id'], r['bp_index'], r['direction']) in sites]
        helices = {key[0] for key in sites}
        strands = {r['strand_id'] for r in local}
        payload['helices'] = [h.model_dump(mode='json') for h in design.helices if h.id in helices]
        payload['strands'] = [s.model_dump(mode='json') for s in design.strands if s.id in strands]
    # Colors and labels are not coordinates. Molecular base identity, placement
    # source, frame, and topology remain in the fingerprint.
    payload['records'] = [{k: v for k, v in r.items() if k not in ('color', 'strand_color')}
                          for r in local]
    return hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).digest()
