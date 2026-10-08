"""Calibrate VR free-draw against seeded controller stress profiles.

The C++ adapter calls the production smoother and spline sampler. Its generated
traces are synthetic stress cases, never measured human/controller accuracy.
Run: python -m tools.vr_motion.sweep_calibration --output /tmp/sweep-calibration.json
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from .model import reach, validate_trace
from .metrics import rotate
from .presets import PRESETS

SHAPES = ("line", "s-curve", "arc")
ROOT = Path(__file__).resolve().parents[2]


def curve(u, shape, length_m=.3):
    if shape == "line":
        return [0., 0., -length_m*u]
    if shape == "s-curve":
        return [length_m*.22*math.sin(2*math.pi*u),
                length_m*.18*math.sin(math.pi*u), -length_m*u]
    if shape == "arc":
        return [length_m*.5*(1-math.cos(math.pi*u)),
                length_m*.25*u, -length_m*.5*math.sin(math.pi*u)]
    raise ValueError(f"Unknown stroke shape: {shape}")


def calibration_stroke(shape="s-curve", preset="variable_fast", seed=0, *, rate_hz=90):
    """One held-trigger stroke with existing OU noise, timing and overshoot."""
    duration, profile = PRESETS[preset]
    trace = reach([0, 0, 0], [0, 0, 0], duration_s=duration*2,
                  profile=profile, seed=seed, rate_hz=rate_hz)
    progress = reach([0, 0, 0], [1, 0, 0], duration_s=duration*2,
                     profile=replace(profile, position_sigma_m=0, rotation_sigma_deg=0),
                     seed=seed, rate_hz=rate_hz)
    ideal = []
    for sample, phase in zip(trace["samples"], progress["samples"]):
        position = curve(phase["hands"]["right"]["position"][0], shape)
        ideal.append(position)
        hand = sample["hands"]["right"]
        hand["position"] = [p+n for p, n in zip(position, hand["position"])]
    trace["events"] = [dict(t=0., hand="right", button="trigger", pressed=True),
                       dict(t=trace["samples"][-1]["t"], hand="right", button="trigger", pressed=False)]
    trace["provenance"].update(shape=shape, preset=preset,
                               kind="synthetic_uncalibrated_sweep", ideal_points_m=ideal)
    validate_trace(trace, playable=True)
    return trace


ADAPTER = r'''
#include "sweep_draft.hpp"
#include <iostream>
#include <iomanip>
int main(int argc, char** argv) {
    nadoc_vr::FreeDrawSettings settings;
    if(argc>1)settings.smoothingRadiusNm=std::stof(argv[1]);
    if(argc>2)settings.simplifyToleranceNm=std::stof(argv[2]);
    if(argc>3)settings.sampleSpacingNm=std::stof(argv[3]);
    size_t n;std::cin>>n;std::vector<glm::vec3> raw(n);
    for(auto& p:raw)std::cin>>p.x>>p.y>>p.z;
    auto knots=nadoc_vr::smoothSweepStroke(raw,settings);
    auto sampled=nadoc_vr::sampleSweepPath(knots,512);
    std::cout<<std::setprecision(9)<<knots.size()<<" "<<sampled.size()<<"\n";
    for(const auto& points:{knots,sampled})for(auto p:points)
        std::cout<<p.x<<" "<<p.y<<" "<<p.z<<"\n";
}
'''


def build_adapter(directory):
    directory = Path(directory)
    source, executable = directory/"sweep-calibration.cpp", directory/"sweep-calibration"
    source.write_text(ADAPTER)
    subprocess.run(["/usr/bin/g++", "-std=c++17", "-O2", "-I", str(ROOT/"native/vr_viewer/src"),
                    str(source), "-o", str(executable)], check=True, capture_output=True, text=True)
    return executable


def smooth_native(executable, points_nm, radius_nm=None, tolerance_nm=None, spacing_nm=None):
    command = [str(executable)]
    if radius_nm is not None:
        command.append(str(radius_nm))
        if tolerance_nm is not None:
            command.append(str(tolerance_nm))
            if spacing_nm is not None:
                command.append(str(spacing_nm))
    payload = str(len(points_nm))+"\n"+"\n".join(" ".join(map(str, p)) for p in points_nm)+"\n"
    output = subprocess.run(command, input=payload, capture_output=True, text=True, check=True).stdout.splitlines()
    knots, sampled = map(int, output[0].split())
    points = np.asarray([[float(v) for v in line.split()] for line in output[1:]], dtype=float).reshape(-1, 3)
    assert len(points) == knots+sampled
    return points[:knots], points[knots:]


def length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def distances_to_polyline(points, line):
    """Geometric nearest-segment distances, independent of drawing speed."""
    points, line = np.asarray(points), np.asarray(line)
    starts, directions = line[:-1], np.diff(line, axis=0)
    squared = np.einsum("ij,ij->i", directions, directions)
    squared = np.maximum(squared, 1e-20)
    result = []
    for point in points:
        t = np.clip(np.einsum("ij,ij->i", point-starts, directions)/squared, 0, 1)
        result.append(float(np.linalg.norm(starts+t[:, None]*directions-point, axis=1).min()))
    return np.asarray(result)


def evaluate(executable, trace, nm_per_m=100., radius_nm=None, tolerance_nm=None, spacing_nm=None):
    # Production draws from a tip 12 cm along controller -Z. Angular variability
    # therefore contributes to the trace, just as it does in the live viewer.
    raw = controller_tip_points(trace)*nm_per_m
    ideal = np.asarray(trace["provenance"]["ideal_points_m"])*nm_per_m
    raw -= raw[0]
    ideal -= ideal[0]
    knots, sampled = smooth_native(executable, raw, radius_nm, tolerance_nm, spacing_nm)
    if len(sampled) < 2:
        return {"accepted": False, "point_count": len(knots)}
    errors = distances_to_polyline(sampled, ideal)
    missing = distances_to_polyline(ideal, sampled)
    return dict(accepted=True, point_count=len(knots), samples=len(raw),
                raw_length_nm=length(raw), ideal_length_nm=length(ideal),
                smoothed_length_nm=length(sampled),
                length_ratio=length(sampled)/length(ideal),
                rms_error_nm=float(np.sqrt(np.mean(errors**2))),
                maximum_error_nm=float(errors.max()),
                maximum_missing_curve_nm=float(missing.max()),
                endpoint_error_nm=float(np.linalg.norm(sampled[-1]-ideal[-1])))


def controller_tip_points(trace):
    return np.asarray([np.asarray(s["hands"]["right"]["position"])
                       + rotate(s["hands"]["right"]["orientation"], [0, 0, -.12])
                       for s in trace["samples"]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--scales", type=float, nargs="+", default=[50., 100., 200.])
    parser.add_argument("--radius-nm", type=float)
    parser.add_argument("--tolerance-nm", type=float)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="nadoc-sweep-calibration-") as temp:
        executable = build_adapter(temp)
        for preset in PRESETS:
            for shape in SHAPES:
                for seed in range(args.seeds):
                    trace = calibration_stroke(shape, preset, seed)
                    for scale in args.scales:
                        radius = args.radius_nm if args.radius_nm is not None else .036*scale
                        tolerance = args.tolerance_nm if args.tolerance_nm is not None else .015*scale
                        results.append(dict(preset=preset, shape=shape, seed=seed, nm_per_m=scale,
                                            radius_nm=radius, tolerance_nm=tolerance,
                                            **evaluate(executable, trace, scale, radius, tolerance, .0015*scale)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(kind="synthetic_uncalibrated_stress_matrix",
        radius_nm=args.radius_nm, tolerance_nm=args.tolerance_nm, cases=results), indent=2)+"\n")
    print(json.dumps(dict(cases=len(results), accepted=sum(r["accepted"] for r in results),
                         output=str(args.output))))


if __name__ == "__main__":
    main()
