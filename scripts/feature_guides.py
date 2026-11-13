"""Portable guide catalog, source fingerprints, Markdown rendering and checks.

Standard-library only: checking documentation never starts NADOC or a browser.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

REPO = Path(__file__).resolve().parents[1]
GUIDES = Path('docs/guides')
CATALOG = GUIDES / 'catalog.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, relative):
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts:
        raise ValueError(f'Expected repository-relative path: {relative}')
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes repository: {relative}')
    return resolved


def inventory(root):
    """Read the existing main-feature/subfeature convention in FEATURES.md."""
    result, category, current = {}, '', None
    for line in (root / 'FEATURES.md').read_text().splitlines():
        if line.startswith('## '):
            category = line[3:]
        match = re.fullmatch(r'- \*\*(.+)\*\*', line)
        if match:
            name = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', match[1])
            key = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            if key in result:
                raise ValueError(f'Duplicate feature: {key}')
            current = {'name': name, 'category': category, 'subfeatures': []}
            result[key] = current
        elif line.startswith('  - ') and current is not None:
            current['subfeatures'].append(line[4:])
    if not result:
        raise ValueError('FEATURES.md contains no recognized features')
    return result


def load_catalog(root=REPO):
    catalog = json.loads((root / CATALOG).read_text())
    if catalog.get('schema') != 1 or not isinstance(catalog.get('features'), dict):
        raise ValueError('Unsupported guide catalog schema')
    for key, feature in catalog['features'].items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key):
            raise ValueError(f'Invalid feature ID: {key}')
        if feature.get('status') not in {'planned', 'partial', 'complete', 'blocked'}:
            raise ValueError(f'Invalid coverage status: {key}')
        if feature.get('guide'):
            inside(root, str(GUIDES / feature['guide']))
            if not feature.get('watch') or not feature.get('covered_workflows'):
                raise ValueError(f'Missing dependencies or coverage scope: {key}')
        elif feature['status'] in {'partial', 'complete'}:
            raise ValueError(f'Coverage claimed without a guide: {key}')
    return catalog


def snapshot(root, catalog, feature):
    patterns = sorted(set(catalog['shared_watch'] + feature['watch']))
    files, unmatched = {}, []
    for pattern in patterns:
        inside(root, pattern)
        matches = [p for p in root.glob(pattern) if p.is_file() and not p.name.endswith('.test.js')]
        if not matches:
            unmatched.append(pattern)
        for path in matches:
            inside(root, path.relative_to(root).as_posix())
            files[path.relative_to(root).as_posix()] = digest(path)
    return {'patterns': patterns, 'files': dict(sorted(files.items())), 'unmatched': unmatched}


def changed_files(before, after):
    return [{'path': name, 'change': 'added' if name not in before else 'deleted' if name not in after else 'modified'}
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]


def directory_hashes(directory):
    return {p.relative_to(directory).as_posix(): digest(p)
            for p in directory.rglob('*') if p.is_file()}


def promote_directory(stage, output, expected=None):
    """Replace only a known unchanged generated directory, with rollback on failure."""
    backup = None
    if output.exists():
        if expected is None or directory_hashes(output) != expected:
            raise ValueError(f'Output exists or changed during capture: {output}')
        backup = Path(tempfile.mkdtemp(prefix='.guide-backup-', dir=output.parent))
        backup.rmdir()
        output.rename(backup)
    elif expected is not None:
        raise ValueError('Existing guide disappeared during capture')
    try:
        stage.rename(output)
    except BaseException:
        if backup is not None:
            backup.rename(output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def render_guide(steps, feature):
    lines = [f'# {steps["title"]}', '', '[All guides](../README.md) · [Coverage ledger](../LEDGER.md)', '',
             feature['introduction'], '',
             'Numbered arrows point to',
             'mouse targets while keeping their labels visible. Dashed boxes show drag extents.',
             'Unmarked images show settings or results. This is an editorial draft for style review.', '',
             '[Download the example](example.nadoc) · [Construction verification](verification.json) ·',
             '[Capture and source metadata](manifest.json) · [UX findings](../UX_LEDGER.md)', '',
             '## Scope', '', *[f'- {s}' for s in feature['covered_workflows']], '']
    sections = steps.get('sections') or [{'title': None, 'body': ''}]
    if steps.get('sections'):
        lines.extend(['## Contents', '', *[f'- [{s["title"]}](#{re.sub(r"[^a-z0-9 -]", "", s["title"].lower()).replace(" ", "-")})' for s in sections], ''])
    for section in sections:
        if section['title']:
            lines.extend([f'## {section["title"]}', '', section['body'], ''])
        for step in steps['steps']:
            if step.get('section') != section['title']:
                continue
            lines.extend([f'### Step {step["number"]}', '', step['caption'], '',
                          f'![Step {step["number"]}: {step["caption"]}]({step["file"]})', ''])
    return '\n'.join(lines)


def inspect_guides(root=REPO):
    catalog = load_catalog(root)
    known = inventory(root)
    findings, rows = [], []
    for key in sorted(known.keys() | catalog['features'].keys()):
        if key not in catalog['features']:
            findings.append(f'Unregistered feature: {key}')
        elif key not in known:
            findings.append(f'Feature removed/renamed in FEATURES.md: {key}')
        elif any(known[key][field] != catalog['features'][key].get(field)
                 for field in ('name', 'category', 'subfeatures')):
            findings.append(f'Inventory changed: {key} (reconcile catalog scope)')
    for key, feature in catalog['features'].items():
        row = {'id': key, 'name': feature['name'], 'coverage': feature['status'],
               'state': 'not-created', 'created_at': None, 'captured_at': None, 'changes': [], 'problems': []}
        if not feature.get('guide'):
            rows.append(row)
            continue
        directory = inside(root, str(GUIDES / feature['guide']))
        try:
            manifest = json.loads((directory / 'manifest.json').read_text())
            if manifest['schema'] != 1 or manifest['feature'] != key:
                raise ValueError('Manifest identity/schema mismatch')
            row.update(created_at=manifest['created_at'], captured_at=manifest['captured_at'])
            current = snapshot(root, catalog, feature)
            row['changes'] = changed_files(manifest['source']['files'], current['files'])
            if manifest['source']['patterns'] != current['patterns']:
                row['changes'].append({'path': 'catalog watch patterns', 'change': 'modified'})
            if manifest['covered_workflows'] != feature['covered_workflows']:
                row['changes'].append({'path': 'catalog covered workflows', 'change': 'modified'})
            if manifest['introduction'] != feature['introduction']:
                row['changes'].append({'path': 'catalog introduction', 'change': 'modified'})
            row['problems'].extend(f'No files match dependency: {p}' for p in current['unmatched'])
            assets = manifest['assets']
            required = {'README.md', 'steps.json', 'example.nadoc', 'verification.json'}
            if not required <= assets.keys():
                raise ValueError('Manifest is missing required asset hashes')
            actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()} - {'manifest.json'}
            if actual != assets.keys():
                row['problems'].append('Guide asset inventory differs from capture')
            for name, expected in assets.items():
                asset = inside(directory, name)
                if not asset.is_file() or digest(asset) != expected:
                    row['problems'].append(f'Missing or modified guide asset: {name}')
            steps = json.loads((directory / 'steps.json').read_text())
            for step in steps['steps']:
                if step['file'] not in assets:
                    row['problems'].append(f'Step image missing from manifest: {step["file"]}')
            row['state'] = 'broken' if row['problems'] else 'stale' if row['changes'] else 'current'
        except (OSError, ValueError, KeyError, TypeError) as error:
            row['state'] = 'broken'
            row['problems'].append(str(error))
        rows.append(row)
    return {'inventory_problems': findings, 'guides': rows}


def render_ledger(root=REPO):
    """Stable coverage ledger; dynamic source freshness is always checked live."""
    catalog = load_catalog(root)
    lines = ['# Feature guide ledger', '', '[Guide library](README.md) · [Maintenance](MAINTENANCE.md) · [UX findings](UX_LEDGER.md)', '',
             'Generated from `catalog.json` and capture manifests. Dates are ISO 8601 with timezone.',
             'Coverage describes the listed workflows, not every subfeature or editor context.',
             'Run `python3 -m scripts.check_feature_guides` for current source freshness;',
             'this table deliberately does not freeze a potentially stale “current” badge.', '',
             '| Feature | Coverage | First created | Last captured | Guide / scope |',
             '|---|---|---|---|---|']
    category = None
    for feature in catalog['features'].values():
        if category != feature['category']:
            category = feature['category']
            lines.append(f'| **{category}** | | | | |')
        first, latest, link = '—', '—', 'Not created'
        if feature.get('guide'):
            directory = inside(root, str(GUIDES / feature['guide']))
            try:
                manifest = json.loads((directory / 'manifest.json').read_text())
                first, latest = manifest['created_at'], manifest['captured_at']
            except (OSError, ValueError, KeyError, TypeError):
                first, latest = 'Missing manifest', 'Missing manifest'
            link = f'[{feature["guide"]}]({feature["guide"]}/README.md): ' + '; '.join(feature['covered_workflows'])
        elif feature.get('reason'):
            link = feature['reason']
        lines.append(f'| {feature["name"]} | {feature["status"]} | {first} | {latest} | {link.replace("|", "&#124;")} |')
    return '\n'.join(lines) + '\n'
