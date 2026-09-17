"""Terminal annotations for the existing 5′ Biotin-TEG conjugate chemistry.

A modification is not a nucleotide: keep it outside Strand.sequence and the
pairing register. Strand identity, rather than helix identity, carries it through
antiparallel overhang relocation.
"""


def ensure_biotin_extensions(design):
    """Backfill missing annotations in memory; preserve explicit user extensions."""
    from backend.core.models import StrandExtension

    strand_ids = {s.id for s in design.strands}
    present = {(e.strand_id, e.end) for e in design.extensions}
    for particle in design.nanoparticles:
        for record in particle.biotin_dna:
            key = (record.strand_id, "five_prime")
            if record.strand_id not in strand_ids or key in present:
                continue
            design.extensions.append(
                StrandExtension(
                    id=f"__biotin_teg__{record.strand_id}",
                    strand_id=record.strand_id,
                    end="five_prime",
                    modification="biotin",
                    label="5′ Biotin-TEG",
                )
            )
            present.add(key)
    return design
