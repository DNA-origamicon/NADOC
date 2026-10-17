#!/usr/bin/env python3
"""Memory-only coating admission evidence; run serially under the test guard.

Uses the existing native builders unchanged. No document session, simulation,
worker, source modification, cache file or artifact is written. The fixtures
are deliberately NOT recipe proofs. A larger capture profile is an experiment,
not a change to production limits or a recommendation to hold the UI lock longer.
"""

import argparse
import hashlib
import json
import pickle
from statistics import median
from time import perf_counter

from pydantic import BaseModel

from backend.api.state import encode_design_snapshot
from backend.core.models import Nanoparticle
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import CaptureLimit, capture
from backend.core.streptavidin import PDB_PATH, build_streptavidin_coating, streptavidin_asset


PROSPECTIVE = {"max_nodes": 100_000, "max_bytes": 4_000_000, "seconds": 0.100}


def timed(callback):
    started = perf_counter()
    value = callback()
    return value, (perf_counter() - started) * 1000


def walk_charge(value):
    """Same node/string accounting as capture, without admission or copying.

    String charge is the conservative UTF-8 allowance, not Python heap size.
    These bounded fixtures have no history entries or recovery payload fields.
    """
    pending, seen, nodes, byte_charge = [value], set(), 0, 0
    while pending:
        item = pending.pop()
        nodes += 1
        if isinstance(item, str):
            byte_charge += 4 * len(item)
        elif isinstance(item, (BaseModel, dict, list, tuple)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, BaseModel):
                pending.extend(item.__dict__.values())
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            else:
                pending.extend(item)
    return {"nodes": nodes, "string_byte_charge": byte_charge}


def charges(design):
    fields = {name: walk_charge(getattr(design, name))
              for name, role in FIELD_ROLES.items()
              if role not in {"presentation", "physical", "history"}}
    fields["recipe_root"] = walk_charge(design.recipe_root)
    return {"total": {key: sum(value[key] for value in fields.values())
                       for key in ("nodes", "string_byte_charge")},
            "authoring": {key: sum(value[key] for name, value in fields.items()
                                   if FIELD_ROLES.get(name) == "authoring")
                          for key in ("nodes", "string_byte_charge")},
            "input_sources": fields["input_sources"]}


def capture_profile(design, repeats, **limits):
    samples, statuses, sizes = [], [], []
    for _ in range(repeats):
        started = perf_counter()
        try:
            isolated = capture(design, **limits)
        except CaptureLimit as exc:
            samples.append((perf_counter() - started) * 1000)
            statuses.append({"status": "capture_limit", "detail": str(exc)})
        else:
            samples.append((perf_counter() - started) * 1000)
            statuses.append({"status": "captured_not_verified"})
            sizes.append(len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL)))
    return {"median_ms": median(samples), "max_ms": max(samples), "statuses": statuses,
            "admitted_pickle_bytes_max": max(sizes) if sizes else None,
            "admitted_pickle_fits_existing_2MB_worker": max(sizes) <= 2_000_000 if sizes else None}


def source_inputs():
    blobs, rows = {}, []
    for name in ("1STP-assembly1.pdb", "streptavidin_coverage.json", "biotin_pockets.json"):
        raw = (PDB_PATH.parent / name).read_bytes()
        source = describe(raw, format="pdb" if name.endswith(".pdb") else "json",
                          media_type="chemical/x-pdb" if name.endswith(".pdb") else "application/json")
        blob = embed(source, raw)
        blobs[name] = (source.sha256, blob)
        row = {"name": name, "raw_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
               "embedded_base64_bytes": len(blob.data_b64),
               "capture_string_byte_charge": len(blob.data_b64) * 4}
        if name.endswith(".pdb"):
            lines = raw.decode("utf-8").splitlines()
            row.update(models=sum(line.startswith("MODEL") for line in lines),
                       atom_records=sum(line.startswith("ATOM  ") for line in lines),
                       hetatm_records=sum(line.startswith("HETATM") for line in lines))
        rows.append(row)
    return blobs, rows


def measure(name, mode, particle_count, placements, pins, blobs, repeats):
    table = dict(blobs[filename] for filename in pins)
    design = create_empty_part("Coating admission fixture", "HONEYCOMB").copy_with(input_sources=table)
    builds, recovery_ms = [], []
    encoded_recovery, raw_recovery = 0, 0
    for index in range(particle_count):
        (pre, pre_size), elapsed = timed(lambda: encode_design_snapshot(design))
        recovery_ms.append(elapsed)
        coating, elapsed = timed(lambda: build_streptavidin_coating(
            20.0, mode=mode, count_override=placements,
            coverage_reference="gold_2007" if "streptavidin_coverage.json" in pins else None))
        builds.append(elapsed)
        particle = Nanoparticle(id=f"coating_benchmark_{index}", diameter_nm=20.0, coating=coating)
        design = design.copy_with(nanoparticles=[*design.nanoparticles, particle])
        (post, post_size), elapsed = timed(lambda: encode_design_snapshot(design))
        recovery_ms.append(elapsed)
        encoded_recovery += len(pre) + len(post)
        raw_recovery += pre_size + post_size
    candidate_bytes = len(design.model_dump_json().encode("utf-8"))
    fixture_pickle_bytes = len(pickle.dumps(design, protocol=pickle.HIGHEST_PROTOCOL))
    return {"case": name, "mode": mode, "particles": particle_count,
            "requested_placements_per_particle": placements,
            "actual_placements": [len(p.coating.poses) for p in design.nanoparticles],
            "atoms_per_asset": [len(p.coating.protein.atoms) for p in design.nanoparticles],
            "pins": pins, "capture_accounting": charges(design),
            "native_build_ms": builds, "native_build_total_ms": sum(builds),
            "fixture_pickle_bytes_not_admitted": fixture_pickle_bytes,
            "candidate_design_json_bytes_without_history_or_envelope": candidate_bytes,
            "modeled_recovery_pairs": particle_count,
            "recovery_base64_bytes_cumulative": encoded_recovery,
            "recovery_uncompressed_bytes_cumulative": raw_recovery,
            "recovery_encode_ms_total": sum(recovery_ms),
            "recovery_fits_existing_8MB_budget": encoded_recovery <= 8_000_000,
            "candidate_plus_recovery_bytes_lower_bound": candidate_bytes + encoded_recovery,
            "default_capture": capture_profile(design, repeats),
            "prospective_job_only_capture": capture_profile(design, repeats, **PROSPECTIVE)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 9:
        parser.error("Use 1..9 capture repeats")
    blobs, sources = source_inputs()
    streptavidin_asset.cache_clear()  # Process-local cache only; expose native cold parsing.
    parsed = []
    for mode in ("adsorption", "biotin_tether"):
        asset, elapsed = timed(lambda: streptavidin_asset(mode))
        parsed.append({"mode": mode, "cold_native_asset_ms": elapsed,
                       "atoms": len(asset.atoms), "bonds": len(asset.bonds),
                       "asset_accounting": walk_charge(asset),
                       "asset_json_bytes": len(asset.model_dump_json().encode("utf-8"))})
    pdb = ["1STP-assembly1.pdb"]
    coverage = [*pdb, "streptavidin_coverage.json"]
    all_pins = [*coverage, "biotin_pockets.json"]
    cases = [("empty", "adsorption", 0, 1, []),
             ("source_only_all_pins", "adsorption", 0, 1, all_pins),
             ("one_adsorption_pdb", "adsorption", 1, 1, pdb),
             ("one_adsorption_coverage", "adsorption", 1, 1, coverage),
             ("one_tether_pdb", "biotin_tether", 1, 1, pdb),
             ("one_tether_all_pins", "biotin_tether", 1, 1, all_pins),
             ("one_particle_16_requested_sites", "adsorption", 1, 16, coverage),
             ("sixteen_independent_coatings", "adsorption", 16, 1, coverage)]
    rows = [measure(*case, blobs, args.repeats) for case in cases]
    print(json.dumps({"scope": "Native software geometry, source/capture/transport/recovery only; no physics or proof",
                      "fixture_is_recipe": False, "production_limits_unchanged": True,
                      "default_capture": {"max_nodes": 30_000, "max_bytes": 2_000_000, "seconds": 0.025},
                      "prospective_job_only_profile_not_production": PROSPECTIVE,
                      "worker_input_bytes": 2_000_000, "candidate_result_bytes": 16_000_000,
                      "recovery_budget_bytes": 8_000_000, "repeats": args.repeats,
                      "sources": sources, "native_assets": parsed, "cases": rows}, indent=2))
    return 0  # Capture refusals are evidence, never a successful proof.


if __name__ == "__main__":
    raise SystemExit(main())
