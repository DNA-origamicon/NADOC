"""Verify the guest's actual colored bones at their projected positions."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

def check(directory,action,offscreen=False):
    directory=Path(directory)
    evidence=json.loads((directory/f'guest-{action}.json').read_text())
    rgb=np.asarray(Image.open(directory/f'canvas-{action}.png').convert('RGB')).astype(int)
    mask=(np.max(abs(rgb-[66,220,232]),axis=2)<12)|(np.max(abs(rgb-[255,179,77]),axis=2)<12)
    points=np.asarray(evidence['points'])+(10000 if offscreen else 0)
    found=[]
    for x,y in points:
        x,y=int(round(x)),int(round(y))
        found.append(bool(0<=x<mask.shape[1] and 0<=y<mask.shape[0] and mask[max(0,y-4):y+5,max(0,x-4):x+5].any()))
    coverage=sum(found)/max(1,len(found))
    result={'passed':len(found)==6 and coverage>=.66 and int(mask.sum())>100,'coverage':coverage,'colored_pixels':int(mask.sum())}
    if not offscreen:(directory/f'pixels-{action}.json').write_text(json.dumps(result,indent=2))
    return result
if __name__=='__main__':
    folder,action=sys.argv[1:3]
    result=check(folder,action)
    if action=='off':assert not result['passed'] and result['colored_pixels']<100,result
    else:
        assert result['passed'],result
        assert not check(folder,action,offscreen=True)['passed']
