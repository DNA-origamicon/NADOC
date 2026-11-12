"""Compatibility entry point for the shared recorded rigidity/clearance workflow."""

from pathlib import Path


def run(folder):
    """Compatibility entry point; rejects legacy source histories before fitting."""
    from tools.design_archive.shared_pipeline import run as shared_run
    return shared_run(design_id='D003', run_id='recorded-rigidity',
                      source_part=Path(folder) / 'D003_imported.nadoc', relax=True)


if __name__ == '__main__':
    run(Path('workspace/Experimental/D003'))
