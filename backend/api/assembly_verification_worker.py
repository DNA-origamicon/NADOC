"""Assembly adapter for the existing bounded disposable-process transport."""
import pickle

from backend.api.part_evaluation_worker import run_operation, native_thread_limit
from backend.api.part_verification_worker import VerificationWorker, _BoundedInput, MAX_RESULT_BYTES
from backend.core.assembly_verification_capture import MAX_INPUT_BYTES


def evaluate(source):
    from backend.api.assembly_history_verification import verify
    with native_thread_limit():
        return verify(source)


def _evaluate(input_name, input_size, output_name):
    run_operation(input_name, input_size, output_name, evaluate, MAX_RESULT_BYTES)


class AssemblyVerificationWorker(VerificationWorker):
    def __init__(self, assembly):
        stream = _BoundedInput(MAX_INPUT_BYTES)
        pickle.dump({'source': assembly}, stream, protocol=pickle.HIGHEST_PROTOCOL)
        self._initialize_input((stream.getvalue(),), _target=_evaluate,
                               _result_limit=MAX_RESULT_BYTES, _name='nadoc-assembly-proof')
