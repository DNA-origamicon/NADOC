"""Partial connector drawings whose endpoint continuity is not yet recovered."""
import numpy as np


def offset_run_hypotheses(traces, lanes, labels, pitch, *, maximum_candidates=100):
    if not 1 <= maximum_candidates <= 500:
        raise ValueError('Invalid offset-run budget.')
    candidates=[];truncated=False
    known=[r for r in lanes.get('rows',[]) if r['staple_side'] is not None]
    for trace in traces:
        hues=trace['hue_bins']
        if not hues or len(hues)>3 or trace['kind']=='scaffold':
            continue
        compatible={v for v in range(13) if any(v==h or (v<12 and h<12 and min((v-h)%12,(h-v)%12)<=1) for h in hues)}
        for domain_index,domain in enumerate(trace['domains']):
            if domain['kind']!='unclassified' or not known:
                continue
            (left,y),(right,_)=domain['span_pixels']
            distance,row,side=min((abs(y-lane),r['observed_row_index'],s) for r in known for s,lane in enumerate(r['lane_y']))
            row_data=next(r for r in known if r['observed_row_index']==row)
            if side!=row_data['staple_side'] or not pitch*.25<=distance<=2.5*pitch:
                continue
            baseline=row_data['lane_y'][side]
            contacts=[]
            for endpoint,is_left in ((left,True),(right,False)):
                lo,hi=(endpoint-4*pitch,endpoint+1) if is_left else (endpoint-1,endpoint+4*pitch)
                xs=range(max(1,int(lo)),min(labels.shape[1]-1,int(hi)+1))
                ys=range(max(0,round(baseline)-1),min(labels.shape[0],round(baseline)+2))
                hits=[]
                for x in xs:
                    matched=[yy for yy in ys if int(labels[yy,x]) in compatible and
                             sum(int(labels[yy,xx]) in compatible for xx in (x-1,x,x+1))>=2]
                    if matched:hits.append((abs(x-endpoint),[float(x),float(np.mean(matched))]))
                hits.sort(key=lambda v:(v[0],v[1]))
                contacts.append([p for _,p in hits[:3]])
            if not any(contacts):
                continue
            if len(candidates)>=maximum_candidates:
                truncated=True;break
            candidates.append({'candidate_id':len(candidates),'kind':'partial_same_helix_offset_connector',
                               'source_trace_id':trace['trace_id'],'source_domain_index':domain_index,
                               'observed_row_index':row,'lane_side':side,'observed_hue_bins':hues,
                               'color_continuity_supported':trace['color_continuity_supported'],
                               'offset_pixels':float(distance),'span_pixels':domain['span_pixels'],
                               'contact_candidates_pixels':contacts,
                               'missing_attachment_sides':[i for i,c in enumerate(contacts) if not c],
                               'status':'endpoint_continuity_unresolved',
                               'base_count_from_drawing':None,'connections_applied':False,
                               'native_routing_resolved':False})
    return {'method':'off-lane-run-with-local-contact-evidence-v1','candidates':candidates,
            'truncated':truncated,'maximum_candidates':maximum_candidates,
            'limitation':'Offset runs and nearby same-lane color evidence only. Proximity does not establish connectivity; no gap is filled or staple merged.'}


def offset_marker_hypotheses(traces, lanes, labels, pitch, *, maximum_candidates=100):
    """Retain small neutral endpoint-marker evidence near a staple domain.

    Neither square/arrow identity nor a ligation is inferred from a dark blob.
    These observations explain missing attachment evidence in offset drawings.
    """
    from scipy.ndimage import label, find_objects
    components,count=label(labels==12)
    rows=[r for r in lanes.get('rows',[]) if r['staple_side'] is not None]
    candidates=[];truncated=False
    for component,box in enumerate(find_objects(components),1):
        if box is None or not rows:
            continue
        yy,xx=np.nonzero(components[box]==component)
        # A solitary dark pixel can be a base-index glyph or compression noise;
        # it provides no shape evidence for an endpoint marker.
        if not 2<=len(xx)<=2*pitch*pitch:
            continue
        width,height=box[1].stop-box[1].start,box[0].stop-box[0].start
        if max(width,height)>2*pitch:
            continue
        x,y=float(xx.mean()+box[1].start),float(yy.mean()+box[0].start)
        distance,row,side=min((abs(y-lane),r['observed_row_index'],s) for r in rows for s,lane in enumerate(r['lane_y']))
        row_data=next(r for r in rows if r['observed_row_index']==row)
        if side!=row_data['staple_side'] or not pitch*.25<=distance<=2*pitch:
            continue
        attached=[]
        for trace in traces:
            for d in trace['domains']:
                if d['kind']=='staple' and d['observed_row_index']==row and min(abs(x-p[0]) for p in d['span_pixels'])<=4*pitch:
                    attached.append(trace['trace_id']);break
        if not attached:
            continue
        if len(candidates)>=maximum_candidates:
            truncated=True;break
        candidates.append({'candidate_id':len(candidates),'kind':'offset_endpoint_marker',
                           'observed_row_index':row,'lane_side':side,'center_pixels':[x,y],
                           'bounds_pixels':[[box[1].start,box[0].start],[box[1].stop,box[0].stop]],
                           'associated_trace_ids':attached,'offset_pixels':distance,
                           'dark_pixel_count':len(xx), 'evidence_resolution':'single_dark_pixel' if len(xx)==1 else 'pixel_cluster',
                           'marker_type':'unresolved','ligation_assignment':'unresolved',
                           'native_routing_resolved':False})
    return {'method':'neutral-offset-marker-evidence-v1','candidates':candidates,'truncated':truncated,
            'limitation':'Nearby endpoint-marker evidence only; no polarity, attachment or ligation has been assigned.'}
