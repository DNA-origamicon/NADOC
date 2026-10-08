"""Optional isolated Exp transport for the connectivity candidate.

Loading this adapter does not replace the installed baseline or modify native
geometry. Promotion is separate from building/evaluating this candidate.
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from backend.core.exp_atomistic import native_atoms, full_frame
from backend.core.exp_local import SCHEMA, prepare, predict, geometry

MODEL_PATH = Path(__file__).resolve().parents[1] / "data/exp/local_rigid_v1.json"


def load_adapter(path=MODEL_PATH):
    if not path.exists():
        return None, None
    model = json.loads(path.read_text())
    if model["schema"] != SCHEMA:
        raise ValueError("Unsupported connectivity predictor schema")

    def run(design, progress, cancel):
        progress(0.05, "Building all DNA atoms and covalent connectivity")
        native = native_atoms(design, include_bonds=True)
        if cancel.is_set():
            raise InterruptedError("Prediction stopped")
        progress(0.25, "Encoding nucleotide neighborhoods")
        data = prepare(native, native["bonds"])
        progress(0.45, "Predicting local geometry and applying constraints")
        if model.get("geometry_schema") == "rigid-bond-angle-v2":
            from backend.core.exp_local_constraints import project

            raw, _, details = predict(
                data, model, constrain=False, cancel=cancel.is_set
            )
            xyz, projection = project(
                data,
                raw,
                native["angle_indices"],
                native["angle_cos"],
                cancel=cancel.is_set,
            )
            details["projection"] = projection
        else:
            xyz, _, details = predict(data, model, cancel=cancel.is_set)
        progress(0.9, "Deriving Full display from all predicted atoms")
        frame = full_frame(
            xyz, native["names"], native["residue_index"], native["keys"]
        )
        audit = geometry(data, xyz)
        label = "Connectivity candidate: rigid nucleotide reconstruction, soft geometric constraints; not seed-qualified"
        if any(c.extra_bases for c in design.crossovers):
            label += "; extra bases outside training coverage"
        return dict(
            positions_nm=xyz.tolist(),
            label=label,
            atoms=dict(
                names=native["names"],
                elements=native["elements"],
                residue_index=np.asarray(native["residue_index"]).tolist(),
                keys=native["keys"],
                includes_hydrogens=True,
            ),
            full=dict(keys=native["keys"], frame=frame),
            diagnostics=dict(prediction=details, geometry=audit),
        )

    return run, model["model_card"]
