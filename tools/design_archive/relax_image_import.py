"""Optional rigid-body relaxation of a reviewed image-derived caDNAno draft.

Usage: python -m tools.design_archive.relax_image_import REGISTERED.json OUTPUT_DIR
The source draft and its topology/provenance are preserved.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from backend.core.cadnano import import_cadnano
from backend.core.cluster_autodetect import _autodetect_clusters
from backend.core.conversion_integrity import require_import_integrity
from backend.core.import_relaxation import relax_imported_design


def write_relaxed_image_import(cadnano, output):
    output = Path(output)
    names = ("image_imported.nadoc", "image_relaxed.nadoc", "image_relaxation.json")
    for name in names:
        if (output / name).exists():
            raise FileExistsError(f"Refusing to replace {output / name}")
    design, warnings = import_cadnano(cadnano)
    require_import_integrity(design)
    design = _autodetect_clusters(design)
    relaxed, report = relax_imported_design(design, enabled=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / names[0]).write_text(design.to_json())
    if report["status"] == "applied":
        relaxed = relaxed.model_copy(
            update={
                "id": str(uuid4()),
                "metadata": relaxed.metadata.model_copy(
                    update={"name": design.metadata.name + " — relaxed image import"}
                ),
            }
        )
        (output / names[1]).write_text(relaxed.to_json())
    (output / names[2]).write_text(
        json.dumps(
            {
                "source": "reviewed image-derived caDNAno",
                "import_warnings": warnings,
                "relaxation": report,
                "imported_file": names[0],
                "relaxed_file": names[1] if report["status"] == "applied" else None,
            },
            indent=2,
        )
        + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            write_relaxed_image_import(json.loads(args.draft.read_text()), args.output),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
