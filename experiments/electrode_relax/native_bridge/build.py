"""Build an isolated NAMD prototype from existing compiled objects; never install it."""
import argparse,hashlib,json,re,shlex,subprocess
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
source=args.source.resolve();build=source/'Linux-x86_64-g++';out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
code=(source/'src/GlobalMasterTcl.C').read_text();header=(source/'src/GlobalMasterTcl.h').read_text()
fragment=Path(__file__).with_name('command.cpp').read_text()
code=code.replace('#include <stdio.h>','#include <stdio.h>\n#include <array>\n#include <vector>')
needle='int GlobalMasterTcl::Tcl_print';assert code.count(needle)==1
code=code.replace(needle,fragment+'\n'+needle)
needle='  Tcl_CreateObjCommand(interp, (char *)"addforce", Tcl_addforce,';assert code.count(needle)==1
code=code.replace(needle,'  Tcl_CreateObjCommand(interp, "nadoc_native_electrode", Tcl_nadoc_electrode, (ClientData)this, NULL);\n'+needle)
needle='  static int Tcl_addforce(';assert header.count(needle)==1
header=header.replace(needle,'  static int Tcl_nadoc_electrode(ClientData, Tcl_Interp *, int, Tcl_Obj * const []);\n'+needle)
(out/'GlobalMasterTcl.C').write_text(code);(out/'GlobalMasterTcl.h').write_text(header)
plan=subprocess.check_output(['make','-n','-W','src/GlobalMasterTcl.C','namd3'],cwd=build,text=True).replace('\\\n',' ').splitlines()
compile=shlex.split(next(l for l in plan if l.startswith('g++ ') and 'GlobalMasterTcl.o' in l))
compile=[str(out/'GlobalMasterTcl.o') if x=='obj/GlobalMasterTcl.o' else str(out/'GlobalMasterTcl.C') if x=='src/GlobalMasterTcl.C' else x for x in compile]
link=next(l for l in plan if l.startswith('.rootdir/') and '/charmc ' in l)
for match in re.findall(r'`([^`]+)`',link):
    replacement=subprocess.check_output(shlex.split(match),cwd=build,text=True).strip();link=link.replace('`'+match+'`',replacement)
link=shlex.split(link)
link=[str(out/'GlobalMasterTcl.o') if x=='obj/GlobalMasterTcl.o' else str(out/'namd3') if x=='namd3' else x for x in link]
# Linker runs from a scratch directory with read-only references to existing inputs.
for entry in build.iterdir():
    if entry.name not in {'namd3'} and not (out/entry.name).exists():(out/entry.name).symlink_to(entry.resolve())
with (out/'build.log').open('w') as log:
 subprocess.run(compile,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
 subprocess.run(link,cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
(out/'provenance.json').write_text(json.dumps(dict(source=str(source),original_binary_sha256=hashlib.sha256((build/'namd3').read_bytes()).hexdigest(),prototype_sha256=hashlib.sha256((out/'namd3').read_bytes()).hexdigest(),fragment_sha256=hashlib.sha256(fragment.encode()).hexdigest(),compile=compile,link=link),indent=2)+'\n')
print(out/'namd3')
