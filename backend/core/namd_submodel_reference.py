"""Frozen full-model settings for derived submodels. No trajectory or geometry edits.

Profiles are registered explicitly per saved design, never selected by recency.
Historical packages keep their embedded profile; changing a binding affects only
new preparations. Fixed-shell execution differences remain explicit.
"""

import hashlib
import json
from pathlib import Path
import re

SETTINGS = "submodel_reference_profiles.json"
# File names, restart chain, run lengths and restraints belong to the new job.
PHYSICS = (
    "timestep",
    "rigidBonds",
    "rigidTolerance",
    "langevin",
    "langevinTemp",
    "langevinDamping",
    "langevinHydrogen",
    "cutoff",
    "switching",
    "switchdist",
    "pairlistdist",
    "exclude",
    "oneFourScaling",
    "PME",
    "PMEGridSpacing",
    "nonbondedFreq",
    "fullElectFrequency",
    "stepspercycle",
    "wrapAll",
    "wrapWater",
)
EXCEPTIONS = [
    "Fixed outer atoms require the existing NVT implementation; full-reference NPT is not copied.",
    "Fixed atoms require CUDA offload; GPUresident is not copied.",
    "Crop cell size, counterion count, restraints, initialization and run duration differ.",
    "Matching the ion recipe does not match total ion number density or the local ion atmosphere.",
    "Relaxation keeps its staged DNA elastic network; production removes it.",
]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def directives(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        fields = line.split("#")[0].split(None, 1)
        if len(fields) == 2:
            result.setdefault(fields[0].lower(), []).append(fields[1].strip())
    return result


def topology_signature(design):
    # Same strands/crossovers, permitting physical display/revision metadata changes.
    value = dict(
        strands=[
            {k: s.get(k) for k in ("id", "domains", "sequence")}
            for s in design["strands"]
        ],
        crossovers=[
            {k: c.get(k) for k in ("id", "half_a", "half_b", "extra_bases")}
            for c in design["crossovers"]
        ],
    )
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def capture(job_dir):
    """Read actual conf + audited census, not nominal legacy salt fields."""
    job_dir = Path(job_dir).resolve()
    job = json.loads((job_dir / "job.json").read_text())
    package = job_dir / job["package_subdir"]
    if job.get("run_kind") != "production" or (package / "submodel.json").exists():
        raise ValueError("Reference must be a whole-model production job")
    if len(job["segments"]) != 1:
        raise ValueError("Select an unambiguous single-segment production reference")
    conf = package / (job["segments"][0]["name"] + ".conf")
    opts = directives(conf)
    settings = {}
    for key in PHYSICS:
        values = opts.get(key.lower(), [])
        if len(values) != 1:
            raise ValueError(f"Reference needs one literal {key}")
        settings[key] = values[0]
    if opts.get("extrabondsfile") != ["mgh_extrabonds.txt"] or opts.get(
        "constraints"
    ) != ["off"]:
        raise ValueError("Reference must have no DNA elastic/positional restraints")
    audit_path = package / "charge_audit.json"
    ion = json.loads(audit_path.read_text())["ionization"]
    # Old packages can report a nominal n_mg_bulk that was NOT actually placed.
    # Validate the actual PSF species census rather than trusting that field.
    psf = package / opts["structure"][0]
    census = {"mg": 0, "na": 0, "cl": 0}
    with psf.open() as stream:
        for line in stream:
            if "!NATOM" in line:
                count = int(line.split()[0])
                break
        for _ in range(count):
            row = next(stream).split()
            atom = row[4].upper()
            if atom in ("MG", "SOD", "CLA"):
                census[{"MG": "mg", "SOD": "na", "CLA": "cl"}[atom]] += 1
    if any(census[k] != ion["n_" + k] for k in census):
        raise ValueError(f"Reference PSF/audit ion census differs: {census}")
    if (
        census["na"]
        or census["cl"]
        or not census["mg"]
        or not ion["mg_hexahydrate"]
        or abs(2 * census["mg"] + ion["dna_charge_from_psf_e"]) > 0.001
    ):
        raise ValueError(
            "This profile importer currently supports neutralizing-Mg-only references"
        )
    parameters = {name: sha(package / name) for name in opts["parameters"]}
    return dict(
        schema="nadoc.submodel-reference.v1",
        job_id=job["job_id"],
        job_dir=str(job_dir),
        design_source_path=job["design_source_path"],
        topology_sha256=topology_signature(
            json.loads((job_dir / "design.json").read_text())
        ),
        config=str(conf),
        config_sha256=sha(conf),
        physics=settings,
        hmr=opts["structure"][0].endswith("_hmr.psf"),
        parameters=parameters,
        counterion="mg",
        nacl_mM=0.0,
        mgcl2_mM=0.0,
        actual_ion_counts=census,
        source_psf=str(psf),
        source_psf_sha256=sha(psf),
        charge_audit_sha256=sha(audit_path),
        reference_ensemble="NPT" if opts.get("langevinpiston") == ["on"] else "NVT",
        exceptions=EXCEPTIONS,
    )


def registry(workspace):
    path = Path(workspace) / SETTINGS
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"bindings": {}, "profiles": {}}
    )


def bind(workspace, job_dir):
    profile = capture(job_dir)
    record = registry(workspace)
    old = record["profiles"].get(profile["job_id"])
    if old is not None and old != profile:
        raise ValueError("Reference profile changed; use a new reference job")
    record["profiles"][profile["job_id"]] = profile
    record["bindings"][profile["design_source_path"]] = profile["job_id"]
    path = Path(workspace) / SETTINGS
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    tmp.replace(path)
    return profile


def lookup(workspace, reference_id=None, design_path=None):
    record = registry(workspace)
    key = reference_id or record["bindings"].get(design_path)
    if not key:
        return None
    if key not in record["profiles"]:
        raise ValueError(f"Unregistered submodel reference: {key}")
    profile = record["profiles"][key]
    if sha(profile["config"]) != profile["config_sha256"]:
        raise ValueError("Reference config changed; register a new immutable reference")
    return profile


def merge_overrides(overrides, physics):
    # A bound comparison profile owns these fields on every stage, including
    # explicit per-stage edits. The wizard exposes the resulting forced settings.
    keys = {k.lower() for k in physics}
    result = {
        str(stage): {k: v for k, v in values.items() if k.lower() not in keys}
        for stage, values in (overrides or {}).items()
    }
    result["*"] = {**result.get("*", {}), **physics}
    return result


def resolve_request(body, workspace):
    saved_job_id = getattr(body, "saved_job_id", None)
    if saved_job_id:
        # Viewing history is not a new comparison request. In particular, an old
        # control must not appear to acquire new ions when a binding is installed.
        from backend.core.md_job import MdJob
        from backend.api.simulation_submodel import SubmodelBox

        job = MdJob.load(saved_job_id, Path(workspace))
        receipt = job.package_dir(Path(workspace)) / "submodel.json"
        if not receipt.exists():
            return body
        recipe = json.loads(receipt.read_text())
        body = body.model_copy(update={"submodel": SubmodelBox(**recipe["box"])})
        profile = recipe.get("reference_profile")
        if profile is None:
            return body.model_copy(update={"submodel_reference_job_id": None})
    else:
        profile = None
    if body.submodel is None:
        if body.submodel_reference_job_id:
            raise ValueError("A reference configuration requires a submodel selection")
        return body
    if not saved_job_id:
        profile = lookup(
            workspace, body.submodel_reference_job_id, body.design_source_path
        )
    if profile is None:
        return body
    p = profile["physics"]
    return body.model_copy(
        update=dict(
            submodel_reference_job_id=profile["job_id"],
            salt_mode="custom",
            ion_conc_mM=0.0,
            mg_conc_mM=0.0,
            relax_timestep_fs=float(p["timestep"]),
            relax_rigid_bonds=p["rigidBonds"],
            relax_hmr=profile["hmr"],
            production_timestep_fs=float(p["timestep"]),
            production_rigid_bonds=p["rigidBonds"],
            production_hmr=profile["hmr"],
            stage_overrides=merge_overrides(body.stage_overrides, p),
        )
    )


def apply_package_profile(package, text, profile):
    from backend.core.md_protocols import apply_conf_overrides

    package = Path(package)
    for name, expected in profile["parameters"].items():
        if sha(package / name) != expected:
            raise ValueError(f"Submodel force-field mismatch: {name}")
    opts = directives_text(text)
    structure = opts.get("structure", [])
    if len(structure) != 1:
        raise ValueError("Submodel config needs one structure PSF")
    base = structure[0].removesuffix("_hmr.psf").removesuffix(".psf")
    target = base + ("_hmr.psf" if profile["hmr"] else ".psf")
    if not (package / target).is_file():
        raise ValueError("Missing PSF for reference HMR policy")
    text = re.sub(
        r"^\s*structure\s+[^\n]+",
        "structure          " + target,
        text,
        flags=re.M | re.I,
    )
    return apply_conf_overrides(text, profile["physics"])


def directives_text(text):
    result = {}
    for line in text.splitlines():
        fields = line.split("#")[0].split(None, 1)
        if len(fields) == 2:
            result.setdefault(fields[0].lower(), []).append(fields[1].strip())
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--reference-job", required=True)
    args = parser.parse_args()
    profile = bind(args.workspace, args.reference_job)
    print(
        json.dumps(
            {
                "bound_design": profile["design_source_path"],
                "reference": profile["job_id"],
                "exceptions": profile["exceptions"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
