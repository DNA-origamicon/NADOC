"""Automatic routing retries local end turns without relaxing track bounds."""
from backend.api import headless_build as build, state
from backend.api.part_recipe_edit import change_recipe, regenerate
from backend.api.routes_design_loadouts import create_loadout, LoadoutCreateBody
from backend.api.routes_sweep import create_sweep
from backend.core.design_loadouts import decode_snapshot
from backend.core.models import Design, LatticeType
from backend.core.seamed_router import auto_scaffold_matched
from backend.core.sweep import SweepRequest
from scripts.agent_structure_guard import audit, publish
from tests.test_document_operations import save
from tests.test_scaffold_continuations import _assert_routed_contract
from tests.test_scaffold_end_clearance import CELLS

ORIGINAL_END = [-25.977535346791882, 26.02855285782208, 36.816115001169905]
EDITED_END = [8, 38, 36]


def author_sweep(endpoint):
    source = build.create_bundle(CELLS, 56, lattice=LatticeType.HONEYCOMB, name='__e2e__sweep-end-window')
    create_sweep(SweepRequest(
        cells=CELLS,
        points_nm=[[0, 0, 0], [0, 13.01427642891104, 18.408057500584952], endpoint],
        source_helix_id=next(h.id for h in source.helices if h.grid_pos == (1, 2)),
        source_end='end',
    ))
    return state.get_or_404()


def test_sweep_edit_in_new_loadout_rebuilds_and_publishes_with_local_end_turns(tmp_path):
    with build.scratch_session():
        author_sweep(ORIGINAL_END)
        original = build.auto_scaffold()
        save(tmp_path)
        create_loadout(LoadoutCreateBody(name='Edited sweep'))
        before = state.get_or_404()
        branch = before.active_loadout_id
        main = decode_snapshot(next(x for x in before.loadouts if x.id == 'main').design_snapshot_gz_b64)
        main_before = main.model_dump(mode='json')
        points = [*original.feature_log[1].params['points_nm'][:-1], EDITED_END]
        change_recipe(1, params={'points_nm': points})
        out = state.get_or_404()
        seed = regenerate(out, out.feature_log[:2], lambda: None)
        _assert_routed_contract(seed, out, seamed=True)
        assert out.active_loadout_id == branch
        assert [row.id for row in out.feature_log] == [row.id for row in original.feature_log]
        assert out.feature_log[1].params['points_nm'][-1] == EDITED_END
        main_after = decode_snapshot(next(x for x in out.loadouts if x.id == 'main').design_snapshot_gz_b64)
        assert main_after.model_dump(mode='json') == main_before
        path = tmp_path / '__e2e__edited-sweep.nadoc'
        publish(save(tmp_path), path)
        reopened = Design.model_validate_json(path.read_text())
        assert reopened.feature_log[1].params['points_nm'][-1] == EDITED_END
        assert audit(reopened)['loadouts_checked'] == 2


def test_explicit_matched_end_request_still_refuses_excessive_extension():
    with build.scratch_session():
        source = author_sweep(EDITED_END)
        before = source.model_dump(mode='json')
        out, result = auto_scaffold_matched(source)
        assert not result.valid
        assert any('local end-turn window' in error for error in result.errors)
        assert out is source
        assert source.model_dump(mode='json') == before


def test_automatic_local_fallback_remains_idempotent():
    with build.scratch_session():
        source = author_sweep(EDITED_END)
        first = build.auto_scaffold()
        second = build.auto_scaffold()
        _assert_routed_contract(source, first, seamed=True)
        _assert_routed_contract(source, second, seamed=True)
        assert first.helices == second.helices
        # Native execution assigns stable routing identities through its history
        # seed; compare occupied domains independently of the second command ID.
        assert [[d.model_dump() for d in s.domains] for s in first.scaffolds()] == [
            [d.model_dump() for d in s.domains] for s in second.scaffolds()]
