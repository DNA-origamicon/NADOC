"""Check actual Bend handle pixels at independently projected world locations."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from tools.vr_motion.visual_checks import project


def check(directory, *, displacement=0):
    directory = Path(directory)
    evidence = json.loads((directory/'evidence.json').read_text())
    state = evidence['state']
    handles = state.get('twist', state.get('bend'))['handles']
    eyes = {}
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        # Native Bend rings are mint, or yellow while held. Avoid red/blue DNA.
        mint = (rgb[:,:,0] < 120) & (rgb[:,:,1] > 180) & (rgb[:,:,2] > 150)
        yellow = (rgb[:,:,0] > 180) & (rgb[:,:,1] > 180) & (rgb[:,:,2] < 120)
        visible = mint | yellow
        counts = []
        for center in handles:
            center = np.array(center)+[displacement,0,0]
            corners = [project(center+offset, eye) for offset in
                ([x,y,z] for x in (-.024,.024) for y in (-.024,.024) for z in (-.024,.024))]
            if any(p is None for p in corners):
                counts.append(0); continue
            lo = np.floor(np.min(corners, axis=0)).astype(int)
            hi = np.ceil(np.max(corners, axis=0)).astype(int)
            if np.any(lo < 0) or hi[0] >= eye['width'] or hi[1] >= eye['height']:
                counts.append(0); continue
            counts.append(int(visible[lo[1]:hi[1]+1,lo[0]:hi[0]+1].sum()))
        eyes[eye['eye']] = {'handle_pixels': counts, 'passed': len(counts) == 2 and min(counts) >= 12}
    return {'passed': bool(eyes) and all(e['passed'] for e in eyes.values()), 'eyes': eyes}


def validate(directory):
    result = check(directory)
    result['offscreen_negative_passed'] = not check(directory, displacement=100)['passed']
    (Path(directory)/'bend-pixels.json').write_text(json.dumps(result, indent=2))
    assert result['passed'] and result['offscreen_negative_passed'], result
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    validate(parser.parse_args().directory)
