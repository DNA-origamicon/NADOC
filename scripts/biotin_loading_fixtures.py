"""Generate matched designs for the browser atomistic-loading benchmark."""
from pathlib import Path
import numpy as np
from backend.core.gold_strep_dna import build_dna_set
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating


def write_fixtures(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    particle = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(10, count_override=3))
    placed = build_dna_set(particle, 'ACGTACGT', dna_per_strep=2, linker_nm=1.8)
    particle.biotin_dna = [r for r, _, _ in placed]
    design = Design(nanoparticles=[particle], helices=[h for _, h, _ in placed], strands=[s for _, _, s in placed])
    design.metadata.name = '__e2e__coated_perf'
    (directory / 'coated.nadoc').write_text(design.to_json())
    regular = design.model_copy(deep=True)
    regular.nanoparticles = []; regular.metadata.name = '__e2e__same_dna_perf'
    (directory / 'dna_same.nadoc').write_text(regular.to_json())
    for helix, strand in zip(regular.helices, regular.strands):
        start = helix.axis_start.to_array()
        axis = helix.axis_end.to_array() - start; axis /= np.linalg.norm(axis)
        helix.length_bp = 96
        helix.axis_end.x, helix.axis_end.y, helix.axis_end.z = (start + axis * .334 * 95).tolist()
        strand.domains[0].end_bp = 95; strand.sequence = 'ACGT' * 24
    regular.metadata.name = '__e2e__equal_atoms_perf'
    (directory / 'dna_equal.nadoc').write_text(regular.to_json())


if __name__ == '__main__':
    import sys
    write_fixtures(sys.argv[1])
