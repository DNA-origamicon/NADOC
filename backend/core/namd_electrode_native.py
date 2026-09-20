"""Optional compiled implementation of the reference electrode Tcl callback."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

SOURCE=Path(__file__).parent/'native'/'electrode_tcl.cpp'
CALLBACK='''
# Same force equations; the reference Tcl callback remains the portable fallback.
if {[catch {load [file join [file dirname [info script]] electrode_native.so] Electrodenative} reason]} {
    print "NADOC_ELECTRODE_NATIVE fallback: $reason"
} else {
    print "NADOC_ELECTRODE_NATIVE active"
    proc calcforces {} {
        global slab_charges slab_mobile slab_axis slab_coefficient slab_low slab_high slab_wall_k electrode_sites
        loadcoords xyz
        nadoc_electrode_forces xyz $slab_charges $slab_mobile $slab_axis $slab_coefficient $slab_low $slab_high $slab_wall_k $electrode_sites
    }
}
'''


def install_native(folder):
    """Compile against Tcl stubs if an SDK is installed; never require it for setup."""
    compiler=shutil.which('g++')
    roots=[Path(os.environ.get('NADOC_TCL_SDK','/usr')),Path('workspace/electrode_native_build/sdk/usr').resolve()]
    tclsh = shutil.which('tclsh')
    if tclsh:
        roots.append(Path(tclsh).resolve().parent.parent)
    for root in roots:
        include=next((path for path in (root/'include/tcl8.6', root/'include')
                      if (path/'tcl.h').is_file()), root/'include/tcl8.6')
        libs=list((root/'lib').glob('**/libtclstub8.6.a')) if include.exists() else []
        if compiler and (include/'tcl.h').exists() and libs:break
    else:return {'enabled':False,'reason':'Tcl 8.6 SDK/compiler unavailable; reference Tcl forces retained'}
    folder=Path(folder)
    command=[compiler,'-std=c++17','-O3','-fPIC','-shared','-DUSE_TCL_STUBS',f'-I{include}',str(SOURCE),str(libs[0]),'-o',str(folder/'electrode_native.so')]
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    except (OSError,subprocess.SubprocessError) as exc:return {'enabled':False,'reason':str(exc)}
    (folder/'electrode_native_build.log').write_text(result.stdout+result.stderr)
    if result.returncode:return {'enabled':False,'reason':'Compiler failed; see electrode_native_build.log'}
    script=folder/'electrode_forces.tcl'
    if 'NADOC_ELECTRODE_NATIVE active' not in script.read_text():
        with script.open('a') as stream:stream.write(CALLBACK)
    return {'enabled':True,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'backend':'compiled Tcl extension (CPU)'}
