"""Parse completed native logs, including restart energies before the first header."""
import math


def parse_log(path, terminal=True):
    if not terminal:
        raise ValueError('This parser requires a completed native log')
    text = path.read_text()
    assert 'FATAL ERROR' not in text and 'End of program' in text
    lines = text.splitlines()
    headers = [line.split()[1:] for line in lines if line.startswith('ETITLE:')]
    assert headers, 'No native energy column header'
    titles = headers[0]
    assert len(set(titles)) == len(titles)
    assert all(h == titles for h in headers), 'Energy columns changed within log'
    rows = []
    for line in lines:
        if line.startswith('ENERGY:'):
            values = list(map(float, line.split()[1:]))
            assert len(values) == len(titles) and all(map(math.isfinite, values))
            rows.append(dict(zip(titles, values)))
    assert rows
    return rows
