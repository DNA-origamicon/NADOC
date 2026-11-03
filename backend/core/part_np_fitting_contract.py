"""Numerical identity for existing nanoparticle fit, move and anchor solve."""
from pathlib import Path
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, StringConstraints
from backend.core.part_command_errors import CommandContractError
from backend.core.part_duplex_relax_contract import SOURCE_PATHS as DNA_PATHS, DATA_PATHS
from backend.core.part_numerical_runtime import digest, file_digest, runtime_fingerprint

ENGINE_ID = 'nadoc.nanoparticle-fitting-native.v1'
_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = tuple(sorted(set(DNA_PATHS + tuple('backend/core/' + name + '.py' for name in (
    'part_np_fitting_contract', 'nanoparticle', 'nanoparticle_connections', 'nanoparticle_attachment_fit',
    'nanoparticle_attachment_obstacles', 'nanoparticle_kinematics', 'protein', 'conjugation',
    'part_saved_topology', 'part_scope_references')) + tuple('backend/api/' + name + '.py' for name in (
    'nanoparticle_attachment', 'part_np_fitting_commands', 'part_np_application_commands',
    'part_thiol_commands', 'part_nanoparticle_connection_commands', 'part_generated_np_fitting')))))
Hash = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class FittingContractError(CommandContractError):
    pass


class EnginePin(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    id: Literal['nadoc.nanoparticle-fitting-native.v1']
    implementation_sha256: Hash
    runtime_sha256: Hash


def implementation_manifest():
    return {'id': ENGINE_ID, 'solver': 'existing-covalent-root-priority-native-v1',
        'files': {name: file_digest(_ROOT / name, error_type=FittingContractError,
            label='nanoparticle fitting') for name in SOURCE_PATHS + DATA_PATHS}}


def contract_defaults():
    return {'_proof_version': 1, 'np_fitting_version': 1, 'engine': {'id': ENGINE_ID,
        'implementation_sha256': digest(implementation_manifest()), 'runtime_sha256': digest(runtime_fingerprint())}}


def validate_environment(engine):
    if engine.implementation_sha256 != digest(implementation_manifest()):
        raise FittingContractError('Nanoparticle fitting code/data differs from its authored engine', code='engine_mismatch')
    if engine.runtime_sha256 != digest(runtime_fingerprint()):
        raise FittingContractError('Nanoparticle fitting runtime differs from its authored engine', code='runtime_mismatch')
