"""Read-only assembly proof adapter; the caller binds the captured revision."""
from fastapi import HTTPException

from backend.api import assembly_command_replay
from backend.core.assembly_history_proof import assess
from backend.core.assembly_source_versions import design_digest, pinned_design
from backend.core.models import Design, PartSourceFile, PartSourceInline
from backend.core.part_history_contract import assess_part_history


def verify(assembly, *, checkpoint=lambda: None, max_entries=2000, allow_prefix=False):
    from backend.api import part_proof_commands
    source_proofs = {}

    def validate(kind, params):
        try:
            assembly_command_replay.validate_definition(kind, params)
        except HTTPException as error:
            raise ValueError(error.detail) from error

    def execute(current, kind, params):
        try:
            return assembly_command_replay.replay(current, kind, params)
        except HTTPException as error:
            raise ValueError(error.detail) from error

    def sources(kind, params, check):
        designs = []
        if kind == 'assembly-add-instance':
            raw = params['inputs']['source']
            source = PartSourceFile.model_validate(raw) if raw['type'] == 'file' else PartSourceInline.model_validate(raw)
            design = source.design if source.type == 'inline' else pinned_design(source)
            if design is None:
                raise ValueError('AGENT_PROCESS_REQUIRED: file source lacks a pinned revision')
            designs.append(design)
        elif kind == 'assembly-replace-instance-source':
            designs.append(Design.from_json(params['inputs']['content']))
        imported = False
        for design in designs:
            check()
            key = design_digest(design)
            if key not in source_proofs:
                source_proofs[key] = assess_part_history(design, execute=part_proof_commands.execute,
                    dependencies=part_proof_commands.dependencies, checkpoint=check, max_entries=max_entries)
            proof = source_proofs[key]
            if proof['status'] not in {'verified', 'reproduced_import'}:
                raise ValueError(f"AGENT_PROCESS_REQUIRED: source part history {proof['status']}: {proof['issues']}")
            imported |= proof['status'] == 'reproduced_import'
        return imported

    result = assess(assembly, execute=execute, validate_definition=validate,
                    verify_sources=sources, checkpoint=checkpoint, max_entries=max_entries, allow_prefix=allow_prefix)
    result['source_proofs'] = source_proofs
    return result
