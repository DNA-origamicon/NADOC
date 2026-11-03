"""Shared time-to-results and billing model. Ranges are planning scenarios, not CIs.

Compute, engine startup, preparation, processing and transport have separate
clocks. In particular, S3 transfers outside a pod lifetime cannot incur GPU rent.
Unknown queues remain unknown; a scheduler walltime cap is never a job duration.
"""

import math

from backend.core.namd_planning import stage_dicts, stage_resident
from backend.core.namd_pme import pme_grid


def stage_rate(
    n_atoms,
    stage,
    *,
    resident_ms,
    resident=True,
    box_nm=None,
    local=False,
    devices="0",
    threads=16,
):
    """ms/step with hardware identity checked before using local measurements."""
    mode = stage_resident(stage, resident)
    role = (
        "minimization"
        if stage.get("role") == "minimization"
        else "resident"
        if mode
        else "offload"
    )
    pair = float(stage.get("pairlistdist", 13.5))
    spacing = float(stage.get("pmegridspacing", 1.5))
    grid = pme_grid([v * 10 for v in box_nm], spacing) if box_nm else None
    basis = "hardware prior"
    calibrated = False
    startup = 3 + n_atoms / 1e6 * 2
    low, high = 0.5, 2.0
    if local:
        from backend.core.namd_timing import _evidence, matches_local

        evidence = _evidence()
        observed = evidence.get("offload_long_case", {})
        if (
            role == "offload"
            and observed
            and threads == observed["threads"]
            and matches_local(
                {**evidence["provenance"], "threads": threads},
                devices=devices,
                threads=threads,
            )
            and abs(n_atoms / observed["atoms"] - 1) < 0.01
            and grid
            and list(grid) == observed["grid"]
            and pair == observed["pairlistdist"]
            and stage.get("margin", 3) == observed["margin"]
        ):
            return dict(
                ms=observed["ms_per_step"],
                low_ms=observed["low_ms"],
                high_ms=observed["high_ms"],
                startup_s=startup,
                basis=observed["basis"],
                calibrated=True,
                mode=role,
            )
        if matches_local(evidence["provenance"], devices=devices, threads=threads):
            model = next(
                (m for m in evidence.get("stage_models", []) if m["mode"] == role), None
            )
            if (
                model
                and (
                    model["atoms"][0] <= n_atoms <= model["atoms"][1]
                    or (
                        role == "resident"
                        and pair <= 13.5
                        and spacing >= 1.5
                        and evidence["points"][0]["atoms"]
                        <= n_atoms
                        <= evidence["points"][-1]["atoms"]
                    )
                )
                and spacing >= 0.75
                and pair <= 24
                and (
                    not grid
                    or (
                        math.prod(grid) / n_atoms
                        <= model["max_pme_points_per_atom"] * 1.05
                        and max(grid) / min(grid)
                        <= max(12, model["max_grid_aspect"]) * 1.05
                    )
                )
            ):
                # Fitted nonnegative terms: fixed, atoms, neighbor volume, FFT work.
                points = math.prod(grid) if grid else n_atoms * 3
                x = [
                    1,
                    n_atoms / 1e6,
                    n_atoms / 1e6 * (pair / 13.5) ** 3,
                    points * math.log2(max(2, points)) / 2e7,
                ]
                ms = sum(a * b for a, b in zip(x, model["coefficients"]))
                if role == "resident" and pair <= 13.5 and spacing >= 1.5:
                    # The longer standard probes better represent sustained late
                    # dynamics than the geometry pilot's short stage intervals.
                    from backend.core.namd_timing import local_step_ms

                    ms = local_step_ms(n_atoms, devices=devices, threads=threads) or ms

                ratios = model["ratio_range"]
                low, high = min(0.8, ratios[0] * 0.9), max(1.5, ratios[1] * 1.15)
                startup = max(startup, model["startup_s"])
                basis = "current local engine/GPU/driver/threads; geometry holdouts"
                calibrated = True
    if not calibrated:
        if resident_ms is None:
            return None
        # Explicit prior for geometry effects and unmeasured execution paths.
        pme_ratio = max(
            1, (math.prod(grid) / (3 * n_atoms)) if grid else (1.5 / spacing) ** 3
        )
        # Allocation volume grows faster than per-step force work: the cutoff
        # stays fixed and neighbor rebuilding/FFT work is only part of a step.
        # Sublinear prior checked against the 22 current RTX 6000 Ada probes.
        geometry = (
            0.65
            + 0.2 * math.sqrt(max(1, (pair / 13.5) ** 3))
            + 0.15 * math.sqrt(pme_ratio)
        )
        ms = resident_ms * (1 if mode else 2.6) * geometry
        if not local:
            # Boundary cloud probes spent ~50–90 s starting the fine-PME
            # 3 M-atom cases. A local warm-start allowance cannot cover this.
            startup = max(
                startup,
                (15 + n_atoms / 1e6 * 12) * (max(1, pme_ratio / 4) if mode else 1),
            )
        if not mode:
            high = 3.0
            basis += "; offload/minimization is CPU-sensitive"
    return dict(
        ms=ms,
        low_ms=ms * low,
        high_ms=ms * high,
        startup_s=startup,
        basis=basis,
        calibrated=calibrated,
        mode=role,
    )


def local_compute(
    n_atoms, stages, *, box_nm=None, resident=True, devices="0", threads=16
):
    from backend.core import namd_timing

    # Thread count changes disable the calibrated models, but a labelled prior
    # on the same device is useful for comparison. CPU-only remains unknown.
    matched = namd_timing.matches_local(
        namd_timing._evidence()["provenance"], devices=devices, threads=16
    )
    base = n_atoms / 1e6 * 22 if matched else None
    return compute_estimate(
        stages,
        lambda s: stage_rate(
            n_atoms,
            s,
            resident_ms=base,
            resident=resident,
            box_nm=box_nm,
            local=True,
            devices=devices,
            threads=threads,
        ),
    )


def compute_estimate(stages, rate_for_stage):
    rows = []
    for stage in stage_dicts(stages):
        steps = int(stage.get("steps") or 0)
        if not steps:
            continue
        rate = rate_for_stage(stage)
        if rate is None:
            return None
        rows.append(
            dict(
                role=stage.get("role") or "relaxation",
                steps=steps,
                **rate,
                hours=steps * rate["ms"] / 3.6e6,
                low_hours=steps * rate["low_ms"] / 3.6e6,
                high_hours=steps * rate["high_ms"] / 3.6e6,
            )
        )
    if not rows:
        return None
    return dict(
        hours=sum(r["hours"] for r in rows),
        low_hours=sum(r["low_hours"] for r in rows),
        high_hours=sum(r["high_hours"] for r in rows),
        startup_hours=sum(r["startup_s"] for r in rows) / 3600,
        calibrated=all(r["calibrated"] for r in rows),
        stages=rows,
    )


def completion_quote(
    compute,
    *,
    target,
    n_atoms,
    stages,
    prepared=False,
    package_bytes=0,
    output_bytes=0,
    upload_mbps=11,
    download_mbps=50,
    transfer_mode="ssh",
    hourly_rate=None,
    volume_size_gb=None,
    queue_hours=None,
    submissions=1,
):
    """Time until local results; only components within the allocation are billed.

    Upload/download rates and remote setup are explicit editable assumptions.
    The compressed package size is unknown before prep: 400 B/atom is a planning
    proxy, not a claim about actual compressed size. Full result size is used for
    download, conservatively without claiming a compression ratio.
    """
    if not compute:
        return dict(
            available=False,
            reason="No timing coverage for this hardware or stage plan.",
        )
    work = stage_dicts(stages)
    count = max(1, sum(bool(s.get("steps")) for s in work))
    remote = target != "local"
    s3 = target == "runpod" and transfer_mode == "s3"
    components = []

    def add(name, hours, low, high, billed=False, basis="planning assumption"):
        components.append(
            dict(
                name=name,
                hours=hours,
                low_hours=low,
                high_hours=high,
                billed=billed,
                basis=basis,
            )
        )

    # Current optimized prep: ~50 s at 2.93 M atoms. Includes wider cold-start/I/O slack.
    prep = 0 if prepared else (20 + n_atoms / 1e6 * 17) / 3600
    add(
        "Preparation",
        prep,
        prep * 0.5,
        prep * 3,
        basis="optimized local prep measurements, scaled; cold I/O allowance",
    )
    if remote:
        size = package_bytes or int(n_atoms * 400)
        upload = size * 8 / (upload_mbps * 1e6) / 3600
        download = output_bytes * 8 / (download_mbps * 1e6) / 3600
        add(
            "Upload",
            upload,
            upload * 0.5,
            upload * 2,
            target == "runpod" and not s3,
            "provided bytes"
            if package_bytes
            else "400 B/atom package proxy; compression/reuse unknown",
        )
        setup = (5 if target == "runpod" else 1) / 60 * submissions
        add("Remote setup", setup, setup * 0.4, setup * 3, True)
    add(
        "Simulation",
        compute["hours"],
        compute["low_hours"],
        compute["high_hours"],
        remote,
        "per-stage steps, execution mode and target throughput",
    )
    startup = compute["startup_hours"]
    add("Engine startup", startup, startup * 0.5, startup * 3, remote)
    # Health/playback serialized at stage boundaries. Do not add concurrent checks
    # to measured simulation time; these are the required boundary/final checks.
    health = count * (3 + n_atoms / 1e6 * 5) / 3600
    add(
        "Stage health checks",
        health,
        health * 0.5,
        health * 3,
        remote,
        "optimized health measurements scaled per stage; periodic overlapping checks excluded",
    )
    if remote:
        add(
            "Download results",
            download,
            download * 0.5,
            download * 2,
            target == "runpod" and not s3,
            "full trajectory/restart byte forecast; configured downstream rate",
        )
        add(
            "Local result processing",
            health / count,
            health / count * 0.5,
            health / count * 3,
        )
    # Playback preprocessing is roughly I/O proportional; sustained 100 MiB/s is
    # an assumption, exposed separately so a slow disk cannot masquerade as GPU cost.
    io = output_bytes / (100 * 1024**2) / 3600
    add(
        "Trajectory processing",
        io,
        io * 0.5,
        io * 4,
        basis="100 MiB/s local I/O assumption",
    )
    known = sum(c["hours"] for c in components)
    low = sum(c["low_hours"] for c in components)
    high = sum(c["high_hours"] for c in components)
    billed = sum(c["hours"] for c in components if c["billed"])
    billed_low = sum(c["low_hours"] for c in components if c["billed"])
    billed_high = sum(c["high_hours"] for c in components if c["billed"])
    unknown = []
    if target == "alpine" and queue_hours is None:
        unknown.append("Queue wait for each submission")
    if target == "runpod":
        unknown.append("GPU capacity wait before rental")
    queue = (queue_hours or 0) * submissions
    rate = hourly_rate if remote else 0
    container_rate = 0
    if target == "runpod":
        from backend.core.runpod_api import DEFAULT_CONTAINER_DISK_GB

        container_rate = DEFAULT_CONTAINER_DISK_GB * 0.10 / 730
    total_rate = None if rate is None else rate + container_rate
    # Network volume rent persists after completion. This is allocated-volume
    # cost for this time window, not an incremental per-job storage purchase.
    storage_rate = (
        (min(volume_size_gb, 1000) * 0.07 + max(0, volume_size_gb - 1000) * 0.05) / 730
        if target == "runpod" and volume_size_gb
        else None
    )
    return dict(
        available=True,
        target=target,
        components=components,
        known_hours=known,
        low_hours=low,
        high_hours=high,
        completion_hours=None if unknown else known + queue,
        unknown=unknown,
        queue_hours=queue_hours,
        submissions=submissions,
        billed_hours=billed,
        billed_low_hours=billed_low,
        billed_high_hours=billed_high,
        cost=None if total_rate is None else billed * total_rate,
        low_cost=None if total_rate is None else billed_low * total_rate,
        high_cost=None if total_rate is None else billed_high * total_rate,
        pod_compute_cost=None if rate is None else billed * rate,
        container_disk_cost=billed * container_rate,
        cost_unit="SU" if target == "alpine" else "USD",
        storage_window_cost=math.ceil(known) * storage_rate if storage_rate else None,
        storage_monthly_cost=storage_rate * 730 if storage_rate else None,
        storage_basis="Standard network-volume tier; 730-hour month; premium storage/tax not included",
        transfer_mode=transfer_mode if remote else None,
        assumptions=dict(
            upload_mbps=upload_mbps,
            download_mbps=download_mbps,
            prepared=prepared,
            package_bytes_estimated=not bool(package_bytes),
        ),
        calibrated_compute=compute["calibrated"],
        confidence=None,
        note="Planning range, not a completion or cost guarantee. Retries, physical convergence extensions and local contention are additional."
        + (
            " Local electricity/hardware costs are excluded."
            if target == "local"
            else ""
        )
        + (
            " Network-volume rent continues until deleted; storage is separate from the pod cap."
            if target == "runpod"
            else ""
        ),
    )
