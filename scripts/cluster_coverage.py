"""Print per-helix bp coverage for each autodetected cluster and compare with scaffold routing.

Usage:
    python scripts/cluster_coverage.py Examples/Voltron_Core_Arm_V6.sc
    python scripts/cluster_coverage.py "Examples/cadnano/Ultimate Polymer Hinge 191016.json"
"""
import sys, json
sys.path.insert(0, '.')
from backend.core.models import StrandType
from backend.api.crud import _autodetect_clusters, _recenter_design
from backend.core.lattice import autodetect_all_overhangs

def load_design(path: str):
    if path.endswith('.sc'):
        from backend.core.scadnano import import_scadnano
        with open(path) as f:
            return import_scadnano(json.loads(f.read()))[0]
    else:
        from backend.core.cadnano import import_cadnano
        with open(path) as f:
            return import_cadnano(json.load(f))[0]

def merge_range(existing, lo, hi):
    if existing is None:
        return (lo, hi)
    return (min(existing[0], lo), max(existing[1], hi))

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'Examples/Voltron_Core_Arm_V6.sc'
    design = load_design(path)
    design = autodetect_all_overhangs(design)
    design = _recenter_design(design)
    design = _autodetect_clusters(design)

    clusters = [ct for ct in design.cluster_transforms if not ct.is_default]

    # Build strand/domain lookup: strand_id → strand, for domain_ids resolution
    strand_by_id = {s.id: s for s in design.strands}

    # For each cluster, compute bp range per helix
    # - If domain_ids is non-empty: only those domain refs contribute bp ranges
    # - If domain_ids is empty: cluster owns all helices fully; use full helix length
    #   (represented as None → "full")
    helix_len = {}
    for h in design.helices:
        all_bps = []
        for s in design.strands:
            for d in s.domains:
                if d.helix_id == h.id:
                    all_bps += [d.start_bp, d.end_bp]
        if all_bps:
            helix_len[h.id] = (min(all_bps), max(all_bps))

    cluster_cov: list[dict[str, tuple[int,int] | None]] = []
    for ct in clusters:
        cov: dict[str, tuple[int,int] | None] = {}
        if not ct.domain_ids:
            # No domain-level split — entire helix belongs to cluster
            for hid in ct.helix_ids:
                cov[hid] = helix_len.get(hid)
        else:
            # Has domain refs — compute merged bp range per helix from those refs
            domain_ranges: dict[str, tuple[int,int]] = {}
            for dr in ct.domain_ids:
                s = strand_by_id.get(dr.strand_id)
                if s is None or dr.domain_index >= len(s.domains):
                    continue
                d = s.domains[dr.domain_index]
                lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
                domain_ranges[d.helix_id] = merge_range(domain_ranges.get(d.helix_id), lo, hi)
            # Helices in helix_ids but NOT in domain_refs are exclusive → full range
            for hid in ct.helix_ids:
                if hid in domain_ranges:
                    cov[hid] = domain_ranges[hid]
                else:
                    cov[hid] = helix_len.get(hid)  # exclusive helix — full range
        cluster_cov.append(cov)

    # ── Scaffold coverage (same logic as scaffold_coverage.py) ─────────────────
    _MIN = 3
    module_scaffolds = [
        i for i, s in enumerate(design.strands)
        if s.strand_type == StrandType.SCAFFOLD
        and len({d.helix_id for d in s.domains}) >= _MIN
    ]
    scaf_cov: dict[int, dict[str, tuple[int,int]]] = {}
    for si in module_scaffolds:
        scaf_cov[si] = {}
        for d in design.strands[si].domains:
            hid = d.helix_id
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            scaf_cov[si][hid] = merge_range(scaf_cov[si].get(hid), lo, hi)

    # Collect all relevant helices
    all_hids: set[str] = set()
    for cov in cluster_cov:
        all_hids |= set(cov.keys())
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

    def fmt(cov):
        if cov is None:
            return "-"
        return f"[{cov[0]},{cov[1]}]"

    col_w = 12

    # ── Table 1: Cluster coverage ───────────────────────────────────────────────
    print(f"\nFile: {path}")
    print(f"\n{'─'*6}  CLUSTER COVERAGE  {'─'*40}")
    header = f"{'Helix':>6}"
    for ct in clusters:
        label = ct.name[:col_w]
        header += f"  {label:>{col_w}}"
    print(header)
    print("-" * (8 + len(clusters) * (col_w + 2)))
    for hid in sorted_hids:
        label = hid_to_label[hid]
        row = f"{label:>6}"
        for cov in cluster_cov:
            row += f"  {fmt(cov.get(hid)):>{col_w}}"
        print(row)

    # ── Table 2: Scaffold coverage ──────────────────────────────────────────────
    print(f"\n{'─'*6}  SCAFFOLD COVERAGE  {'─'*40}")
    header2 = f"{'Helix':>6}"
    for si in module_scaffolds:
        lbl = f"Scaffold {si}"[:col_w]
        header2 += f"  {lbl:>{col_w}}"
    print(header2)
    print("-" * (8 + len(module_scaffolds) * (col_w + 2)))
    for hid in sorted_hids:
        label = hid_to_label[hid]
        row = f"{label:>6}"
        for si in module_scaffolds:
            row += f"  {fmt(scaf_cov[si].get(hid)):>{col_w}}"
        print(row)

    # ── Mismatch report ─────────────────────────────────────────────────────────
    if len(module_scaffolds) == len([ct for ct in clusters if 'Scaffold' in ct.name]):
        scaf_clusters = [ct for ct in clusters if 'Scaffold' in ct.name]
        print(f"\n{'─'*6}  MISMATCH REPORT (scaffold clusters vs scaffold routing)  {'─'*10}")
        mismatches = []
        for hid in sorted_hids:
            label = hid_to_label[hid]
            for k, (ct, cov, si) in enumerate(zip(scaf_clusters, cluster_cov[:len(scaf_clusters)], module_scaffolds)):
                cl_range = cov.get(hid)
                sc_range = scaf_cov[si].get(hid)
                if cl_range != sc_range:
                    mismatches.append(
                        f"  helix {label:>4}  {ct.name}: cluster={fmt(cl_range)}  scaffold={fmt(sc_range)}"
                    )
        if mismatches:
            for m in mismatches:
                print(m)
        else:
            print("  No mismatches — scaffold clusters match scaffold routing exactly.")

if __name__ == '__main__':
    main()
