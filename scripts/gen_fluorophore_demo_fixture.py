"""Generate the Playwright fixture for the fluorophore view-toggle test.

A tiny renderable design: one staple strand with a Cy3 fluorophore extension on its
3' end. Toggling View ▸ Fluorescence should glow it.

Run once:  PYTHONPATH=. python scripts/gen_fluorophore_demo_fixture.py
Writes:    workspace/playwright_tests/fluorophore_demo.nadoc
"""
from __future__ import annotations

import os

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, Direction, Domain, Helix, Strand, StrandExtension, StrandType, Vec3,
)

OUT = "/home/joshua/NADOC/workspace/playwright_tests/fluorophore_demo.nadoc"


def build() -> Design:
    L = 16
    h = Helix(id="hA", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
              axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
              phase_offset=0.0, length_bp=L, grid_pos=(0, 0))
    st = Strand(id="st", strand_type=StrandType.STAPLE, sequence="ACGTACGTACGTACGT",
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=L - 1,
                                direction=Direction.FORWARD)])
    ext = StrandExtension(strand_id="st", end="three_prime", modification="cy3", label="Cy3")
    return Design(helices=[h], strands=[st], extensions=[ext])


def main() -> None:
    design = build()
    assert design.extensions[0].modification == "cy3"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(design.model_dump_json())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
