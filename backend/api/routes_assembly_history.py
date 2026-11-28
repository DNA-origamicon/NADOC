"""Assembly history job hosts; domain execution lives in shared workers."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StrictInt

from backend.api import assembly_verification_jobs, assembly_evaluation_jobs
from backend.api.assembly_evaluation import EvaluationRequest

router = APIRouter()


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: StrictInt | None = None


@router.post('/assembly/features/verification/jobs', status_code=202)
def start_verification(body: VerificationRequest = None):
    return assembly_verification_jobs.start(expected_revision=body.expected_revision if body else None)


@router.get('/assembly/features/verification/jobs/{job_id}')
def inspect_verification(job_id: str):
    return assembly_verification_jobs.inspect(job_id)


@router.delete('/assembly/features/verification/jobs/{job_id}')
def cancel_verification(job_id: str):
    return assembly_verification_jobs.inspect(job_id, cancel=True)


@router.post('/assembly/features/evaluation/jobs', status_code=202)
def start_evaluation(body: EvaluationRequest):
    return assembly_evaluation_jobs.start(body)


@router.get('/assembly/features/evaluation/jobs/{job_id}')
def inspect_evaluation(job_id: str):
    return assembly_evaluation_jobs.inspect(job_id)


@router.delete('/assembly/features/evaluation/jobs/{job_id}')
def cancel_evaluation(job_id: str):
    return assembly_evaluation_jobs.inspect(job_id, cancel=True)


@router.post('/assembly/features/evaluation/jobs/{job_id}/commit')
def commit_evaluation(job_id: str):
    return assembly_evaluation_jobs.commit(job_id)


@router.get('/assembly/features/dependencies')
def inspect_dependencies():
    from backend.api.assembly_history_dependencies import current_dependencies
    return current_dependencies()


@router.get('/assembly/instances/{instance_id}/features/dependencies')
def inspect_instance_dependencies(instance_id: str):
    from fastapi import HTTPException
    from backend.api import assembly_state
    from backend.api.part_history_dependencies import dependencies_for
    with assembly_state._lock:
        session = assembly_state._session()
        assembly = session.assembly
        instance = next((i for i in assembly.instances if i.id == instance_id), None) if assembly else None
        if instance is None:
            raise HTTPException(404, detail='Selected assembly instance does not exist')
        source = instance.source.design if instance.source.type == 'inline' else instance.source.revision
        if source is None:
            raise HTTPException(409, detail='Pin this instance source revision before inspecting history')
        return {**dependencies_for(source, session.revision), 'assembly_id': assembly.id, 'instance_id': instance_id}


@router.get('/assembly/features/{index}/inputs')
def inspect_feature_inputs(index: int, expected_revision: int, expected_feature_id: str):
    from backend.api.assembly_input_schema import input_editor
    return input_editor(index, expected_revision, expected_feature_id)
