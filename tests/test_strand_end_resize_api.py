from backend.api import state as design_state
from backend.api.main import app
from backend.api.crud import StrandEndResizeEntry, StrandEndResizeRequest, strand_end_resize
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Design, Direction, Domain, Helix, LatticeType, Strand, StrandType, Vec3


def setup_function():
    design_state.clear_history()


def teardown_function():
    design_state.clear_history()


def _single_helix_design() -> Design:
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=50 * BDNA_RISE_PER_BP),
        length_bp=50,
        bp_start=0,
    )
    scaffold = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
    )
    staple = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=5, end_bp=35, direction=Direction.FORWARD)],
    )
    return Design(helices=[helix], strands=[scaffold, staple], lattice_type=LatticeType.HONEYCOMB)


def test_strand_end_resize_route_returns_geometry_and_axes():
    design_state.set_design(_single_helix_design())

    registered_methods = {
        method
        for route in app.routes
        if getattr(route, "path", None) == "/api/design/strand-end-resize"
        for method in getattr(route, "methods", set())
    }
    assert "POST" in registered_methods

    body = strand_end_resize(StrandEndResizeRequest(entries=[
        StrandEndResizeEntry(strand_id="stap", helix_id="h0", end="3p", delta_bp=10),
    ]))
    assert body["design"]["strands"]
    assert body["nucleotides"]
    assert body["helix_axes"]
    staple = next(s for s in body["design"]["strands"] if s["id"] == "stap")
    assert staple["domains"][-1]["end_bp"] == 45
