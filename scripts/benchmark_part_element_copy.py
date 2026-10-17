#!/usr/bin/env python3
"""Paired in-memory rigid-copy/atomic-recording/capture qualification fixtures.

Run under the shared validation guard. No files, simulations, routes or browser
state are created. Synthetic assets are benchmark inputs, not proof evidence;
independent native replay is covered by test_native_element_copy_proof.py.
"""

import argparse
import json
from statistics import median
from time import perf_counter

from backend.api import part_element_copy_commands as commands, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core import models as m
from backend.core.element_copy import paste_elements
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import CaptureLimit, capture


def fixture(*, protein_count=1, atom_count=12, particle_count=2, unrelated_helices=0, history_entries=0,
            unique_assets=False):
    assets = []
    for asset_index in range(protein_count if unique_assets else min(protein_count, 1)):
        atoms = [m.ProteinAtom(serial=index + 1, name="CA", element="C", res_name="ALA",
            chain_id="A", res_seq=index + 1, x=float(index % 10), y=float(index // 10 % 10),
            z=float(index // 100)) for index in range(atom_count)]
        assets.append(m.ProteinAsset(id=f"asset-{asset_index}", atoms=atoms,
            bonds=[(index, index + 1) for index in range(max(0, atom_count - 1))]))
    proteins = [m.ProteinAttachment(id=f"protein-{index}", asset_id=f"asset-{index if unique_assets else 0}",
        target=m.ProteinTargetFree(), conjugation_atom_serial=1) for index in range(protein_count)]
    particles = [m.Nanoparticle(id=f"gold-{index}", diameter_nm=10.0 + index) for index in range(particle_count)]
    helices = [m.Helix(id=f"unrelated-helix-{index}", length_bp=100,
        axis_start=m.Vec3(x=index * 3.0, y=0, z=0), axis_end=m.Vec3(x=index * 3.0, y=0, z=34))
        for index in range(unrelated_helices)]
    strands = [m.Strand(id=f"unrelated-strand-{index}", domains=[m.Domain(helix_id=helix.id,
        start_bp=0, end_bp=99, direction=m.Direction.FORWARD)]) for index, helix in enumerate(helices)]
    history = [m.SnapshotLogEntry(op_kind="strand-sequence", label="Unrelated recovery fixture",
        params={"strand_id": f"unrelated-strand-{index}", "sequence": "A"},
        design_snapshot_gz_b64="x" * 16_000, post_state_gz_b64="y" * 16_000) for index in range(history_entries)]
    design = m.Design(protein_assets=assets, protein_attachments=proteins, nanoparticles=particles,
                      helices=helices, strands=strands, feature_log=history)
    params = {"_proof_version": 1, "copy_version": 1,
        "protein_ids": [item.id for item in proteins], "protein_output_ids": [f"{item.id}-copy" for item in proteins],
        "nanoparticle_ids": [item.id for item in particles], "nanoparticle_output_ids": [f"{item.id}-copy" for item in particles],
        "paste_index": 1}
    return design, params


def timed(callback):
    start = perf_counter()
    value = callback()
    return value, (perf_counter() - start) * 1000


def stats(samples):
    return {"median_ms": median(samples), "max_ms": max(samples)} if samples else None


def normalized_legacy(design, params):
    result, _ = paste_elements(design, design, params["protein_ids"], params["nanoparticle_ids"], params["paste_index"])
    for item, identity in zip(result.protein_attachments[len(design.protein_attachments):], params["protein_output_ids"]):
        item.id = identity
    for item, identity in zip(result.nanoparticles[len(design.nanoparticles):], params["nanoparticle_output_ids"]):
        item.id = identity
    return result


def measure(name, options, repeats):
    design, params = fixture(**options)
    # Exclude one-time imports/compilation from paired warm measurements.
    expected = normalized_legacy(design, params)
    actual = commands.build("element-paste", design, params)
    equal = expected.model_dump(include=AUTHORING_FIELDS) == actual.model_dump(include=AUTHORING_FIELDS)
    legacy_times, native_times, capture_times, recording_times, captured = [], [], [], [], []
    token = set_current_doc("__benchmark_part_element_copy__")
    try:
        for iteration in range(repeats):
            # Alternate order to reduce systematic cache/thermal bias.
            callbacks = [("legacy", lambda: normalized_legacy(design, params)),
                         ("native", lambda: commands.build("element-paste", design, params))]
            for family, callback in callbacks[::1 if iteration % 2 == 0 else -1]:
                candidate, elapsed = timed(callback)
                (legacy_times if family == "legacy" else native_times).append(elapsed)
                if family == "native":
                    actual = candidate
            recorded = actual.copy_with(feature_log=[*design.feature_log, m.SnapshotLogEntry(
                op_kind="element-paste", label="Copy", params=params,
                design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")])
            started = perf_counter()
            try:
                capture(recorded)
                captured.append("captured")
            except CaptureLimit as error:
                captured.append(str(error))
            capture_times.append((perf_counter() - started) * 1000)
            # Session recording owns/mutates its history. Isolate fixture reset
            # outside the timing so repeated runs use identical input headers.
            state.load_design(design.model_copy(deep=True))
            _, elapsed = timed(lambda: state.mutate_with_feature_log("element-paste", "Copy rigid elements", params,
                lambda current: commands.build("element-paste", current, params)))
            recording_times.append(elapsed)
    finally:
        state.close_session()
        reset_current_doc(token)
    return {"name": name, "fixture": options, "selected_elements": len(params["protein_ids"]) + len(params["nanoparticle_ids"]),
        "protein_atoms_transformed": len(params["protein_ids"]) * options.get("atom_count", 12),
        "complete_authoring_equal": equal, "legacy_copy": stats(legacy_times), "native_copy": stats(native_times),
        "atomic_native_recording": stats(recording_times), "capture": stats(capture_times), "capture_results": captured}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("repeats must be in 1–20")
    cases = [
        ("small_mixed", {}),
        ("small_mixed_large_unrelated", {"unrelated_helices": 64, "history_entries": 100}),
        ("particle_batch_boundary", {"protein_count": 0, "particle_count": commands.MAX_ELEMENTS}),
        ("shared_asset_boundary", {"protein_count": commands.MAX_ATOM_WORK // 1000, "atom_count": 1000, "particle_count": 0}),
        ("distinct_asset_boundary", {"protein_count": commands.MAX_ATOM_WORK // 1000, "atom_count": 1000,
                                     "particle_count": 0, "unique_assets": True}),
        ("many_small_shared_placements", {"protein_count": commands.MAX_ELEMENTS,
                                         "atom_count": commands.MAX_ATOM_WORK // commands.MAX_ELEMENTS, "particle_count": 0}),
    ]
    rows = [measure(name, settings, args.repeats) for name, settings in cases]
    print(json.dumps({"scope": "warm copy, atomic in-memory recording and bounded capture; excludes HTTP, rendering, proof and scientific validity",
        "repeats": args.repeats, "capture_limits_unchanged": True,
        "candidate_admission_provisional": True, "max_atom_work": commands.MAX_ATOM_WORK, "cases": rows}, indent=2))
    return int(not all(row["complete_authoring_equal"] for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
