"""Guest pixels must match actual native label/icon or tool-guide projections."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

def check(folder,action,offscreen=False):
    folder=Path(folder);data=json.loads((folder/f'guest-{action}.json').read_text())
    rgb=np.asarray(Image.open(folder/f'canvas-{action}.png').convert('RGB')).astype(int)
    if action=='off':
        colored=((np.max(abs(rgb-[66,220,232]),axis=2)<12)|(np.max(abs(rgb-[255,179,77]),axis=2)<12)).sum()
        return {'passed':not data['visible'] and int(colored)<100,'colored_pixels':int(colored)}
    found=[]
    for sample in data['samples']:
        x,y=np.asarray(sample['point'])+(10000 if offscreen else 0)
        if not np.isfinite([x,y]).all():continue
        x,y=int(round(x)),int(round(y))
        patch=rgb[max(0,y-2):y+3,max(0,x-2):x+3] if 0<=x<rgb.shape[1] and 0<=y<rgb.shape[0] else np.empty((0,0,3))
        found.append(bool(patch.size and (np.max(abs(patch-sample['rgb']),axis=2)<45).any()))
    coverage=sum(found)/max(1,len(found))
    return {'passed':len(found)>20 and coverage>=.6,'coverage':coverage,'samples':len(found)}
if __name__=='__main__':
    folder,action=sys.argv[1:3];result=check(folder,action)
    (Path(folder)/f'pixels-{action}.json').write_text(json.dumps(result,indent=2))
    assert result['passed'],result
    if action!='off':assert not check(folder,action,True)['passed']
