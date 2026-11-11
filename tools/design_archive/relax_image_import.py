"""Compatibility gate for pre-feature-history image-import callers.

Use shared_pipeline with a reviewed editor-operation recipe. A generated caDNAno
snapshot cannot substitute for the operations that constructed its topology.
"""
from experiments.recorded_review_process import ProcessRequired


def write_relaxed_image_import(cadnano, output):
    raise ProcessRequired(
        'Image-derived caDNAno has no native construction recipe. Use '
        'python -m tools.design_archive.shared_pipeline Dnnn RUN --recipe RECIPE.json --relax; '
        'no imported snapshot or history-free NADOC file was written.'
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('draft')
    parser.add_argument('output')
    parser.parse_args()
    try:
        write_relaxed_image_import(None, None)
    except ProcessRequired as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()
