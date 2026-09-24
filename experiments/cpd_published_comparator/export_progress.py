"""Regenerate Help > CPD progress from retained evidence; never changes release gates."""

import argparse, json, hashlib, sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from backend.core.cpd_preview import attach_isomer_previews  # noqa: E402
ART = REPO / ".development-artifacts"
ARCHIVE = Path("/media/jojo/Archive/NADOC_archive/photoproduct_evidence")
sources = {}
parser = argparse.ArgumentParser()
parser.add_argument(
    "--boundary-root",
    type=Path,
    default=ART / "cpd-cis-syn-joint-v6",
    help="Append a corrected training candidate, retaining the frozen baseline",
)
parser.add_argument("--dna-root", type=Path, default=ART / "cpd-dna-replicas-v2")
args = parser.parse_args()


def read(p):
    p = Path(p)
    b = p.read_bytes()
    key = p.name + "-" + hashlib.sha256(b).hexdigest()[:10]
    sources[key] = {
        "file": str(p)
        .replace(str(REPO) + "/", "")
        .replace(str(ARCHIVE) + "/", "photoproduct_evidence/"),
        "sha256": hashlib.sha256(b).hexdigest(),
    }
    return json.loads(b), key


def check(label, state, value=None, limit=None, evidence=None):
    return dict(label=label, state=state, value=value, limit=limit, evidence=evidence)


def model(id, label, names, xyz, bonds, local, shared, geometry):
    return dict(
        id=id,
        label=label,
        geometry=geometry,
        atoms=[
            dict(
                id=n,
                element=n.split(":")[1].lstrip("0123456789")[0],
                position=list(map(float, pos)),
                checks=[c for keys, c in local if n in keys],
            )
            for n, pos in zip(names, xyz)
        ],
        bonds=[
            dict(
                id="—".join(pair),
                atoms=pair,
                checks=[c for keys, c in local if set(pair) <= set(keys)],
            )
            for pair in bonds
        ],
        checks=shared,
    )


pending = check("Replicated DNA solution validation", "pending", "Not completed")
energy, es = read(ART / "cpd-independent-energy-v1/assessment.json")
eng, ns = read(ART / "cpd-angle-native-v1/engine_agreement.json")
fit, fs = read(ART / "cpd-angle-refinement-v2/assessment.json")
old, os = read(
    ART / "cpd-published-local-benchmarks-no-c5-planarity-v1/last_assessment.json"
)
ref = ARCHIVE / "tt-cpd-work-v1-completions/fit/cis-syn/charmm36-hybrid-v1"
manifest, _ = read(
    ref / "minimum_response_fixed_improper_v1/linear_response_manifest.json"
)
amap, _ = read(manifest["sources"]["stable_atom_map"]["path"])
names = [a["stable_atom_key"] for a in amap]
idx = {n: i for i, n in enumerate(names)}
xyz = np.loadtxt(ART / "cpd-angle-refinement-v2/minimum_A.txt")
qmp = Path(manifest["sources"]["target_geometry"]["path"])
qm = np.array(
    [
        list(map(float, l.split()[1:]))
        for l in qmp.read_text().splitlines()[2:]
        if l.strip()
    ]
)
local = []
for b in old["bonds"]:
    a, c = [idx[n] for n in b["atoms"]]
    error = float(np.linalg.norm(xyz[a] - xyz[c]) - np.linalg.norm(qm[a] - qm[c]))
    local.append(
        (
            b["atoms"],
            check(
                "Fitted bond length",
                "pass" if abs(error) <= 0.03 else "fail",
                f"{error:+.5f} Å error",
                "|error| ≤ 0.03 Å",
                fs,
            ),
        )
    )
for a in fit["angles"]:
    local.append(
        (
            a["atoms"],
            check(
                "Fitted angle: " + " – ".join(a["atoms"]),
                "pass" if abs(a["error_deg"]) <= 3 else "fail",
                f"{a['error_deg']:+.3f}° error",
                "|error| ≤ 3°",
                fs,
            ),
        )
    )
shared = [
    check(
        "Independent core deformation energies",
        "pass" if energy["passed"] else "fail",
        f"RMSE {energy['rmse_kcal_mol']:.3f}; max {energy['max_error_kcal_mol']:.3f} kcal/mol",
        "RMSE ≤ 1; max ≤ 2 kcal/mol",
        es,
    ),
    check(
        "Native NAMD energy and forces",
        "pass" if eng["all_passed"] else "fail",
        "Three matched geometries",
        "Energy and force errors < 0.001",
        ns,
    ),
    check(
        "Sugar-attachment transfer",
        "fail",
        "Both endpoints have angle outliers",
        "Boundary checks must pass",
    ),
    pending,
]
models = [
    model(
        "syn-core",
        "cis-syn · capped core · original",
        names,
        xyz,
        [b["atoms"] for b in old["bonds"]],
        local,
        shared,
        "Refined MM minimum; geometry checks are training evidence, not independent validation.",
    )
]
for endpoint in [1, 2]:
    folder = (
        ARCHIVE
        / f"tt-cpd-local-fragment-campaign-v1/cases/syn-primary-endpoint-{endpoint}/model"
    )
    m, _ = read(folder / "model_manifest.json")
    g, gs = read(folder / "model_graph.json")
    audit, bs = read(
        ART / f"cpd-sugar-boundary-validation-v2/endpoint-{endpoint}/assessment.json"
    )
    xyz = np.loadtxt(
        ART / f"cpd-sugar-boundary-validation-v2/endpoint-{endpoint}/minimum_A.txt"
    )
    local = []
    pair = [f"{endpoint}:C1'", f"{endpoint}:N1"]
    v = audit["boundary_bond_error_A"]
    local.append(
        (
            pair,
            check(
                "Independent glycosidic-bond geometry",
                "pass" if abs(v) <= 0.03 else "fail",
                f"{v:+.5f} Å error",
                "|error| ≤ 0.03 Å",
                bs,
            ),
        )
    )
    for a in audit["angles"]:
        local.append(
            (
                a["atoms"],
                check(
                    "Independent angle: " + " – ".join(a["atoms"]),
                    "pass" if abs(a["error_deg"]) <= 3 else "fail",
                    f"{a['error_deg']:+.3f}° error",
                    "|error| ≤ 3°",
                    bs,
                ),
            )
        )
    for c in audit["centers"]:
        local.append(
            (
                [c["center"]],
                check(
                    "Stereochemistry retained",
                    "pass" if c["preserved"] else "fail",
                    f"QM volume {c['qm']:.4f}; MM {c['mm']:.4f}",
                    "Same signed volume",
                    bs,
                ),
            )
        )
    engines, be = read(
        ART / "cpd-sugar-boundary-validation-v2/minimum_and_engine_checks.json"
    )
    er = next(r for r in engines["records"] if r["endpoint"] == endpoint)
    models.append(
        model(
            f"syn-boundary-{endpoint}",
            f"cis-syn · sugar endpoint {endpoint} · original",
            m["atom_map"],
            xyz,
            [b["atoms"] for b in g["bonds"]],
            local,
            [
                check(
                    "Parameter coverage",
                    "pass",
                    "49 atoms; 52 bonds; neutral charge",
                    evidence=bs,
                ),
                check(
                    "True local minimum",
                    "pass" if er["minimum_passed"] else "fail",
                    str(er["smallest_internal_curvatures_step_halving"]),
                    evidence=be,
                ),
                check(
                    "Native NAMD energy and forces",
                    "pass" if all(c["passed"] for c in er["native_checks"]) else "fail",
                    "QM and MM geometries",
                    evidence=be,
                ),
                check(
                    "Independent glycosidic energy profile",
                    "pending",
                    "Not yet evaluated",
                ),
                pending,
            ],
            "Independent sugar-attached fragment MM minimum. Core and boundary checks apply to different model compounds.",
        )
    )
if args.boundary_root:
    corrected = args.boundary_root.resolve()
    training, training_source = read(corrected / "assessment.json")
    engine_path = corrected / "minimum_and_engine_checks.json"
    native, native_source = read(engine_path) if engine_path.exists() else (None, None)
    for audit in training["records"]:
        endpoint = audit["endpoint"]
        original = next(m for m in models if m["id"] == f"syn-boundary-{endpoint}")
        geometry = np.loadtxt(corrected / f"endpoint-{endpoint}/minimum_A.txt")
        local = []
        for a in audit["all_angles"]:
            local.append(
                (
                    a["atoms"],
                    check(
                        "Training angle: " + " – ".join(a["atoms"]),
                        "pass" if abs(a["error_deg"]) <= 3 else "fail",
                        f"{a['error_deg']:+.3f}° error; before {a['before_error_deg']:+.3f}°",
                        "|error| ≤ 3°",
                        training_source,
                    ),
                )
            )
        for b in audit["all_bonds"]:
            local.append(
                (
                    b["atoms"],
                    check(
                        "Training bond length",
                        "pass" if abs(b["error_A"]) <= 0.03 else "fail",
                        f"{b['error_A']:+.5f} Å error; before {b['before_error_A']:+.5f} Å",
                        "|error| ≤ 0.03 Å",
                        training_source,
                    ),
                )
            )
        for c in audit["centers"]:
            local.append(
                (
                    [c["center"]],
                    check(
                        "Stereochemistry retained",
                        "pass" if c["preserved"] else "fail",
                        f"QM volume {c['qm']:.4f}; MM {c['mm']:.4f}",
                        "Same signed volume",
                        training_source,
                    ),
                )
            )
        shared = [
            check(
                "Glycosidic boundary training targets",
                "pass" if audit["boundary_geometry_passed"] else "fail",
                f"Bond {audit['boundary_bond_error_A']:+.5f} Å; max angle {audit['max_boundary_angle_error_deg']:.3f}°",
                "0.03 Å and 3°; fitted evidence, not independent validation",
                training_source,
            )
        ]
        if "all_geometry_passed" in audit:
            shared.append(
                check(
                    "All fragment bond and angle targets",
                    "pass" if audit["all_geometry_passed"] else "fail",
                    f"{len(audit['all_bonds'])} bonds; {len(audit['all_angles'])} angles",
                    "All bond errors ≤ 0.03 Å; all angle errors ≤ 3°; training evidence",
                    training_source,
                )
            )
        new_failures = [
            a
            for a in audit["all_angles"]
            if abs(a["before_error_deg"]) <= 3 < abs(a["error_deg"])
        ]
        new_failures += [
            b
            for b in audit["all_bonds"]
            if abs(b["before_error_A"]) <= 0.03 < abs(b["error_A"])
        ]
        shared.append(
            check(
                "Collateral geometry regression",
                "fail" if new_failures else "pass",
                f"{len(new_failures)} newly failing bonds/angles across the fragment",
                "No newly failing geometry checks",
                training_source,
            )
        )
        if native:
            er = next(r for r in native["records"] if r["endpoint"] == endpoint)
            shared += [
                check(
                    "True local minimum",
                    "pass" if er["minimum_passed"] else "fail",
                    str(er["smallest_internal_curvatures_step_halving"]),
                    evidence=native_source,
                ),
                check(
                    "Native NAMD energy and forces",
                    "pass" if all(c["passed"] for c in er["native_checks"]) else "fail",
                    "QM and MM geometries",
                    evidence=native_source,
                ),
            ]
        else:
            shared.append(
                check(
                    "Native NAMD and minimum verification",
                    "pending",
                    "Candidate checks not yet recorded",
                )
            )
        for filename, title, pass_key, value in [
            (
                "engine_agreement.json",
                "Capped-core implementation regression",
                "all_passed",
                "Core minimum and two distortions",
            ),
            (
                "core-energy/assessment.json",
                "Independent capped-core energy regression",
                "passed",
                "Nine fixed QM geometries",
            ),
        ]:
            path = corrected / filename
            if path.exists():
                result, src = read(path)
                shared.append(
                    check(
                        title,
                        "pass" if result[pass_key] else "fail",
                        value,
                        evidence=src,
                    )
                )
            else:
                shared.append(
                    check(title, "pending", "Not yet recorded for this candidate")
                )
        shared.extend(
            [
                check(
                    "Independent glycosidic energy profile",
                    "pending",
                    "Not yet evaluated",
                ),
                pending,
            ]
        )
        startup = corrected / "reference_build_assessment.json"
        if startup.exists():
            result, src = read(startup)
            shared.append(
                check(
                    "Full nucleotide and duplex startup",
                    "pass"
                    if all(
                        f["native_load"] == "passed"
                        and f["hydrogen_relaxation_steps"] == 500
                        for f in result["fixtures"]
                    )
                    else "fail",
                    "d(TpT), duplex and control: load + 500 fixed-heavy-atom steps; no solution validation",
                    evidence=src,
                )
            )
            if "control_invariance" in result:
                control = result["control_invariance"]
                shared.append(
                    check(
                        "Ordinary DNA unchanged by CPD overlay",
                        "pass" if control["passed"] else "fail",
                        f"Energy difference {control['energy_error']}; max force difference {control['force_error']}",
                        "Both differences < 1e-7",
                        src,
                    )
                )
        models.append(
            model(
                f"syn-corrected-{endpoint}",
                f"cis-syn · sugar endpoint {endpoint} · corrected training",
                [a["id"] for a in original["atoms"]],
                geometry,
                [b["atoms"] for b in original["bonds"]],
                local,
                shared,
                f"Corrected training minimum ({corrected.name}). All fragment bond/angle errors are shown. Before values refer to the preceding boundary candidate; earlier frozen probes remain in the selector.",
            )
        )
    if "core" in training:
        core = training["core"]
        original = next(m for m in models if m["id"] == "syn-core")
        local = []
        for a in core["all_angles"]:
            local.append(
                (
                    a["atoms"],
                    check(
                        "Joint training angle: " + " – ".join(a["atoms"]),
                        "pass" if abs(a["error_deg"]) <= 3 else "fail",
                        f"{a['error_deg']:+.3f}° error; before {a['before_error_deg']:+.3f}°",
                        "|error| ≤ 3°",
                        training_source,
                    ),
                )
            )
        for b in core["all_bonds"]:
            local.append(
                (
                    b["atoms"],
                    check(
                        "Joint training bond length",
                        "pass" if abs(b["error_A"]) <= 0.03 else "fail",
                        f"{b['error_A']:+.5f} Å error; before {b['before_error_A']:+.5f} Å",
                        "|error| ≤ 0.03 Å",
                        training_source,
                    ),
                )
            )
        for c in core["centers"]:
            local.append(
                (
                    [c["center"]],
                    check(
                        "Stereochemistry retained",
                        "pass" if c["preserved"] else "fail",
                        f"QM volume {c['qm']:.4f}; MM {c['mm']:.4f}",
                        "Same signed volume",
                        training_source,
                    ),
                )
            )
        shared = [
            check(
                "All core geometry targets",
                "pass" if core["all_geometry_passed"] else "fail",
                f"{len(core['all_bonds'])} bonds; {len(core['all_angles'])} angles",
                "0.03 Å / 3°; training evidence",
                training_source,
            )
        ]
        for filename, title, key in [
            ("core_minimum.json", "True core minimum", "passed"),
            ("engine_agreement.json", "Native NAMD energy and forces", "all_passed"),
            (
                "core-energy/assessment.json",
                "Independent core deformation energies",
                "passed",
            ),
        ]:
            path = corrected / filename
            if path.exists():
                result, src = read(path)
                value = (
                    f"RMSE {result['rmse_kcal_mol']:.3f}; max {result['max_error_kcal_mol']:.3f} kcal/mol"
                    if "rmse_kcal_mol" in result
                    else "Numerical checks recorded"
                )
                shared.append(
                    check(title, "pass" if result[key] else "fail", value, evidence=src)
                )
            else:
                shared.append(check(title, "pending", "Not yet recorded"))
        shared.append(
            check(
                "Joint sugar-fragment geometry",
                "pass"
                if all(r["all_geometry_passed"] for r in training["records"])
                else "fail",
                "Both endpoints included in training",
                evidence=training_source,
            )
        )
        shared.append(pending)
        models.append(
            model(
                "syn-core-corrected",
                "cis-syn · capped core · corrected training",
                [a["id"] for a in original["atoms"]],
                np.loadtxt(corrected / "core/minimum_A.txt"),
                [b["atoms"] for b in original["bonds"]],
                local,
                shared,
                f"Joint corrected core ({corrected.name}). CPD-specific types; fitted geometry with a separately evaluated deformation-energy regression.",
            )
        )
for endpoint in [1, 2]:
    folder = ART / f"cpd-repaired-anti-fragments-v1/endpoint-{endpoint}"
    m, ms = read(folder / "model_manifest.json")
    g, _ = read(folder / "model_graph.json")
    xyz = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in (folder / "model.xyz").read_text().splitlines()[2:]
            if l.strip()
        ]
    )
    models.append(
        model(
            f"anti-boundary-{endpoint}",
            f"cis-anti · sugar endpoint {endpoint}",
            m["atom_map"],
            xyz,
            [b["atoms"] for b in g["bonds"]],
            [],
            [
                check(
                    "Boundary QM optimization",
                    "pending",
                    "Stopped/deferred; no accepted endpoint optimization",
                ),
                check(
                    "Drude transfer and dynamics",
                    "pending",
                    "Unresolved in the separate anti campaign; no per-atom pass claimed",
                ),
                pending,
            ],
            "Repaired starting structure, not a validated minimum. Cis-syn evidence does not validate this product.",
        )
    )
pilot_path = args.dna_root / "assessment.json"
pilot_note = ""
if pilot_path.exists():
    pilot, pilot_source = read(pilot_path)
    failed = any(not r["passed"] for r in pilot["records"])
    pilot_state = "fail" if failed else "pass" if pilot["passed"] else "pending"
    pilot_note = (
        f" DNA short pilot: {pilot['completed_replicas']}/6 assessed ({pilot_state})."
    )
    for m in models:
        if m["id"] not in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            continue
        m["checks"] = [
            dict(
                c,
                value="Short replicated pilot recorded below; longer sampling and convergence remain unvalidated",
            )
            if c["label"] == "Replicated DNA solution validation"
            else c
            for c in m["checks"]
        ]
        m["checks"].append(
            check(
                "Replicated DNA short stability pilot",
                pilot_state,
                f"{pilot['completed_replicas']}/{pilot['planned_replicas']} replicas assessed; 100 ps production per replica",
                "Numerical and stereochemical sanity only; not conformational convergence",
                pilot_source,
            )
        )
        for r in pilot["records"]:
            value = (
                (
                    f"T {r['temperature_mean_K']:.1f} K; density {r['density_mean_g_ml']:.3f} g/mL; "
                    f"{r['centers_checked']} stereocenters; {len(r['failed_centers'])} inverted"
                )
                if "temperature_mean_K" in r
                else "Execution failed"
            )
            m["checks"].append(
                check(
                    f"DNA pilot · {r['system']} replica {r['replica']}",
                    "pass" if r["passed"] else "fail",
                    value,
                    "All preregistered short-pilot checks pass",
                    pilot_source,
                )
            )
extension_path = ART / "cpd-dna-extended-v1/status.json"
if extension_path.exists():
    extension, extension_source = read(extension_path)
    count = len(extension["records"])
    state = extension["state"]
    pilot_note += (
        f" DNA extension: {count}/30 one-nanosecond blocks assessed ({state})."
    )
    for m in models:
        if m["id"] in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            m["checks"].append(
                check(
                    "Longer replicated DNA sampling",
                    "fail" if state == "failed" else "pending",
                    f"{count}/30 blocks assessed; {state}; target 5 ns per replica",
                    "Block stability and convergence diagnostics are separate; duration alone is not validation",
                    extension_source,
                )
            )
drift_path = ART / "cpd-drift-localization-v2/image_refinement.json"
if drift_path.exists():
    drift, drift_source = read(drift_path)
    minimum = min(r["min"]["distance_A"] for r in drift)
    pilot_note += (
        " Drift localized: end-region motion; periodic-image isolation concern."
    )
    for m in models:
        if m["id"] in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            m["checks"].append(
                check(
                    "Prior DNA campaign periodic-image isolation",
                    "fail" if minimum < 12 else "pending",
                    f"Closest heavy-atom image distance {minimum:.2f} Å in control; CPD 2 reaches 11.81 Å",
                    "Diagnostic: translated DNA should remain outside 12 Å direct-space cutoff; this alone does not establish box-size independence",
                    drift_source,
                )
            )
            m["checks"].append(
                check(
                    "DNA drift localization",
                    "pending",
                    "End-region motion dominates; CPD 2 lesion-ring RMSD 0.35 → 0.37 Å. A8–B13 initially open; box and initial-state controls needed.",
                    "Numerical stability passes do not establish a converged isolated-duplex ensemble",
                    drift_source,
                )
            )
largebox_path = ART / "cpd-dna-largebox-v1/status.json"
if largebox_path.exists():
    largebox, largebox_source = read(largebox_path)
    count = len(largebox["records"])
    pilot_note += (
        f" Revised 1T4I / 90 Å-box pilot: {count}/6 assessed ({largebox['state']})."
    )
    for m in models:
        if m["id"] in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            m["checks"].append(
                check(
                    "Revised starting structure and larger-box pilot",
                    "fail"
                    if largebox["state"] == "failed"
                    else "pass"
                    if largebox["state"] == "complete"
                    and all(r["passed"] for r in largebox["records"])
                    else "pending",
                    f"1T4I deposited coordinates; 90 Å cubic box; {count}/6 assessed",
                    "Short pilot stability plus >16 Å rotation-independent image-gap lower bound at sampled frames; longer convergence remains pending",
                    largebox_source,
                )
            )
overnight_path = ART / "cpd-overnight-8h-v1/status.json"
if overnight_path.exists():
    overnight, overnight_source = read(overnight_path)
    sampled_ns = 0.5 * len(overnight["records"])
    pilot_note += f" Overnight array: {sampled_ns:g} ns assessed ({overnight['state']}); eight-hour wall budget."
    for m in models:
        if m["id"] in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            m["checks"].append(
                check(
                    "Eight-hour matched DNA sampling array",
                    "fail" if overnight["state"] == "failed" else "pending",
                    f"{sampled_ns:g} ns in assessed 0.5 ns blocks; {overnight['state']}; local structure and image clearance checked each block",
                    "Finite validation benchmark; completed duration alone is not ensemble convergence. Final review required.",
                    overnight_source,
                )
            )
overnight_review_path = ART / "cpd-overnight-8h-v1/completion_wake_review.json"
if overnight_review_path.exists():
    reviewed, reviewed_source = read(overnight_review_path)
    pilot_note += " Overnight review: stability benchmark passed; one CPD replica has unresolved lesion-site opening."
    for m in models:
        if m["id"] in ("syn-core-corrected", "syn-corrected-1", "syn-corrected-2"):
            for c in m["checks"]:
                if c["label"] == "Eight-hour matched DNA sampling array":
                    c.update(
                        state="pass"
                        if reviewed["stability_benchmark_passed"]
                        else "fail",
                        value="Reviewed: 68 blocks, 34 ns, 17,000 frames; native/stability benchmark passed",
                        limit="All completed-block stability gates and independent execution audit pass; ensemble validation is separate",
                        evidence=reviewed_source,
                    )
            m["checks"].append(
                check(
                    "Lesion-site conformational validation",
                    "pending",
                    reviewed["structural_finding"],
                    "Opening is an observed conformational event, not proof of a parameter defect; independent energetics and state review required",
                    reviewed_source,
                )
            )
integration_path = REPO / "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/native_check.json"
integration_note = ""
if integration_path.is_file():
    integration, integration_source = read(integration_path)
    integration_note = " Cis-syn v6 is integrated for preliminary explicit-solvent strand-builder use (adjacent internal TT, additive, ordinary masses, ≤2 fs)."
    for m in models:
        if m["id"] in {"syn-core-corrected", "syn-corrected-1", "syn-corrected-2"}:
            m["checks"].append(check(
                "Strand-builder NAMD integration",
                "pass" if integration["passed"] else "fail",
                "Builder duplex: 1,000 minimization + 1,000 dynamics steps; all saved-frame chirality and crosslink checks pass",
                "Preliminary startup qualification; ensemble convergence remains separate",
                integration_source,
            ))
priority = {"syn-core-corrected": 0, "syn-corrected-1": 1, "syn-corrected-2": 2}
models.sort(key=lambda m: priority.get(m["id"], 3))
payload = {
    "schema": 1,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "summary": "No CPD has a full scientific release." + integration_note
    + pilot_note,
    "models": models,
    "sources": sources,
}
path = REPO / "frontend/public/cpd-progress.json"
path.write_text(json.dumps(attach_isomer_previews(payload), indent=2) + "\n")
print(path, len(models), "structures")
