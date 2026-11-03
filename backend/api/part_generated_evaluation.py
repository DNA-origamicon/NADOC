"""Generated construction on the existing isolated recipe job lifecycle."""
from backend.core.part_command_errors import CommandContractError


def parse_settings(params):
    from backend.core.two_np_generator import GeneratorSettings
    unknown = set(params) - GeneratorSettings.model_fields.keys()
    if unknown:
        raise ValueError('Unknown generator settings: ' + ', '.join(sorted(unknown)))
    settings = GeneratorSettings.model_validate(params)
    if settings.shape == 'branched':
        raise ValueError('Experimental branched generation is outside native asset composition')
    if settings.mechanics in {'fem-linear', 'fem-nonlinear', 'oxdna'}:
        raise ValueError('Native construction does not launch scientific validation; run it explicitly after generation')
    return settings


def generate(source, request, header, executor, dependencies):
    from backend.api.generated_history import build_recorded
    from backend.api.branch_optimization import plan_for_generation
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_history_proof import root_design
    from backend.core.part_verification_capture import admit
    from backend.core.part_recovery_storage import retained_recovery_bytes
    from backend.core.validator import validate_design

    if header.get('source_revision') != request.expected_revision or header.get('source_design_id') != source.id:
        raise CommandContractError('Generation source context changed', code='invalid_capture_context')
    settings = parse_settings(request.params)
    prefix = ReplayPrefix(source, len(source.feature_log))
    last = None

    def run(kind, current, params):
        nonlocal last
        last = prefix.execute(executor, kind, current, params)
        return last

    proof = assess_part_history(source, execute=run, dependencies=dependencies)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        raise CommandContractError('Generation requires a reproducible input recipe', code='recipe_not_reproducible')
    current = (last if last is not None else root_design(source.recipe_root,
        input_sources=source.input_sources)).copy_with(id=source.id, feature_log=prefix.log, recipe_root=source.recipe_root)
    planned, report = plan_for_generation(current, settings)
    candidate, placement = build_recorded(current, planned, settings, native_assets=True)
    if placement.get('history_unverified_steps'):
        raise CommandContractError('Generated construction contains an unverified command', code='generated_command_unverified')
    admit(candidate, preserve_entry_types=True)
    retained_recovery_bytes(candidate.feature_log, max_rows=2000)
    validation = validate_design(candidate)
    if not validation.passed:
        raise ValueError('Generated topology did not pass validation: ' + str(validation))
    proof = assess_part_history(candidate, execute=executor, dependencies=dependencies)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        raise CommandContractError('Generated recipe did not reproduce its complete authoring state', code='generated_proof_failed')
    return candidate, validation, {**report, **placement}
