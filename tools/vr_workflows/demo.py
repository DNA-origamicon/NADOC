"""Watch both VR authoring workflows. Run: uv run python -m tools.vr_workflows.demo.

Requires the established SteamVR/X11 runtime and owned idle viewer launch record.
Uses real headed browser + native eye mirror; deletes marked review .nadoc files.
"""
def main():
    import argparse
    argparse.ArgumentParser(description=__doc__).parse_args()
    import json,os,signal,subprocess,tempfile,time,sys,fcntl
    from pathlib import Path
    from tools.vr_workflows.workspace import initialize, campaign_workspace, reset_parts, publish_parts
    repo=Path(__file__).resolve().parents[2]
    os.chdir(repo)
    sys.path.insert(0,str(repo))
    browser_path=os.environ["PATH"]
    hold=float(os.environ.get("NADOC_VR_DEMO_HOLD","6"))
    if not 0 <= hold <= 30:raise ValueError("demo review hold must be 0..30 seconds")
    base=Path('.development-artifacts/vr-workflows').resolve()
    base.mkdir(parents=True,exist_ok=True)
    lock=(base/'.demo.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    root=Path(tempfile.mkdtemp(prefix='demo-',dir=base))
    print('Demo evidence:',root,flush=True)
    launchfile=Path('.development-artifacts/vr-human-motion-live/launch.json')
    if not launchfile.exists():
        raise RuntimeError('No owned viewer launch record; start the established NADOC VR session first')
    launch=json.loads(launchfile.read_text());pid=launch['viewer_pid']
    from backend.api.routes_vr import _build_environment,_read_state
    assert _read_state() is None, 'another browser VR session is active'
    review=initialize(repo/'workspace'/'VR Testing')
    with campaign_workspace(review):
        (root/'review-reset.json').write_text(json.dumps({'deleted':reset_parts(review)},indent=2))
    (root/'inventory.md').write_text('Headed, serial demo. Private temporary NADOC_WORKSPACE; __e2e__ and e2e__ parts removed by global teardown, wrapper verifies, TemporaryDirectory removes root. Matching viewer PID stopped by afterEach. Captures and logs only under this evidence directory. Review outputs replaced under marked workspace/VR Testing; launch.json updated on restoration. No session cache. No validation reads from review outputs.\n')
    if Path(f'/proc/{pid}').exists():
        assert Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')[:-1]==launch['command']
        env=dict(item.split('=',1) for item in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in item)
        os.kill(pid,signal.SIGTERM)
        for _ in range(100):
            if not Path(f'/proc/{pid}').exists():break
            time.sleep(.1)
        else:raise RuntimeError('existing viewer did not exit')
    else:
        env=_build_environment()
    try:
        with tempfile.TemporaryDirectory(prefix='native-confirm-workspace-',dir=root) as workspace:
            runenv={**env,'PATH':browser_path,'NADOC_WORKSPACE':workspace,'NADOC_PHYSICAL_VR_TEST':'1','NADOC_VR_DEMO':'1','NADOC_VR_DEMO_HOLD':os.environ.get('NADOC_VR_DEMO_HOLD','6'),'NADOC_VR_FREEFORM':'0','NADOC_VR_PROFILE_END':'1','NADOC_VR_PROFILE_PLACEMENT':'1','NADOC_VR_PROFILE_CONTROLS':'1','NADOC_VR_APPROACH_CONTROLS':'1','NADOC_VR_APPROACH_CELLS':'1','NADOC_VR_REVIEW_VIEW':'1','NADOC_VR_DESKTOP_REVIEW':'1','NADOC_VR_PROFILE_WHEEL':'1','NADOC_VR_FINE_LENGTH':'1','NADOC_VR_MENU_ACTIVATION':'1','NADOC_VR_FEEDBACK_ACQUISITION':'1','NADOC_VR_PROFILE':'steady_fast','NADOC_VR_EXISTING_FRAME':'0','NADOC_VR_DESKTOP_BUNDLE':'0','NADOC_VR_PAINT_ZOOM':'fit','NADOC_VR_PAINT_APPROACH':'normal'}
            with (root/'demo.log').open('w') as log:
                result=subprocess.run(['npx','playwright','test','--config','playwright.smoke.config.js',
                    'vr_combined_authoring.spec.js','vr_native_confirm.spec.js','--workers=1','--headed','--global-timeout=1200000','--output',str(root/'output')],cwd='frontend',env=runenv,stdout=log,stderr=subprocess.STDOUT)
            remaining=list(Path(workspace).rglob('*.nadoc'))
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'remaining_parts':[str(p) for p in remaining],'temporary_root':workspace},indent=2))
            assert not remaining,remaining
    finally:
        # Never launch over an uncleaned physical test process.
        import backend.api.routes_vr as vr
        state=vr._read_state()
        if state is not None:raise RuntimeError('test viewer still active; preserve it for inspection')
        import socket
        live_socket=Path(launch['socket'])
        live_socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if live_socket.exists():
            probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);probe.settimeout(1)
            try:probe.connect(str(live_socket))
            except ConnectionRefusedError:live_socket.unlink()
            else:raise RuntimeError('restore socket has an active listener')
            finally:probe.close()
        proc=subprocess.Popen(launch['command'],env=env,stdout=(root/'native-confirm-restored-viewer.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
        launch['viewer_pid']=proc.pid
        launch['mode']='Idle empty-scene diagnostic restored after visible workflow demo; no input loop'
        launchfile.write_text(json.dumps(launch,indent=2)+'\n')
        print('Restored diagnostic viewer',proc.pid)
    if result.returncode == 0:
        outputs=list((root/'output').rglob('review-part.nadoc'))
        sources={name:next(p for p in outputs if prefix in str(p)) for name,prefix in [('desktop-then-vr','vr_combined_authoring'),('vr-first','vr_native_confirm')]}
        (root/'publication.json').write_text(json.dumps(publish_parts(review,sources),indent=2)+'\n')
        print('Verified review parts:',review,flush=True)
    print('Demo exit',result.returncode,'— log:',root/'demo.log',flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
