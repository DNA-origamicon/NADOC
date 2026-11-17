"""Frozen isomer-specific interaction inputs shared by every managed oxDNA stage."""

import hashlib
import json
import os
from pathlib import Path
import shutil

MODEL = Path(__file__).resolve().parents[1] / "data/oxdna/cpd_cis_syn_v1.json"
MODELS = {
    "cis-syn": MODEL,
    "cis-anti-I": MODEL.with_name("cpd_cis_anti_I_v1.json"),
    "trans-syn-I": MODEL.with_name("cpd_trans_syn_I_v1.json"),
    "trans-syn-II": MODEL.with_name("cpd_trans_syn_II_v1.json"),
}
FILES = ("cpd.dat", "cpd_model.json", "cpd_manifest.json")


def physical_geometry(design, geometry):
    """Project authored CPD atoms using the same landmarks as the NAMD fit.

    This is derived simulation geometry; authored atom coordinates stay intact.
    Unmodified particles continue through the existing calibrated projection.
    """
    if not getattr(design, "photoproduct_junctions", None) or not any(
        r.get("placement_source") not in (None, "oxdna-particle-frame-v1")
        for r in geometry
    ):
        return geometry
    import numpy as np
    from backend.core.atomistic import build_atomistic_model
    from backend.core.base_keys import atom_base_key
    from backend.physics.oxdna_cpd_fit import ATOM_NAMES, particle_frame

    selected = {
        k
        for lesion in design.photoproduct_junctions
        for k in (lesion.base_key_1, lesion.base_key_2, *lesion.context_coordinates)
    }
    atoms = {}
    for atom in build_atomistic_model(design).atoms:
        key = atom_base_key(atom)
        if key in selected:
            atoms.setdefault(key, {})[atom.name] = (
                np.array([atom.x, atom.y, atom.z]) * 10
            )
    output = []
    for record in geometry:
        if record.get("placement_source") in (None, "oxdna-particle-frame-v1"):
            output.append(record)
            continue
        key = (
            record.get("cpd_base_key")
            or f"{record['helix_id']}:{record['bp_index']}:{record['direction']}"
        )
        if record.get("copy_k"):
            key += f":{record['copy_k']}"
        if key not in atoms:
            output.append(record)
            continue
        positions = atoms[key]
        if all(name in positions for name in ATOM_NAMES):
            cm, frame = particle_frame([positions[n] for n in ATOM_NAMES])
        else:
            # Context bases retain their ring centroid and glycosidic direction.
            names = ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4")
            centre = np.mean([positions[n] for n in names], axis=0)
            a1 = centre - positions["C1'"]
            a1 /= np.linalg.norm(a1)
            a3 = -np.cross(
                positions["C4"] - positions["N9"], positions["C8"] - positions["N9"]
            )
            a3 -= a3.dot(a1) * a1
            a3 /= np.linalg.norm(a3)
            frame = np.column_stack((a1, np.cross(a3, a1), a3))
            cm = centre / 8.518 - 0.4 * a1
        item = {
            k: v
            for k, v in record.items()
            if k != "helical_site" and not k.startswith("slab_")
        }
        item.update(
            placement_source="oxdna-particle-frame-v1",
            backbone_position=(cm * 0.8518).tolist(),
            base_position=((cm + 0.4 * frame[:, 0]) * 0.8518).tolist(),
            base_normal=frame[:, 0].tolist(),
            axis_tangent=(
                frame[:, 2] * (1 if record["direction"] == "FORWARD" else -1)
            ).tolist(),
            cpd_particle_frame=True,
        )
        output.append(item)
    return output


def project_extra_particles(design, resolved):
    keys = {
        key
        for lesion in design.photoproduct_junctions
        for key in (lesion.base_key_1, lesion.base_key_2)
    }
    selected = []
    for key, record in resolved.items():
        if key[0] == "__xb__" and (canonical := f"__xb__:{key[1]}:{key[2]}") in keys:
            selected.append(
                (
                    key,
                    {
                        **record,
                        "cpd_base_key": canonical,
                        "placement_source": "authored-cpd-extra-v1",
                    },
                )
            )
    if selected:
        projected = physical_geometry(design, [v for _, v in selected])
        resolved = {
            **resolved,
            **{key: value for (key, _), value in zip(selected, projected, strict=True)},
        }
    return resolved


def configure(specs):
    for spec in specs:
        if spec.interaction not in (None, "DNA2", "CpdDNA2") or spec.parfile:
            raise ValueError(
                "CPD interaction cannot be combined with a different particle interaction model"
            )
        spec.interaction = "CpdDNA2"
        if spec.sim_type == "MC":
            spec.backend = "CPU"
        if spec.sim_type == "MD":
            spec.dt = min(spec.dt, 0.0001)


def plugin_directory():
    directory = Path(
        os.environ.get(
            "NADOC_OXDNA_CPD_PLUGIN",
            Path.home() / ".local/share/nadoc/engines/oxdna/cpd-v1",
        )
    )
    manifest = json.loads((directory / "build.json").read_text())
    if (
        hashlib.sha256((directory / "CpdDNA2.so").read_bytes()).hexdigest()
        != manifest["plugin_sha256"]
    ):
        raise ValueError("CPD plugin differs from its build record")
    source = Path(__file__).resolve().parents[2] / "tools/oxdna_cpd/CpdDNA2.cpp"
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise ValueError(
            "Rebuild the CPD interaction with python tools/oxdna_cpd/build.py"
        )
    return directory.resolve()


def prepare(design, directory, specs):
    if not design.photoproduct_junctions:
        return None
    from backend.core.base_keys import parse_base_key
    from backend.physics.oxdna_interface import _strand_nucleotide_order, topology_rows

    order = _strand_nucleotide_order(design)
    lookup = {key: i for i, key in enumerate(order)}
    rows, _ = topology_rows(design)
    models = {}
    used, endpoints = set(), []
    for lesion in design.photoproduct_junctions:
        if lesion.product != "TT-CPD" or lesion.stereochemistry not in MODELS:
            raise ValueError("No fitted oxDNA CPD model for this isomer")
        stereo = lesion.stereochemistry
        if stereo not in models:
            models[stereo] = json.loads(MODELS[stereo].read_bytes())
            if models[stereo]["stereochemistry"] != stereo:
                raise ValueError("CPD model identity does not match its registry entry")
        indices = []
        keys = [lesion.base_key_1, lesion.base_key_2]
        if lesion.patch_order == "base-key-2-first":
            keys.reverse()
        for key in keys:
            parsed = parse_base_key(key)
            if parsed is None:
                raise ValueError("CPD endpoint is missing its canonical base identity")
            native = (
                ("__xb__", parsed.crossover_id, parsed.k)
                if parsed.family == "xover"
                else (parsed.helix_id, parsed.bp_index, parsed.direction.upper())
            )
            if parsed.copy:
                native += (parsed.copy,)
            i = lookup.get(native)
            if i is None:
                i = lookup.get((*native, 0))
            if i is None or rows[i][1] != "T" or i in used:
                raise ValueError(
                    "CPD requires two distinct, present, unconsumed thymine particles"
                )
            used.add(i)
            indices.append(i)
        endpoints.append(
            {
                "id": lesion.id,
                "base_keys": keys,
                "particles": indices,
                "stereochemistry": stereo,
            }
        )
    if len(models) == 1:
        model_raw = MODELS[next(iter(models))].read_bytes()
        model = json.loads(model_raw)
    else:
        model = {
            "schema": "nadoc.oxdna-cpd-bundle.v1",
            "model": "conditional-rigid-weld-v1",
            "qualification": "exploratory; not validated melting thermodynamics",
            "models": models,
        }
        model_raw = (json.dumps(model, indent=2) + "\n").encode()
    configure(specs)
    plugin = plugin_directory()
    text = [f"NADOC_CPD 1 {len(endpoints)}"]
    for entry in endpoints:
        pars = models[entry["stereochemistry"]]["parameters"]
        text.append(f"{entry['particles'][0]} {entry['particles'][1]} 16")
        for i, a in enumerate(pars["sites"]):
            for j, b in enumerate(pars["sites"]):
                k = 4 * i + j
                text.append(
                    " ".join(
                        format(v, ".17g")
                        for v in (*a, *b, pars["lengths"][k], pars["stiffness"][k])
                    )
                )
    directory = Path(directory)
    (directory / "cpd.dat").write_text("\n".join(text) + "\n")
    (directory / "cpd_model.json").write_bytes(model_raw)
    frozen_plugin = directory / "cpd_plugin"
    frozen_plugin.mkdir(exist_ok=True)
    for name in ("CpdDNA2.so", "build.json"):
        shutil.copy2(plugin / name, frozen_plugin / name)
    manifest = {
        "schema": "nadoc.oxdna-cpd-package.v1",
        "model": model["model"],
        "qualification": model["qualification"],
        "endpoints": endpoints,
        "backend": "CUDA" if any(s.backend == "CUDA" for s in specs) else "CPU",
        "maximum_dt": 0.0001,
        "model_sha256": hashlib.sha256(model_raw).hexdigest(),
        "interaction_sha256": hashlib.sha256(
            (directory / "cpd.dat").read_bytes()
        ).hexdigest(),
        "plugin_sha256": hashlib.sha256(
            (frozen_plugin / "CpdDNA2.so").read_bytes()
        ).hexdigest(),
    }
    manifest["topology_sha256"] = hashlib.sha256(
        (directory / "topology.top").read_bytes()
    ).hexdigest()
    from backend.physics.oxdna_cpd_cuda import add_cuda, wants_cuda
    if wants_cuda(specs):
        add_cuda(directory, manifest, plugin)
    (directory / "cpd_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def inherit(parent, child, specs):
    parent, child = Path(parent), Path(child)
    if not (parent / "cpd_manifest.json").exists():
        return
    verify(parent)
    for name in FILES:
        if parent.resolve() != child.resolve():
            shutil.copy2(parent / name, child / name)
    if parent.resolve() != child.resolve():
        shutil.copytree(parent / "cpd_plugin", child / "cpd_plugin", dirs_exist_ok=True)
    configure(specs)
    from backend.physics.oxdna_cpd_cuda import add_cuda, verify_cuda, wants_cuda
    if wants_cuda(specs):
        manifest = json.loads((child / 'cpd_manifest.json').read_text())
        if not manifest.get('cuda_plugin_sha256'):
            add_cuda(child, manifest, plugin_directory())
            manifest['backend'] = 'CUDA'
            (child / 'cpd_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        verify_cuda(child, manifest)


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "cpd_manifest.json").read_text())
    for name, key in (
        ("cpd.dat", "interaction_sha256"),
        ("cpd_model.json", "model_sha256"),
        ("topology.top", "topology_sha256"),
    ):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest.get(
            key
        ):
            raise ValueError("Frozen CPD interaction inputs changed")
    if (
        hashlib.sha256((directory / "cpd_plugin/CpdDNA2.so").read_bytes()).hexdigest()
        != manifest["plugin_sha256"]
    ):
        raise ValueError("Frozen CPD native plugin changed")
    if manifest.get('cuda_plugin_sha256'):
        from backend.physics.oxdna_cpd_cuda import verify_cuda, digest
        verify_cuda(directory, manifest)
        if digest(directory / 'cpd_plugin/cuda_build.json') != manifest.get('cuda_build_sha256'):
            raise ValueError('Frozen CPD CUDA build record changed')
    return manifest


def stage_input(directory, spec):
    directory = Path(directory)
    if not (directory / "cpd_manifest.json").exists():
        snapshot = directory / "design.json"
        if snapshot.exists() and json.loads(snapshot.read_text()).get(
            "photoproduct_junctions"
        ):
            raise ValueError(
                "CPD job lacks its permanent interaction package; prepare a new CPD job"
            )
        return ""
    verify(directory)
    configure([spec])
    if spec.backend == 'CUDA':
        from backend.physics.oxdna_cpd_cuda import verify_cuda
        verify_cuda(directory, verify(directory))
    return f"\nplugin_search_path = {(directory / 'cpd_plugin').resolve()}\ncpd_file = {(directory / 'cpd.dat').resolve()}\n"
