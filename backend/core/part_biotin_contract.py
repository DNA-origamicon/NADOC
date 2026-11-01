"""Numerical provenance for the unchanged native biotin pocket search."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.core.part_command_errors import CommandContractError
from backend.core.part_duplex_relax_contract import SOURCE_PATHS as DNA_PATHS, DATA_PATHS
from backend.core.part_streptavidin_contract import SOURCE_PATHS as COATING_PATHS
from backend.core.part_numerical_runtime import digest, file_digest, runtime_fingerprint

ENGINE_ID = 'nadoc.biotin-dna-native.v1'
_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = tuple(sorted(set(DNA_PATHS + COATING_PATHS + (
    'backend/core/part_biotin_contract.py', 'backend/core/gold_strep_dna.py',
    'backend/core/biotin_extensions.py', 'backend/api/part_biotin_commands.py'))))
Hash = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class BiotinContractError(CommandContractError):
    pass


class EnginePin(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    id: Literal['nadoc.biotin-dna-native.v1']
    implementation_sha256: Hash
    runtime_sha256: Hash


def implementation_manifest():
    return {'id': ENGINE_ID, 'placement': 'existing-pocket-native-clearance-v2',
        'files': {name: file_digest(_ROOT / name, error_type=BiotinContractError,
                                   label='biotin attachment') for name in SOURCE_PATHS + DATA_PATHS}}


def contract_defaults():
    return {'_proof_version': 1, 'biotin_version': 1, 'engine': {'id': ENGINE_ID,
        'implementation_sha256': digest(implementation_manifest()),
        'runtime_sha256': digest(runtime_fingerprint())}}


def validate_environment(engine):
    if engine.implementation_sha256 != digest(implementation_manifest()):
        raise BiotinContractError('Biotin placement code/data differs from its authored engine', code='engine_mismatch')
    if engine.runtime_sha256 != digest(runtime_fingerprint()):
        raise BiotinContractError('Biotin placement runtime differs from its authored engine', code='runtime_mismatch')
