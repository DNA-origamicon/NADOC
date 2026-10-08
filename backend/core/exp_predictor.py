"""Experimental screening inference lifecycle, independent of MD engines.

The installed adapter supplies ``predict`` and its model card. Lifecycle tests
inject deterministic adapters; they do not establish scientific accuracy.
Results are session-only physical previews in the input coordinate frame (nm).
The bundled 0xT pilot targets historical Na-neutralized production windows;
its model card records the ion-recipe limitation alongside its shape errors.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

import numpy as np


class ModelUnavailable(RuntimeError):
    pass


class ExpPredictor:
    def __init__(self, predict=None, model_card=None):
        self.predict = predict
        self.model_card = model_card
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exp-cpu")
        self._lock = Lock()
        self._jobs = {}

    def status(self):
        return {
            "available": self.predict is not None and self.model_card is not None,
            "model": self.model_card,
            "message": "No trained model installed. Training windows are being qualified."
            if self.predict is None
            else "Experimental screening model; see model limits.",
        }

    def start(self, owner, design):
        if not self.status()["available"]:
            raise ModelUnavailable(self.status()["message"])
        # Isolate all adapter work from the live topological model.
        snapshot = design.without_reference_geometry().model_copy(deep=True)
        with self._lock:
            # Only one CPU task at once; no unbounded queued snapshots.
            if any(j["status"] in {"running", "stopping"} for j in self._jobs.values()):
                raise RuntimeError("An Exp prediction is already running.")
            # One ephemeral result per document. A new run replaces its prior preview.
            self._jobs = {k: v for k, v in self._jobs.items() if v["owner"] != owner}
            job_id = uuid4().hex
            self._jobs[job_id] = dict(
                owner=owner,
                snapshot=snapshot,
                job_id=job_id,
                status="running",
                progress=0.0,
                message="Preparing prediction",
                result=None,
                cancel=Event(),
                model=self.model_card,
            )
        self._pool.submit(self._run, job_id, snapshot)
        return self.get(owner, job_id)

    def _run(self, job_id, snapshot):
        job = self._jobs[job_id]

        def progress(fraction, message):
            if job["cancel"].is_set():
                raise InterruptedError("Stopped")
            value = float(fraction)
            if not np.isfinite(value):
                raise ValueError("Non-finite progress")
            with self._lock:
                job.update(
                    progress=max(job["progress"], min(0.99, max(0.0, value))),
                    message=str(message),
                )

        try:
            result = self.predict(snapshot, progress, job["cancel"])
            positions = np.asarray(result["positions_nm"], dtype=float)
            if (
                positions.ndim != 2
                or positions.shape[1] != 3
                or not len(positions)
                or not np.isfinite(positions).all()
            ):
                raise ValueError("Predictor returned invalid positions")
            # Preserve all-atom identities and the atom-derived NAMD Full frame.
            # Deliberately no atomistic seed or topology-edit endpoint.
            if "atoms" in result or "full" in result:
                atoms, full = result["atoms"], result["full"]
                keys = atoms["keys"]
                residues = np.asarray(atoms["residue_index"])
                frame = np.asarray(full["frame"], dtype=float)
                if (
                    not keys
                    or full["keys"] != keys
                    or len(atoms["names"]) != len(positions)
                    or len(atoms["elements"]) != len(positions)
                    or residues.shape != (len(positions),)
                    or not np.issubdtype(residues.dtype, np.integer)
                    or np.any(residues < 0)
                    or np.any(residues >= len(keys))
                    or frame.shape != (12 * len(keys),)
                    or not np.isfinite(frame).all()
                ):
                    raise ValueError(
                        "Predictor returned invalid atom identities or Full frame"
                    )
                result = {
                    "positions_nm": positions.tolist(),
                    "label": str(result["label"]),
                    "atoms": atoms,
                    "full": full,
                }
            else:
                result = {
                    "positions_nm": positions.tolist(),
                    "label": str(result["label"]),
                }
            with self._lock:
                if job["cancel"].is_set():
                    job.update(status="stopped", message="Stopped", result=None)
                else:
                    job.update(
                        status="completed",
                        progress=1.0,
                        message="Prediction complete",
                        result=result,
                    )
        except Exception as exc:
            with self._lock:
                stopped = job["cancel"].is_set() or isinstance(exc, InterruptedError)
                job.update(
                    status="stopped" if stopped else "failed",
                    message="Stopped" if stopped else str(exc),
                    result=None,
                )

    def get(self, owner, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["owner"] != owner:
                raise KeyError(job_id)
            return {
                k: v for k, v in job.items() if k not in {"owner", "cancel", "snapshot"}
            }

    def snapshot_geometry(self, owner, job_id):
        """Display-only Full model for assembly jobs, without replacing the document."""
        from backend.core.deformation import (
            _apply_ovhg_rotations_to_axes,
            deformed_helix_axes,
        )
        from backend.core.design_geometry import _geometry_for_helices

        self.get(owner, job_id)
        with self._lock:
            design = self._jobs[job_id]["snapshot"]
        nucleotides = _geometry_for_helices(design, None, junction_balance=True)
        axes = deformed_helix_axes(design)
        _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
        return {
            "design": design.model_dump(mode="json"),
            "nucleotides": nucleotides,
            "helix_axes": axes,
        }

    def stop(self, owner, job_id):
        self.get(owner, job_id)
        with self._lock:
            job = self._jobs[job_id]
            if job["status"] in {"running", "stopping"}:
                job["cancel"].set()
                job.update(status="stopping", message="Stopping…")
        return self.get(owner, job_id)


from backend.core.exp_atomistic import load_adapter  # noqa: E402

predictor = ExpPredictor(*load_adapter())
