"""Fixed assembly evaluation entry point using the shared bounded transport."""
import pickle
from backend.api.part_evaluation_worker import run_operation, native_thread_limit, MAX_CANDIDATE_BYTES
from backend.api.part_verification_worker import VerificationWorker, _BoundedInput
from backend.core.assembly_verification_capture import MAX_INPUT_BYTES


def evaluate(source, operation):
    from backend.api.assembly_evaluation import evaluate as run
    with native_thread_limit():
        return run(source, operation)


def _evaluate(input_name, input_size, output_name):
    run_operation(input_name, input_size, output_name, evaluate, MAX_CANDIDATE_BYTES)


class AssemblyEvaluationWorker(VerificationWorker):
    def __init__(self, source, operation):
        stream = _BoundedInput(MAX_INPUT_BYTES)
        pickle.dump({'source': source, 'operation': operation}, stream, protocol=pickle.HIGHEST_PROTOCOL)
        self._initialize_input((stream.getvalue(),), _target=_evaluate,
                               _result_limit=MAX_CANDIDATE_BYTES, _name='nadoc-assembly-evaluation')

    def result(self):
        result = self._read_result()
        if result.get('status') not in {'ready', 'failed', 'mismatch', 'unverified'}:
            raise ValueError('Invalid assembly evaluation result')
        if result['status'] == 'ready' and not isinstance(result.get('candidate'), dict):
            raise ValueError('Assembly candidate missing')
        return result
