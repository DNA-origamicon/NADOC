from types import SimpleNamespace

from backend.api.routes_display_geometry import SurfaceRegionRequest, build_region_surface


def test_exact_surface_membership_excludes_complement_and_loop_copy(monkeypatch):
    import backend.core.atomistic as atomistic
    import backend.core.surface as surface
    import backend.api.routes_display_geometry as routes

    atoms = [SimpleNamespace(helix_id="h", bp_index=4, direction=direction, copy_k=copy)
             for direction, copy in [("FORWARD", 0), ("REVERSE", 0), ("FORWARD", 1)]]
    monkeypatch.setattr(atomistic, "build_atomistic_model", lambda *a, **kw: SimpleNamespace(atoms=atoms))
    monkeypatch.setattr(routes, "_flexible_display_override", lambda _: None)
    seen = []
    monkeypatch.setattr(surface, "compute_surface", lambda atoms, **kw: seen.extend(atoms) or "mesh")
    monkeypatch.setattr(surface, "smooth_mesh", lambda mesh, **kw: mesh)
    monkeypatch.setattr(surface, "surface_to_json", lambda *a, **kw: {})
    request = SurfaceRegionRequest(segments=[{"helix_id": "h", "bp_start": 4, "bp_end": 4}], nucleotide_keys=["h:4:FORWARD"])
    build_region_surface(object(), request)
    assert seen == [atoms[0]]
    seen.clear()
    request.nucleotide_keys = ["h:4:FORWARD:1"]
    build_region_surface(object(), request)
    assert seen == [atoms[2]]
    seen.clear()
    request.nucleotide_keys = None
    build_region_surface(object(), request)
    assert seen == atoms
