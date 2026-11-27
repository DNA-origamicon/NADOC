"""Decode damaged numeric PDF labels by deterministic glyph template matching.

PDF subset fonts sometimes have incorrect ToUnicode maps. Rasterize the actual
visible character, never infer its identity from font glyph IDs or design files.
Only confidently matched all-digit spans are returned; no OCR service is used.
"""
from functools import lru_cache

import numpy as np
from PIL import Image
import pymupdf


def _mask(pix):
    pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = pixels[:, :, :3].min(axis=2) < 160
    ys, xs = np.where(ink)
    if not len(xs):
        return None
    crop = ink[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return np.asarray(Image.fromarray(crop).resize((24, 40), Image.Resampling.NEAREST), bool)


@lru_cache(maxsize=1)
def _templates():
    output = []
    with pymupdf.open() as doc:
        page = doc.new_page(width=100, height=100)
        for font in ('helv', 'hebo', 'tiro', 'cour'):
            for digit in '0123456789':
                page = doc.new_page(width=100, height=100)
                page.insert_text((15, 70), digit, fontsize=60, fontname=font)
                output.append((digit, _mask(page.get_pixmap())))
    return output


def numeric_labels(page):
    """Return numeric spans with baseline origins and observed glyph confidence.

    Glyphs are matched once per font/glyph, including Unicode digits: a broken
    mapping can substitute the wrong digit too. Prose is excluded first.
    """
    traces = page.get_texttrace()
    cache, output = {}, []
    for span in traces:
        chars = span['chars']
        if not chars or len(chars) > 5:
            continue
        raw = ''.join(chr(c[0]) for c in chars)
        if any(c.isalpha() for c in raw):
            continue
        decoded, scores = [], []
        for unicode, glyph, origin, bbox in chars:
            key = (span['font'], glyph)
            if key not in cache:
                rect = pymupdf.Rect(bbox)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(min(40, 70/span['size']), min(40, 70/span['size'])), clip=rect, colorspace=pymupdf.csRGB, alpha=False)
                mask = _mask(pix)
                ranks = {}
                if mask is not None:
                    for digit, template in _templates():
                        score = np.count_nonzero(mask & template) / max(1, np.count_nonzero(mask | template))
                        ranks[digit] = max(ranks.get(digit, 0), score)
                ordered = sorted(ranks.items(), key=lambda pair: -pair[1])
                cache[key] = ordered[0] if len(ordered)>1 and ordered[0][1]>.68 and ordered[0][1]-ordered[1][1]>.06 else (None, 0)
            digit, score = cache[key]
            if digit is None:
                break
            decoded.append(digit); scores.append(score)
        if len(decoded) == len(chars):
            output.append({'value':int(''.join(decoded)), 'x':chars[0][2][0],
                           'y':chars[0][2][1], 'confidence':min(scores), 'raw':raw,
                           'direction':tuple(round(value) for value in span['dir'])})
    return output
