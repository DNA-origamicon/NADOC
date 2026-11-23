"""Native HC export/import preserves absolute molecular coordinates, without fitting."""

from copy import deepcopy
import json

import numpy as np
import pytest

from backend.api import crud, headless_build, state
from backend.api.routes_part_cadnano_import import _prepare
from backend.core.atomistic import build_atomistic_model
from backend.core.cadnano import export_cadnano
from backend.core.cadnano_roundtrip import KEY, has_roundtrip_metadata
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_cadnano_source import parse_source
from backend.core.part_input_sources import describe


@pytest.fixture(params=[(42, [[4, 6], [4, 7]], (0.0, 0.0)),
                        (-42, [[-4, -6], [-4, -5]], (1.234, -2.345))])
def native(request):
    """Use actual authoring routes and retain their feature log in memory."""
    with headless_build.scratch_session():
        length_bp, cells, shift = request.param
        crud.create_bundle(crud.BundleRequest(cells=cells,
            length_bp=length_bp, name="Native roundtrip", ligate_adjacent=False))
        if shift != (0.0, 0.0):
            for h in list(state.get_or_404().helices):
                crud.update_helix(h.id, crud.HelixRequest(length_bp=h.length_bp,
                    phase_offset=h.phase_offset,
                    axis_start=h.axis_start.model_copy(update={"x": h.axis_start.x + shift[0],
                                                              "y": h.axis_start.y + shift[1]}),
                    axis_end=h.axis_end.model_copy(update={"x": h.axis_end.x + shift[0],
                                                          "y": h.axis_end.y + shift[1]})))
        for strand in list(state.get_or_404().strands):
            length = sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)
            crud.update_strand(strand.id, crud.StrandRequest(
                domains=[d.model_dump(include={"helix_id", "start_bp", "end_bp", "direction"})
                         for d in strand.domains], strand_type=strand.strand_type,
                sequence=("ACGT" * ((length + 3) // 4))[:length]))
        yield state.get_or_404()


def _site_positions(design):
    cells = {h.id: h.grid_pos for h in design.helices}
    return {(cells[n["helix_id"]], n["bp_index"], n["direction"], n.get("copy_k", 0)):
            np.asarray([n["backbone_position"], n["base_position"]])
            for n in _geometry_for_design(design)}


def _atoms(design):
    cells = {h.id: h.grid_pos for h in design.helices}
    model = build_atomistic_model(design, fast_bridges=True)
    values = {(cells[a.helix_id], a.bp_index, a.direction, a.copy_k or 0, a.name, a.residue):
              np.asarray([a.x, a.y, a.z]) for a in model.atoms}
    assert len(values) == len(model.atoms)
    serial_keys = {a.serial: (cells[a.helix_id], a.bp_index, a.direction,
                            a.copy_k or 0, a.name, a.residue) for a in model.atoms}
    bonds = {frozenset((serial_keys[a], serial_keys[b])) for a, b in model.bonds}
    return values, bonds


def test_native_roundtrip_restores_origin_sequence_every_atom_and_bond(native):
    before = native.model_dump_json()
    source = export_cadnano(native)
    assert has_roundtrip_metadata(source)
    imported, _ = _prepare(json.dumps(source).encode(), None)
    assert imported.feature_log[0].params["importer_version"] == 3
    assert native.model_dump_json() == before
    assert sorted(s.sequence for s in imported.strands) == sorted(s.sequence for s in native.strands)
    assert sorted((h.grid_pos, h.bp_start, h.length_bp) for h in imported.helices) == sorted(
        (h.grid_pos, h.bp_start, h.length_bp) for h in native.helices)
    actual, expected = _site_positions(imported), _site_positions(native)
    assert actual.keys() == expected.keys()
    for key in actual:
        np.testing.assert_allclose(actual[key], expected[key], atol=1e-10, rtol=0)
    actual_atoms, actual_bonds = _atoms(imported)
    expected_atoms, expected_bonds = _atoms(native)
    assert actual_atoms.keys() == expected_atoms.keys()
    assert actual_bonds == expected_bonds
    for key in actual_atoms:
        np.testing.assert_allclose(actual_atoms[key], expected_atoms[key], atol=1e-10, rtol=0)


@pytest.mark.parametrize("mutation, match", [
    (lambda d: d[KEY].update(atoms=[]), "Extra inputs"),
    (lambda d: d[KEY].update(version=True), "version"),
    (lambda d: d[KEY].update(bp_offset=1), "21-bp register"),
    (lambda d: d[KEY]["helices"][0]["grid_pos"].__setitem__(0, 8), "translation"),
    (lambda d: d[KEY]["helices"][0].update(length_bp=2_049), "2048"),
    (lambda d: d[KEY]["sequences"][0].update(sequence="A"), "sequence length"),
    (lambda d: d["vstrands"][0].update(row=16), "source topology"),
])
def test_metadata_is_bounded_and_cannot_override_changed_source(native, mutation, match):
    data = deepcopy(export_cadnano(native))
    mutation(data)
    raw = json.dumps(data).encode()
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    with pytest.raises(ValueError, match=match):
        parse_source(raw, descriptor)


def test_standard_topology_remains_available_without_nadoc_extension(native):
    data = export_cadnano(native)
    data.pop(KEY)
    imported, _ = _prepare(json.dumps(data).encode(), None)
    assert not has_roundtrip_metadata(data)
    assert all(s.sequence is None for s in imported.strands)
    assert sorted(sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)
                  for s in imported.strands) == sorted(
        sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains) for s in native.strands)
