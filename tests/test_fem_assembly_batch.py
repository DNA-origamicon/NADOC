"""Assembly preserves energy, shared-node addition, and the editable sparse API."""

import numpy as np
import pytest
from scipy.sparse import lil_matrix
from backend.physics import fem_solver as fem


@pytest.mark.parametrize("material", ["cando", "snupi"])
@pytest.mark.parametrize("registered,diagonal", [(False, False), (True, True)])
def test_assembly_superposition(material, registered, diagonal):
    nodes = [fem.FEMNode("h", i, np.array([0.0, 0.0, i * 0.34])) for i in range(4)]
    mesh = fem.FEMMesh(
        nodes=nodes,
        elements=[
            fem.FEMElement(i, i + 1, 0.34, np.eye(3), R_bp=np.eye(3)) for i in range(3)
        ],
        springs=[fem.FEMSpring(0, 2, 3.0, 0.0), fem.FEMSpring(0, 2, 7.0, 2.0)],
        rigid_links=[fem.FEMRigidLink(1, 3, np.array([2.0, 0.5, 0.1]))],
    )
    kwargs = dict(
        material=material, bp_registered_frame=registered, diagonal_material=diagonal
    )
    expected = np.zeros((24, 24))
    # Independent scatter of two-node matrices, including repeated contributions
    # at the same global entry and nonadjacent node indices.
    for field in ["elements", "springs", "rigid_links"]:
        for component in getattr(mesh, field):
            from dataclasses import replace

            pair = replace(component, node_i=0, node_j=1)
            local = fem.FEMMesh(nodes=nodes[:2], **{field: [pair]})
            block, _ = fem.assemble_global_stiffness(local, **kwargs)
            dofs = list(range(6 * component.node_i, 6 * component.node_i + 6)) + list(
                range(6 * component.node_j, 6 * component.node_j + 6)
            )
            expected[np.ix_(dofs, dofs)] += block.toarray()
    matrix, force = fem.assemble_global_stiffness(mesh, **kwargs)
    assert isinstance(matrix, lil_matrix)
    np.testing.assert_allclose(matrix.toarray(), expected, rtol=1e-14, atol=1e-9)
    np.testing.assert_array_equal(force, np.zeros(24))
    displacement = np.random.default_rng(42).normal(size=24)
    assert displacement @ matrix @ displacement == pytest.approx(
        displacement @ expected @ displacement, rel=1e-14
    )


def test_empty_assembly():
    matrix, force = fem.assemble_global_stiffness(fem.FEMMesh())
    assert matrix.shape == (0, 0)
    assert force.shape == (0,)
