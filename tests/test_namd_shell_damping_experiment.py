"""Scientific pilot plumbing: boundary support and rigid-body-invariant analysis."""

import numpy as np
import json
from backend.core.namd_submodel import crop_topology, sections
from experiments.namd_submodel_damping.run import boundary_atoms
from tests.test_namd_submodel import toy_topology, BOX


def test_mobile_buffer_never_touches_a_cut_bonded_term():
    full = toy_topology()
    _, receipt = crop_topology(full, BOX)
    frozen = set(boundary_atoms(full.psf_text, receipt))
    retained = receipt["retained_source_indices"]
    mobile_source = {
        source + 1 for output, source in enumerate(retained) if output not in frozen
    }
    assert mobile_source
    assert not frozen.intersection(receipt["mobile_output_indices"])
    source = sections(full.psf_text)
    for key, arity in [("NBOND", 2), ("NPHI", 4)]:
        flat = list(map(int, " ".join(source[key][1]).split()))
        for i in range(0, len(flat), arity):
            term = set(flat[i : i + arity])
            if term.intersection(mobile_source):
                assert term <= {index + 1 for index in retained}


def test_core_alignment_removes_rotation_but_preserves_internal_motion():
    from experiments.namd_submodel_damping.analyze import aligned

    reference = np.array(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 3.0]]
    )
    rotation = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    moved = reference @ rotation + 7
    np.testing.assert_allclose(
        aligned(moved, reference), reference - reference.mean(0), atol=1e-12
    )
    moved[0, 0] += 1
    assert (
        np.linalg.norm(aligned(moved, reference) - (reference - reference.mean(0)))
        > 0.1
    )


def test_native_trial_inputs_separate_global_and_per_atom_thermostats(
    tmp_path, monkeypatch
):
    from experiments.namd_submodel_damping import run

    packages = {}
    for kind in ("crop", "full"):
        package = tmp_path / kind
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({"box_ang": [100, 100, 100]}))
        packages[kind] = {"package": str(package), "stem": "trial"}
    inputs = {}
    monkeypatch.setattr(
        run,
        "run_native",
        lambda binary, pkg, name, root: inputs.update(
            {name: (pkg / (name + ".conf")).read_text()}
        ),
    )
    run.run_production(tmp_path, "unused", 12500, packages)
    assert len(inputs) == 10
    for name, text in inputs.items():
        directives = dict(
            line.split(None, 1)
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        )
        assert directives["temperature"] == "300"
        assert "binVelocities" not in directives
        assert directives["timestep"].strip() == "4"
        assert directives["structure"].endswith("_hmr.psf")
        if name.startswith("gamma_"):
            assert "langevinFile" in directives
            assert "langevinDamping" not in directives
            assert "langevinHydrogen" not in directives
        else:
            assert directives["langevinDamping"].strip() == "1"
            assert "langevinFile" not in directives
