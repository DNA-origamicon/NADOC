"""Run a command under a private, automatically cleaned NVIDIA MPS service.

python -m tools.oxdna_umbrella.mps -- python -m tools.oxdna_umbrella.run ...
Does not change the GPU compute mode or any other application's environment.
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


def main(command):
    executable=shutil.which('nvidia-cuda-mps-control')
    if not executable:raise RuntimeError('NVIDIA MPS control is unavailable.')
    with tempfile.TemporaryDirectory(prefix='nadoc-umbrella-mps-') as temporary:
        root=Path(temporary);(root/'pipe').mkdir();(root/'log').mkdir()
        env={**os.environ,'CUDA_MPS_PIPE_DIRECTORY':str(root/'pipe'),'CUDA_MPS_LOG_DIRECTORY':str(root/'log')}
        subprocess.run([executable,'-d'],env=env,check=True)
        process=subprocess.Popen(command,env=env,start_new_session=True)
        def stop(*_):
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        previous={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
        try:return process.wait()
        finally:
            stop()
            process.wait()
            for sig,handler in previous.items():signal.signal(sig,handler)
            subprocess.run([executable],input='quit\n',text=True,env=env,check=True,capture_output=True)


if __name__=='__main__':
    command=sys.argv[1:]
    if command and command[0]=='--':command=command[1:]
    if not command:raise SystemExit(__doc__)
    raise SystemExit(main(command))
