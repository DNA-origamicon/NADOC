import hashlib
import json

import numpy as np
from PIL import Image
import pytest
from scipy.ndimage import map_coordinates

from tools.vr_tracking import frame_identity as fi
from tools.vr_tracking.template_tracking import SourceFrame

SESSION = '12345-918966553299961'
SIDE = fi.GRID_CELLS*8


def image(frame=100, eye='left', session=SESSION, cell=8, protocol=fi.PROTOCOL):
    return np.repeat(np.repeat(fi.marker_cells(session, eye, frame, protocol), cell, axis=0), cell, axis=1)


def source(rgb, eye='left', space='application_eye_undistorted'):
    return SourceFrame(rgb, space, {eye:(0,0,rgb.shape[1],rgb.shape[0])}, {'fixture':True})


def decode(rgb, eye='left', session=SESSION, space='application_eye_undistorted', protocol=fi.PROTOCOL):
    return fi.decode_frame_identity(source(rgb,eye,space),eye,session,(0,0,rgb.shape[1],rgb.shape[0]),protocol=protocol)


def assert_id(result, frame=100):
    assert result['status']=='decoded', result
    assert result['identity']['frame']==frame
    assert result['identity']['session']==SESSION
    assert result['lens_calibration'] is False
    assert result['identity']['bit_error_correction'] is False


def test_wire_independent_cpp_zlib_golden_full_uint64():
    packet=fi.marker_packet(f'{0x12345678}-{0x0123456789abcdef}','right',0xfedcba9876543210,fi.LEGACY_PROTOCOL)
    assert packet.hex()=='4e460101123456780123456789abcdeffedcba9876543210a6ba7322a55ac33c'
    result=decode(image(0xfedcba9876543210,'right',f'{0x12345678}-{0x0123456789abcdef}',protocol=fi.LEGACY_PROTOCOL),
                  'right',f'{0x12345678}-{0x0123456789abcdef}',protocol=fi.LEGACY_PROTOCOL)
    assert result['identity']['frame']==0xfedcba9876543210
    assert fi.marker_packet(f'{0x12345678}-{0x0123456789abcdef}','right',0xfedcba9876543210).hex()=='4e460201123456780123456789abcdeffedcba98765432109fc2de62a55ac33c'


@pytest.mark.parametrize('eye',['left','right'])
@pytest.mark.parametrize('space',['application_eye_undistorted','final_swapchain_distorted'])
def test_original_rgb_both_eyes_sources_no_mutation(eye,space):
    rgb=image(2**63+93,eye); before=rgb.tobytes()
    result=decode(rgb,eye,space=space)
    assert_id(result,2**63+93)
    assert result['coordinate_space']==space
    assert rgb.tobytes()==before


@pytest.mark.parametrize('scale',[.4,.65,1.4])
def test_scaled_marker_fixture(scale):
    native=image()
    size=round(len(native)*scale)
    changed=np.array(Image.fromarray(native).resize((size,size),Image.Resampling.BILINEAR))
    assert_id(decode(changed))


def test_projective_fixture_with_mild_radial_warp():
    # Inverse map output coordinates to the original, independently specified
    # affine/perspective transform plus a small nonlinear radial perturbation.
    native=image()
    yy,xx=np.mgrid[:240,:260].astype(float)
    h=np.array([[1.03,.12,25.0],[-.035,.98,31.0],[.0004,-.0003,1.]])
    points=np.stack([xx.ravel(),yy.ravel(),np.ones(xx.size)])
    mapped=np.linalg.inv(h)@points
    sx=(mapped[0]/mapped[2]).reshape(xx.shape);sy=(mapped[1]/mapped[2]).reshape(xx.shape)
    center=(SIDE-1)/2;dx=(sx-center)/(SIDE/2);dy=(sy-center)/(SIDE/2);radial=.008*(dx*dx+dy*dy)
    sx+=(sx-center)*radial;sy+=(sy-center)*radial
    distorted=np.stack([map_coordinates(native[:,:,c].astype(float),[sy,sx],order=1,mode='constant',cval=0)
                        for c in range(3)],axis=2).clip(0,255).astype(np.uint8)
    result=decode(distorted,space='final_swapchain_distorted')
    assert_id(result)
    assert result['lens_calibration'] is False


@pytest.mark.parametrize('damage',['bit','occlusion','uncertain','all_black','checker','gray_payload'])
def test_invalid_unmarked_or_damaged_pixels_unknown(damage):
    rgb=image()
    if damage=='bit':rgb[8*8:9*8,8*8:9*8]=255-rgb[8*8:9*8,8*8:9*8]
    if damage=='occlusion':rgb[:24,:24]=0
    if damage=='uncertain':rgb[8*8:9*8,8*8:9*8]=127
    if damage=='all_black':rgb[:]=0
    if damage=='checker':rgb[:]=np.repeat(((np.indices(rgb.shape[:2]).sum(axis=0)%2)*255)[:,:,None],3,axis=2)
    if damage=='gray_payload':rgb[24:152,24:152]=127
    result=decode(rgb)
    assert result['status']=='unknown' and result['identity'] is None
    if damage=='bit':assert result['candidate_rejections'].get('crc_mismatch')==1
    if damage=='uncertain':assert result['candidate_rejections'].get('uncertain_payload_bits')==1


@pytest.mark.parametrize('change',['session','eye'])
def test_valid_packet_wrong_exact_identity_rejected(change):
    result=decode(image(session='54321-918966553299961' if change=='session' else SESSION,
                        eye='right' if change=='eye' else 'left'))
    assert result['status']=='unknown'
    assert result['candidate_rejections'].get(change+'_mismatch')==1


def test_two_valid_markers_explicit_ambiguous_even_if_identical():
    rgb=np.zeros((210,410,3),dtype=np.uint8);rgb[15:191,10:186]=image(protocol=fi.LEGACY_PROTOCOL);rgb[15:191,222:398]=image(protocol=fi.LEGACY_PROTOCOL)
    result=decode(rgb,protocol=fi.LEGACY_PROTOCOL)
    assert result['status']=='unknown'
    assert result['reason']=='ambiguous_multiple_valid_markers'
    assert result['valid_candidate_count']==2


def cluttered_marker(fragment_side=1, damage=None):
    rgb=np.zeros((232,232,3),dtype=np.uint8)
    rgb[20:212,20:212]=image()
    # 80 disconnected fragments in padding, with unchanged marker pixels.
    for y in (2,7,222,227):
        for x in range(8,208,10):
            rgb[y:y+fragment_side,x:x+fragment_side,1]=255
    if damage=='bit':
        rgb[84:92,84:92]=255-rgb[84:92,84:92]
    elif damage=='occlusion':
        rgb[20:44,20:44]=0
    elif damage=='unmarked':
        rgb[20:212,20:212]=0
    return rgb


def test_subminimum_scene_fragments_do_not_consume_fiducial_candidates():
    rgb=cluttered_marker();before=rgb.tobytes()
    assert_id(decode(rgb))
    assert rgb.tobytes()==before


@pytest.mark.parametrize('damage',['bit','occlusion','unmarked'])
def test_fragment_filter_does_not_accept_damaged_or_absent_marker(damage):
    result=decode(cluttered_marker(damage=damage))
    assert result['status']=='unknown' and result['identity'] is None
    if damage=='bit':assert result['candidate_rejections'].get('crc_mismatch')==1


def test_eligible_component_overflow_still_fails_before_find_objects(monkeypatch):
    def unexpected_find_objects(*args,**kwargs):
        raise AssertionError('Unbounded eligible components reached find_objects')
    monkeypatch.setattr(fi,'find_objects',unexpected_find_objects)
    result=decode(cluttered_marker(fragment_side=2))
    assert result['status']=='unknown'
    assert result['reason']=='too_many_green_components'


def test_two_v2_markers_with_subminimum_clutter_are_not_selected_by_identity():
    rgb=np.zeros((232,452,3),dtype=np.uint8)
    rgb[20:212,20:212]=image(100)
    rgb[20:212,240:432]=image(101)
    for y in (2,7,222,227):
        rgb[y,8:208:10,1]=255
    result=decode(rgb)
    assert result['status']=='unknown' and result['identity'] is None


def test_find_objects_only_receives_bounded_dense_eligible_labels(monkeypatch):
    original=fi.find_objects
    observed=[]
    def checked(labels):
        values=np.unique(labels)
        assert labels.max()<=fi.DecodeConfig().max_color_components
        assert np.array_equal(values,np.arange(labels.max()+1))
        observed.append(int(labels.max()))
        return original(labels)
    monkeypatch.setattr(fi,'find_objects',checked)
    assert_id(decode(cluttered_marker()))
    assert observed


def test_eye_layout_search_and_memory_bounds_are_not_guessed():
    rgb=np.zeros((200,400,3),dtype=np.uint8);rgb[8:8+SIDE,8:8+SIDE]=image()
    frame=SourceFrame(rgb,'final_swapchain_distorted',{'left':(0,0,200,200),'right':(200,0,400,200)}, {})
    with pytest.raises(ValueError,match='wholly'):
        fi.decode_frame_identity(frame,'left',SESSION,(0,0,250,200))
    with pytest.raises(ValueError,match='bounded'):
        fi.decode_frame_identity(frame,'left',SESSION,(0,0,200,200),fi.DecodeConfig(max_search_pixels=1000))
    assert fi.decode_frame_identity(frame,'right',SESSION,(200,0,400,200))['status']=='unknown'


@pytest.mark.parametrize('session',['0-1','01-2','1-02','-1-4','1-0','1--1','fixture',f'{2**32}-4',f'1-{2**64}'])
def test_invalid_session_canonical_identity(session):
    with pytest.raises(ValueError):fi.marker_packet(session,'left',1)


def join_fixture(tmp_path, ids=(100,100,103,104,104)):
    header={'event':'pose_journal_start','schema':1,'source':'application_projection','session':SESSION,'pid':12345,
            'request':17,'space':'OpenXR_LOCAL','units':'meters','clock':'CLOCK_MONOTONIC','clock_mapping':'unavailable',
            'capture_start_monotonic_ns':1000,'capture_end_monotonic_ns':10000,'capacity_frames':8192,
            'frame_identity':{'enabled':True,'protocol':fi.PROTOCOL,'version':2,'session_pid':12345,'session_start_ns':918966553299961}}
    records=[]
    for frame in sorted(set(ids)):
        packet=fi.marker_packet(SESSION,'left',frame)
        records.append({'event':'application_frame','source':'application_projection','frame':frame,
                        'submitted':True,'xr_end_frame_succeeded':True,'clock_mapping':'unavailable',
                        'predicted_display_time_ns':frame*10,'predicted_display_monotonic_ns':None,
                        'eyes':[{'eye':'left','rendered':True,'frame_identity':{'rendered':True,'frame':frame,
                                 'packet_crc32':int.from_bytes(packet[24:28],'big')}}]})
    manifest={'schema':1,'coordinate_space':'final_swapchain_distorted','eye_rectangles':{'left':[0,0,SIDE,SIDE]},
              'marker_search_rectangles':{'left':[0,0,SIDE,SIDE]},'frames':[]}
    for index,frame in enumerate(ids):
        file=tmp_path/f'original-{index}.png';Image.fromarray(image(frame)).save(file)
        manifest['frames'].append({'id':index,'file':file.name,'png_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                                   'provenance':{'request':17,'index':index,'present':200+index,'host_present_enter_ns':1200+index*11,
                                       'source_event':{'event':'frame_saved','request':17,'present':200+index,'swapchain':'1','events_file':'events-1.jsonl'},
                                       'present_event':{'event':'present','armed':1,'request':17,'present':200+index,'enter_ns':1200+index*11,'swapchain':'1','events_file':'events-1.jsonl'}}})
    journal=tmp_path/'journal.jsonl';mpath=tmp_path/'manifest.json'
    def save():
        trailer={'event':'pose_journal_complete','complete':True,'overflow_frames':0,'frames':len(records),'mapping_failures':0}
        journal.write_text(''.join(json.dumps(row)+'\n' for row in [header,*records,trailer]))
        mpath.write_text(json.dumps(manifest))
    save()
    return mpath,journal,header,records,manifest,save


def test_exact_join_and_reuse_gaps_no_nearest_timestamp(tmp_path):
    m,j,h,r,manifest,save=join_fixture(tmp_path)
    result=fi.join_frame_identities(m,j,17)
    assert result['status_counts']=={'left':{'joined':5}}
    assert [v['captured_present_count'] for v in result['reuse']['left']['runs']]==[2,1,2]
    assert result['reuse']['left']['reused_present_count']==2
    transition=result['reuse']['left']['transitions'][0]
    assert transition['not_observed_app_ids_between']==2
    assert result['frames'][0]['eyes']['left']['journal']['frame']==100
    assert result['frames'][0]['eyes']['left']['journal']['predicted_display_monotonic_ns'] is None


def test_full_counter_does_not_wrap_or_infer_loop(tmp_path):
    high=2**64-2
    m,j,*_=join_fixture(tmp_path,(high,high,high+1,3))
    result=fi.join_frame_identities(m,j,17)
    assert result['frames'][2]['eyes']['left']['identity']['frame']==high+1
    assert result['reuse']['left']['transitions'][-1]['kind']=='regression'


@pytest.mark.parametrize('failure',['missing_row','unsubmitted','unrendered_marker','wrong_crc'])
def test_decoded_unjoined_preserved_and_breaks_runs(tmp_path,failure):
    m,j,h,rows,manifest,save=join_fixture(tmp_path,(100,101,100))
    row=rows[1]
    if failure=='missing_row':rows.pop()
    if failure=='unsubmitted':row['submitted']=False
    if failure=='unrendered_marker':row['eyes'][0]['frame_identity']['rendered']=False
    if failure=='wrong_crc':row['eyes'][0]['frame_identity']['packet_crc32']^=1
    save();result=fi.join_frame_identities(m,j,17)
    assert result['frames'][1]['eyes']['left']['status']=='decoded_unjoined'
    assert result['frames'][1]['eyes']['left']['identity']['frame']==101
    assert len(result['reuse']['left']['runs'])==2
    assert not result['reuse']['left']['transitions']


@pytest.mark.parametrize('failure',['request','item_request','hash','disabled','source_order','missing_search','header_pid','header_session','event_request','event_time','invalid_armed'])
def test_inconsistent_evidence_rejected(tmp_path,failure):
    m,j,h,rows,manifest,save=join_fixture(tmp_path)
    if failure=='invalid_armed':manifest['frames'][1]['provenance']['present_event']['armed']=2
    if failure=='event_request':manifest['frames'][1]['provenance']['source_event']['request']=99
    if failure=='event_time':manifest['frames'][1]['provenance']['present_event']['enter_ns']+=1
    if failure=='header_pid':h['pid']=9
    if failure=='header_session':h['frame_identity']['session_start_ns']+=1
    if failure=='request':h['request']=99
    if failure=='item_request':manifest['frames'][1]['provenance']['request']=99
    if failure=='hash':manifest['frames'][1]['png_sha256']='0'*64
    if failure=='disabled':h['frame_identity']['enabled']=False
    if failure=='source_order':manifest['frames'][1]['provenance']['index']=0
    if failure=='missing_search':manifest.pop('marker_search_rectangles')
    save()
    with pytest.raises(ValueError):fi.join_frame_identities(m,j,17)


def test_unknown_and_sampling_gaps_break_runs(tmp_path):
    m,j,h,rows,manifest,save=join_fixture(tmp_path,(100,100,100,100))
    item=manifest['frames'][1];path=tmp_path/item['file'];Image.fromarray(np.zeros((SIDE,SIDE,3),np.uint8)).save(path)
    item['png_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['frames'][3]['provenance']['index']=8
    save();result=fi.join_frame_identities(m,j,17)
    assert result['status_counts']=={'left':{'joined':3,'unknown':1}}
    assert len(result['reuse']['left']['runs'])==3
    assert result['reuse']['left']['reused_present_count']==0


def moving_join_fixture(tmp_path, offsets=(20,32,44,56)):
    m,j,h,rows,manifest,save=join_fixture(tmp_path,tuple(range(100,100+len(offsets))))
    manifest['eye_rectangles']={'left':[0,0,400,232]}
    manifest['marker_search_rectangles']={'left':[8,8,224,224]}
    manifest['marker_roi_follow']={'margin_px':20,'max_search_rectangles':{'left':[0,0,360,232]}}
    for item,offset in zip(manifest['frames'],offsets):
        rgb=np.zeros((232,400,3),dtype=np.uint8)
        rgb[20:212,offset:offset+SIDE]=image(100+item['id'])
        path=tmp_path/item['file'];Image.fromarray(rgb).save(path)
        item['png_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    save()
    return m,j,h,rows,manifest,save


def test_optional_roi_follow_keeps_exact_identity_when_marker_leaves_initial_roi(tmp_path):
    m,j,h,rows,manifest,save=moving_join_fixture(tmp_path)
    result=fi.join_frame_identities(m,j,17)
    assert result['status_counts']=={'left':{'joined':4}}
    assert [r['eyes']['left']['roi_follow']['source_capture_index'] for r in result['frames']]==[None,0,1,2]
    assert all(r['eyes']['left']['roi_follow']['identity_inferred'] is False for r in result['frames'])
    assert result['frames'][3]['eyes']['left']['search_rect'][2]>224
    manifest.pop('marker_roi_follow');save()
    fixed=fi.join_frame_identities(m,j,17)
    assert fixed['frames'][3]['eyes']['left']['status']=='unknown'


@pytest.mark.parametrize('failure',['corrupt','unsubmitted','wrong_session','missing_marker'])
def test_roi_follow_freezes_on_unknown_or_unjoined_without_guessing_id(tmp_path,failure):
    m,j,h,rows,manifest,save=moving_join_fixture(tmp_path,(20,32,44,52))
    item=manifest['frames'][2];path=tmp_path/item['file']
    rgb=np.array(Image.open(path))
    if failure=='corrupt':rgb[84:92,108:116]=255-rgb[84:92,108:116]
    elif failure=='unsubmitted':rows[2]['submitted']=False
    elif failure=='wrong_session':rgb[20:212,44:236]=image(102,session='54321-918966553299961')
    elif failure=='missing_marker':rgb[:]=0
    Image.fromarray(rgb).save(path);item['png_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();save()
    result=fi.join_frame_identities(m,j,17)
    bad=result['frames'][2]['eyes']['left'];next_row=result['frames'][3]['eyes']['left']
    assert bad['status']==('decoded_unjoined' if failure=='unsubmitted' else 'unknown')
    assert bad['roi_follow']['geometry_updated'] is False
    assert next_row['roi_follow']['source_capture_index']==1
    assert next_row['status']=='joined' and next_row['identity']['frame']==103
    assert not result['reuse']['left']['reused_present_count']


def test_roi_follow_capture_gap_resets_initial_region(tmp_path):
    m,j,h,rows,manifest,save=moving_join_fixture(tmp_path)
    manifest['frames'][2]['provenance']['index']=8
    manifest['frames'][3]['provenance']['index']=9
    save();result=fi.join_frame_identities(m,j,17)
    for row in result['frames'][2:]:
        value=row['eyes']['left']
        assert value['roi_follow']['source_capture_index'] is None
        assert value['search_rect']==manifest['marker_search_rectangles']['left']
        assert value['status']=='unknown'


def test_roi_follow_never_searches_outside_explicit_maximum(tmp_path):
    m,j,h,rows,manifest,save=moving_join_fixture(tmp_path,(20,32,100))
    maximum=[0,0,240,232]
    manifest['marker_roi_follow']['max_search_rectangles']['left']=maximum
    save();result=fi.join_frame_identities(m,j,17)
    assert result['frames'][-1]['eyes']['left']['status']=='unknown'
    for row in result['frames']:
        value=row['eyes']['left']
        assert fi._contains(maximum,value['search_rect'])
        assert fi._contains(maximum,value['roi_follow']['next_search_rect'])


@pytest.mark.parametrize('failure',['margin','bool_margin','missing_eye','outside_eye','excludes_initial','extra_option'])
def test_roi_follow_rejects_unbounded_or_ambiguous_configuration(tmp_path,failure):
    m,j,h,rows,manifest,save=moving_join_fixture(tmp_path)
    config=manifest['marker_roi_follow']
    if failure=='margin':config['margin_px']=65
    elif failure=='bool_margin':config['margin_px']=True
    elif failure=='missing_eye':config['max_search_rectangles']={}
    elif failure=='outside_eye':config['max_search_rectangles']['left']=[0,0,401,232]
    elif failure=='excludes_initial':config['max_search_rectangles']['left']=[20,20,360,232]
    elif failure=='extra_option':config['guess_frame']=True
    save()
    with pytest.raises(ValueError,match='marker|Marker'):fi.join_frame_identities(m,j,17)


def test_roi_follow_preserves_hard_maximum_pixel_budget():
    manifest={'eye_rectangles':{'left':[0,0,2000,2000]},
              'marker_roi_follow':{'margin_px':20,'max_search_rectangles':{'left':[0,0,2000,2000]}}}
    with pytest.raises(ValueError,match='pixel budget'):
        fi._marker_follow_config(manifest,{'left':[0,0,200,200]})


def test_v2_independent_chromatic_channel_warp_preserves_green_identity():
    native=image();yy,xx=np.mgrid[:SIDE,:SIDE].astype(float)
    center=(SIDE-1)/2; radius=((xx-center)**2+(yy-center)**2)/(SIDE/2)**2
    channels=[]
    for channel,shift in enumerate((6.0,0.0,-7.0)):
        sx=xx+shift*.18*radius; sy=yy+shift*(.7+.3*radius)
        channels.append(map_coordinates(native[:,:,channel].astype(float),[sy,sx],order=1,mode='constant',cval=0))
    warped=np.stack(channels,axis=2).clip(0,255).astype(np.uint8)
    result=decode(warped,space='final_swapchain_distorted')
    assert_id(result)
    assert result['sampling_channel']=='green'
    # A green-bit error still fails despite the other two channels retaining
    # their original information. No alternate-channel or CRC search fallback.
    warped[8*8:9*8,8*8:9*8,1]=255-warped[8*8:9*8,8*8:9*8,1]
    assert decode(warped)['status']=='unknown'


def test_v2_two_markers_cannot_be_silently_joined():
    rgb=np.zeros((230,440,3),dtype=np.uint8)
    rgb[15:15+SIDE,10:10+SIDE]=image()
    rgb[15:15+SIDE,232:232+SIDE]=image(101)
    result=decode(rgb)
    assert result['status']=='unknown' and result['identity'] is None
