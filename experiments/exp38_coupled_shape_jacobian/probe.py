"""exp38 G1 grounding probe: does a per-helix skip change move BOTH twist AND bend on a honeycomb
bend design?  If yes (coupling), the coupled 2xH authority Jacobian is real and worth solving."""
import time
from backend.api import headless_build as hb
from backend.api import state as ds
from backend.core.models import LatticeType
from backend.core import cando_autorefine as car
from backend.physics.fem_solver import predict_shape
from backend.core.cando_deviation import compute_deviation
from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_arc_bend

HC = LatticeType.HONEYCOMB
SIX_HB = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
LEN = 210
BEND = 60.0   # programmed bend (deg) over the length


def build(realize=True):
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        hb.add_bend(0, LEN, curvature_deg_per_bp=BEND / LEN)
        if realize:
            hb.apply_loop_skip_deformations()
        return ds.get_or_404().model_copy(deep=True)


def measure(design, marks=None):
    d = car.apply_marks(design, marks) if marks is not None else design
    shape = predict_shape(d, nonlinear=False, with_rmsf=False)
    ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
    core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
    tw = measure_bundle_twist(core)
    try:
        bd = float(measure_bundle_arc_bend(core))
    except Exception:
        bd = None
    dev = compute_deviation(d, shape["positions"])
    return tw, bd, dev["rmsd_nm"]


d = build(realize=True)
n_marks = sum(len(h.loop_skips) for h in d.helices)
print(f"6HB honeycomb, {len(d.helices)} helices, {LEN}bp, bend {BEND}°, realized marks={n_marks}")

# intended (target) twist/bend
shape0 = predict_shape(d, nonlinear=False, with_rmsf=False)
ck = car._core_keys(shape0)
tgt = car.target_metrics(d, ck)
print(f"INTENDED twist={tgt['twist_deg']}, bend={tgt['bend_deg']}")

tw0, bd0, rmsd0 = measure(d)
print(f"BASELINE FEM: twist={tw0:.2f} bend={bd0:.2f} rmsd={rmsd0:.3f}")

# per-helix coupling probe: add ONE skip on each helix (mid-interior), measure Δtwist AND Δbend
base_marks = car.current_marks_by_helix(d)
forb, _ = car._forbidden_bps(d)
helix_by_id = {h.id: h for h in d.helices}
print("\nper-helix single-skip authority (Δtwist, Δbend):")
for h in d.helices:
    free = car.free_interior_candidates(d, h, forb[h.id])
    if not free:
        continue
    bp = free[len(free) // 2]
    m = {hid: dict(bps) for hid, bps in base_marks.items()}
    m.setdefault(h.id, {})[bp] = -1
    tw, bd, rmsd = measure(d, m)
    print(f"  {h.id:12s} +1 skip@{bp:3d}: Δtwist={tw-tw0:+.3f}  Δbend={(bd-bd0 if bd and bd0 else 0):+.3f}")
