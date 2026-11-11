"""Compose existing editor commands; never capture an extracted graph as a root."""

from backend.api import headless_build as author, state
from backend.api.part_cell_commands import build as cell
from backend.api.part_structural_commands import build as structural
from backend.api.part_native_commands import build_loop, build_sequence
from backend.api.part_ligation_commands import build as ligation
from backend.core.part_history_contract import create_empty_part
from experiments.recorded_review_process import ProcessRequired
from scripts.agent_structure_guard import audit


def audit_image_history(design):
    from backend.core.part_history_proof import command_rows
    for _, kind, _ in command_rows(design, 2000):
        if 'import' in kind:
            raise ProcessRequired('Image-only authoring cannot substitute an import command for construction')
    return audit(design)


def crossover(kind, design, params):
    from backend.api.crud import PlaceCrossoverRequest, _build_place_crossover
    updated, _, ligated = _build_place_crossover(design, PlaceCrossoverRequest.model_validate(params))
    if not ligated:
        raise ProcessRequired('Requested crossover did not join the selected strand ends')
    return updated


def sequence(kind, design, params):
    from backend.api.part_strand_patch import build
    from backend.api.crud import StrandPatchRequest
    return build(design, params['strand_id'], StrandPatchRequest.model_validate(params))[0]


# Deliberately bounded to reviewed editor operations, not every replay executor.
# Imports, frozen topology, diagnostic operations and assembly commands are absent.
BUILDERS = {
    **dict.fromkeys(('helix-add-at-cell', 'helix-extend', 'scaffold-domain-paint'), cell),
    **dict.fromkeys(('strand-add', 'strand-update', 'domain-add', 'helix-reorder', 'helix-update'), structural),
    'loop-skip-insert': build_loop,
    'crossover-place': crossover,
    'strand-sequence': sequence,
    **dict.fromkeys(('assign-scaffold-sequence', 'assign-staple-sequences'), build_sequence),
    **dict.fromkeys(('ligate', 'forced-ligation-create', 'crossover-extra-bases',
                     'forced-ligation-extra-bases'), ligation),
}


def construct(recipe, *, progress=None):
    """Execute an explicit reviewed operation recipe through the real recorders."""
    from backend.api.part_proof_commands import PROOF_MINOR_KINDS

    if (recipe.get('version') != 1 or type(recipe.get('operations')) is not list
            or not 1 <= len(recipe['operations']) <= 1900):
        raise ProcessRequired('A version-1, nonempty editor-operation recipe is required')
    if type(recipe.get('unresolved')) is not list:
        raise ProcessRequired('Recipe must explicitly list unresolved selections (empty only when reviewed)')
    if recipe.get('unresolved'):
        raise ProcessRequired('Unresolved reconstruction selections: ' + str(recipe['unresolved']))
    for operation in recipe['operations']:
        if operation['kind'] not in BUILDERS:
            raise ProcessRequired(f"No admitted editor authoring adapter: {operation['kind']}")
        if any(key.startswith('_') and key not in {'_helix_id', '_strand_id', '_scaffold_id',
                '_staple_id', '_fl_id', '_color'} for key in operation['params']):
            raise ProcessRequired('Private replay/captured-state parameters are not recipe inputs')
    with author.scratch_session():
        state.load_design(create_empty_part(recipe['name'], recipe['lattice']))
        for number, operation in enumerate(recipe['operations'], 1):
            kind, params = operation['kind'], dict(operation['params'])
            params['_generator'] = {'tool': 'All Origami recorded authoring',
                'design_id': recipe.get('design_id'), 'sources': recipe.get('sources', []),
                'evidence': operation.get('evidence', []), 'selection': operation['label'],
                'execution_code': recipe.get('execution_code')}
            builder = BUILDERS[kind]
            fn = lambda d, k=kind, p=params, b=builder: b(k, d, p)
            try:
                if kind in PROOF_MINOR_KINDS:
                    state.mutate_with_minor_log(op_subtype=kind, label=operation['label'],
                                                params=params, fn=fn)
                else:
                    state.mutate_with_feature_log(kind, operation['label'], params, fn)
            except Exception as exc:
                raise ProcessRequired(f"Native {kind} failed: {getattr(exc, 'detail', str(exc))}") from exc
            if progress is not None and (number % 100 == 0 or number == len(recipe['operations'])):
                progress(number, len(recipe['operations']))
        design = state.get_or_404().model_copy(deep=True)
    audit_image_history(design)
    return design


def detect_and_relax(design, *, relax=False):
    """Record detected memberships and fitted poses as Make Cluster/Move commands."""
    from backend.api.part_import_relaxation import record_fit
    from backend.core.cluster_autodetect import _cluster_by_lattice_neighbors
    from backend.core.import_relaxation import relax_imported_design

    audit_image_history(design)  # A legacy file must not acquire a misleading history suffix.
    detected = _cluster_by_lattice_neighbors(design)
    groups = detected.cluster_transforms
    # Existing intentional memberships/poses are upstream authoring, not disposable
    # autodetection output. Detection still runs and its proposal is reported.
    existing = [g for g in design.cluster_transforms if not g.is_default
                or any(g.translation) or list(g.rotation) != [0, 0, 0, 1]]
    if not existing:
        design = record_fit(design, detected)
    report = {'cluster_detection': {'method': 'lattice adjacency with FL-only edge removal',
              'memberships': [list(g.helix_ids) for g in groups],
              'existing_groups_preserved': bool(existing)},
              'relaxation': {'status': 'not_requested'}, 'simulation_validated': False}
    if relax:
        fitted, fit = relax_imported_design(design, enabled=True)
        report['relaxation'] = fit
        if fit['status'] == 'applied':
            from tools.design_archive.rigid_fit_audit import audit_fit
            before = design
            design = record_fit(design, fitted)
            report['independent_geometry_audit'] = audit_fit(before, design)
    audit(design)
    return design, report
