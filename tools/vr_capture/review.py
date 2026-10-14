"""Build a frame-by-frame viewer from retained final-swapchain pixel files.

PNG export happens offline. Pixels keep their panel layout, including any lens
warp already applied by SteamVR; no optical reconstruction or frame blending.
"""
from __future__ import annotations
import argparse
import json
import statistics
from pathlib import Path
import struct
import zlib

from .audit import audit_directory, load_events
from .pixels import decode_frame


def png_bytes(raw, width, height, format_number):
    if format_number not in (37, 43, 44, 50):
        raise ValueError(f'Unsupported format {format_number}')
    expected = width * height * 4
    if len(raw) != expected:
        raise ValueError('Frame size mismatch')
    bgra = format_number in (44, 50)
    channels = bytearray(width * height * 3)
    view = memoryview(raw)
    channels[0::3] = view[2 if bgra else 0::4]
    channels[1::3] = view[1::4]
    channels[2::3] = view[0 if bgra else 2::4]
    stride = width * 3
    scanlines = b''.join(b'\0' + channels[y*stride:(y+1)*stride] for y in range(height))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanlines, 1)) + chunk(b'IEND', b''))


def frame_index(rows, report, limit=0):
    """Join by log, request, swapchain and present, never by compression order."""
    if limit < 0:
        raise ValueError('limit must be nonnegative')
    starts = [r for r in rows if r.get('event') == 'capture_start'
              and r.get('request') == report['request']]
    if len(starts) != 1:
        raise ValueError('Review needs one unambiguous capture_start')
    start = starts[0]
    own = [r for r in rows if r.get('_source') == start['_source']
           and r.get('request') == report['request']]
    presents = sorted((r for r in own if r.get('event') == 'present'
                       and r.get('armed', start['start_ns'] <= r.get('enter_ns', -1) < start['end_ns'])),
                      key=lambda r: r.get('enter_ns', float('inf')))
    key = lambda row: (row['swapchain'], row['present'])
    by_key = {}
    for index, row in enumerate(presents):
        by_key.setdefault(key(row), []).append((index, row))
    images = [r for r in own if r.get('event') == 'frame_saved']
    def timestamp(row):
        found = by_key.get(key(row), [])
        return found[0][1].get('enter_ns') if len(found) == 1 else None
    images.sort(key=lambda r: (timestamp(r) is None, timestamp(r) or 0, r['present']))
    total_saved = len(images)
    saved_keys = {key(row) for row in images}
    intervals = [(b['enter_ns']-a['enter_ns'])/1e6 for a,b in zip(presents,presents[1:])
                 if 'enter_ns' in a and 'enter_ns' in b and b['enter_ns'] > a['enter_ns']]
    median_ms = statistics.median(intervals) if intervals else None
    threshold = median_ms*1.5 if median_ms else None
    elapsed = lambda ns: (ns-start['start_ns'])/1e6
    gaps = [{'start_ms':elapsed(a['enter_ns']), 'end_ms':elapsed(b['enter_ns']),
             'duration_ms':(b['enter_ns']-a['enter_ns'])/1e6,
             'previous_present':a['present'], 'present':b['present']}
            for a,b in zip(presents,presents[1:]) if threshold and 'enter_ns' in a and 'enter_ns' in b
            and (b['enter_ns']-a['enter_ns'])/1e6 > threshold]
    missing = [{'elapsed_ms':elapsed(r['enter_ns']), 'present':r['present'], 'swapchain':r['swapchain']}
               for r in presents if key(r) not in saved_keys and 'enter_ns' in r]
    if limit:
        images = images[:limit]
    frames = []
    previous_time, previous_index = None, -1
    for number, row in enumerate(images):
        found = by_key.get(key(row), [])
        present_index, present = found[0] if len(found) == 1 else (None, {})
        host_ns = timestamp(row)
        gap = None
        if present_index is not None and present_index > 0 and host_ns is not None:
            previous = presents[present_index-1].get('enter_ns')
            if previous is not None:
                gap = (host_ns-previous)/1e6
        missing_before = (sum(key(p) not in saved_keys for p in presents[previous_index+1:present_index])
                          if present_index is not None else None)
        frames.append({'file':f"frame-{number:05d}-present-{row['present']}.png",
                       'original_file':row['file'], 'events_file':start['_source'],
                       'original_file_offset':row.get('file_offset'),
                       'compressed_frame_bytes':row.get('compressed_bytes') if 'file_offset' in row else None,
                       'present':row['present'], 'swapchain':row['swapchain'],
                       'present_id':str(present['present_id']) if 'present_id' in present else None,
                       'width':row['width'], 'height':row['height'], 'format':row['format'],
                       'host_present_enter_ns':str(host_ns) if host_ns is not None else None,
                       'source_elapsed_ms':elapsed(host_ns) if host_ns is not None else None,
                       'present_gap_ms':gap,
                       'saved_frame_gap_ms':(host_ns-previous_time)/1e6 if host_ns is not None and previous_time is not None else None,
                       'unsaved_presents_before':missing_before,
                       'long_present_gap':bool(threshold and gap is not None and gap > threshold)})
        previous_time = host_ns
        if present_index is not None:
            previous_index = present_index
    timed = bool(len(frames)>1 and all(f['source_elapsed_ms'] is not None for f in frames)
                 and all(b['source_elapsed_ms']>a['source_elapsed_ms'] for a,b in zip(frames,frames[1:])))
    metadata = {'schema':2, 'request':str(report['request']), 'events_file':start['_source'],
                'capture_boundary':'final_swapchain_before_queue_present',
                'timing_boundary':'host_vkQueuePresentKHR_entry',
                'capture_start_ns':str(start['start_ns']), 'capture_end_ns':str(start['end_ns']),
                'capture_duration_ms':(start['end_ns']-start['start_ns'])/1e6,
                'default_playback_rate':0.25, 'timestamp_playback_available':timed,
                'total_saved_frames':total_saved, 'exported_frames':len(frames),
                'limited_export':len(frames)<total_saved, 'median_present_interval_ms':median_ms,
                'long_gap_threshold_ms':threshold, 'present_gaps':gaps, 'unsaved_presents':missing,
                'eye_crop_assumption':'equal_side_by_side_halves_unverified',
                'complete_present_capture':bool(report['complete_present_capture']),
                'direct_display_provenance':bool(report.get('direct_display_provenance')),
                'headset_identity_verified':False,
                'refresh_mapping_verified':False, 'optical_output_verified':False,
                'playback_policy':'every exported frame; hold over source-time gaps; buffer instead of skipping; no interpolation or blending'}
    return images, frames, metadata


def build_review(directory, output, request=None, limit=0):
    directory = Path(directory).resolve(strict=True)
    output = Path(output).resolve()
    if limit < 0:
        raise ValueError('limit must be nonnegative')
    output.mkdir(parents=True, exist_ok=False)
    report = audit_directory(directory, request)
    rows, _ = load_events(directory)
    images, frames, metadata = frame_index(rows, report, limit)
    for row, frame in zip(images, frames, strict=True):
        raw = decode_frame(directory, row)
        (output / frame['file']).write_bytes(png_bytes(raw, row['width'], row['height'], row['format']))
    (output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'frames.json').write_text(json.dumps(frames, indent=2) + '\n')
    (output / 'review.json').write_text(json.dumps(metadata, indent=2) + '\n')
    payload = json.dumps({'frames':frames, 'meta':metadata}).replace('<', '\\u003c')
    (output / 'index.html').write_text(HTML.replace('__CAPTURE_DATA__', payload))
    return output / 'index.html'


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SteamVR final-output review</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{font:15px/1.5 system-ui,sans-serif;background:#11151b;color:#e7edf3;margin:0;padding:24px}main{max-width:1280px;margin:auto}h1{font-size:26px;margin:0 0 6px}p{margin:6px 0 14px}.muted{color:#aebbc9}.notice{border-left:3px solid #ffba66;padding:10px 14px;background:#211f1b}.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0}button,select{font:inherit;color:inherit;background:#25313e;border:1px solid #506476;border-radius:5px;padding:7px 12px}button:disabled{opacity:.45}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #8cceff}#play{min-width:100px;background:#174669}label{display:flex;align-items:center;gap:7px}a{color:#91d6ff}#slider{width:100%;margin:8px 0 0;accent-color:#65bdff}#timeline{width:100%;height:40px;display:block;cursor:pointer}.time-labels{display:flex;justify-content:space-between;color:#aebbc9;font-variant-numeric:tabular-nums}.readout{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;min-height:28px;font-variant-numeric:tabular-nums}#gap-status{color:#ffbd74}#viewport{max-height:70vh;overflow:auto;background:#07090c;border:1px solid #344351;border-radius:6px;margin:12px 0;display:flex;justify-content:flex-start}#stage{position:relative;overflow:hidden;flex:none;margin:auto;aspect-ratio:1.8}#stage img{position:absolute;top:0;height:100%;max-width:none;image-rendering:auto}#stage.full img{left:0;width:100%}#stage.left img{left:0;width:200%}#stage.right img{left:-100%;width:200%}#stage.native img{image-rendering:pixelated}details{margin:16px 0;color:#b7c3cf}summary{cursor:pointer}code{overflow-wrap:anywhere}.badge{display:inline-block;padding:2px 8px;background:#283542;border-radius:4px;margin-right:8px}.amber{color:#ffc482}.red{color:#ff8b8b}.links{display:flex;flex-wrap:wrap;gap:15px}#empty{padding:30px}#play-status{color:#aebbc9}
</style></head><body><main>
<h1>SteamVR final-output review</h1>
<p class="muted">Captured compositor frames, before presentation. Lossless PNGs retain the full panel layout and any SteamVR lens warp.</p>
<p class="notice">Screen playback is not physical headset output. These are present-call timestamps, not measured scanout times. A monitor cannot reproduce headset refresh, pixel persistence, or lens optics.</p>
<div id="accounting" aria-live="polite"></div>
<div class="controls"><button id="prev" title="Left arrow">Previous</button><button id="play" title="Space">Play</button><button id="next" title="Right arrow">Next</button>
<label>Speed <select id="rate"><option value="0.1">0.1×</option><option value="0.25" selected>0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option></select></label>
<label>View <select id="crop"><option value="full">Full panel</option><option value="left">Left half / eye area</option><option value="right">Right half / eye area</option></select></label>
<label>Scale <select id="scale"><option value="fit">Fit window</option><option value="native">1 source pixel = 1 CSS pixel</option></select></label></div>
<div class="readout"><strong id="frame-label"></strong><span id="source-time"></span></div>
<input id="slider" aria-label="Captured frame" type="range" min="0" value="0" step="1">
<canvas id="timeline" height="40" aria-label="Captured time: amber marks long presentation gaps; red marks presentations with no saved image"></canvas>
<div class="time-labels"><span id="time-start"></span><span><span class="amber">Amber: long present gap</span> · <span class="red">Red: unsaved present</span></span><span id="time-end"></span></div>
<div class="readout"><span id="gap-status"></span><span id="play-status">Paused · 0.25× default</span></div>
<div id="viewport"><div id="stage" class="full"><div id="empty">Loading captured frame…</div></div></div>
<p class="muted" id="crop-note">No interpolation or frame blending. Fit view scales display pixels; exported PNGs keep their original resolution.</p>
<div class="links"><a id="original" target="_blank" rel="noopener">Open full-resolution frame</a><a href="audit.json">Capture audit</a><a href="frames.json">Frame index</a><a href="review.json">Playback provenance</a></div>
<details><summary>Timing and provenance</summary><p id="provenance"></p><p>Playback shows every exported frame. It holds the previous image across a source-time gap; that does not prove the headset repeated that image. If decoding or monitor refresh is too slow, playback buffers instead of skipping frames. Half-panel crops assume equal side-by-side eyes; eye identity and layout are not verified by this viewer.</p></details>
</main><script>
'use strict';
const DATA=__CAPTURE_DATA__;const {frames,meta}=DATA;const $=id=>document.getElementById(id);
let index=0,playing=false,epoch=0,drawVersion=0,anchorWall=0,anchorSource=0,stalls=0;const cache=new Map();
const validTime=f=>f&&f.source_elapsed_ms!==null&&Number.isFinite(f.source_elapsed_ms);
const timeText=ms=>(ms/1000).toFixed(3)+' s';const firstTime=frames.length&&validTime(frames[0])?frames[0].source_elapsed_ms:0;
const lastTime=frames.length&&validTime(frames.at(-1))?frames.at(-1).source_elapsed_ms:firstTime;const span=Math.max(1,lastTime-firstTime);
$('slider').max=Math.max(0,frames.length-1);$('time-start').textContent=timeText(firstTime);$('time-end').textContent=timeText(lastTime);
$('accounting').textContent=`${frames.length} exported / ${meta.total_saved_frames} saved frames · ${meta.present_gaps.length} long present gaps · ${meta.unsaved_presents.length} unsaved presents${meta.limited_export?' · LIMITED EXPORT':''}${meta.complete_present_capture?'':' · CAPTURE AUDIT INCOMPLETE'}`;
$('provenance').textContent=`Request ${meta.request}; ${meta.events_file}. Capture duration ${timeText(meta.capture_duration_ms)}. Complete present-boundary capture: ${meta.complete_present_capture}. Direct-display provenance: ${meta.direct_display_provenance}. Headset identity, refresh mapping, and optical output: unverified by this viewer. ${meta.median_present_interval_ms===null?'No observed frame interval.':`Median observed present interval ${meta.median_present_interval_ms.toFixed(3)} ms; gap markers exceed ${meta.long_gap_threshold_ms.toFixed(3)} ms (1.5× median).`}`;
function load(i){if(cache.has(i))return cache.get(i);const image=new Image();image.decoding='async';image.alt=`Captured panel, present ${frames[i].present}`;image.src=frames[i].file;const promise=image.decode().then(()=>image);cache.set(i,promise);return promise;}
function preload(){for(const key of cache.keys())if(key<index-1||key>index+3)cache.delete(key);for(let n=index+1;n<=Math.min(index+3,frames.length-1);n++)load(n).catch(()=>{});}
function layout(){if(!frames.length)return;const f=frames[index];const crop=$('crop').value;const native=$('scale').value==='native';const width=crop==='full'?f.width:f.width/2;const stage=$('stage');stage.className=crop+(native?' native':'');stage.style.aspectRatio=`${width}/${f.height}`;stage.style.width=native?width+'px':`min(100%,${width/f.height*62}vh)`;$('crop-note').textContent=(crop==='full'?'Full panel. ':'Equal half-panel crop only; side-by-side eye identity is unverified. ')+(native?'Display uses one CSS pixel per source pixel. ':'Fit display is scaled. ')+'Original PNG exports are full resolution; no frame blending or interpolation.';}
function timeline(){const canvas=$('timeline');const ratio=window.devicePixelRatio||1;canvas.width=Math.round(canvas.clientWidth*ratio);canvas.height=Math.round(40*ratio);const c=canvas.getContext('2d');c.scale(ratio,ratio);const w=canvas.clientWidth;const x=ms=>(ms-firstTime)/span*w;c.fillStyle='#25313e';c.fillRect(0,7,w,26);c.fillStyle='#b47c32';for(const gap of meta.present_gaps){c.fillRect(x(gap.start_ms),7,Math.max(2,x(gap.end_ms)-x(gap.start_ms)),26);}c.fillStyle='#ea7777';for(const p of meta.unsaved_presents)c.fillRect(x(p.elapsed_ms)-1,3,3,34);c.fillStyle='#9cabb7';for(const f of frames)if(validTime(f))c.fillRect(x(f.source_elapsed_ms),24,1,9);if(validTime(frames[index])){c.fillStyle='#eff9ff';c.fillRect(x(frames[index].source_elapsed_ms)-1,0,2,40);}}
async function show(wanted){if(!frames.length)return false;const version=++drawVersion;const next=Math.max(0,Math.min(frames.length-1,wanted));let image;try{image=await load(next);}catch(error){pause();$('play-status').textContent='Image decode failed; inspect original file';return false;}if(version!==drawVersion)return false;index=next;$('stage').replaceChildren(image);$('slider').value=index;const f=frames[index];$('frame-label').textContent=`Frame ${index+1}/${frames.length} · present ${f.present} · ${f.width}×${f.height}`;$('source-time').textContent=validTime(f)?`Source elapsed ${timeText(f.source_elapsed_ms)} / ${timeText(meta.capture_duration_ms)}`:'Source time unavailable';$('original').href=f.file;const parts=[];if(f.present_gap_ms!==null)parts.push(`Previous present gap ${f.present_gap_ms.toFixed(3)} ms${f.long_present_gap?' — long gap':''}`);if(f.unsaved_presents_before)parts.push(`${f.unsaved_presents_before} unsaved presents before this frame`);$('gap-status').textContent=parts.join(' · ');layout();timeline();preload();return true;}
function pause(){playing=false;epoch++;$('play').textContent='Play';$('play-status').textContent=`Paused · ${stalls} playback stalls`;}function step(i){pause();show(i);}
async function play(){if(playing){pause();return;}if(!meta.timestamp_playback_available)return;if(index===frames.length-1)await show(0);playing=true;const run=++epoch;anchorWall=performance.now();anchorSource=frames[index].source_elapsed_ms;stalls=0;$('play').textContent='Pause';$('play-status').textContent=`Playing at ${$('rate').value}×; every exported frame`;
async function tick(now){if(!playing||run!==epoch)return;if(index>=frames.length-1){pause();$('play-status').textContent=`Finished · ${stalls} playback stalls`;return;}const next=index+1;const due=anchorWall+(frames[next].source_elapsed_ms-anchorSource)/Number($('rate').value);if(now>=due){$('play-status').textContent='Playing / waiting for next decoded frame';const shown=await show(next);if(!shown||!playing||run!==epoch)return;const finished=performance.now();if(finished-due>25){stalls++;anchorWall=finished;anchorSource=frames[index].source_elapsed_ms;}$('play-status').textContent=`${$('rate').value}× requested · ${stalls} playback stalls; no skipped frames`;}requestAnimationFrame(tick);}requestAnimationFrame(tick);}
$('prev').onclick=()=>step(index-1);$('next').onclick=()=>step(index+1);$('play').onclick=play;$('slider').oninput=()=>step(Number($('slider').value));$('crop').onchange=layout;$('scale').onchange=layout;$('rate').onchange=()=>{const resume=playing;pause();if(resume)play();};
$('timeline').onclick=event=>{const rect=$('timeline').getBoundingClientRect();const target=firstTime+(event.clientX-rect.left)/rect.width*span;let nearest=0,best=Infinity;frames.forEach((f,i)=>{if(validTime(f)&&Math.abs(f.source_elapsed_ms-target)<best){nearest=i;best=Math.abs(f.source_elapsed_ms-target);}});step(nearest);};
window.addEventListener('resize',()=>{layout();timeline();});document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});window.addEventListener('keydown',event=>{if(['INPUT','SELECT','BUTTON','A'].includes(event.target.tagName))return;if(event.code==='Space'){event.preventDefault();play();}if(event.key==='ArrowRight'){event.preventDefault();step(index+1);}if(event.key==='ArrowLeft'){event.preventDefault();step(index-1);}if(event.key==='Home')step(0);if(event.key==='End')step(frames.length-1);});
if(!meta.timestamp_playback_available){$('play').disabled=true;$('play-status').textContent=frames.length>1?'Missing or ambiguous timestamps; step frames manually':'A single frame has no playback timeline';}if(!frames.length){for(const id of ['prev','next','play','slider','crop','scale'])$(id).disabled=true;$('empty').textContent='No saved pixel frames in this request';$('original').removeAttribute('href');}else show(0);
</script></body></html>'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--request', type=int)
    parser.add_argument('--limit', type=int, default=0, help='Export only first N frames (0 means all)')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit must be nonnegative')
    print(build_review(args.directory, args.output, args.request, args.limit))


if __name__ == '__main__':
    main()
