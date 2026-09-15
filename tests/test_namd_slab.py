import subprocess
import shutil
import pytest
from backend.core.namd_slab import slab_energy_forces, render_slab_tcl


@pytest.mark.parametrize('axis', [0, 1, 2])
def test_slab_force_is_negative_energy_gradient_and_translation_invariant(axis):
    positions = [[2., 4., 6.], [9., 7., 3.]]
    charges = [1., -1.]
    cell = [30., 40., 90.]
    energy, forces = slab_energy_forces(positions, charges, cell, axis)
    h = 1e-5
    for i in range(2):
        positions[i][axis] += h
        plus = slab_energy_forces(positions, charges, cell, axis)[0]
        positions[i][axis] -= 2*h
        minus = slab_energy_forces(positions, charges, cell, axis)[0]
        positions[i][axis] += h
        assert forces[i][axis] == pytest.approx(-(plus-minus)/(2*h), abs=1e-8)
    shifted = [[v+123 for v in p] for p in positions]
    assert slab_energy_forces(shifted, charges, cell, axis)[0] == pytest.approx(energy)
    assert sum(f[axis] for f in forces) == pytest.approx(0)
    with pytest.raises(ValueError, match='neutrality'):
        slab_energy_forces(positions, [1., 0.], cell, axis)


def test_generated_tcl_matches_reference_energy_and_confinement(tmp_path):
    if not shutil.which('tclsh'):
        pytest.skip('tclsh unavailable')
    script = render_slab_tcl([1., -1.], [30., 40., 90.], mobile_ids=[1], bounds=(10., 30.))
    harness = '''proc addatom {id} {}
set energy 0.0
array set forces {1 {0 0 0} 2 {0 0 0}}
proc loadcoords {name} {upvar 1 $name xyz; array set xyz {1 {2 4 9} 2 {9 7 20}}}
proc addenergy {e} {global energy; set energy [expr {$energy+$e}]}
proc addforce {id f} {global forces; set forces($id) [lmap a $forces($id) b $f {expr {$a+$b}}]}
'''
    path = tmp_path / 'probe.tcl'
    path.write_text(harness+script+'\ncalcforces\nputs "$energy [lindex $forces(1) 2] [lindex $forces(2) 2]"\n')
    result = subprocess.run(['tclsh', str(path)], capture_output=True, text=True, check=True)
    actual = list(map(float, result.stdout.split()))
    energy, forces = slab_energy_forces([[2,4,9],[9,7,20]], [1.,-1.], [30.,40.,90.])
    assert actual == pytest.approx([energy+5,forces[0][2]+10,forces[1][2]])


def test_native_force_reader_rejects_truncated_and_nonfinite_output(tmp_path):
    import struct
    from experiments.two_electrodes.qualify import read_force
    path = tmp_path/'probe.force'
    path.write_bytes(struct.pack('<i3d',1,1.,2.,3.))
    assert read_force(path,1).tolist() == [[1.,2.,3.]]
    with pytest.raises(ValueError,match='format'):
        read_force(path,2)
    path.write_bytes(struct.pack('<i3d',1,1.,float('nan'),3.))
    with pytest.raises(ValueError,match='Nonfinite'):
        read_force(path,1)
