"""CPD chemistry and desktop Full landmarks survive native scene export."""
import json
import subprocess
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest

from backend.api.routes_vr import VRLaunchRequest, _snapshot
from backend.core.models import Design
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.cpd_representation import inject_cpd_representation


@pytest.mark.parametrize("stereo", ["cis-syn", "cis-anti-I", "trans-syn-I", "trans-syn-II"])
@pytest.mark.parametrize("moved", [False, True])
def test_cpd_crosslinks_and_slab_sites_survive_vr_export(stereo, moved):
    # The fixture's coordinates stay fixed: this checks chemistry dispatch and
    # display transport, not a new molecular placement for another stereoisomer.
    design = Design.from_json(Path("tests/fixtures/cpd_2hb_1xt.nadoc").read_text())
    lesion = design.photoproduct_junctions[0]
    lesion.stereochemistry = stereo
    if moved:
        from backend.core.models import NucleotideTransform
        from backend.core.base_keys import parse_base_key
        from scipy.spatial.transform import Rotation
        design.nucleotide_transforms.clear()
        for key in (lesion.base_key_1, lesion.base_key_2):
            parsed = parse_base_key(key)
            design.nucleotide_transforms.append(NucleotideTransform(
                kind="extra_base", crossover_id=parsed.crossover_id, extra_base_k=parsed.k,
                pivot=[1, 2, 3], translation=[.2, -.1, .3],
                rotation=Rotation.from_rotvec([.2, -.3, .1]).as_quat().tolist()))
    before = design.to_json()
    text = _snapshot(VRLaunchRequest(), design_snapshot=design,
                     representations={"full", "ballstick", "stick"})
    sections = {}
    transforms = {}
    for line in text.splitlines():
        row = line.split()
        if row[0] == "R":
            current = sections.setdefault(row[1], [])
            current_transforms = transforms.setdefault(row[1], {})
        elif row[0] in {"C", "B", "P"}:
            current.append((row[0], unquote(row[1]), np.array(row[2:14], float)))
        elif row[0] == "T":
            current_transforms[unquote(row[1])] = {
                row[i]: (float(row[i+1]), float(row[i+2]))
                for i in range(3, len(row), 3)}
    definition = load_chemical_definition(lesion.product, stereo)
    keys = {"1": lesion.base_key_1, "2": lesion.base_key_2}
    expected = []
    for bond in definition["graph_delta"]["bonds_added"]:
        refs = [address.split(":") for address in (bond["atom_1"], bond["atom_2"])]
        expected.append("atom-bond-ref:" + json.dumps(
            sorted([[keys[end], name] for end, name in refs]), separators=(",", ":")))
    for rep in ("ballstick", "stick"):
        ids = [identity for kind, identity, _ in sections[rep] if kind == "C"]
        assert all(ids.count(identity) == 1 for identity in expected)
    bars = [values[:6].reshape(2, 3) for kind, identity, values in sections["full"]
            if identity.startswith("cpd:")]
    assert len(bars) == 2
    for i in range(2):
        bar_owners = transforms["full"][f"cpd:{lesion.id}:{i}"]
        for endpoint, key in enumerate(keys.values()):
            slab_id = "extra-base-ref:" + json.dumps([key, "slab"], separators=(",", ":"))
            slab_owners = transforms["full"][slab_id]
            assert slab_owners
            for owner, weights in slab_owners.items():
                assert bar_owners[owner][endpoint] == weights[0]
    from backend.core.atomistic import build_atomistic_model
    from backend.core.base_keys import atom_base_key
    model = build_atomistic_model(design, fast_bridges=True)
    atom_positions = {(atom_base_key(a), a.name): [a.x, a.y, a.z] for a in model.atoms}
    for points, bond in zip(bars, definition["graph_delta"]["bonds_added"]):
        for point, address in zip(points, (bond["atom_1"], bond["atom_2"])):
            end, name = address.split(":")
            np.testing.assert_allclose(point, atom_positions[keys[end], name], atol=2e-5)
    payload = {"photoproduct_junctions": [lesion.model_dump(mode="json")]}
    inject_cpd_representation(payload)
    # Exercise the actual desktop bar builder on these authoritative slab matrices.
    # Full's schematic slab sites need not coincide with all-atom coordinates.
    slabs = {}
    for kind, identity, values in sections["full"]:
        if kind == "B" and identity.startswith("extra-base-ref:"):
            key, primitive = json.loads(identity.split(":", 1)[1])
            if primitive == "slab":
                matrix = np.eye(4)
                matrix[:3, 3] = values[:3]
                matrix[:3, :3] = values[3:12].reshape(3, 3).T
                slabs[key] = matrix.T.reshape(-1).tolist()
    script = """
import fs from 'node:fs'
import * as THREE from 'three'
import {createCpdSlabBonds} from './src/scene/cpd_slab_bonds.js'
const {design, slabs, keys} = JSON.parse(fs.readFileSync(0,'utf8'))
const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial(),2)
keys.forEach((key,i)=>mesh.setMatrixAt(i,new THREE.Matrix4().fromArray(slabs[key])))
const bars = createCpdSlabBonds(design,mesh,target=>keys.findIndex(k=>k===`__xb__:${target.crossover_id}:${target.k}`))
const out=[], m=new THREE.Matrix4()
for(let i=0;i<bars.mesh.count;i++){bars.mesh.getMatrixAt(i,m);out.push(
 [new THREE.Vector3(0,-.5,0).applyMatrix4(m).toArray(),new THREE.Vector3(0,.5,0).applyMatrix4(m).toArray()])}
process.stdout.write(JSON.stringify(out))
"""
    desktop = subprocess.check_output(["node", "--input-type=module", "-e", script],
                                      input=json.dumps({"design": payload, "slabs": slabs,
                                                        "keys": list(keys.values())}),
                                      text=True, cwd="frontend")
    np.testing.assert_allclose(bars, json.loads(desktop), atol=2e-5)
    assert design.to_json() == before


def test_no_cpd_bars_without_formed_coordinates():
    design = Design.from_json(Path("tests/fixtures/cpd_2hb_1xt.nadoc").read_text())
    design.photoproduct_junctions.clear()
    text = _snapshot(VRLaunchRequest(), design_snapshot=design, representations={"full"})
    assert "C cpd:" not in text
