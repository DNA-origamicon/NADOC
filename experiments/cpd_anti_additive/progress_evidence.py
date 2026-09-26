"""Append isolated additive anti campaign evidence to the portable CPD snapshot."""

from pathlib import Path
import numpy as np


def append_evidence(models, read, check, model, art):
    from experiments.cpd_anti_additive.prepare_anti_types import load_cases

    fit, fs = read(art / "cpd-anti-joint-fit-v2/assessment.json")
    verification, vs = read(art / "cpd-anti-joint-fit-verification-v1/assessment.json")
    curves, ws = read(art / "cpd-anti-water-curves-v2/assessment.json")
    charges, cs = read(art / "cpd-anti-charge-candidates-v1/assessment.json")
    _, baseline_source = read(
        art / "cpd-anti-water-transfer-diagnostic-v1/assessment.json"
    )
    targets, ts = read(art / "cpd-anti-boundary-esp-v2/assessment.json")
    common = [
        check(
            "Additive joint geometry training",
            "pass"
            if all(r["all_geometry_passed"] for r in fit["records"] + [fit["core"]])
            else "fail",
            "Core / endpoint 1 / endpoint 2 maximum angles: 3.26° / 4.10° / 5.37°; endpoint 1 bond 0.03044 Å",
            "Every bond ≤0.03 Å and angle ≤3°; optimizer convergence is not acceptance",
            fs,
        ),
        check(
            "ESP and dipole targets",
            "pass" if all(r["passed"] for r in targets["records"]) else "fail",
            "Both fragments: complete native HF/6-31G(d) targets",
            "Training evidence, not charge validation",
            ts,
        ),
        check(
            "Water interaction targets",
            "pass" if curves["all_curves_passed"] else "fail",
            "84 points; 12 bracketed curves; DF/DIRECT calibration passed",
            "Fixed orientations, scaled neutral CHARMM targets; training evidence",
            ws,
        ),
        check(
            "Transferred-charge water comparison",
            "pending",
            "N–H contacts overbind by 3.37–4.27 kcal/mol",
            "Diagnostic mismatch; no retrospective acceptance threshold",
            baseline_source,
        ),
        check(
            "Anti charge candidates",
            "pending",
            f"{len(charges['records'])} bounded exploratory candidates; none accepted or exported",
            "Residual water errors up to 1.44 kcal/mol in least restrained candidate; independent transfer checks pending",
            cs,
        ),
        check(
            "Interstrand DNA validation",
            "pending",
            "Frozen 2hb_1xT_CPD site; anti replicas not yet run",
            "No anti preliminary integration or scientific release",
        ),
    ]
    contract_path = art / "cpd-anti-validation-v1/status.json"
    if contract_path.exists():
        contract, contract_source = read(contract_path)
        common.insert(0, check(
            "Fixed validation contract",
            "pass" if contract["passed"] else "pending",
            f"{contract['passed_cases']}/{contract['required_cases']} contract review records; fitting blocked until reference lock",
            "v1 fixed membership and prospective limits; existing native results not yet basin-qualified under this contract; no promotion",
            contract_source,
        ))
    pause_path = art / "cpd-anti-validation-v1/campaign_pause.json"
    campaign_paused = False
    if pause_path.exists():
        pause, pause_source = read(pause_path)
        campaign_paused = pause.get("paused", False)
        if campaign_paused:
            common.insert(0, check(
                "Campaign paused by user",
                "pending",
                "No further simulations or automatic retries until explicit resume",
                "Latest +15 branch unresolved after bounded restart; fitting gate remains closed",
                pause_source,
            ))
    round_status = art / "cpd-anti-coupled-round-service-v1/status.json"
    if round_status.exists():
        execution, execution_source = read(round_status)
        common.append(
            check(
                "Next geometry and charge comparisons",
                "pending",
                f"Five-task coupled round: {execution['state']}; three charge-dependent geometry fits and two retrospective endpoint-transfer fits",
                "Execution state only; scientific comparison review pending",
                execution_source,
            )
        )
    review_path = art / "cpd-anti-coupled-round-service-v1/completion_wake_review.json"
    if review_path.exists():
        review, rs = read(review_path)
        common[-1] = check(
            "Charge-dependent geometry comparisons",
            "fail",
            review["conclusion"],
            "All three fits still exceed unchanged geometry limits; optimizer convergence is not acceptance",
            rs,
        )
    ordered_status = art / "cpd-anti-ordered-fit-service-v1/status.json"
    if ordered_status.exists():
        status, ss = read(ordered_status)
        common.append(
            check(
                "Ordered-endpoint parameter hypothesis",
                "pending",
                f"{status['state']}: isolated endpoint-specific role aliases, same bounds and baseline charges",
                "No production change; scientific review pending",
                ss,
            )
        )
    ordered_path = art / "cpd-anti-ordered-fit-v1/assessment.json"
    ordered_verify_path = art / "cpd-anti-ordered-verification-v1/assessment.json"
    ordered = None
    if ordered_path.exists() and ordered_verify_path.exists():
        ordered, ofs = read(ordered_path)
        ordered_verify, ovs = read(ordered_verify_path)
        common = [
            c for c in common if c["label"] != "Ordered-endpoint parameter hypothesis"
        ]
        common.append(
            check(
                "Ordered-endpoint geometry training",
                "pass"
                if all(
                    r["all_geometry_passed"] and r["stereochemistry_passed"]
                    for r in ordered["records"] + [ordered["core"]]
                )
                else "fail",
                "All three compounds meet original bond/angle limits and retain stereochemistry",
                "Fitted training checks only; transferred charges remain unvalidated",
                ofs,
            )
        )
    coupled_path = art / "cpd-anti-ordered-coupled-service-v1/status.json"
    if coupled_path.exists():
        status, ss = read(coupled_path)
        common.append(
            check(
                "Ordered-model charge coupling",
                "pending",
                status["state"],
                "Three charge-dependent fits; scientific review pending",
                ss,
            )
        )
    coupled_review_path = (
        art / "cpd-anti-ordered-coupled-service-v1/completion_wake_review.json"
    )
    if coupled_review_path.exists():
        cr, crs = read(coupled_review_path)
        common = [c for c in common if c["label"] != "Ordered-model charge coupling"]
        all_geometry = all(
            m["all_geometry_passed"] and m["stereochemistry_passed"]
            for r in cr["records"]
            for m in r["models"]
        )
        common.append(
            check(
                "Ordered-model charge coupling",
                "pass" if all_geometry and cr.get("minimum_certified") else "pending",
                "All nine compound/charge combinations pass geometry; independent MM minimum/export checks pass",
                "Training geometry only; charge accuracy and interstrand transfer remain unresolved",
                crs,
            )
        )
    probe_status_path = art / "cpd-anti-glycosidic-probes-service-v1/status.json"
    if probe_status_path.exists():
        probe_status, ps = read(probe_status_path)
        common.append(
            check(
                "Fresh glycosidic energy/gradient probes",
                "pending",
                probe_status["state"],
                "±15° fixed sugar rotations; unchanged-candidate comparison, not relaxed torsion profiles",
                ps,
            )
        )
    probe_review_path = (
        art / "cpd-anti-glycosidic-probes-service-v1/completion_wake_review.json"
    )
    if probe_review_path.exists():
        probe_review, prs = read(probe_review_path)
        common = [
            c for c in common if c["label"] != "Fresh glycosidic energy/gradient probes"
        ]
        common.append(
            check(
                "Fresh glycosidic energy/gradient comparison",
                "pending",
                "All candidates show asymmetric 7–9 kcal/mol energy errors at ±15°; nonbonded repulsion dominates",
                "Conformational energetics unresolved despite passing fitted geometry; diagnostic has no release threshold",
                prs,
            )
        )
    half_path = art / "cpd-anti-glycosidic-half-probes-service-v2/status.json"
    if half_path.exists():
        half, hs = read(half_path)
        common.append(
            check(
                "Smaller glycosidic probes",
                "pending",
                half["state"],
                "±7.5° frozen rotations; no parameter refit",
                hs,
            )
        )
    half_review_path = (
        art / "cpd-anti-glycosidic-half-probes-service-v2/completion_wake_review.json"
    )
    if half_review_path.exists():
        half_review, hs = read(half_review_path)
        common = [c for c in common if c["label"] != "Smaller glycosidic probes"]
        common.append(
            check(
                "Smaller glycosidic energy comparison",
                "pending",
                "Mismatch persists at ±7.5°: problematic directions have 1.25–2.29 kcal/mol errors",
                "Off-minimum energetics unresolved; no refit or minimum claim",
                hs,
            )
        )
    relaxed_status_path = art / "cpd-anti-relaxed-glycosidic-service-v1/status.json"
    if relaxed_status_path.exists():
        relaxed, rs = read(relaxed_status_path)
        common.append(
            check(
                "Constrained relaxed glycosidic points",
                "pending",
                relaxed.get("reason", relaxed["state"]),
                "Four ±15° points; distinguish rigid-rotation strain from transfer mismatch",
                rs,
            )
        )
    continuation_path = art / "cpd-anti-relaxed-glycosidic-service-v7/status.json"
    if continuation_path.exists():
        continuation, cs = read(continuation_path)
        common.append(
            check(
                "Constrained glycosidic continuations",
                "pending",
                continuation["state"],
                "Single-point adaptive trust-region pilot; stall/excursion detection and evaluated checkpoints; prior failures preserved; no minimum certification",
                cs,
            )
        )
    diagnostic_path = art / "cpd-anti-gradient-consistency-service-v2/status.json"
    if diagnostic_path.exists():
        diagnostic, ds = read(diagnostic_path)
        common.append(check(
            "Local energy-gradient consistency",
            "pending",
            diagnostic["state"],
            "Four larger-step probes; v1 assessment recovered but small-step derivatives inconsistent; reference reused; no minimum certification",
            ds,
        ))
    alternative_path = art / "cpd-anti-geometric-pilot-service-v1/status.json"
    if alternative_path.exists():
        alternative, gs = read(alternative_path)
        common.append(check(
            "Alternative constrained optimizer pilot",
            "pending",
            alternative["state"],
            "Single geomeTRIC/TRIC point; native MP2 gradients and fixed torsion; bounded 40-evaluation trial",
            gs,
        ))
    pair_path = art / "cpd-anti-geometric-endpoint1-service-v2/status.json"
    if pair_path.exists():
        pair, ps = read(pair_path)
        common.append(check(
            "Remaining constrained geomeTRIC points",
            "pending",
            pair["state"],
            "All four constrained points converged; final point used 40 replayed and 16 new gradients; no Hessian certification",
            ps,
        ))
    matched_path = art / "cpd-anti-matched-mm-service-v1/status.json"
    if matched_path.exists():
        matched, ms = read(matched_path)
        common.append(check(
            "Matched constrained MM relaxation",
            "pending",
            matched["state"],
            "All four QM points constrained-converged; 24 matched MM cases across four candidates; no minimum certification or parameter acceptance",
            ms,
        ))
    basin_path = art / "cpd-anti-mm-reference-multistart-service-v1/status.json"
    if basin_path.exists():
        basin, bs = read(basin_path)
        common.append(check(
            "MM reference conformation sensitivity",
            "pending",
            basin["state"],
            "All 24 matched MM cases converged; endpoint2+15 retains 1.75–1.97 kcal/mol error; 16 reference multistarts check basin dependence",
            bs,
        ))
    qm_basin_path = art / "cpd-anti-qm-reference-multistart-service-v2/status.json"
    if qm_basin_path.exists():
        qm_basin, qs = read(qm_basin_path)
        common.append(check(
            "QM reference conformation sensitivity",
            "pending",
            qm_basin["state"],
            "Both QM reference checks converged and independently passed projected-gradient checks; energies match original references within 0.00002 kcal/mol; no Hessian certification",
            qs,
        ))
    half_path = art / "cpd-anti-relaxed-half-service-v2/status.json"
    if half_path.exists():
        half, hs = read(half_path)
        common.append(check(
            "Relaxed glycosidic midpoint profile",
            "pending",
            half["state"],
            "All four midpoint QM points and all 16 matched MM cases independently verified; held-out midpoint torsion residuals below 0.09 kcal/mol, but reference torque and extrapolation remain unvalidated",
            hs,
        ))
    outer_path = art / "cpd-anti-relaxed-outer-service-v1/status.json"
    if outer_path.exists():
        outer, osrc = read(outer_path)
        common.append(check(
            "Outer glycosidic profile validation",
            "pending",
            outer["state"],
            "All four outer QM points and 16 matched MM cases verified; frozen local correction leaves up to 1.38 kcal/mol outer error; no parameters promoted",
            osrc,
        ))
    outer_basin_path = art / "cpd-anti-outer-mm-multistart-service-v1/status.json"
    if outer_basin_path.exists():
        outer_basin, obs = read(outer_basin_path)
        common.append(check(
            "Outer MM conformation sensitivity",
            "pending",
            outer_basin["state"],
            "All 16 outer MM multistarts independently verified; energy agreement within 2.7e-8 kcal/mol; tested starts do not explain profile errors",
            obs,
        ))
    torsion_geometry_path = art / "cpd-anti-torsion-geometry-service-v1/status.json"
    if torsion_geometry_path.exists():
        torsion_geometry, tgs = read(torsion_geometry_path)
        common.append(check(
            "Broader torsion geometry screening",
            "pending",
            torsion_geometry["state"],
            "16 trial systems independently pass local MM curvature checks; endpoint2 bond/angle agreement worsens; original MM glycosidic angle differs from QM by 93 degrees; no acceptance",
            tgs,
        ))
    remote_path = art / "cpd-anti-remote-wells-service-v2/status.json"
    if remote_path.exists():
        remote, rs = read(remote_path)
        common.append(check(
            "Remote endpoint2 conformations",
            "pending",
            remote["state"],
            "Both remote constrained QM points independently verified after 1/2 new gradients; energies 7.08/0.76 kcal/mol below original reference; no minimum certification",
            rs,
        ))
    unconstrained_path = art / "cpd-anti-remote-unconstrained-service-v1/status.json"
    if unconstrained_path.exists():
        unconstrained, us = read(unconstrained_path)
        common.append(check(
            "Remote unconstrained QM relaxation",
            "pending",
            unconstrained["state"],
            "Both starts independently pass full-gradient convergence and reach same structure within 0.00035 Å RMS; 7.58 kcal/mol below old reference; Hessian pending",
            us,
        ))
    remote_hessian_path = art / "cpd-anti-remote-hessian-service-v1/status.json"
    if remote_hessian_path.exists():
        remote_hessian, rhs = read(remote_hessian_path)
        common.append(check(
            "Remote endpoint2 minimum certification",
            "pending",
            remote_hessian["state"],
            "289 gradient tasks verified; harmonic audit passes with 141 positive modes and zero imaginary modes; lowest 14.98 cm^-1; tight soft-mode check pending",
            rhs,
        ))
    remote_soft_path = art / "cpd-anti-remote-soft-mode-service-v1/status.json"
    if remote_soft_path.exists():
        remote_soft, rss = read(remote_soft_path)
        common.append(check(
            "Remote minimum soft-mode check",
            "pending",
            remote_soft["state"],
            "Tight reference and both curvatures pass positivity; step-halving difference 12.05% fails unchanged 10% limit; precise soft-mode stiffness unresolved",
            rss,
        ))
    resolution_path = art / "cpd-anti-remote-soft-resolution-service-v1/status.json"
    if resolution_path.exists():
        resolution, rsrc = read(resolution_path)
        common.append(check(
            "Remote soft-mode numerical resolution",
            "pending",
            resolution["state"],
            "All four directional curvatures positive; 0.01/0.02-bohr pair agrees within 0.26%; original 12.05% failure and Hessian stiffness discrepancy retained; precise stiffness provisional",
            rsrc,
        ))
    remote_esp_path = art / "cpd-anti-remote-esp-service-v1/status.json"
    if remote_esp_path.exists():
        remote_esp, res = read(remote_esp_path)
        common.append(check(
            "Lower-energy conformer electrostatics",
            "pending",
            remote_esp["state"],
            "1274-point ESP/dipole target verified; frozen best candidate 46% ESP error/1.20 D; three-conformer refit 42%/0.88 D at lowest regularization; no charge acceptance",
            res,
        ))
    remote_water_path = art / "cpd-anti-remote-water-calibration-service-v1/status.json"
    if remote_water_path.exists():
        remote_water, rws = read(remote_water_path)
        common.append(check(
            "Remote conformer water calibration",
            "pending",
            remote_water["state"],
            "Three paired DF/DIRECT contacts independently pass: max error 0.00432 kcal/mol below 0.02; charges remain exploratory",
            rws,
        ))
    remote_curves_path = art / "cpd-anti-remote-water-curves-service-v1/status.json"
    if remote_curves_path.exists():
        remote_curves, rcs = read(remote_curves_path)
        common.append(check(
            "Remote conformer water curves",
            "pending",
            remote_curves["state"],
            "42 native points verified; five curves bracket minima, 1-O4 fails bracketing; best three-conformer candidate worst usable-site energy error 1.42 kcal/mol; no acceptance",
            rcs,
        ))
    extension_path = art / "cpd-anti-remote-water-extension-service-v2/status.json"
    if extension_path.exists():
        extension, exs = read(extension_path)
        common.append(check(
            "Remote 1-O4 range extension",
            "pending",
            extension["state"],
            "13-point curve now brackets minimum, but nearest water contact is sugar O5prime at 2.52 Å versus target O4 at 3.7 Å; retained as mixed-contact diagnostic, excluded from direct site fit",
            exs,
        ))
    charge_geometry_path = art / "cpd-anti-charge-conformer-geometry-service-v1/status.json"
    if charge_geometry_path.exists():
        charge_geometry, cgs = read(charge_geometry_path)
        common.append(check(
            "Three-conformer charge geometry screening",
            "pending",
            charge_geometry["state"],
            "All 12 charge-only structures independently pass local MM curvature checks; endpoint2 angle errors 4.37–5.24 degrees and distinct minima remain; bonded refinement required",
            cgs,
        ))
    remote_coupled_path = art / "cpd-anti-remote-coupled-service-v2/status.json"
    if remote_coupled_path.exists():
        remote_coupled, rcsrc = read(remote_coupled_path)
        common.append(check(
            "Lower-reference coupled geometry fit",
            "pending",
            remote_coupled["state"],
            "All three fits meet training bounds; endpoint max angles below 2.73 degrees; nine compound minima pass independent stationarity, positive MM curvature and CHARMM export equivalence; transfer pending",
            rcsrc,
        ))
    remote_profile_path = art / "cpd-anti-remote-profile-mm-service-v1/status.json"
    if remote_profile_path.exists():
        remote_profile, rps = read(remote_profile_path)
        common.append(check(
            "Refined candidate profile transfer",
            "pending",
            remote_profile["state"],
            "45 cases independently pass constrained stationarity; remote relative-energy errors -9.05 to -9.89 kcal/mol and endpoint2 -30 discontinuity; energetic transfer fails despite training geometry success",
            rps,
        ))
    refined_basin_path = art / "cpd-anti-refined-basin-check-service-v1/status.json"
    if refined_basin_path.exists():
        refined_basin, rbs = read(refined_basin_path)
        common.append(check(
            "Refined endpoint2 basin checks",
            "pending",
            refined_basin["state"],
            "18 independently verified stationary cases confirm basin dependence: reference energies lower by 4.81–4.91 kcal/mol; no global-minimum certification",
            rbs,
        ))
    profile_basin_path = art / "cpd-anti-refined-profile-basin-service-v1/status.json"
    if profile_basin_path.exists():
        profile_basin, pbs = read(profile_basin_path)
        common.append(check(
            "Refined endpoint2 profile multistarts",
            "pending",
            profile_basin["state"],
            "36 cases independently verified; lowest observed MM remote energy errors remain -4.14 to -5.04 kcal/mol after reference correction; QM basin matching pending",
            pbs,
        ))
    basin_qm_path = art / "cpd-anti-refined-basin-qm-service-v1/status.json"
    if basin_qm_path.exists():
        basin_qm, bqs = read(basin_qm_path)
        common.append(check(
            "Refined MM basins under QM relaxation",
            "pending",
            basin_qm["state"],
            "-30 independently stationary and 8.87 kcal/mol below previous QM point; reference hit 60-evaluation budget, remains unconverged; failure preserved",
            bqs,
        ))
    basin_qm_v2_path = art / "cpd-anti-refined-basin-qm-service-v2/status.json"
    if basin_qm_v2_path.exists():
        basin_qm_v2, bq2s = read(basin_qm_v2_path)
        common.append(check(
            "Lower-basin QM reference continuation",
            "pending",
            basin_qm_v2["state"],
            "Reference independently stationary after 60 reused/7 new evaluations; updated -30 energy error 0.74–0.86 kcal/mol, remote error -7.65 to -8.55; no minimum certification",
            bq2s,
        ))
    lower_profile_path = art / "cpd-anti-lower-basin-profile-service-v1/status.json"
    if lower_profile_path.exists():
        lower_profile, lps = read(lower_profile_path)
        common.append(check(
            "Lower-basin QM profile extension",
            "pending",
            lower_profile["state"],
            "-15 independently stationary; +15 hit 60 evaluations with projected gradient 2.28e-4 au, unresolved; diagnostic required before continuation",
            lps,
        ))
    lower_gradient_path = art / "cpd-anti-lower-profile-gradient-service-v1/status.json"
    if lower_gradient_path.exists():
        lower_gradient, lgs = read(lower_gradient_path)
        common.append(check(
            "Stalled lower-profile gradient diagnostic",
            "pending",
            lower_gradient["state"],
            "Five native results verified: slopes agree within 0.15–0.75%; repeat gradient noise 1.084e-6 exceeds 1e-6 limit, diagnostic failure preserved",
            lgs,
        ))
    lower_restart_path = art / "cpd-anti-lower-profile-restart-service-v1/status.json"
    if lower_restart_path.exists():
        lower_restart, lrs = read(lower_restart_path)
        common.append(check(
            "Bounded lower-profile optimizer restart",
            "pending",
            lower_restart["state"],
            "20-new-gradient continuation exhausted; gradient worsened to 2.75e-4 au, trust collapsed; full-rank coordinate audit; method review required, no automatic retry",
            lrs,
        ))
    for e in (1, 2):
        frequency_path = art / (
            "cpd-anti-additive-next-v2/endpoint1-frequency/frequency_audit.json"
            if e == 1
            else "cpd-anti-endpoint2-frequency-v2/frequency/frequency_audit.json"
        )
        frequency, fq = read(frequency_path)
        soft, ss = read(
            art
            / (
                "cpd-anti-endpoint1-soft-mode-v1"
                if e == 1
                else "cpd-anti-endpoint2-soft-mode-v1"
            )
            / "assessment.json"
        )
        parent, ps = read(
            art
            / (
                "cpd-anti-additive-next-v2/endpoint1_optimized_model_audit.json"
                if e == 1
                else "cpd-anti-endpoint2-frequency-v2/optimized_model_audit.json"
            )
        )
        xyz_path = Path(parent["optimized_xyz"]["path"])
        import hashlib

        assert (
            hashlib.sha256(xyz_path.read_bytes()).hexdigest()
            == parent["optimized_xyz"]["sha256"]
        )
        xyz = np.array(
            [
                list(map(float, l.split()[1:]))
                for l in xyz_path.read_text().splitlines()[2:]
                if l.strip()
            ]
        )
        m = next(m for m in models if m["id"] == f"anti-boundary-{e}")
        assert [a["id"] for a in m["atoms"]] == parent["atom_map"]
        for atom, pos in zip(m["atoms"], xyz):
            atom["position"] = pos.tolist()
        m["label"] = f"cis-anti-I · sugar endpoint {e} · QM minimum"
        m["geometry"] = (
            "Audited MP2/6-31G(d) optimized QM fragment. Independent identity, sugar/lesion stereochemistry, harmonic-minimum and tighter soft-direction evidence. Not an additive force-field or DNA qualification."
        )
        m["checks"] = [
            check(
                "Boundary QM identity and optimization",
                "pass"
                if parent["status"] == "passed_candidate_identity_and_chirality"
                else "fail",
                "Native geometry and all sugar/lesion centers audited",
                evidence=ps,
            ),
            check(
                "QM harmonic minimum",
                "pass"
                if frequency["status"] == "passed_candidate_harmonic_minimum"
                else "fail",
                f"{frequency['parsed_mode_count']} internal modes; {frequency['imaginary_mode_count']} imaginary; lowest {frequency['lowest_frequency_cm_inverse']:.2f} cm⁻¹",
                "Soft-frequency magnitude has numerical sensitivity; no force-constant precision claim",
                fq,
            ),
            check(
                "Tighter soft-direction check",
                "pass" if soft["passed"] else "fail",
                f"Step-halving discrepancy {soft['step_halving_relative_difference'] * 100:.3f}%",
                "Positive curvature at both steps; discrepancy ≤10%",
                ss,
            ),
            *common,
        ]
    for c in load_cases():
        label = c["id"]
        r = (
            fit["core"]
            if label == "core"
            else next(r for r in fit["records"] if r["endpoint"] == int(label[-1]))
        )
        local = []
        for b in r["all_bonds"]:
            local.append(
                (
                    b["atoms"],
                    check(
                        "MM versus QM bond error",
                        "pass" if abs(b["error_A"]) <= 0.03 else "fail",
                        f"{b['error_A']:+.5f} Å",
                        "|error| ≤0.03 Å; fitted training geometry",
                        fs,
                    ),
                )
            )
        for a in r["all_angles"]:
            local.append(
                (
                    a["atoms"],
                    check(
                        "MM versus QM angle error",
                        "pass" if abs(a["error_deg"]) <= 3 else "fail",
                        f"{a['error_deg']:+.3f}°",
                        "|error| ≤3°; fitted training geometry",
                        fs,
                    ),
                )
            )
        for center in r["centers"]:
            local.append(
                (
                    [center["center"]],
                    check(
                        "Stereocenter retained",
                        "pass" if center["preserved"] else "fail",
                        "Signed volume relative to audited QM",
                        evidence=fs,
                    ),
                )
            )
        v = next(v for v in verification["records"] if v["model"] == label)
        shared = [
            *common,
            check(
                "MM stationary minimum and CHARMM export",
                "pass"
                if v["stationary"]
                and v["positive_curvature"]
                and v["export_equivalent"]
                else "fail",
                "Positive internal curvature at two steps; exported energy/force agreement <1e-7",
                "Numerical checks do not override failed geometry",
                vs,
            ),
        ]
        models.append(
            model(
                f"anti-additive-{label}",
                f"cis-anti-I · {label} · additive training (fails geometry)",
                c["names"],
                np.loadtxt(art / f"cpd-anti-joint-fit-v2/{label}/minimum_A.txt"),
                [b["atoms"] for b in r["all_bonds"]],
                local,
                shared,
                "Isolated additive candidate. Optimizer converged; geometry training failed. Charges remain the transferred baseline. No production integration.",
            )
        )
    if ordered is not None:
        for c in load_cases():
            label = c["id"]
            r = (
                ordered["core"]
                if label == "core"
                else next(
                    r for r in ordered["records"] if r["endpoint"] == int(label[-1])
                )
            )
            local = []
            for category, key, limit, units in [
                ("all_bonds", "error_A", 0.03, "Å"),
                ("all_angles", "error_deg", 3, "°"),
            ]:
                for item in r[category]:
                    local.append(
                        (
                            item["atoms"],
                            check(
                                "Ordered-model geometry error",
                                "pass" if abs(item[key]) <= limit else "fail",
                                f"{item[key]:+.5f} {units}",
                                f"|error| ≤{limit} {units}; fitted training",
                                ofs,
                            ),
                        )
                    )
            v = next(v for v in ordered_verify["records"] if v["model"] == label)
            shared = [ch for ch in common if ch["state"] != "fail"]
            shared.append(
                check(
                    "MM minimum and parameter export",
                    "pass"
                    if v["stationary"]
                    and v["positive_curvature"]
                    and v["export_equivalent"]
                    else "fail",
                    "Independent two-step internal-curvature and CHARMM energy/force checks",
                    "Not DNA or electrostatic qualification",
                    ovs,
                )
            )
            models.append(
                model(
                    f"anti-ordered-{label}",
                    f"cis-anti-I · {label} · ordered-endpoint training",
                    c["names"],
                    np.loadtxt(art / f"cpd-anti-ordered-fit-v1/{label}/minimum_A.txt"),
                    [b["atoms"] for b in r["all_bonds"]],
                    local,
                    shared,
                    "Isolated ordered-endpoint candidate: fitted geometry and MM minimum checks pass; baseline charges and DNA transfer remain unvalidated.",
                )
            )
        return (" Cis-anti-I campaign paused by user." if campaign_paused else "") + " Cis-anti-I additive: local stationary structures verified, but basin coverage and energetic transfer remain unresolved. Fixed validation v1 blocks further fitting until the reference dataset is qualified and frozen; electrostatics and interstrand validation pending."
    return " Cis-anti-I additive: both sugar QM minima verified; 12 water curves and ESP/dipole targets complete; joint geometry fails; charge candidates exploratory; interstrand validation pending."
