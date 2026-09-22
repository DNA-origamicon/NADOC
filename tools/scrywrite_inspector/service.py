"""Bounded capture history and exclusive profile execution; no alternate VR driver."""
import json
import math
from pathlib import Path
import shutil
import struct
import threading
import time
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import target_metrics
from tools.vr_motion.presets import INITIAL_PRESET, FINAL_PRESETS
from tools.vr_motion.extrude_probe import run as run_extrude

CAPTURE_FILES = ('left.png','right.png','left.ids.u32','right.ids.u32',
                 'left.classes.u8','right.classes.u8','objects.json','evidence.json')


def target_details(state):
    targets=[]
    for target in state.get('controls',[]):
        item={**target,'key':state.get('menu','')+':'+target['label']}
        hand=state.get('hands',[{},{}])[1]
        if hand.get('valid'):
            try:
                item['ray_metrics']=target_metrics(target,hand)
            except ValueError:
                item['ray_metrics']=None
        targets.append(item)
    return targets


class Inspector:
    def __init__(self, socket, path_file, output):
        self.socket=str(socket)
        self.path_file=Path(path_file)
        self.output=Path(output)
        self.output.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock()
        self.history=[]
        self.job={'status':'idle'}
        self.cancel=threading.Event()
        self.counter=0
        self.initial_session=None

    def status(self):
        state=Bridge(self.socket).call('scrywrite_observe',{})
        return {'state':state,'targets':target_details(state),'history':list(self.history),
                'job':dict(self.job),'profiles':list(FINAL_PRESETS),'initial_preset':INITIAL_PRESET,'initial_ready':self.initial_session==state.get('session')}

    def mutate(self, operation):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('A profile run or capture owns this session; wait or stop the run')
        try:
            return operation(LiveSession(Bridge(self.socket),physical=True))
        finally:
            self.lock.release()

    def capture(self):
        def perform(live):
            self.counter+=1
            name=f'capture-{self.counter:06d}'
            dest=self.output/name
            evidence,_=live.capture_to(dest,files=CAPTURE_FILES,discard_source=True)
            entry={'name':name,'frame':evidence['state']['frame'],'session':live.session,
                   'captured_at':time.time(),'scene_visibility':evidence['state'].get('scene_visibility','normal')}
            self.history.append(entry)
            if len(self.history)>4:
                old=self.history.pop(0)
                if not old.get('retained_report'):shutil.rmtree(self.output/old['name'])
            return entry
        return self.mutate(perform)

    def visibility(self, value):
        if value not in ('normal','hidden'):
            raise ValueError('invalid scene visibility')
        return self.mutate(lambda live:live.send('scene_visibility',visibility=value))

    def pick(self, name, eye, x, y):
        if name not in [h['name'] for h in self.history] or eye not in ('left','right'):
            raise ValueError('capture expired or invalid eye')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<1 for v in (x,y)):
            raise ValueError('pixel coordinates must be normalized within [0,1)')
        directory=self.output/name
        evidence=json.loads((directory/'evidence.json').read_text())
        view=next(e for e in evidence['eyes'] if e['eye']==eye)
        px,py=int(x*view['width']),int(y*view['height'])
        offset=(view['height']-1-py)*view['width']+px
        with (directory/(eye+'.ids.u32')).open('rb') as stream:
            stream.seek(offset*4);identifier=struct.unpack('=I',stream.read(4))[0]
        with (directory/(eye+'.classes.u8')).open('rb') as stream:
            stream.seek(offset);render_class=stream.read(1)[0]
        objects=json.loads((directory/'objects.json').read_text())
        return {'frame':evidence['state']['frame'],'session':evidence['state']['session'],
                'pixel':[px,py],'render_class':render_class,
                'object':next((o for o in objects if o['id']==identifier),None),
                'meaning':'Captured design identity; zero denotes background or UI, not a missing design object'}

    def start(self, final=False, review=False):
        if type(final) is not bool or type(review) is not bool:
            raise ValueError('final must be boolean')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('session busy')
        try:
            live=LiveSession(Bridge(self.socket),physical=True)
            if live.state['mode']!='control':
                raise ValueError('profile tests require isolated control mode, not inspect/transactions')
            if final and live.state.get('scene_visibility','normal')!='normal':
                raise ValueError('restore Normal scene for final validation')
            if final and self.initial_session!=live.session:
                raise ValueError('run steady_fast successfully in this viewer session before final validation')
            if not self.path_file.is_file() or not live.state.get('controller_path_generation'):
                raise ValueError('viewer needs --controller-path matching the configured path file')
            self.cancel.clear()
            name=f'profiles-{time.time_ns()}'
            self.job={'status':'running','phase':INITIAL_PRESET,'name':name,'session':live.session,'final':final}
        except BaseException:
            self.lock.release();raise
        def preview(directory,evidence,stage):
            relative=str(directory.relative_to(self.output))
            self.history.append({'name':relative,'frame':evidence['state']['frame'],
                'session':live.session,'scene_visibility':evidence['state'].get('scene_visibility','normal'),
                'retained_report':True})
            if len(self.history)>4:
                old=self.history.pop(0)
                if not old.get('retained_report'):shutil.rmtree(self.output/old['name'])
            self.job.update(preview=relative,stage=stage)
        def worker():
            try:
                report=run_extrude(self.socket,self.path_file,self.output/name,final,
                    cancel=self.cancel,expected_session=live.session,preview=preview,review_only=review,progress=lambda preset:self.job.update(phase=preset))
                passed=all(t['passed'] for t in report['trials'])
                if not final and not review and passed:
                    self.initial_session=live.session
                self.job.update(status='passed' if passed else 'failed',
                    report=f'/artifacts/{name}/report.html',
                    outcomes=[{'preset':t['preset'],'checks':t['checks']} for t in report['trials']])
            except Exception as error:
                self.job.update(status='cancelled' if self.cancel.is_set() else 'error',error=str(error))
                if (self.output/name/'report.html').exists():
                    self.job['report']=f'/artifacts/{name}/report.html'
            finally:
                self.lock.release()
        threading.Thread(target=worker,daemon=True).start()
        return dict(self.job)
