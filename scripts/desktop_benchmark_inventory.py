"""Static desktop benchmark census. Does not import or start NADOC.

Run from any directory: python scripts/desktop_benchmark_inventory.py
Classification is ownership mapping, never evidence of measured latency.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks/desktop'

# First matching ownership rule wins; unclassified files remain visible.
DOMAINS = [
    ('history', r'design_revisions|feature|part_|recipe|immutable|recovery|generated_|snapshot|proof'),
    ('assembly', r'instance_layout|kinematics|group_gizmo|assembly|connector|joint|belt|gear|loadout|polymer|cluster|pattern'),
    ('simulation', r'routes_md\.|periodic_cell|physical_input|thermo|ssdna_fjc|exp_|routes_exp|/parameterization/|/checkers/|md_|namd|oxdna|mrdna|cando|snupi|fem|simulate|simulation|relax|physics|xpbd|electrode|lammps|openmm|gromacs|engine|autorefine|blade|ion_transport|thermal'),
    ('jobs', r'resume_transfer|hardware|system_resources|job|queue|runpod|alpine|remote|ssh|slurm|chain_sim'),
    ('chemistry', r'two_np|attachment_layout|binding_drivers|protein|aptamer|biotin|streptavidin|nanoparticle|quantum|thiol|coating|peg_|cpd|photoproduct|gold|conjugat'),
    ('authoring', r'generation_progress|generate_design|generator|build_spec|backbone|base_keys|bp_index|chain_ids|connection_|continuation_source|element_copy|flexible_segments|join_crossbars|junction_topology|origami_path|t_junction|seamed_router|seamless_router|section_router|legacy_plane|cadnano|scaffold|staple|routing|sequence|strand|nucleotide|helix|helices|lattice|duplex|crossover|overhang|ligation|nick|loop|skip|hairpin|extension|extrud|sweep|primitive|frame_cell|subdomain|corner|hinge|branch|connectivity|design_diff|headless|linker|bend'),
    ('rendering', r'atom_serial_index|atomistic|atom_filter|atom_table|attribute_updates|expanded_spacing|extra_base_spacing|glow|occupancy|instance_alpha|native_connection_lines|design_scene_visibility|reference_models|flex_tethers|flexible_arcs|view_volume|visibility|render|surface|geometry|display|color|colour|material|lighting|camera|viewport|postprocess|shadow|ambient|clash|lod|picking|selection|select|deform|representation|visualization|photo|texture|mesh|bead|raycast|frustum|occlusion'),
    ('playback', r'dcd_fast|encode_webm|motion_chip|animation|trajectory|playback|interpolat|frame|strand-anim'),
    ('sharing', r'viewer|meeting|present|share|collaborat|broadcast|peer|websocket|(^|/)ws\.'),
    ('documents', r'design_identity|design_disk|disk_guard|fs_browse|json_artifacts|clipboard|pdb_to_design|document|project|session|workspace|file|import|export|interchange|persist|autosave|save|library|fs\.|crud|doc_|doc\.|startup|cache|load'),
    ('analysis', r'extra_base_sample_audit|molecular_placement|native_full_placement|native_slab_placement|ring_piercing|validator|fret_|metric|analysis|analyz|shape|comparison|compare|validation|integrity|readiness|qualification|measure|dimension|annotation|mass|hydrodynamic'),
    ('interaction', r'/scene/(axis_snap|base_pick|base_ref|create_seam|cross_section|design_queries|domain_ends|efield|empty_space|end_resize|fit_view|fov_pan|graphene_nanopore|hull_volume|instance_gizmo|lazy_map|move_rotate|multiscale|native_pose|nav_controller|ndc|optimistic_preview|reference_navigation|response_delta|right_click|rotation_math|scene|section_view|slice_|sub_domain|translate_rotate|undefined_highlight|unfold_view|vec_math|view_cube|zoom_scope)|field_anchor'),
    ('shell', r'/library/|/ui/|/app/|/input/|/state/|/shared/|/perf/|/api/client|main\.|constants|server_info|routes_system|routes_benchmark|benchmark|/routes\.|/state\.|/schemas|/models|/api/__init__|/core/__init__|/physics/__init__'),
]


def domain(path):
    return next((name for name, pattern in DOMAINS if re.search(pattern, path)), 'unmapped')


def exclusion(path):
    name = Path(path).name
    if re.search(r'(^|_)vr(_|\.)|headset|native_view_tool', name):
        return 'VR-specific filename (shared desktop consumers may exist)'
    if any(x in path for x in ('/archive/', '/test-helpers/')) or name.endswith('.test.js') or name == 'debug_snippet.js' or '/scene/debug' in path:
        return 'test/archive/debug helper'
    if name.startswith('test_') or '_test_' in name or name.startswith('validation_stub'):
        return 'test helper'
    return ''


def main():
    rows, fingerprints = [], {}
    for base, suffix, layer in [('backend/api', '*.py', 'backend-api-module'),
                                ('backend/core', '*.py', 'backend-core-module'),
                                ('backend/physics', '*.py', 'backend-physics-module'),
                                ('backend/parameterization', '*.py', 'backend-parameterization-module'),
                                ('backend/checkers', '*.py', 'backend-checker-module'),
                                ('backend/library', '*.py', 'backend-library-module'),
                                ('frontend/src', '*.js', 'frontend-module')]:
        for file in sorted((ROOT / base).rglob(suffix)):
            path = file.relative_to(ROOT).as_posix()
            raw = file.read_bytes()
            fingerprints[path] = hashlib.sha256(raw).hexdigest()
            excluded = exclusion(path)
            rows.append(dict(layer=layer, source=path, line=1, operation=file.stem,
                             domain=domain(path), excluded=excluded))
            if layer != 'backend-api-module':
                continue
            tree = ast.parse(raw, filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                        continue
                    if dec.func.attr not in {'get', 'post', 'put', 'patch', 'delete', 'websocket', 'api_route', 'head', 'options'}:
                        continue
                    if not dec.args or not isinstance(dec.args[0], ast.Constant) or not isinstance(dec.args[0].value, str):
                        continue
                    route = dec.args[0].value
                    rows.append(dict(layer='backend-route', source=path, line=node.lineno,
                                     operation=f'{dec.func.attr.upper()} {route} [{node.name}]',
                                     domain=domain(path), excluded=excluded or ('VR route' if '/vr/' in route or route.startswith('/vr') else '')))
    counts = {}
    for layer in sorted({r['layer'] for r in rows}):
        active = [r for r in rows if r['layer'] == layer and not r['excluded']]
        mapped = sum(r['domain'] != 'unmapped' for r in active)
        counts[layer] = dict(total=len(active), mapped=mapped,
                             mapped_percent=round(100 * mapped / len(active), 2) if active else 0,
                             excluded=sum(r['layer'] == layer and bool(r['excluded']) for r in rows),
                             domains=dict(sorted(Counter(r['domain'] for r in active).items())))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'inventory.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = dict(schema=1, git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  scope='Static ownership proxies, not execution-frequency or measured-latency coverage. Routes are decorator declarations, not resolved live URLs.',
                  counts=counts, source_sha256=fingerprints)
    (OUT / 'coverage.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Desktop source coverage (generated)', '',
             'Regenerate with `python scripts/desktop_benchmark_inventory.py`. See [methodology](README.md) before interpreting percentages.', '',
             '| Proxy | Mapped | Eligible | Mapped % | Excluded |', '|---|---:|---:|---:|---:|']
    for layer, c in counts.items():
        lines.append(f"| {layer} | {c['mapped']} | {c['total']} | {c['mapped_percent']}% | {c['excluded']} |")
    lines += ['', '## Ownership domains', '', '| Domain | Routes | Frontend modules | Backend core modules | Physics modules |', '|---|---:|---:|---:|---:|']
    for name in [d[0] for d in DOMAINS] + ['unmapped']:
        values = [counts[layer]['domains'].get(name, 0) for layer in ['backend-route', 'frontend-module', 'backend-core-module', 'backend-physics-module']]
        lines.append('| ' + name + ' | ' + ' | '.join(map(str, values)) + ' |')
    lines += ['', '## Unmapped sources', '', 'These remain in the denominator. Classification does not imply benchmark coverage.', '']
    for path in sorted({r['source'] for r in rows if not r['excluded'] and r['domain'] == 'unmapped'}):
        lines.append(f'- `{path}`')
    (OUT / 'coverage.md').write_text('\n'.join(lines) + '\n')
    workflow_rows = list(csv.DictReader((OUT / 'workflows.tsv').open(), delimiter='\t'))
    assert len({row['id'] for row in workflow_rows}) == len(workflow_rows)
    workflow_counts = Counter()
    lines = ['# Desktop workflow benchmark matrix', '',
             'Each row is a broad operation family, equally weighted. Evidence covers only the stated component, not every operation or end-to-end latency.', '',
             '| ID | Area / operation | Source owner | Evidence status | Fixture and measurement contract |',
             '|---|---|---|---|---|']
    for row in workflow_rows:
        source = row['owner_glob']
        assert list(ROOT.glob(source)), source
        evidence = row['evidence']
        if evidence == 'current':
            status, label = 'current_component', '[Current CPU sample](current_baseline.json)'
        elif evidence.startswith('current:'):
            target = evidence.removeprefix('current:')
            assert (OUT / target).is_file(), target
            status, label = 'current_component', f'[Current component evidence]({target})'
        elif evidence == 'gap':
            status, label = 'gap', 'No evidence linked; proposed benchmark'
        elif evidence.startswith(('scripts/', 'frontend/')):
            assert (ROOT / evidence).is_file(), evidence
            status, label = 'harness_only', f'[Existing harness](../../../{evidence}); not run here'
        else:
            assert (OUT / evidence).is_file(), evidence
            status, label = 'historical_component', f'[Historical component evidence]({evidence}); not refreshed'
        workflow_counts[status] += 1
        lines.append(f"| {row['id']} | {row['area']}: {row['operation']} | [{source}](../../../{source}) | {label} | {row['fixture_and_measurement']} |")
    lines += ['', '## Evidence coverage', '', f"Denominator: {len(workflow_rows)} curated operation families. This is an estimate of breadth, not a count of every UI action.", '']
    for status, count in sorted(workflow_counts.items()):
        lines.append(f'- {status}: {count}/{len(workflow_rows)} ({count / len(workflow_rows):.1%}).')
    lines += ['', 'No row is certified as fully benchmarked across frontend, transport, backend, persistence and visible completion.']
    (OUT / 'workflows.md').write_text('\n'.join(lines) + '\n')
    report['workflow_evidence'] = dict(total=len(workflow_rows), counts=dict(workflow_counts))
    (OUT / 'coverage.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    main()
