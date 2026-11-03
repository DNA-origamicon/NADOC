"""Render saved CPD isomers with production native GL, without taking over VR."""
import argparse
import hashlib
import json
import os
import resource
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.parse import quote, unquote

from tools.vr_workflows.tour_catalog import ROOT


def check_crosslinks(snapshot, design):
    """Compare the separate Full and atomistic export paths, not just bar count."""
    import numpy as np
    from backend.core.photoproduct_chemistry import load_chemical_definition
    atoms, bars = {}, {}
    for line in snapshot.read_text().splitlines():
        row = line.split()
        if row[0] == "P" and row[1].startswith("atom-ref:"):
            key, name = json.loads(unquote(row[1]).split(":", 1)[1])
            atoms[key, name] = np.array(row[2:5], float)
        elif row[0] == "C" and row[1].startswith("cpd:"):
            bars[unquote(row[1])] = np.array(row[2:8], float).reshape(2, 3)
    errors = []
    for lesion in design.photoproduct_junctions:
        keys = {"1": lesion.base_key_1, "2": lesion.base_key_2}
        definition = load_chemical_definition(lesion.product, lesion.stereochemistry)
        for i, bond in enumerate(definition["graph_delta"]["bonds_added"]):
            for point, address in zip(bars[f"cpd:{lesion.id}:{i}"],
                                      (bond["atom_1"], bond["atom_2"])):
                end, name = address.split(":")
                errors.append(float(np.max(abs(point-atoms[keys[end], name]))))
    assert errors and max(errors) < 2e-5, errors
    return max(errors)


def main():
    # Assertion failures retain logs/images, not multi-GB system core dumps.
    _, hard_limit = resource.getrlimit(resource.RLIMIT_CORE)
    resource.setrlimit(resource.RLIMIT_CORE, (0, hard_limit))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design-dir", type=Path, default=ROOT / "workspace/CPD_1xT_isomers")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    output = args.output or ROOT / ".development-artifacts/cpd-vr" / uuid.uuid4().hex[:10]
    output.mkdir(parents=True, exist_ok=False)
    scratch = output / "tmp"
    scratch.mkdir()
    if not Path("/media/jojo/Archive").is_mount() or output.stat().st_dev != Path("/media/jojo/Archive").stat().st_dev:
        raise RuntimeError("CPD captures require mounted Archive storage")
    os.environ["TMPDIR"] = str(scratch.resolve())
    env = {**os.environ, "TMPDIR": str(scratch.resolve()),
           "PATH": "/usr/bin:/bin:" + os.environ.get("PATH", "")}
    build = ROOT / ".development-artifacts/vr-cpd-native-build"
    guard = str(ROOT / "scripts/validation_guard.sh")
    with (output / "build.log").open("w") as log:
        subprocess.run([guard, "cmake", "-S", str(ROOT / "native/vr_viewer"),
                        "-B", str(build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_C_COMPILER=/usr/bin/gcc", "-DCMAKE_CXX_COMPILER=/usr/bin/g++"],
                       env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run([guard, "cmake", "--build", str(build), "--target",
                        "nadoc-vr-cpd-render-test", "-j1"], env=env, check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    from backend.api.routes_vr import VRLaunchRequest, _snapshot
    from backend.core.models import Design
    from backend.core.photoproduct_chemistry import load_chemical_definition
    from PIL import Image
    report = {"scope": "Production native GL with diagnostic stereo cameras; no OpenXR submission or headset scanout",
              "isomers": []}
    for isomer in ("cis-syn-I", "cis-anti-I", "trans-syn-I", "trans-syn-II"):
        source = args.design_dir / f"2hb_1xT_CPD_{isomer}.nadoc"
        raw = source.read_bytes()
        design = Design.from_json(raw.decode())
        directory = output / isomer
        directory.mkdir()
        snapshot = directory / "scene.nadocvr"
        with snapshot.open("w") as stream:
            _snapshot(VRLaunchRequest(), design_snapshot=design,
                      line_writer=lambda line: stream.write(line+"\n"))
        error = check_crosslinks(snapshot, design)
        identities = []
        for lesion in design.photoproduct_junctions:
            keys = {"1": lesion.base_key_1, "2": lesion.base_key_2}
            definition = load_chemical_definition(lesion.product, lesion.stereochemistry)
            for bond in definition["graph_delta"]["bonds_added"]:
                refs = [address.split(":") for address in (bond["atom_1"], bond["atom_2"])]
                identities.append("atom-bond-ref:" + json.dumps(
                    sorted([[keys[end], name] for end, name in refs]), separators=(",", ":")))
        links = directory / "crosslinks.txt"
        links.write_text("\n".join(quote(identity, safe="-_.:~") for identity in identities)+"\n")
        with (directory / "render.log").open("w") as log:
            subprocess.run([guard, str(build / "nadoc-vr-cpd-render-test"),
                            str(snapshot), str(directory), str(links)],
                           env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
        for ppm in directory.glob("*.ppm"):
            with Image.open(ppm) as image:
                image.save(ppm.with_suffix(".png"))
            ppm.unlink()  # Only this invocation's disposable uncompressed capture.
        assert source.read_bytes() == raw
        report["isomers"].append({"isomer": isomer, "source_sha256": hashlib.sha256(raw).hexdigest(),
                                 "max_full_atom_site_error_nm": error,
                                 "crosslinks": identities, "render_log": (directory/"render.log").read_text()})
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(isomer, "passed", flush=True)
    scratch.rmdir()
    print(output, flush=True)


if __name__ == "__main__":
    if os.environ.get("NADOC_VALIDATION_SCOPE") != "1":
        guard = str(ROOT / "scripts/validation_guard.sh")
        os.execv(guard, [guard, sys.executable, "-m",
                        "tools.vr_workflows.cpd_representation_check", *sys.argv[1:]])
    main()
