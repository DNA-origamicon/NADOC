"""Read-only CPD source audit and endpoint inventory; launches no calculations.

Run from the repository root with Python 3. Writes a JSON inventory to stdout.
Geometry descriptors refer to archived gas-phase N-methyl cores, not DNA exits.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FF = ROOT / "backend/data/forcefield"
QM = Path("/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/qm")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pin(path, expected=None):
    path = Path(path)
    actual = digest(path)
    if expected is not None and actual != expected:
        raise ValueError(f"Hash mismatch: {path}")
    return {"path": str(path), "sha256": actual, "prior_pin_verified": expected is not None}


def read(path):
    return json.loads(Path(path).read_text())


def resolve(record, local):
    for path in (Path(record["path"]), Path(local)):
        if path.is_file() and digest(path) == record["sha256"]:
            result = pin(path, record["sha256"])
            result["declared_path"] = record["path"]
            return result
    raise ValueError(f"Missing or changed source: {record['path']}")


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def shortest_path(edges, source, target):
    graph = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
        graph[b].add(a)
    queue = deque([(source, 0)])
    seen = {source}
    while queue:
        node, distance = queue.popleft()
        if node == target:
            return distance
        for neighbor in graph[node] - seen:
            seen.add(neighbor)
            queue.append((neighbor, distance + 1))
    raise ValueError("Disconnected attachment atoms")


def core_sources(definition, equivalent):
    pid = definition["id"]
    evidence = definition.get("minimum_geometry_evidence", {})
    pins = []
    if pid in {"tt-cpd-cis-syn", "tt-cpd-cis-syn-ii"}:
        refs = equivalent["source_frequency"]
        pins.extend(pin(refs[k]["path"], refs[k]["sha256"]) for k in
                    ("job_manifest", "frequency_audit", "source_geometry"))
        job = read(refs["job_manifest"]["path"])
        frequency_path = Path(refs["frequency_audit"]["path"])
        xyz_path = Path(refs["source_geometry"]["path"])
        keys = (equivalent["target_atom_map_in_source_matrix_order"]
                if pid.endswith("-ii") else job["atom_map"])
    else:
        pins.extend(pin(evidence[k]["path"], evidence[k]["sha256"]) for k in
                    ("frequency_job_manifest", "frequency_audit", "optimized_xyz", "optimized_model_audit"))
        job = read(evidence["frequency_job_manifest"]["path"])
        frequency_path = Path(evidence["frequency_audit"]["path"])
        xyz_path = Path(evidence["optimized_xyz"]["path"])
        keys = job["atom_map"]
    pin(xyz_path, job["source_xyz"]["sha256"])
    frequency = read(frequency_path)
    for field in ("cartesian_hessian", "output"):
        record = frequency[field]
        pins.append(resolve(record, frequency_path.parent / Path(record["path"]).name))
    lines = xyz_path.read_text().splitlines()
    count = int(lines[0])
    xyz = [[float(x) for x in line.split()[1:4]] for line in lines[2:2+count]]
    if len(xyz) != count or len(keys) != count or len(set(keys)) != count:
        raise ValueError("Atom map/coordinate count mismatch")
    if not all(len(v) == 3 and all(math.isfinite(x) for x in v) for v in xyz):
        raise ValueError("Invalid coordinates")
    return job, frequency, dict(zip(keys, xyz)), pins


def inventory():
    registry = read(FF / "photoproduct_registry.json")
    equivalent_path = QM / "cis-syn-ii-equivalent-hessian-reference-v1.json"
    equivalent = read(equivalent_path)
    equivalent_definition = read(FF / "photoproducts/tt-cpd-cis-syn-ii/chemical_definition.json")
    equivalent_pin = pin(equivalent_path, equivalent_definition["minimum_geometry_evidence"]
                         ["equivalent_hessian_reference"]["sha256"])
    equivalence_audit = equivalent["equivalence_audit"]
    equivalence_pin = pin(equivalence_audit["path"], equivalence_audit["sha256"])
    if not equivalent["passed"]:
        raise ValueError("Endpoint exchange reference did not pass")
    rows = []
    signatures = defaultdict(list)
    for product in registry["products"]:
        pid = product["id"]
        definition_ref = product["assets"]["chemical_definition"]
        definition_path = FF / definition_ref["path"]
        definition_pin = pin(definition_path, definition_ref["sha256"])
        definition = read(definition_path)
        delta = definition["graph_delta"]
        bonds = [f"{b['atom_1']}--{b['atom_2']}" for b in delta["bonds_added"]]
        if sorted(bonds) != sorted(product["graph_delta"]["bonds_added"]):
            raise ValueError(f"Registry/definition graph mismatch: {pid}")
        edges = definition["precursor_local_connectivity"]["bonds"] + [
            [b["atom_1"], b["atom_2"]] for b in delta["bonds_added"]]
        signature = tuple(sorted(tuple(sorted(edge)) for edge in edges))
        signatures[signature].append(pid)
        job, frequency, coords, sources = core_sources(definition, equivalent)
        signs = []
        for center in definition["product_stereocenters"]:
            vectors = [sub(coords[k], coords[center["atom"]]) for k in center["signed_volume_reference_atoms"]]
            determinant = dot(vectors[0], cross(vectors[1], vectors[2]))
            expected = center["expected_signed_volume"]
            passed = determinant < 0 if expected == "negative" else determinant > 0
            signs.append({"atom": center["atom"], "neighbor_determinant_angstrom3": determinant,
                          "expected_sign": expected, "passed": passed})
        if not all(s["passed"] for s in signs):
            raise ValueError(f"Mapped stereochemical sign mismatch: {pid}")
        if not (frequency["frequency_table_complete"] and frequency["parsed_mode_count"] == 102
                and frequency["imaginary_mode_count"] == 0 and len(frequency["frequencies"]) == 102
                and all(not f["imaginary"] and f["value_cm_inverse"] > 0 for f in frequency["frequencies"])):
            raise ValueError(f"Incomplete/failed archived harmonic evidence: {pid}")
        u = sub(coords["1:CM"], coords["1:N1"])
        v = sub(coords["2:CM"], coords["2:N1"])
        angle = math.degrees(math.acos(max(-1, min(1, dot(u, v) / norm(u) / norm(v)))))
        asset_pins = {k: pin(FF / ref["path"], ref["sha256"])
                      for k, ref in product["assets"].items() if k != "chemical_definition"}
        rows.append({
            "id": pid, "label": product["label"], "class": product["structural_class"],
            "definition": definition_pin, "added_bonds": bonds,
            "backbone_and_glycosidic_connectivity": delta["backbone_and_glycosidic_connectivity"],
            "local_graph_N1_to_N1_bond_count": shortest_path(edges, "1:N1", "2:N1"),
            "local_graph_C1prime_to_C1prime_bond_count": shortest_path(edges, "1:C1'", "2:C1'"),
            "endpoint_quotient_edge": [1, 2],
            "requested_contexts_not_validation": product["requested_contexts"],
            "registry_validated_contexts": product["validated_contexts"],
            "registry_release_status": product["gates"]["release_review"]["status"],
            "registered_assets_verified": asset_pins,
            "core": {
                "model": "N1-methyl capped TT-CPD, gas phase, 36 atoms; no sugars or backbone",
                "method": job["method"], "basis": job["basis"], "source_records": sources,
                "mapped_stereocenters_recomputed": signs,
                "harmonic_evidence_kind": ("endpoint-exchange reuse of cis-syn-I; not an independent run"
                                           if pid == "tt-cpd-cis-syn-ii" else "direct archived frequency calculation"),
                "archived_frequency_status": frequency["status"],
                "archived_positive_mode_count": frequency["parsed_mode_count"],
                "archived_lowest_frequency_cm_inverse": frequency["lowest_frequency_cm_inverse"],
                "N1_to_N1_angstrom": norm(sub(coords["1:N1"], coords["2:N1"])),
                "methyl_cap_C_to_C_angstrom": norm(sub(coords["1:CM"], coords["2:CM"])),
                "N1_to_cap_direction_angle_degrees": angle,
            },
        })
    if len(rows) != 8 or len(signatures) != 2:
        raise ValueError("Unexpected catalog/connectivity coverage")
    evidence_paths = [
        "docs/cpd_strand_builder.md",
        "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/completion_review.md",
        "docs/cpd_anti_validation_closeout_20261010.md",
        ".development-artifacts/cpd-anti-readiness-fit-v3-r1/assessment.json",
        ".development-artifacts/cpd-anti-prospective-score-v3-r1/assessment.json",
        ".development-artifacts/cpd-anti-gpu-cube-context-v5/campaign_closeout_v17.json",
    ]
    return {
        "schema": "nadoc.cpd-isomer-endpoint-inventory.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": pin(Path(__file__)), "registry": pin(FF / "photoproduct_registry.json"),
        "scope": "Source inventory and static core descriptors only; no new QM, MD, fitting, registry edits, or cloud spending.",
        "verification": "Rehashed definitions, registry assets, mapped geometries, job/frequency records, Hessians and output files; recomputed four signed centers and descriptors. Archived positive-mode tables checked, not a new Hessian/stationarity calculation.",
        "descriptor_method": {
            "distance": "Euclidean norm of the difference of the named atom coordinates",
            "direction_angle": "acos(dot(CM1-N1_1, CM2-N1_2)/(norm(CM1-N1_1)*norm(CM2-N1_2))), in degrees",
            "graph_distances": "Unweighted shortest paths in the local base-plus-C1prime graph, without an external phosphodiester backbone",
            "stereo": "Determinant of the three definition-ordered neighbor vectors from each center; only sign compared",
        },
        "connectivity_classes": [{"products": ids, "atom_graph_ignores_stereochemistry": True}
                                 for ids in signatures.values()],
        "cis_syn_II_core_equivalence": {"reference": equivalent_pin, "audit": equivalence_pin,
                                        "scope": equivalent["reuse_scope"], "not_established": equivalent["not_established"]},
        "most_developed": {
            "tt-cpd-cis-syn": "Additive v6 preliminary adjacent-internal intrastrand DNA package; 34 ns matched overnight CPD/control benchmark. One CPD replica opened locally. Terminal/interstrand builder contexts not qualified.",
            "tt-cpd-cis-anti-i": "Additive v3 fit with independent prospective points and completed three anti plus three control 10 ns finite-context runs. Replica effects differed. Separate Archive research package; no general registry promotion.",
            "evidence_sources": [pin(ROOT / p) for p in evidence_paths],
            "comparison_limit": "These are different DNA systems and validation contexts, not a matched syn/anti experiment.",
        },
        "interpretation": [
            "The two developed cis models cover both registered atom-connectivity classes (syn and anti), but neither trans class.",
            "Every product connects the same two generic nucleotide endpoints and preserves their backbone/glycosidic connectivity. No additional generic endpoint pairing class appears among the other six.",
            "Same endpoint graph does not establish the same spatial embedding, winding, loop closure, accessibility, or thermal behavior in a particular DNA design.",
            "Trans-syn and trans-anti add stereochemical geometry, not a third atom-connectivity graph. Both deserve local placement screening before assuming cis representatives suffice.",
            "Cis-syn-II is a strong candidate for capped-core reuse because an explicit atom permutation already exists; its ordered DNA boundary equivalence is not established.",
            "Other I/II pairs remain distinct in ordered chiral DNA even when the reported scalar distances and angles nearly coincide.",
        ],
        "limitations": [
            "One archived local core conformer per direct calculation; no conformational ensemble or free-energy ranking.",
            "N-methyl carbon positions are attachment proxies, not C1prime, O3prime, O5prime or DNA 5prime/3prime exits.",
            "Distances and one angle omit handedness, ring-face arrangement, sugar torsions, sterics and backbone winding.",
            "Preview coordinates and stale frontend progress labels were not used as physical evidence.",
            "No isomer thermal equivalence, melting shift, actual weld occupancy or photochemical yield is inferred.",
            "Legacy QM harmonic evidence describes capped models only, not current full-DNA minimum certification or production release.",
        ],
        "recommended_next_screen": {
            "scope": "Same real weld site, same surrounding DNA and endpoint identities, both developed cis models and all four trans candidates; compare II variants where the ordered attachment differs.",
            "metrics": ["5prime/3prime exit orientation and spacing", "properly mapped sugar chirality", "closure strain and clashes", "neighbor pairing/stacking"],
            "priority": "Cover trans-syn and trans-anti geometry before extensive independent campaigns on every I/II variant; choose representatives by actual site compatibility.",
            "status": "Recommendation only; no simulation launched.",
        },
        "literature": [{
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11305913/",
            "title": "Distinguishing Isomeric Cyclobutane Thymidine Dimers by Ion Mobility and Tandem Mass Spectrometry",
            "use": "Primary support for separate syn/anti connectivity and cis/trans stereochemistry axes; not origami melting equivalence.",
        }],
        "products": rows,
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
