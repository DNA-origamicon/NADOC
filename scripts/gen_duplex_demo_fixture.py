"""Generate the Playwright fixture for the Duplex-graph visible test.

Builds a small renderable design (two overhang helices) where overhang A (6 bp)
is bound to overhang B (4 bp) over a 4 bp window — leaving a 2 bp TOEHOLD on A.
The design carries a legacy ``OverhangBinding`` (no ``duplexes``); on load the
``_derive_duplexes_if_empty`` bridge turns it into the register-bearing graph, so
the UI colours A as 4 bp paired + 2 bp toehold.

Run once:  python scripts/gen_duplex_demo_fixture.py
Writes:    workspace/playwright_tests/duplex_demo.nadoc
"""
from __future__ import annotations

import os

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangBinding, OverhangSpec, Strand,
    StrandType, SubDomain, Vec3,
)

OUT = "/home/joshua/NADOC/workspace/playwright_tests/duplex_demo.nadoc"


def build() -> Design:
    hA = Helix(id="oh_helix_a", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
               axis_end=Vec3(x=0.0, y=0.0, z=6 * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=6, grid_pos=(0, 0))
    hB = Helix(id="oh_helix_b", axis_start=Vec3(x=2.5, y=0.0, z=0.0),
               axis_end=Vec3(x=2.5, y=0.0, z=4 * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=4, grid_pos=(0, 1))
    sA = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="oh_helix_a", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="oh_a")])
    sB = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="oh_helix_b", start_bp=3, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="oh_b")])
    # A: 4 bp bound sub-domain "AAAC" + 2 bp toehold "GG".
    ohA = OverhangSpec(id="oh_a", helix_id="oh_helix_a", strand_id="st_a",
                       label="OH-A", sequence="AAACGG",
                       sub_domains=[
                           SubDomain(id="sdA1", name="a", start_bp_offset=0, length_bp=4,
                                     sequence_override="AAAC"),
                           SubDomain(id="sdA2", name="t", start_bp_offset=4, length_bp=2,
                                     sequence_override="GG"),
                       ])
    # B: 4 bp, RC of A's bound window (RC(AAAC)=GTTT).
    ohB = OverhangSpec(id="oh_b", helix_id="oh_helix_b", strand_id="st_b",
                       label="OH-B", sequence="GTTT",
                       sub_domains=[SubDomain(id="sdB", name="b", start_bp_offset=0,
                                              length_bp=4, sequence_override="GTTT")])
    binding = OverhangBinding(name="B1", sub_domain_a_id="sdA1", sub_domain_b_id="sdB",
                              overhang_a_id="oh_a", overhang_b_id="oh_b")
    return Design(helices=[hA, hB], strands=[sA, sB], overhangs=[ohA, ohB],
                  overhang_bindings=[binding])


def _verify_survives_load(design: Design) -> None:
    """Run the same helpers /design/load does and assert the derived duplex +
    toehold survive."""
    from backend.core.lattice import autodetect_all_overhangs
    from backend.api.crud import _backfill_sub_domains_if_empty, _derive_duplexes_if_empty
    from backend.core.duplex import overhang_pairing_map
    d = autodetect_all_overhangs(design)
    d = _backfill_sub_domains_if_empty(d)
    d = _derive_duplexes_if_empty(d)
    assert len(d.duplexes) == 1, f"expected 1 duplex, got {len(d.duplexes)}"
    cov = list(overhang_pairing_map(d, "oh_a").values())
    assert cov.count("paired") == 4 and cov.count("unpaired") == 2, cov
    print(f"verified: 1 duplex, oh_a coverage paired=4 toehold=2 ({cov})")


def main() -> None:
    design = build()
    _verify_survives_load(design)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(design.model_dump_json())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
