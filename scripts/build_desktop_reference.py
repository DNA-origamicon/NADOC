"""Author the user-specified 24HB/30-mer through ordinary recorded commands.

Only cells and initial length are selected from the existing HC reference; none
of its chemistry, geometry, strands or legacy history are transplanted. The new
part is published through agent_structure_guard and the assembly independently
replayed, including its audited upstream part. No simulation/materialization.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def report_saved(root, relative, reference, reference_hash, params, report_path):
    from backend.core.models import Design, Assembly
    from backend.core.part_history_proof import command_rows
    from backend.core.sequences import strand_nucleotide_count
    from scripts.agent_structure_guard import audit
    from scripts.guide_assembly_audit import audit as audit_assembly
    directory = root / 'workspace' / relative
    part_path, assembly_path = directory / 'HC24-polymerization.nadoc', directory / 'HC24-30mer.nass'
    design = Design.model_validate_json(part_path.read_bytes())
    assembly = Assembly.from_json(assembly_path.read_text())
    if reference_hash not in design.metadata.description:
        raise ValueError('Saved fixture references a different input')
    result = {'reference': str(reference), 'reference_sha256': reference_hash,
        'reference_selection': {'cells': params['cells'], 'initial_length_bp': params['length_bp']},
        'part': {'path': str(part_path), 'sha256': hashlib.sha256(part_path.read_bytes()).hexdigest(), 'audit': audit(design)},
        'assembly': {'path': str(assembly_path), 'sha256': hashlib.sha256(assembly_path.read_bytes()).hexdigest(),
                     'audit': audit_assembly(assembly, directory, workspace_root=root / 'workspace')},
        'part_commands': [{'id': i, 'kind': k, 'params': p} for i, k, p in command_rows(design, 2000)],
        'assembly_commands': [{'id': f.id, 'kind': f.op_kind, 'params': f.params} for f in assembly.feature_log],
        'helices_per_part': len(design.helices), 'instances': len(assembly.instances),
        'nucleotides_per_part': sum(strand_nucleotide_count(s, design) for s in design.strands),
        'periodic_seams': sum(f.is_periodic_seam for f in design.forced_ligations), 'simulation_performed': False}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ['helices_per_part', 'instances', 'nucleotides_per_part', 'periodic_seams']}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--audit-existing", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    reference_bytes = args.reference.read_bytes()
    reference_hash = hashlib.sha256(reference_bytes).hexdigest()
    reference = json.loads(reference_bytes)
    rows = [row for row in reference['feature_log'] if row.get('op_kind') == 'bundle-create']
    if len(rows) != 1 or reference['lattice_type'] != 'HONEYCOMB' or len(reference['helices']) != 24:
        raise ValueError('Reference must contain one recorded HC 24HB bundle creation')
    params = rows[0]['params']
    cells, length = params['cells'], params['length_bp']
    relative = Path('Shared Designs/Desktop Benchmarks/HC24-30mer-20261124')
    part_name = 'HC24-polymerization'
    part_rel, assembly_rel = relative / f'{part_name}.nadoc', relative / 'HC24-30mer.nass'
    if args.audit_existing:
        report_saved(root, relative, args.reference, reference_hash, params, args.report)
        return
    if (root / 'workspace' / relative).exists():
        raise FileExistsError('Reference destination already exists; never replace a benchmark silently')
    scratch = os.environ.get('NADOC_TEST_SCRATCH_ROOT') or os.environ.get('TMPDIR')
    with tempfile.TemporaryDirectory(prefix='__e2e__hc24-author-', dir=scratch) as tmp:
        workspace = Path(tmp) / '__e2e__workspace'
        workspace.mkdir()
        os.environ['NADOC_WORKSPACE'] = str(workspace)
        os.environ['NADOC_DISABLE_SESSION_CACHE'] = '1'
        os.environ['NADOC_RUNPOD_AUTOCONNECT'] = '0'
        # No lifespan context: construction never supervises or starts jobs.
        from fastapi.testclient import TestClient
        from backend.api.main import app
        from backend.core.models import Design, Assembly
        from scripts.agent_structure_guard import publish, audit
        from scripts.guide_assembly_audit import publish as publish_assembly, audit as audit_assembly
        client = TestClient(app, headers={'X-NADOC-Doc': '__e2e__desktop-reference', 'X-NADOC-Skip-Geometry': '1'})
        operations = []

        def command(method, path, body):
            response = client.request(method, '/api' + path, json=body)
            if response.status_code >= 400:
                raise RuntimeError(f'{path}: {response.status_code} {response.text[:2000]}')
            result = response.json()
            operations.append({'method': method, 'path': path, 'inputs': body, 'warnings': result.get('warnings', [])})
            print(path, response.status_code, flush=True)
            return result

        command('POST', '/design', {'name': part_name, 'lattice_type': 'HONEYCOMB'})
        command('POST', '/design/bundle', {'cells': cells, 'length_bp': length, 'name': part_name,
            'plane': 'XY', 'strand_filter': 'both', 'lattice_type': 'HONEYCOMB', 'ligate_adjacent': True})
        command('POST', '/design/auto-scaffold-seamed', {})
        command('POST', '/design/full-autostaple', {})
        command('POST', '/design/route-for-polymerization', {})
        command('PUT', '/design/metadata', {'description':
            f'Desktop benchmark authorized 2026-11-24. Cross-section and initial length ({length} bp) '
            f'selected from {args.reference.name}, SHA-256 {reference_hash}. '
            'New native construction: HC bundle, Seamed Autoscaffold, Full Autostaple, Route for polymerization. '
            'Periodic staples retained; no simulation preparation or strand-extension conversion.',
            'tags': ['desktop-benchmark', '24HB', 'periodic']})
        design = Design.model_validate_json(client.get('/api/design/export').content)
        staged = workspace / part_rel
        staged.parent.mkdir(parents=True)
        publish(design, staged)
        reopened = Design.model_validate_json(staged.read_bytes())
        audit(reopened)
        seams = [bond for bond in reopened.forced_ligations if bond.is_periodic_seam]
        if len(reopened.helices) != 24 or not seams:
            raise RuntimeError('Expected 24 helices and native periodic seams')
        command('POST', '/assembly', {'name': 'HC24-30mer'})
        added = command('POST', '/assembly/instances', {'name': part_name, 'source': {'type': 'file', 'path': part_rel.as_posix()}})
        seed = added['assembly']['instances_v2'][0]['id']
        command('POST', '/assembly/polymerize-periodic', {'instance_id': seed, 'count': 30, 'direction': 'forward'})
        assembly = Assembly.from_json(client.get('/api/assembly/export').text)
        if len(assembly.instances) != 30 or len(assembly.joints) != 29:
            raise RuntimeError('Expected an open-ended 30-mer with 29 seam joints')
        publish_assembly(assembly, workspace / assembly_rel, workspace_root=workspace)
        assembly_reopened = Assembly.from_json((workspace / assembly_rel).read_text())
        audit_assembly(assembly_reopened, staged.parent, workspace_root=workspace)
        # Final portable publication occurs only after both saved/reopened audits.
        destination = root / 'workspace' / relative
        destination.mkdir(parents=True)
        publish(reopened, root / 'workspace' / part_rel)
        publish_assembly(assembly_reopened, root / 'workspace' / assembly_rel, workspace_root=root / 'workspace')
        report_saved(root, relative, args.reference, reference_hash, params, args.report)
        client.close()
        if hashlib.sha256(args.reference.read_bytes()).hexdigest() != reference_hash:
            raise RuntimeError('Source reference changed')
        print(json.dumps({'part': str(part_rel), 'assembly': str(assembly_rel), 'seams': len(seams)}), flush=True)


if __name__ == '__main__':
    main()
