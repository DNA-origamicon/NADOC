"""All Origami evidence → recorded editor operations → Shared Designs.

Run with ``python -m tools.design_archive.shared_pipeline --help``.
No Git writes, native reference downloads, or simulations are performed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from experiments.recorded_review_process import ProcessRequired

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / 'workspace/Shared Designs/All Origami'
DEVELOPMENT = ROOT / '.development-artifacts/all-origami/runs'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def code_provenance():
    paths = [Path(__file__).with_name(name) for name in (
        'shared_pipeline.py', 'recorded_authoring.py', 'image_sequence_evidence.py',
        'import_d003_figure.py', 'd003_recipe.py', 'd003_audit.py', 'rigid_fit_audit.py', 'relax_d003_clashes.py')]
    paths += [ROOT / name for name in (
        'scripts/agent_structure_guard.py', 'experiments/recorded_review_process.py',
        'backend/api/feature_recording.py', 'backend/api/part_import_relaxation.py',
        'backend/api/part_proof_commands.py', 'backend/api/part_cell_commands.py',
        'backend/api/part_structural_commands.py', 'backend/api/part_native_commands.py',
        'backend/core/part_overlay_commands.py',
        'backend/api/part_ligation_commands.py', 'backend/core/cluster_autodetect.py',
        'backend/core/origami_relax.py')]
    return {
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
        'implementation_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
    }


def copy_source(path, output, role, expected=None):
    path = Path(path)
    digest = sha(path)
    if expected is not None and digest != expected:
        raise ProcessRequired(f'Input hash mismatch: {path.name}')
    target = output / 'inputs' / (digest + path.suffix.lower())
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        if path.suffix.lower() == '.nadoc':
            from backend.core.models import Design
            from scripts.agent_structure_guard import publish
            publish(Design.model_validate_json(path.read_text()), target)
        else:
            shutil.copyfile(path, target)
    return {'path': target.relative_to(output).as_posix(), 'sha256': sha(target),
            'original_sha256': digest, 'role': role}


def upstream_evidence(design):
    """Source citations travel in the standalone part; replay needs no sidecars."""
    from backend.core.part_history_proof import command_rows
    retained = {}
    for _, _, params in command_rows(design, 2000):
        generator = params.get('_generator', {})
        if generator.get('tool') != 'All Origami recorded authoring':
            continue
        for source in generator['sources']:
            retained[source['sha256']] = source
    return list(retained.values())


def run(*, design_id, run_id, shared_root=SHARED, pdf=None, recipe_path=None,
        source_part=None, relax=False, development_root=DEVELOPMENT, progress=None):
    if not re.fullmatch(r'D\d{3}', design_id) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise ValueError('Use a catalog ID Dnnn and a simple unique run name')
    if sum(value is not None for value in (pdf, recipe_path, source_part)) != 1:
        raise ValueError('Select exactly one source: PDF extraction, operation recipe, or recorded part')
    shared_output = Path(shared_root).resolve() / design_id / run_id
    output = Path(development_root).resolve() / design_id / run_id
    if output.is_relative_to(Path(shared_root).resolve()):
        raise ValueError('Development evidence must be outside Shared Designs')
    if shared_output.exists():
        raise FileExistsError(shared_output)
    output.mkdir(parents=True, exist_ok=False)
    report = {'version': 1, 'design_id': design_id, 'run_id': run_id,
              'status': 'running', 'code': code_provenance(), 'inputs': [], 'stages': [],
              'native_reference_used': False if pdf is not None else None,
              'native_reference_policy': 'Image/sequence construction only; supplied recipe provenance requires review',
              'simulation_validated': False,
              'simulation_ready': False, 'outputs': []}
    report['development_directory'] = str(output)
    try:
        if pdf is not None:
            from tools.design_archive.image_sequence_evidence import CASES, tables, vector_2009, stroke_graph
            import pymupdf
            case = next((c for c in CASES if c[0] == design_id), None)
            if case is None:
                raise ProcessRequired(f'{design_id}: no qualified figure/table extraction profile yet')
            catalog = json.loads((ROOT / 'experiments/origami_publication_catalog/catalog.json').read_text())
            row = next(r for r in catalog['rows'] if r['id'] == design_id)
            manifest = json.loads((ROOT / 'experiments/origami_publication_catalog/assets_manifest.json').read_text())
            expected = next(r['sha256'] for r in manifest if r['path'] == row['source_file'])
            source = copy_source(pdf, output, 'published_figure_and_sequence_tables', expected)
            report['inputs'].append(source)
            evidence = output / 'evidence'
            evidence.mkdir()
            with pymupdf.open(output / source['path']) as doc:
                page = doc[case[2] - 1]
                rows = tables(doc, case[3], design_id)
                table = {'figure_page': case[2], 'sequence_pages': list(case[3]),
                         'sequence_rows': rows, 'extracted_sequence_rows': len(rows),
                         'sequence_mapping_validated': False}
                if design_id in {'D005', 'D006'}:
                    table['vector_evidence'] = vector_2009(page, rotated=design_id == 'D006')
                elif design_id in {'D002', 'D003'}:
                    table['stroke_graph'] = stroke_graph(page)
                if not rows or any(r['length'] != len(r['sequence']) for r in rows):
                    raise ProcessRequired('Sequence table extraction is empty or has inconsistent lengths')
                write_json(evidence / 'image-sequences.json', table)
            if design_id == 'D003':
                from tools.design_archive.import_d003_figure import derive
                derive(output / source['path'], evidence)
                provenance = json.loads((evidence / 'provenance.json').read_text())
                provenance['source_pdf'] = '../' + source['path']
                write_json(evidence / 'provenance.json', provenance)
                graph = json.loads((evidence / 'registered.cadnano.json').read_text())
                table['traced_linear_strand_starts'] = {
                    kind: sum(edge != [-1] * 4 and edge[:2] == [-1, -1]
                              for helix in graph['vstrands'] for edge in helix[kind])
                    for kind in ('scaf', 'stap')}
                write_json(evidence / 'image-sequences.json', table)
            report['stages'].append({'stage': 'figure_extraction', 'status': 'completed',
                                    'evidence': 'evidence/image-sequences.json'})
            report['gaps'] = [
                'Case-specific figure/table selection and decoding assumptions require review.',
                'Sequence-table rows are not yet mapped and validated against the traced strand graph.',
                'A reviewed native editor-operation recipe must account for every traced connection and indel.',
            ]
            if design_id == 'D003':
                report['gaps'] += [
                    'Crop, palette, rail polarity and slice interpretation are specific to Fig. S71.',
                    'Register is a scored hypothesis modulo 32; absolute origin is unresolved.',
                    f"Traced linear starts {table['traced_linear_strand_starts']}; extracted staple rows {len(rows)}; reconcile before authoring."]
            elif design_id == 'D005':
                report['gaps'].append('144-nt loop has no admitted loop-skip-insert command; rigid poses cannot represent distributed torsion.')
            elif design_id == 'D006':
                report['gaps'].append('Helper routing row 19 has no established placement in the 18-circle slice.')
            if design_id != 'D003':
                raise ProcessRequired(f'{design_id} extraction retained; native operation compilation and sequence mapping require review')
            from tools.design_archive.d003_recipe import compile_recipe
            scaffold_source = copy_source(ROOT / 'backend/core/m13mp18.txt', output, 'M13mp18_sequence_library')
            sequence = ''.join((output / scaffold_source['path']).read_text().split()).upper()
            recipe, recovery = compile_recipe(graph, rows, sequence, [source, scaffold_source])
            write_json(evidence / 'sequence-mapping.json', recovery)
            table['sequence_mapping_validated'] = True
            write_json(evidence / 'image-sequences.json', table)
            report['gaps'] = recipe['profile_selections']
            recipe_path = output / 'compiled-recipe.json'
            write_json(recipe_path, recipe)
            report['stages'].append({'stage': 'sequence_mapping_and_compilation', **recovery})

        from tools.design_archive.recorded_authoring import construct, detect_and_relax, audit_image_history
        from backend.core.models import Design
        from scripts.agent_structure_guard import audit, publish

        if recipe_path is not None:
            recipe_path = Path(recipe_path).resolve()
            recipe = json.loads(recipe_path.read_text())
            if recipe.get('design_id') != design_id or not recipe.get('sources'):
                raise ProcessRequired('Recipe needs matching catalog ID and pinned source evidence')
            folded = recipe.get('folded_geometry')
            if not isinstance(folded, dict) or type(folded.get('required')) is not bool or not folded.get('evidence'):
                raise ProcessRequired('Recipe must state folded-geometry evidence and whether relaxation is required')
            relax = relax or folded['required']
            report['folded_geometry'] = folded
            # Source material stays with development evidence; exact authoring
            # inputs and source hashes are embedded in the standalone part log.
            portable = json.loads(json.dumps(recipe))
            portable['execution_code'] = report['code']
            for source in portable['sources']:
                relative = Path(source['path'])
                if relative.suffix.lower() in {'.nadoc', '.nass', '.cdn', '.sc'}:
                    raise ProcessRequired('Native reference documents are not image/sequence recipe evidence')
                if relative.is_absolute() or '..' in relative.parts:
                    raise ProcessRequired('Recipe sources must stay inside its own directory')
                resolved = (recipe_path.parent / relative).resolve()
                if not resolved.is_relative_to(recipe_path.parent):
                    raise ProcessRequired('Recipe source symlink escapes its directory')
                copied = copy_source(resolved, output, source['role'], source['sha256'])
                if copied not in report['inputs']:
                    report['inputs'].append(copied)
                source.update(copied)
            write_json(output / 'recipe.json', portable)
            report['recipe_sha256'] = sha(output / 'recipe.json')
            design = construct(portable, progress=progress)
            report['stages'].append({'stage': 'native_authoring', 'status': 'completed',
                                    'proof': audit(design)})
        else:
            # Read/audit before retaining a legacy source in a published bundle.
            design = Design.model_validate_json(Path(source_part).read_text())
            proof = audit_image_history(design)
            report['upstream_source_citations'] = upstream_evidence(design)
            source = copy_source(source_part, output, 'recorded_upstream_part')
            report['inputs'].append(source)
            report['stages'].append({'stage': 'upstream_replay', 'status': 'completed', 'proof': proof})
            report['native_reference_used'] = None  # Upstream source usage is not re-inferred.

        design, fitting = detect_and_relax(design, relax=relax)
        report['stages'].append({'stage': 'cluster_detection_and_pose', **fitting})
        if relax and fitting['relaxation']['status'] != 'applied':
            raise ProcessRequired('Required folded-geometry fit unavailable: ' + str(fitting['relaxation']))
        if relax and fitting['relaxation'].get('optimizer_converged') is False:
            raise ProcessRequired('Required folded-geometry optimizer did not converge')
        if pdf is not None and design_id == 'D003':
            from tools.design_archive.d003_audit import audit_reconstruction
            report['reconstruction_audit'] = audit_reconstruction(design, graph, rows, sequence)
        shared_output.mkdir(parents=True, exist_ok=False)
        target = shared_output / f'{design_id}.nadoc'
        proof = publish(design, target)
        reopened = audit(Design.model_validate_json(target.read_text()))
        if pdf is not None and design_id == 'D003':
            report['reopened_reconstruction_audit'] = audit_reconstruction(
                Design.model_validate_json(target.read_text()), graph, rows, sequence)
        report['outputs'].append({'path': target.name, 'sha256': proof['sha256'],
                                  'saved_reopened_replay': reopened})
        report['status'] = 'published_for_review'
        return shared_output, report
    except Exception as exc:
        report['status'] = 'blocked'
        report['error'] = str(exc)
        raise
    finally:
        evidence = output / 'evidence'
        if evidence.is_dir():
            report['evidence_sha256'] = {p.relative_to(output).as_posix(): sha(p)
                                        for p in sorted(evidence.iterdir()) if p.is_file()}
        write_json(output / 'run.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design_id')
    parser.add_argument('run_id', help='New immutable run folder; existing runs are never overwritten')
    parser.add_argument('--shared-root', type=Path, default=SHARED)
    parser.add_argument('--development-root', type=Path, default=DEVELOPMENT)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--pdf', type=Path)
    inputs.add_argument('--recipe', type=Path)
    inputs.add_argument('--recorded-part', type=Path)
    parser.add_argument('--relax', action='store_true', help='Require a recorded clash-aware rigid-body fit')
    args = parser.parse_args()
    try:
        output, report = run(design_id=args.design_id, run_id=args.run_id,
            shared_root=args.shared_root, pdf=args.pdf, recipe_path=args.recipe,
            source_part=args.recorded_part, relax=args.relax, development_root=args.development_root,
            progress=lambda n, total: print(f'Native authoring: {n}/{total}', flush=True))
    except (ValueError, FileExistsError) as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps({'output': str(output), 'status': report['status']}, indent=2))


if __name__ == '__main__':
    main()
