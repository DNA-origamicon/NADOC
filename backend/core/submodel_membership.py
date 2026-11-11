"""Read-only display membership from native submodel preparation receipts."""
import json
from pathlib import Path


def key_string(key):
    parts = list(key)
    if len(parts) == 4 and not parts[-1]:
        parts.pop()
    return ':'.join(str(getattr(p, 'value', p)) for p in parts)


def membership(source, retained):
    retained = set(retained)
    if not retained <= set(range(len(source))):
        raise ValueError('Invalid retained submodel indices')
    return dict(ready=True, omitted_keys=sorted({key_string(k) for i,k in enumerate(source) if i not in retained}),
                retained_keys=sorted({key_string(source[i]) for i in retained}))


def namd_membership(package, design):
    from backend.core.atomistic_to_nadoc import build_namd_coarse_reference, load_segid_chain_map, md_pkey
    package = Path(package)
    path = package/'submodel.json'
    if not path.exists():
        return dict(ready=False, reason='Prepare this submodel to identify its simulated nucleotides.')
    if design is None:
        raise ValueError('Saved job design is unavailable')
    receipt = json.loads(path.read_text())
    source = [tuple(r) for r in receipt['source_residues']]
    retained = {tuple(r) for r in receipt['retained_residues']}
    if not retained <= set(source):
        raise ValueError('Invalid retained NAMD residue identities')
    segments = load_segid_chain_map(package)
    if not segments:
        raise ValueError('Saved NAMD residue mapping is unavailable')
    chain_map, _ = build_namd_coarse_reference(design, None, segments, mapping_only=True)
    addresses = [(segments.get(seg),int(res)) for seg,res in source]
    if len(chain_map) != len(source) or any(a not in chain_map for a in addresses):
        # Synthetic inserts/extensions require the same identity mapping as playback.
        from backend.core.atomistic import build_atomistic_model
        chain_map = {(a.chain_id,a.seq_num):md_pkey(a) for a in build_atomistic_model(design).atoms}
    if any(a not in chain_map for a in addresses):
        raise ValueError('Submodel source residues do not match the saved design')
    return membership([chain_map[a] for a in addresses], [i for i,r in enumerate(source) if r in retained])


def oxdna_membership(directory):
    path = Path(directory)/'submodel_plan.json'
    if not path.exists():
        return dict(ready=False, reason='Prepare this submodel to identify its simulated nucleotides.')
    receipt = json.loads(path.read_text())
    from backend.core.oxdna_submodel import selected, fingerprint
    box = selected(directory)
    if box is not None and receipt.get('selection_fingerprint') != fingerprint(box):
        return dict(ready=False, reason='Prepare the current region to update its simulated nucleotides.')
    return membership(receipt['source_keys'], receipt['retained_source_indices'])
