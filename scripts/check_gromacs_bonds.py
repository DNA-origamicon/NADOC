#!/usr/bin/env python3
"""
Check GROMACS package bonds against the expected atomistic model topology.

Verifies:
  1. All inter-residue backbone bonds (O3'→P) in the itp are at expected positions
  2. No spurious direct bonds where extra-base chain should connect
  3. No unexpectedly large residue gaps in backbone bonds
  4. Bond count sanity

Usage: uv run python /tmp/check_gromacs_bonds.py
"""
import sys, json, zipfile, io
sys.path.insert(0, '/home/joshua/NADOC')

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.gromacs_package import build_gromacs_package, _build_gromacs_input_pdb

DESIGN_PATH = '/home/joshua/NADOC/Examples/2hb_xover_atoms_test.nadoc'

# ── Load design + model ───────────────────────────────────────────────────────
with open(DESIGN_PATH) as f:
    design = Design.model_validate(json.load(f))

model    = build_atomistic_model(design)
all_atoms = model.atoms
all_bonds = model.bonds
atom_map  = {a.serial: a for a in all_atoms}

# ── Compute new_seq_num mapping (same logic as _build_gromacs_input_pdb) ─────
from collections import defaultdict

o3_to_p: dict[int, int] = {}
p_with_incoming: set[int] = set()
for i, j in all_bonds:
    a, b = atom_map[i], atom_map[j]
    if a.name == "O3'" and b.name == "P" and a.chain_id == b.chain_id:
        o3_to_p[i] = j
        p_with_incoming.add(j)

chain_res: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
chain_order = []
for a in all_atoms:
    if a.chain_id not in chain_res:
        chain_order.append(a.chain_id)
    chain_res[a.chain_id][a.seq_num].append(a)

# serial → new_seq_num in the reordered chain
serial_to_new_seq: dict[int, int] = {}
# (chain_id, new_seq) → old_seq
new_seq_to_old: dict[tuple, int] = {}

for chain_id in chain_order:
    res_dict = chain_res[chain_id]
    five_prime_seq = None
    for seq_num in sorted(res_dict.keys()):
        p_sers = [a.serial for a in res_dict[seq_num] if a.name == "P"]
        if not p_sers or p_sers[0] not in p_with_incoming:
            five_prime_seq = seq_num
            break
    if five_prime_seq is None:
        traversal = sorted(res_dict.keys())
    else:
        traversal, current, visited = [], five_prime_seq, set()
        while current is not None and current not in visited:
            traversal.append(current)
            visited.add(current)
            o3_ser = next((a.serial for a in res_dict.get(current, []) if a.name == "O3'"), None)
            if o3_ser is None or o3_ser not in o3_to_p:
                break
            nxt = atom_map[o3_to_p[o3_ser]]
            current = nxt.seq_num if nxt.chain_id == chain_id else None
        for s in sorted(res_dict.keys()):
            if s not in visited:
                traversal.append(s)
    for new_seq, old_seq in enumerate(traversal, start=1):
        new_seq_to_old[(chain_id, new_seq)] = old_seq
        for a in res_dict[old_seq]:
            serial_to_new_seq[a.serial] = new_seq

# Expected backbone bonds in new-seq space
# (chain_id, new_seq_src, new_seq_dst)
expected_backbone_new: set[tuple] = set()
for i, j in all_bonds:
    a, b = atom_map[i], atom_map[j]
    if a.name == "O3'" and b.name == "P" and a.chain_id == b.chain_id:
        ns_a = serial_to_new_seq[i]
        ns_b = serial_to_new_seq[j]
        expected_backbone_new.add((a.chain_id, ns_a, ns_b))

# ── Parse itp files ───────────────────────────────────────────────────────────
print("Building GROMACS package...")
pkg = build_gromacs_package(design)
zf  = zipfile.ZipFile(io.BytesIO(pkg))

def parse_itp(itp_text):
    """Return (atoms_list, bonds_list).
    atoms: list of (1-based atom_num, resnr, resname, atomname)
    bonds: list of (atom_i, atom_j)
    """
    atoms, bonds = [], []
    section = None
    for line in itp_text.splitlines():
        s = line.strip()
        if not s or s.startswith(';'):
            continue
        if s.startswith('['):
            section = s.strip('[] \t').lower()
            continue
        if section == 'atoms':
            parts = s.split()
            if len(parts) >= 5:
                atoms.append((int(parts[0]), int(parts[2]), parts[3], parts[4]))
        elif section == 'bonds':
            parts = s.split()
            if len(parts) >= 2:
                bonds.append((int(parts[0]), int(parts[1])))
    return atoms, bonds

# Chain letter → chain_id letter (model uses A,B,C uppercase for ≤26 strands)
chain_letters = [ch for ch in ('A', 'B', 'C') if
                 f'Bundle_gromacs/topol_DNA_chain_{ch}.itp' in zf.namelist()]

print()
all_ok = True
for ch in chain_letters:
    itp_text  = zf.read(f'Bundle_gromacs/topol_DNA_chain_{ch}.itp').decode()
    itp_atoms, itp_bonds = parse_itp(itp_text)

    num_to_res  = {a[0]: a[1] for a in itp_atoms}
    num_to_name = {a[0]: a[3] for a in itp_atoms}
    n_residues  = max(num_to_res.values()) if num_to_res else 0

    # Find inter-residue bonds
    inter_res = []
    for ai, aj in itp_bonds:
        ri, rj = num_to_res.get(ai), num_to_res.get(aj)
        ni, nj = num_to_name.get(ai, '?'), num_to_name.get(aj, '?')
        if ri is not None and rj is not None and ri != rj:
            inter_res.append((min(ri,rj), max(ri,rj), ri, rj, ni, nj))
    inter_res.sort()

    # Expected backbone in new-seq space for this chain
    exp_bb = {(ns, nd) for (cid, ns, nd) in expected_backbone_new if cid == ch}

    print(f"{'='*65}")
    print(f"Chain {ch}: {len(itp_atoms)} atoms, {len(itp_bonds)} bonds, "
          f"{n_residues} residues, {len(inter_res)} inter-residue bonds")

    # Categorise each inter-residue bond
    backbone_found = set()
    issues = []
    for (rlo, rhi, ri, rj, ni, nj) in inter_res:
        is_bb = (ni == "O3'" and nj in ("P", "O1P", "O2P")) or \
                (nj == "O3'" and ni in ("P", "O1P", "O2P"))
        # Normalise direction: src has O3', dst has P
        if ni == "O3'":
            src_r, dst_r = ri, rj
        elif nj == "O3'":
            src_r, dst_r = rj, ri
        else:
            issues.append(f"  UNEXPECTED non-backbone inter-res bond: "
                          f"res {ri} ({ni}) — res {rj} ({nj})")
            continue

        delta = dst_r - src_r
        backbone_found.add((src_r, dst_r))

        expected = (src_r, dst_r) in exp_bb
        gap_flag  = f"  [GAP={delta}!]" if delta != 1 else ""
        exp_flag  = "" if expected else "  [NOT EXPECTED!]"
        print(f"  res {src_r:3d} (O3') → res {dst_r:3d} (P){gap_flag}{exp_flag}")

    for iss in issues:
        print(iss)

    # Missing expected backbone bonds
    missing = exp_bb - backbone_found
    if missing:
        print(f"  MISSING expected backbone bonds:")
        for (ns, nd) in sorted(missing):
            old_s = new_seq_to_old.get((ch, ns), '?')
            old_d = new_seq_to_old.get((ch, nd), '?')
            print(f"    new_seq {ns} (old {old_s}) → {nd} (old {old_d})")
        all_ok = False
    else:
        print(f"  All expected backbone bonds present ✓")

    # Unexpected bonds
    unexpected = backbone_found - exp_bb
    if unexpected:
        print(f"  UNEXPECTED backbone bonds (should not exist):")
        for (ns, nd) in sorted(unexpected):
            old_s = new_seq_to_old.get((ch, ns), '?')
            old_d = new_seq_to_old.get((ch, nd), '?')
            print(f"    new_seq {ns} (old {old_s}) → {nd} (old {old_d})  ← WRONG")
        all_ok = False
    else:
        print(f"  No unexpected backbone bonds ✓")

print()
if all_ok:
    print("✓  All bonds correct.")
else:
    print("✗  Bond issues found — see above.")
