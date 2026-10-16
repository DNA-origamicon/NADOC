"""Numerical identity for explicit pinned-source streptavidin packing.

A seed fixes one runtime's random stream, not cross-version placement. Strict
clash decisions can change which sites survive, so replay must fail closed on
an unqualified implementation/runtime instead of silently regenerating new
coating geometry. Installed code remains immutable while a worker runs.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.core.part_command_errors import CommandContractError
from backend.core.part_numerical_runtime import digest, file_digest, runtime_fingerprint


ENGINE_ID = "nadoc.streptavidin-native.v1"
_ROOT = Path(__file__).resolve().parents[2]
# Executed native closure for the admitted one-particle/no-DNA set operation:
# preparation, parser/bond inference, tether rotation, result schema and gold
# replacement. Imported simulation/rendering functions are not executed here.
# PDB and optional publication bytes are independently pinned command inputs;
# there is intentionally no bundled-data lookup or hidden file in this list.
SOURCE_PATHS = tuple(f"backend/core/{name}.py" for name in (
    "part_streptavidin_contract", "part_numerical_runtime", "part_numerical_schema_compatibility", "streptavidin",
    "protein", "pdb_to_design", "nanoparticle", "models",
)) + ("backend/api/part_streptavidin_commands.py",)
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CoatingContractError(CommandContractError):
    pass


class EnginePin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: Literal["nadoc.streptavidin-native.v1"]
    implementation_sha256: Hash
    runtime_sha256: Hash


def implementation_manifest():
    return {"id": ENGINE_ID, "preparation": "1stp-assembly-centering-native-v1",
        "packing": "fibonacci-random-rotation-clash-filter-native-v1",
        "source_policy": "pinned-complete-1stp-and-optional-coverage-v1",
        "files": {name: file_digest(_ROOT / name, error_type=CoatingContractError,
                                    label="streptavidin coating") for name in SOURCE_PATHS}}


def contract_defaults():
    """Server-selected pin inside its single-thread evaluation worker.

    This records an identity only; it neither configures numerical threads nor
    parses atoms. Public append adapters must reject caller-supplied engine
    pins. Existing rows never call this function to refresh their own pins.
    """
    return {"_proof_version": 1, "coating_version": 1, "importer_version": 1,
        "engine": {"id": ENGINE_ID, "implementation_sha256": digest(implementation_manifest()),
                   "runtime_sha256": digest(runtime_fingerprint())}}


def validate_environment(engine):
    from backend.core.part_numerical_schema_compatibility import require_implementation

    transition = require_implementation(ENGINE_ID, engine.implementation_sha256,
        implementation_manifest(), error_type=CoatingContractError,
        detail="Coating code differs from the authored numerical engine")
    if engine.runtime_sha256 != digest(runtime_fingerprint()):
        raise CoatingContractError("Coating runtime differs from the authored numerical engine",
                                   code="runtime_mismatch")
    return transition
