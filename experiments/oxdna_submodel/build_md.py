"""Build an isolated CPU MD executable with immutable outside-particle poses.

Compile the upstream CPU backend with a mask in both Verlet half-steps, and pass
only mobile particles to the per-particle Brownian thermostat. All forces and
interactions remain upstream. Link against the installed library; do not change
its files. The executable exports its backend symbols to the shared factory.
"""
import argparse
import hashlib
import json
import os
import shlex
from pathlib import Path
import subprocess

HELPER = r'''
#include <fstream>
#include <set>
static std::string submodel_file;
static std::vector<bool> submodel_mobile;
static std::vector<BaseParticle *> submodel_particles;
static void submodel_init(const std::vector<BaseParticle *> &particles) {
    submodel_mobile.assign(particles.size(), false);
    submodel_particles.clear();
    std::ifstream stream(submodel_file);
    int id;
    while (stream >> id) {
        if (id < 0 || id >= static_cast<int>(particles.size()) || submodel_mobile[id])
            throw oxDNAException("Invalid or duplicate submodel particle index");
        submodel_mobile[id] = true;
    }
    if (!stream.eof() || std::count(submodel_mobile.begin(), submodel_mobile.end(), true) == 0)
        throw oxDNAException("Missing or empty submodel mobile file");
    for (auto p: particles) {
        if (submodel_mobile.at(p->index)) submodel_particles.push_back(p);
        else { p->vel = LR_vector(0.,0.,0.); p->L = LR_vector(0.,0.,0.); }
    }
    OX_LOG(Logger::LOG_INFO, "SUBMODEL_MD_V1: %lu mobile / %lu total; fixed poses and momenta; Brownian thermostat only on mobile DOFs",
           submodel_particles.size(), particles.size());
}
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Upstream CPU backend changed; review patch before building: '+before[:65])
    return text.replace(before, after)


def build(source, library, output, runtime_libraries=()):
    source, library, output = map(lambda p:Path(p).resolve(), (source,library,output))
    output.mkdir(parents=True,exist_ok=False)
    path = source/'src/Backends/MD_CPUBackend.cpp'
    original = path.read_text()
    patched = original.replace('#include "MD_CPUBackend.h"', '#include "MD_CPUBackend.h"\n#include <algorithm>\n'+HELPER)
    settings = '''
    getInputString(&inp, "submodel_mobile_file", submodel_file, 1);
    std::string thermostat;
    getInputString(&inp, "thermostat", thermostat, 1);
    if (thermostat != "brownian" && thermostat != "john")
        throw oxDNAException("Submodel MD requires the per-particle Brownian thermostat");
    if (_enable_fix_diffusion || _reset_initial_com_momentum || _reset_com_momentum || _use_barostat || _lees_edwards)
        throw oxDNAException("Submodel MD forbids diffusion fixing, COM resets, barostat and shear");
    bool builtin = false;
    getInputBool(&inp, "MD_use_builtin_langevin_thermostat", &builtin, 0);
    if (builtin) throw oxDNAException("Submodel MD requires Brownian rotation and translation thermostat");
'''
    patched = replace_once(patched, 'MDBackend::get_settings(inp);', 'MDBackend::get_settings(inp);\n'+settings)
    patched = replace_once(patched, 'MDBackend::init();', 'MDBackend::init();\n    submodel_init(_particles);')
    for function in ('_first_step', '_second_step'):
        begin = patched.index('void MD_CPUBackend::'+function+'()')
        loop = patched.index('for(auto p : _particles) {', begin)
        end = loop + len('for(auto p : _particles) {')
        patched = patched[:end]+'\n        if (!submodel_mobile.at(p->index)) continue;'+patched[end:]
    patched = replace_once(patched, '_thermostat->apply(_particles, current_step());',
                           '_thermostat->apply(submodel_particles, current_step());')
    main = (source/'src/oxDNA.cpp').read_text()
    main = replace_once(main, 'SimManager mysim(input);', '''std::string backend, sim_type;
        getInputString(&input, "backend", backend, 1);
        getInputString(&input, "sim_type", sim_type, 1);
        if (backend != "CPU" || sim_type != "MD") throw oxDNAException("Submodel executable supports CPU MD only");
        SimManager mysim(input);''')
    (output/'MD_CPUBackend.cpp').write_text(patched)
    (output/'main.cpp').write_text(main)
    subprocess.run([os.environ.get('CC','cc'), '-O2', '-c', str(source/'src/extern/tinyexpr/tinyexpr.c'), '-o', str(output/'tinyexpr.o')],check=True)
    command = [os.environ.get('CXX','c++'), '-std=c++14','-O2',*shlex.split(os.environ.get('CXXFLAGS','')),'-include','string',
               '-I'+str(source/'src'),'-I'+str(source/'src/extern'),'-I'+str(source/'src/Backends'),
               '-DRELEASE="experimental-submodel-md-v1"','-DGIT_COMMIT="see-build-manifest"',
               '-DBUILD_TIME="isolated-local-build"',str(output/'main.cpp'), str(output/'MD_CPUBackend.cpp'),
               '-L'+str(library),'-Wl,-rpath,'+str(library),'-Wl,--export-dynamic',
               '-loxdna_common',str(output/'tinyexpr.o')]
    for item in runtime_libraries:
        item=Path(item).resolve()
        command.extend([str(item), '-Wl,-rpath,'+str(item.parent)])
    command.extend(['-o',str(output/'oxDNA-submodel')])
    subprocess.run(command,check=True)
    (output/'build.json').write_text(json.dumps({'command':command,
        'upstream_backend_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'library_sha256':hashlib.sha256((library/'liboxdna_common.so').read_bytes()).hexdigest(),
        'binary_sha256':hashlib.sha256((output/'oxDNA-submodel').read_bytes()).hexdigest(),
        'method':'Executable symbol interposition of CPU backend; unchanged shared interaction library'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','library','output'):p.add_argument(name)
    p.add_argument('--runtime-library',action='append',default=[])
    a=p.parse_args();build(a.source,a.library,a.output,a.runtime_library)
