"""Read-only article screening. Evidence detection is never topology validation."""
import base64
import binascii
import re
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
import pymupdf

from backend.core.image_evaluation import MAX_PAGES

CHECKS = (
    ('paper', 'Paper available or findable'),
    ('origami', 'DNA origami identified'),
    ('supplement', 'caDNAno diagram evidence in supplements'),
    ('detail', 'Image detail analysis'),
    ('reconstruction', 'Reconstruction feasibility and confidence'),
)


def decode_pdf(item):
    try:
        data = base64.b64decode(item['data'], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ValueError('Invalid PDF upload.') from exc
    if not data.startswith(b'%PDF-'):
        raise ValueError('Upload a valid PDF.')
    return data


def pdf_text(data):
    try:
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            if doc.needs_pass or len(doc) > MAX_PAGES:
                raise ValueError('Use an unlocked PDF with at most 100 pages.')
            return '\n'.join(page.get_text() for page in doc)
    except RuntimeError as exc:
        raise ValueError('The PDF could not be read.') from exc


def lookup_doi(value):
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value.strip(), flags=re.I)
    doi = re.sub(r'^doi:\s*', '', doi, flags=re.I)
    if not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        raise ValueError('Enter a DOI such as 10.1038/example, or upload the paper PDF.')
    # Fixed public literature services; never follow arbitrary publisher URLs.
    text, notes = [], []
    found = False
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        try:
            record = remote_json(client, 'https://api.crossref.org/works/' + quote(doi, safe=''))['message']
            text.extend(record.get('title', []))
            text.append(record.get('abstract', ''))
            found = True
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            notes.append(f'Crossref lookup unavailable ({type(exc).__name__}).')
        try:
            records = remote_json(client, 'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                                  params={'query': f'DOI:"{doi}"', 'format': 'json', 'resultType': 'core', 'pageSize': 1})
            for record in records.get('resultList', {}).get('result', []):
                # Require the result to identify the requested DOI, not just match search text.
                if record.get('doi', '').lower() != doi.lower():
                    continue
                found = True
                text.extend([record.get('title', ''), record.get('abstractText', '')])
                pmcid = record.get('pmcid', '')
                if re.fullmatch(r'PMC[0-9]+', pmcid) and record.get('isOpenAccess') == 'Y':
                    xml = remote_bytes(client, f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML')
                    root = ElementTree.fromstring(xml)
                    text.append(' '.join(root.itertext()))
                    notes.append('Open-access full text and available captions read from Europe PMC.')
        except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
            notes.append(f'Europe PMC full-text lookup unavailable ({type(exc).__name__}).')
    if not found:
        raise ValueError('Paper could not be found with the available services. Check the DOI, retry, or upload the paper PDF. ' + ' '.join(notes))
    return {'text': '\n'.join(text), 'notes': notes}


def remote_bytes(client, url, **kwargs):
    """Read remote metadata/full text incrementally."""
    with client.stream('GET', url, **kwargs) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
    return bytes(data)


def remote_json(client, url, **kwargs):
    import json
    return json.loads(remote_bytes(client, url, **kwargs))


def diagram_evidence(text, *, supplement=False):
    """Caption/label evidence is sufficient for screening, not recovered topology."""
    normalized = re.sub(r'\s+', ' ', text)
    for match in re.finditer(r'ca[\s-]*dna[\s-]*no', normalized, re.I):
        context = normalized[max(0, match.start()-160):match.end()+160]
        diagram = re.search(r'diagram|schematic|routing|design|representation', context, re.I)
        supplemental = supplement or re.search(r'supplement|supporting|(?:fig(?:ure)?\.?|table)\s*S\d', context, re.I)
        if diagram and supplemental:
            return context.strip()
    return None


def screen_article(payload):
    """Yield actual stage results incrementally; never author or modify a design."""
    paper_text = ''
    paper_ok = False
    origami = False
    evidence = None
    notes = []
    for key, label in CHECKS:
        if key in ('detail', 'reconstruction'):
            detail = ('Use Detect designs to extract diagram paths, pair staple lists and compare direction hypotheses. Image completeness remains to be assessed.' if key == 'detail' else
                      'Later stage: derive the required information and report reconstruction confidence. caDNAno files are not required.')
            yield {'id': key, 'label': label, 'status': 'deferred', 'detail': detail}
            continue
        yield {'id': key, 'label': label, 'status': 'running', 'detail': 'Checking…'}
        try:
            if key == 'paper':
                if payload.get('paper'):
                    paper_text = pdf_text(decode_pdf(payload['paper']))
                    detail = 'Uploaded paper PDF opened successfully.'
                elif payload.get('doi'):
                    record = lookup_doi(payload['doi'])
                    paper_text = record['text']
                    notes = record['notes']
                    detail = 'Paper found by DOI. Checked available metadata and open-access text. ' + ' '.join(notes)
                else:
                    raise ValueError('Enter a DOI or upload a paper PDF.')
                paper_ok = True
                passed = True
            elif key == 'origami':
                origami = paper_ok and bool(re.search(r'\bDNA[\s-]+origami\b', paper_text, re.I))
                passed = origami
                detail = ('DNA origami identified in available article text.' if passed else
                          'DNA origami not confirmed in available text; this does not establish absence. Supply a searchable paper PDF if access is limited.')
            else:
                evidence = diagram_evidence(paper_text)
                supplement_text = []
                for item in payload.get('supplements', []):
                    text = pdf_text(decode_pdf(item))
                    supplement_text.append(text)
                    evidence = evidence or diagram_evidence(text, supplement=True)
                passed = bool(evidence)
                if passed:
                    detail = 'Diagram evidence found: “' + evidence + '”. Sufficient to proceed to image analysis; image quality has not yet been assessed.'
                else:
                    detail = 'No supplemental caDNAno diagram label or description found in accessible text. Upload the supplement if it is not available in the article text.'
                has_staples = bool(re.search(r'staple|oligonucleotide', ' '.join([paper_text, *supplement_text]), re.I))
                detail += (' Staple/oligonucleotide list mentioned; completeness unchecked.' if has_staples else
                           ' Staple list not confirmed; this does not block image analysis.')
            yield {'id': key, 'label': label, 'status': 'passed' if passed else 'failed', 'detail': detail}
        except (ValueError, KeyError, TypeError, httpx.HTTPError, RuntimeError) as exc:
            if key == 'supplement':
                evidence = None
            yield {'id': key, 'label': label, 'status': 'failed', 'detail': str(exc)}
    yield {'type': 'complete', 'can_reconstruct': False,
           'ready_for_analysis': bool(paper_ok and origami and evidence), 'confidence': None}
