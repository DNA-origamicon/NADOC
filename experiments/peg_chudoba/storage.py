"""Keep large benchmark artifacts on the persistent workspace archive."""
from pathlib import Path


def create_run_directory(requested):
    requested=Path(requested).absolute()
    root=Path(__file__).resolve().parents[2]
    local=root/'experiments/peg_chudoba/runs'
    if requested.is_relative_to(local):
        actual=root/'workspace/peg_chudoba/runs'/requested.relative_to(local)
        if requested.exists() or requested.is_symlink():
            raise FileExistsError(requested)
        actual.mkdir(parents=True,exist_ok=False)
        requested.parent.mkdir(parents=True,exist_ok=True)
        requested.symlink_to(actual.resolve(),target_is_directory=True)
    else:
        requested.mkdir(parents=True,exist_ok=False)
    return requested
