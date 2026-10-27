from pathlib import Path
import json
import pytest

from backend.physics.oxdna_attachments import (
    inherit_attachments, compose_stage_forces, molecular_blocks,
)


def spring(a, b):
    return f"{{\ntype = mutual_trap\nparticle = {a}\nref_particle = {b}\nstiff = 1.424\nr0 = 1.071\n}}\n"


def test_inheritance_and_rewritten_stages_preserve_only_molecular_springs(tmp_path):
    parent, child = tmp_path / 'parent', tmp_path / 'child'
    parent.mkdir(); child.mkdir()
    for directory in (parent, child):
        (directory / 'topology.top').write_text('4 2 2 2 1\n')
    molecular = spring(0, 2) + spring(2, 0)
    relaxation = spring(2, 3) + spring(3, 2)
    (parent / 'equil_forces.txt').write_text(molecular + '{\ntype = trap\nparticle = 0\n}\n')
    (parent / 'forces.txt').write_text(molecular + relaxation)
    inherit_attachments(parent, child)
    for name in ('gentle', 'approach', 'retry', 'settle', 'equil', 'production'):
        stage = child / name; stage.mkdir()
        protocol = child / 'protocol.txt'
        protocol.write_text('{\ntype = repulsion_plane\nparticle = -1\n}\n')
        output = compose_stage_forces(child, stage, protocol)
        assert output.read_text().count('mutual_trap') == 2
        assert 'type = trap' not in output.read_text()
        assert molecular_blocks(output.read_text(), child).keys() == {(0, 2), (2, 0)}
        assert 'mutual_trap' not in protocol.read_text()
    # Existing relaxation forces must not double the physical spring.
    out = compose_stage_forces(parent, parent, parent / 'forces.txt')
    assert out.read_text().count('mutual_trap') == 4
    assert compose_stage_forces(child, child, None).read_text().count('mutual_trap') == 2


def test_inheritance_rejects_changed_topology_and_asymmetric_spring(tmp_path):
    parent, child = tmp_path / 'p', tmp_path / 'c'
    parent.mkdir(); child.mkdir()
    (parent / 'topology.top').write_text('4 2 2 2 1\n')
    (child / 'topology.top').write_text('5 2 3 2 1\n')
    (parent / 'equil_forces.txt').write_text(spring(0, 2))
    with pytest.raises(ValueError, match='reciprocal'):
        inherit_attachments(parent, child)
    (parent / 'equil_forces.txt').write_text(spring(0, 2) + spring(2, 0))
    with pytest.raises(ValueError, match='different particle'):
        inherit_attachments(parent, child)


def test_legacy_child_recovers_frozen_ancestor_on_copy_only(tmp_path):
    for name in ('parent', 'old', 'new'):
        directory = tmp_path / name; directory.mkdir()
        (directory / 'topology.top').write_text('4 2 2 2 1\n')
    (tmp_path / 'parent/equil_forces.txt').write_text(spring(0, 2) + spring(2, 0))
    (tmp_path / 'old/job.json').write_text(json.dumps({'parent_job_id': 'parent'}))
    inherit_attachments(tmp_path / 'old', tmp_path / 'new')
    assert 'mutual_trap' in (tmp_path / 'new/attachment_forces.txt').read_text()
    assert not (tmp_path / 'old/attachment_forces.txt').exists()
