"""Materialize CPD-only role/type aliases; prove numerical equivalence before fitting."""

import argparse
import copy
from pathlib import Path
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
import parmed as pmd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from experiments.cpd_anti_additive.core_baseline import checked
from experiments.cpd_drude_recovery.campaign import OLD

PARENT = Path(".development-artifacts/cpd-published-comparator-v1").resolve()


def load_cases():
    campaign = json.loads(
        (
            OLD / "bundle/results/response_campaign/response_campaign_manifest.json"
        ).read_text()
    )
    manifest = json.loads(
        checked(campaign["training_datasets"][0]["response_manifest"]).read_text()
    )
    core_names = [
        r["stable_atom_key"]
        for r in json.loads(checked(manifest["sources"]["stable_atom_map"]).read_text())
    ]
    boundary_manifest = Path(
        ".development-artifacts/cpd-repaired-anti-fragments-v1/endpoint-1/model_manifest.json"
    )
    boundary_names = json.loads(boundary_manifest.read_text())["atom_map"]
    specs = [
        (
            "core",
            Path(".development-artifacts/cpd-anti-additive-core-baseline-v1"),
            core_names,
            "core.psf",
            "last_system.xml",
            "last_minimum_A.txt",
        ),
        (
            "endpoint-1",
            Path(
                ".development-artifacts/cpd-anti-additive-boundary-baseline-v1/endpoint-1"
            ),
            boundary_names,
            "fragment.psf",
            "system.xml",
            "minimum_A.txt",
        ),
    ]
    specs.append(
        (
            "endpoint-2",
            Path(
                ".development-artifacts/cpd-anti-additive-boundary-endpoint2-v1/endpoint-2"
            ),
            json.loads(
                Path(
                    ".development-artifacts/cpd-repaired-anti-fragments-v1/endpoint-2/model_manifest.json"
                ).read_text()
            )["atom_map"],
            "fragment.psf",
            "system.xml",
            "minimum_A.txt",
        )
    )
    return [
        dict(
            id=label,
            names=names,
            psf_path=(folder / psf).resolve(),
            system=mm.XmlSerializer.deserialize((folder / system).read_text()),
            initial=np.loadtxt(folder / coords),
            sources=[source(folder / f) for f in (psf, system, coords)],
        )
        for label, folder, names, psf, system, coords in specs
    ]


from experiments.cpd_published_comparator.reconstruct import BASE, FF, write, source


def main(root, ordered_endpoints=False):
    root.mkdir(exist_ok=False)
    (root / "executed_source.py").write_text(Path(__file__).read_text())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        params = pmd.charmm.CharmmParameterSet(
            str(BASE / "top_all36_na.rtf"),
            str(BASE / "par_all36_na.prm"),
            str(FF / "top_all36_cgenff.rtf"),
            str(FF / "par_all36_cgenff.prm"),
            str(PARENT / "comparator_last.prm"),
        )
    cases = load_cases()
    fixtures = []
    aliases = {}
    for c in cases:
        s = pmd.charmm.CharmmPsfFile(str(c["psf_path"]))
        s.load_parameters(params)
        fixtures.append(
            (
                c["id"],
                s,
                [n if ordered_endpoints else n.split(":")[1] for n in c["names"]],
                None,
            )
        )
    all_keys = sorted(
        {
            (a.type, role)
            for _, s, roles, _ in fixtures
            for a, role in zip(s.atoms, roles)
            if role
        }
    )
    aliases = {key: f"CA{i:03d}" for i, key in enumerate(all_keys, 1)}
    combined = None
    for label, s, roles, path in fixtures:
        for a, role in zip(s.atoms, roles):
            if role:
                alias = aliases[(a.type, role)]
                typ = copy.copy(a.atom_type)
                typ.name = alias
                typ._bond_type = alias
                a.type = alias
                a.atom_type = typ
        out = root / label
        out.mkdir()
        s.title = ["REMARKS CPD-specific typed candidate; isolated validation fixture"]
        pmd.formats.PSFFile.write(s, str(out / "fragment.psf"))
        combined = s if combined is None else combined + s
    exported = pmd.charmm.CharmmParameterSet.from_structure(combined)
    exported.write(top=str(root / "aliases.rtf"), par=str(root / "comparator_last.prm"))
    # Masses must travel with the standalone parameter export.
    prm = root / "comparator_last.prm"
    content = prm.read_text()
    masses = "\n".join(
        l
        for l in (root / "aliases.rtf").read_text().splitlines()
        if l.startswith("MASS")
    )
    # ParmEd 4.3.1's CHARMM writer rounds equilibrium terms and omits UB terms.
    # Restore full precision and explicit Urey-Bradley constants before checking.
    content = content.rsplit("END", 1)[0] + "\nBONDS\n"
    for key, p in exported.bond_types.items():
        if key > key[::-1]:
            continue
        content += " ".join(key) + f" {p.k:.15g} {p.req:.15g}\n"
    reverse = {v: k[0] for k, v in aliases.items()}
    content += "\nANGLES\n"
    for key, p in exported.angle_types.items():
        if key > key[::-1]:
            continue
        orig = tuple(reverse.get(k, k) for k in key)
        ub = params.urey_bradley_types.get(orig)
        content += " ".join(key) + f" {p.k:.15g} {p.theteq:.15g}"
        if ub is not None and ub.k not in (None, 0):
            content += f" {ub.k:.15g} {ub.req:.15g}"
        content += "\n"
    content += "\nNBFIX\n"
    for (a, b), (epsilon, rmin) in params.nbfix_types.items():
        left = [a] + [v for k, v in aliases.items() if k[0] == a]
        right = [b] + [v for k, v in aliases.items() if k[0] == b]
        for x in left:
            for y in right:
                content += f"{x} {y} {-abs(epsilon):.15g} {rmin:.15g}\n"
    prm.write_text(
        "* CPD-specific alias baseline, no numerical changes\n*\nATOMS\n"
        + masses
        + "\n"
        + content
        + "END\n"
    )
    records = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        new = app.CharmmParameterSet(str(prm))
    for c in cases:
        psf = app.CharmmPsfFile(str(root / c["id"] / "fragment.psf"))
        system = psf.createSystem(
            new, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
        )
        (root / c["id"] / "system.xml").write_text(mm.XmlSerializer.serialize(system))
        evaluations = []
        for s in (c["system"], system):
            it = mm.VerletIntegrator(0.001)
            ctx = mm.Context(s, it, mm.Platform.getPlatformByName("Reference"))
            ctx.setPositions(c["initial"] * u.angstrom)
            state = ctx.getState(getEnergy=True, getForces=True)
            evaluations.append(
                (
                    state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                    np.asarray(
                        state.getForces(asNumpy=True).value_in_unit(
                            u.kilocalorie_per_mole / u.angstrom
                        )
                    ),
                )
            )
            del ctx, it
        de = abs(evaluations[0][0] - evaluations[1][0])
        df = float(np.max(abs(evaluations[0][1] - evaluations[1][1])))
        records.append(
            dict(
                model=c["id"],
                energy_error=de,
                force_error=df,
                passed=de < 1e-7 and df < 1e-7,
            )
        )
    write(
        root / "assessment.json",
        dict(
            ordered_endpoints=ordered_endpoints,
            simulation_ready=False,
            records=records,
            all_passed=all(r["passed"] for r in records),
            aliases=[
                dict(original_type=k[0], role=k[1], alias=v) for k, v in aliases.items()
            ],
            source=source(Path(__file__)),
            inputs=[dict(model=c["id"], sources=c["sources"]) for c in cases],
            scope="Anti core and both sugar endpoint alias preparation; no fitting or electrostatic validation",
        ),
    )
    print(records, flush=True)
    assert all(r["passed"] for r in records), (
        "Aliasing must preserve energies and forces"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--ordered-endpoints", action="store_true")
    args = p.parse_args()
    main(args.root.resolve(), args.ordered_endpoints)
