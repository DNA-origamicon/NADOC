#!/usr/bin/env python3
"""Headless steric-aware relaxation of saved CPDs; writes a separate design copy.

PYTHONPATH=. .venv/bin/python scripts/relax_cpd_design.py INPUT.nadoc --output OUTPUT.nadoc
"""

import argparse
import json
from pathlib import Path
from backend.core.models import Design
from backend.core.cpd_design import relax_existing_cpd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Use a separate output path to preserve the source design.")
    if args.report and args.report.resolve() in {
        args.input.resolve(),
        args.output.resolve(),
    }:
        parser.error("The report path must differ from both design paths.")
    design = Design.from_json(args.input.read_text())
    reports = []
    for lesion in design.photoproduct_junctions:
        if lesion.design_coordinates:
            design, report = relax_existing_cpd(design, lesion.id)
            reports.append({"photoproduct_id": lesion.id, **report})
    if not reports:
        parser.error("No converted CPDs found in the input design.")
    # The output is a new authored snapshot; old replay snapshots describe the
    # unrelaxed design and must not masquerade as its editing history.
    design = design.copy_with(
        feature_log=[], feature_log_cursor=-1, feature_log_sub_cursor=None
    )
    args.output.write_text(design.to_json())
    summary = json.dumps(
        {"input": str(args.input), "output": str(args.output), "products": reports},
        indent=2,
    )
    if args.report:
        args.report.write_text(summary + "\n")
    print(summary)


if __name__ == "__main__":
    main()
