"""Print per-helix scaffold bp coverage for a scadnano or cadnano design file.

Usage:
    python scripts/scaffold_coverage.py Examples/Voltron_Core_Arm_V6.sc
    python scripts/scaffold_coverage.py "Examples/cadnano/Ultimate Polymer Hinge 191016.json"
"""
import sys, json
sys.path.insert(0, '.')
from backend.core.models import StrandType

def load_design(path: str):
    if path.endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        with open(path) as f:
            return import_scadnano(json.loads(f.read()))[0]
    else:
        from backend.core.cadnano import import_cadnano
        with open(path) as f:
            return import_cadnano(json.load(f))[0]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'Examples/Voltron_Core_Arm_V6.sc'
    design = load_design(path)

    _MIN_MODULE_HELICES = 3
    module_scaffolds = [
        i for i, s in enumerate(design.strands)
        if s.strand_type == StrandType.SCAFFOLD
        and len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES
    ]

    print(f"File: {path}")
    print(f"Module scaffolds ({len(module_scaffolds)}): {module_scaffolds}")
    for si in module_scaffolds:
        s = design.strands[si]
        print(f"  Scaffold {si}: {len({d.helix_id for d in s.domains})} unique helices, "
              f"{len(s.domains)} domains")

    # Build merged bp coverage per scaffold per helix
    scaf_cov: dict[int, dict[str, tuple[int, int]]] = {}
    for si in module_scaffolds:
        scaf_cov[si] = {}
        for d in design.strands[si].domains:
            hid = d.helix_id
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            if hid in scaf_cov[si]:
                olo, ohi = scaf_cov[si][hid]
                scaf_cov[si][hid] = (min(lo, olo), max(hi, ohi))
            else:
                scaf_cov[si][hid] = (lo, hi)

    all_hids = set()
    for si in module_scaffolds:
        all_hids |= set(scaf_cov[si].keys())

    hid_to_label = {
        h.id: (h.label if h.label is not None else str(i))
        for i, h in enumerate(design.helices)
    }

    def sort_key(hid):
        lbl = hid_to_label[hid]
        return int(lbl) if lbl.isdigit() else lbl

    sorted_hids = sorted(all_hids, key=sort_key)

    col_w = 24
    header = f"{'Helix':>6}  {'ID':>12}"
    for si in module_scaffolds:
        header += f"  {'Scaffold '+str(si)+' bp range':>{col_w}}"
    header += "  Type"
    print()
    print(header)
    print("-" * (6 + 14 + len(module_scaffolds) * (col_w + 2) + 10))

    for hid in sorted_hids:
        label = hid_to_label[hid]
        covs = [scaf_cov[si].get(hid) for si in module_scaffolds]
        cov_strs = [f"[{c[0]}, {c[1]}]" if c else "-" for c in covs]
        n_present = sum(1 for c in covs if c)
        if n_present > 1:
            htype = "BRIDGE"
        elif n_present == 1:
            idx = next(i for i, c in enumerate(covs) if c)
            htype = f"excl-S{module_scaffolds[idx]}"
        else:
            htype = "orphan"
        row = f"{label:>6}  {hid:>12}"
        for cs in cov_strs:
            row += f"  {cs:>{col_w}}"
        row += f"  {htype}"
        print(row)

if __name__ == '__main__':
    main()
