"""Content-verified reuse of recovery bodies across undo and redo responses."""
import hashlib

from pydantic import BaseModel, Field


class HistoryCacheRequest(BaseModel):
    history_body_digests: dict[str, str] = Field(default_factory=dict)


def body_values(entry: dict) -> list:
    values = [entry.get(key) or '' for key in (
        'design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64')]
    for index, child in enumerate(entry.get('children') or []):
        values.extend([child.get('id') if child.get('id') is not None else index, *[child.get(key) or '' for key in (
            'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64')]])
    return values


def body_digest(entry: dict) -> str:
    digest = hashlib.sha256()
    for value in body_values(entry):
        raw = str(value).encode()
        digest.update(str(len(raw)).encode() + b':')
        digest.update(raw)
    return digest.hexdigest()


def reuse_history_bodies(payload: dict, known: dict[str, str]) -> None:
    """Only omit bodies proven identical to the caller's cache, including empty ones.

    Entry IDs alone are insufficient: undo can restore older bodies under the
    same ID. The explicit reuse list also prevents a deliberately empty restored
    body from being filled with a newer nonempty one by the client merge.
    """
    if not known or not payload.get('design'):
        return
    from backend.api.crud import _strip_feature_log_payloads

    entries = payload['design'].get('feature_log', [])
    reuse = {e['id'] for e in entries if e['id'] in known and (payload.get('history_body_digests', {}).get(e['id']) or body_digest(e)) == known[e['id']]}
    _strip_feature_log_payloads(payload['design'], {e['id'] for e in entries} - reuse)
    payload['feature_log_payloads_partial'] = True
    payload['feature_log_reused_entry_ids'] = sorted(reuse)


def tag_history_bodies(entries: list[dict]) -> None:
    """Wire-only content tokens; canonical documents/history remain unchanged."""
    for entry in entries:
        entry['history_body_digest'] = body_digest(entry)


def take_history_digests(entries: list[dict]) -> dict[str, str]:
    """Keep transport acknowledgements outside the authored feature records."""
    return {entry['id']: entry.pop('history_body_digest')
            for entry in entries if 'history_body_digest' in entry}
