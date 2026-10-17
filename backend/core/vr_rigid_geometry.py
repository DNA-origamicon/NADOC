"""Rigid elements in native scene exports, with canonical selectable owners."""
import json
import numpy as np
from backend.core.protein import compose_protein_world_transform, resolve_overhang_anchor


def append_rigid_elements(design, geometry, rotation, emit, owner_tokens):
    def palette(hex_color):
        return tuple(((hex_color >> shift) & 255)/255 for shift in (16,8,0))*4

    for p in getattr(design, 'nanoparticles', ()):
        if not p.visible:
            continue
        token = owner_tokens(('nanoparticle', p.id))
        identity = 'rigid-ref:' + json.dumps(['nanoparticle',p.id,'core'],separators=(',',':'))
        color = palette(0xE4B84D if p.kind == 'gold_nanosphere' else 0xB06FE8)
        emit('P',identity,*(rotation @ p.pose.to_array()[:3,3]),p.diameter_nm/2,*color,aliases=token)
    assets = {a.id:a for a in getattr(design, 'protein_assets', ())}
    for p in getattr(design, 'protein_attachments', ()):
        if not p.visible or p.asset_id not in assets:
            continue
        asset = assets[p.asset_id]
        tip, outward = resolve_overhang_anchor(geometry,p.target.overhang_id,p.target.attach_end) if p.target.kind == 'overhang' else (None,None)
        world = compose_protein_world_transform(asset,p,tip,outward)
        atoms = [a for a in asset.atoms if a.name == 'CA'] or asset.atoms
        aliases = owner_tokens(('protein',p.id))
        color = palette(0x58A6FF)
        previous = {}
        for i,a in enumerate(atoms):
            point = rotation @ (world @ np.array([a.x,a.y,a.z,1]))[:3]
            identity = 'rigid-ref:' + json.dumps(['protein',p.id,str(i)],separators=(',',':'))
            emit('P',identity,*point,.16,*color,aliases=aliases)
            if a.chain_id in previous:
                old = previous[a.chain_id]
                if np.linalg.norm(point-old) <= 1.2:
                    emit('C','rigid-ref:'+json.dumps(['protein',p.id,str(i)+':trace'],separators=(',',':')),*old,*point,.16,*color,aliases=aliases)
            previous[a.chain_id] = point
