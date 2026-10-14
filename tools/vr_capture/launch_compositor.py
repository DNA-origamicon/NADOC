"""Launch the stock SteamVR compositor with an optional process-local capture layer.

No installed runtime binary, capability, Vulkan manifest, or SteamVR setting is
changed. Replacing a compositor interrupts its current VR session. The explicit
PID must match the stock compositor executable; no broad process kill is used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

STEAMVR = Path.home() / '.local/share/Steam/steamapps/common/SteamVR'


def make_environment(layer_directory=None, output=None, mode='pixels', diagnostic_fds=False):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('NADOC_VR_CAPTURE_', 'VK_LAYER_', 'VK_ADD_LAYER_', 'VK_LOADER_LAYERS_')) or key in (
                'LD_LIBRARY_PATH', 'LD_PRELOAD', 'VK_INSTANCE_LAYERS', 'DRI_PRIME'):
            env.pop(key, None)
    env.update(DISPLAY=':0', XAUTHORITY=f'/run/user/{os.getuid()}/gdm/Xauthority',
               XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}',
               PATH='/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin',
               __NV_PRIME_RENDER_OFFLOAD='1', __GLX_VENDOR_LIBRARY_NAME='nvidia',
               __VK_LAYER_NV_optimus='NVIDIA_only', VK_LOADER_DRIVERS_SELECT='nvidia_icd.json')
    if layer_directory:
        env.update(VK_LAYER_PATH=str(layer_directory), VK_INSTANCE_LAYERS='VK_LAYER_NADOC_present_capture',
                   NADOC_VR_CAPTURE_DIR=str(output), NADOC_VR_CAPTURE_MODE=mode,
                   NADOC_VR_CAPTURE_MAX_BYTES=str(128*1024*1024),
                   # Visible menus need more space than the stationary scene.
                   # Per-request scaling selects 512 MiB for two seconds.
                   NADOC_VR_CAPTURE_COMPRESSED_BYTES=str(1280*1024*1024))
        if diagnostic_fds:
            env['NADOC_VR_CAPTURE_DIAGNOSTIC_FDS'] = '1'
    return env


def prepare_output(output):
    output = Path(output).resolve()
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not os.path.ismount('/media/jojo/Archive') or os.stat(ancestor).st_dev != os.stat('/media/jojo/Archive').st_dev:
        raise RuntimeError('This workstation workflow requires mounted Archive storage')
    output.mkdir(parents=True, exist_ok=False)
    return output


def process_ids(name):
    found = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if (path/'comm').read_text().strip() == name:
                found.append(int(path.name))
        except OSError:
            continue
    return sorted(found)


def launch_stack(output, layer_directory=None, mode='pixels', diagnostic_fds=False):
    if any(process_ids(name) for name in ('vrserver', 'vrcompositor', 'vrmonitor')):
        raise RuntimeError('A VR runtime is already active; preserve or stop it before starting a separate capture stack')
    output = prepare_output(output)
    runtime = STEAMVR.parent/'SteamLinuxRuntime_sniper/run-in-sniper'
    def start(name, args):
        command = [str(runtime), '--filesystem='+str(STEAMVR), '--',
                   str(STEAMVR/'bin/vrenv.sh'), str(STEAMVR/'bin/linux64'/name), *args]
        with (output/f'{name}.log').open('xb') as stream:
            child = subprocess.Popen(command, cwd=STEAMVR, env=make_environment(),
                                     stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        return {'launcher_pid': child.pid, 'argv': command}
    record = {'persistent_configuration_changes': False, 'started_wall_time_ns': time.time_ns()}
    record['vrserver'] = start('vrserver', ['-waitformonitor'])
    (output/'stack-launch.json').write_text(json.dumps(record, indent=2)+'\n')
    deadline = time.monotonic()+10
    while not process_ids('vrserver') and time.monotonic()<deadline:
        time.sleep(.1)
    if not process_ids('vrserver'):
        raise RuntimeError('Stock vrserver did not start; retained launch evidence')
    record['compositor'] = launch(output/'compositor', layer_directory, mode, diagnostic_fds=diagnostic_fds)
    record['vrmonitor'] = start('vrmonitor', ['-nokillprocess', '-startupappid', '250820',
                                            '-startupreason', 'steamvr_vrstartup', '-startupapptype', '7'])
    (output/'stack-launch.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


def launch(output, layer_directory=None, mode='pixels', replace_pid=None, diagnostic_fds=False):
    output = prepare_output(output)
    executable = (STEAMVR / 'bin/linux64/vrcompositor').resolve(strict=True)
    existing = process_ids('vrcompositor')
    if existing and existing != [replace_pid]:
        raise RuntimeError(f'Compositor already running: {existing}; specify its exact PID with --replace-compositor')
    record = {'started_wall_time_ns': time.time_ns(), 'capture_enabled': bool(layer_directory),
              'persistent_configuration_changes': False, 'replaced_pid': replace_pid}
    if layer_directory:
        layer_directory = Path(layer_directory).resolve(strict=True)
        manifest = json.loads((layer_directory/'VkLayer_NADOC_present_capture.json').read_text())
        library = Path(manifest['layer']['library_path'])
        library = (library if library.is_absolute() else layer_directory/library).resolve(strict=True)
        record['layer_library'] = str(library)
        record['layer_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    if replace_pid:
        proc = Path(f'/proc/{replace_pid}')
        # Elevated compositor /proc/exe may be unreadable; cmdline and comm still
        # identify the stock executable. Require both, never trust only a PID.
        if (proc/'comm').read_text().strip() != 'vrcompositor':
            raise RuntimeError('Replacement PID is not a compositor')
        argv = (proc/'cmdline').read_bytes().split(b'\0')
        if Path(os.fsdecode(argv[0])).resolve() != executable:
            raise RuntimeError('Replacement compositor executable differs from stock runtime')
        record['previous_argv'] = [os.fsdecode(v) for v in argv if v]
        os.kill(replace_pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while proc.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if proc.exists():
            raise RuntimeError('Compositor did not exit gracefully; no force kill performed')
    env = make_environment(layer_directory, output, mode, diagnostic_fds)
    command = [str(STEAMVR/'bin/linux64/vrcompositor-launcher.sh')]
    with (output/'launcher.log').open('xb') as stream:
        child = subprocess.Popen(command, cwd=STEAMVR, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    record.update(pid=child.pid, argv=command, capture_mode=mode if layer_directory else None,
                  status='spawned_display_not_yet_verified',
                  graphics_environment={k: v for k, v in env.items() if k in (
                      'DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', '__NV_PRIME_RENDER_OFFLOAD',
                      '__GLX_VENDOR_LIBRARY_NAME', '__VK_LAYER_NV_optimus', 'VK_LOADER_DRIVERS_SELECT',
                      'VK_LAYER_PATH', 'VK_INSTANCE_LAYERS') or k.startswith('NADOC_VR_CAPTURE_')})
    (output/'launch.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--layer-directory', type=Path, help='Omit to restore ordinary compositor launch')
    parser.add_argument('--mode', choices=['off', 'metadata', 'pixels'], default='pixels')
    parser.add_argument('--diagnostic-fds', action='store_true', help='One-time allowlisted display-device descriptor evidence')
    parser.add_argument('--replace-compositor', type=int)
    parser.add_argument('--start-runtime', action='store_true', help='Start stock server, instrumented compositor, and stock monitor; requires VR closed')
    args = parser.parse_args()
    if args.start_runtime:
        if args.replace_compositor:
            parser.error('--start-runtime and --replace-compositor are mutually exclusive')
        result = launch_stack(args.output, args.layer_directory, args.mode, args.diagnostic_fds)
    else:
        result = launch(args.output, args.layer_directory, args.mode, args.replace_compositor, args.diagnostic_fds)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
