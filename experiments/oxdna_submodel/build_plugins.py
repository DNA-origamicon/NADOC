"""Build isolated, masked versions of upstream oxDNA single-particle MC moves.

The default keeps upstream proposal, energy and acceptance code unchanged.
Only particle selection changes. Optional downhill mode rejects all uphill moves
at the same force-field temperature; it is stochastic minimization, not sampling. Generated derivatives retain the upstream GPL license.
No installed source or executable is modified.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

HELPER = r'''
#include <fstream>
#include <set>
static int submodel_particle(std::shared_ptr<ConfigInfo> info) {
    static std::vector<int> ids;
    if (ids.empty()) {
        std::ifstream stream("mobile.txt");
        int id;
        std::set<int> unique;
        while (stream >> id) {
            if (id < 0 || id >= info->N() || !unique.insert(id).second)
                throw oxDNAException("Invalid submodel particle index");
            ids.push_back(id);
        }
        if (!stream.eof() || ids.empty())
            throw oxDNAException("Missing or invalid mobile.txt");
    }
    return ids.at(static_cast<size_t>(drand48() * ids.size()));
}
'''


def build(source, library, output, *, downhill=False):
    source, library, output = map(Path, (source, library, output))
    output.mkdir(parents=True, exist_ok=False)
    moves = source / 'src/Backends/MCMoves'
    manifest = {'acceptance': 'downhill-only' if downhill else 'Metropolis'}
    for original, name in [('MCTras', 'SubmodelTranslation'), ('MCRot', 'SubmodelRotation')]:
        cpp = (moves / f'{original}.cpp').read_text()
        header = (moves / f'{original}.h').read_text()
        needle = 'int pi = (int) (drand48() * this->_Info->N());'
        if cpp.count(needle) != 1:
            raise ValueError('Upstream move changed; inspect before rebuilding')
        manifest[original] = hashlib.sha256(cpp.encode()).hexdigest()
        cpp = cpp.replace(needle, 'int pi = submodel_particle(this->_Info);')
        if downhill:
            uphill = ' || exp(-(delta_E + delta_E_ext) / this->_T) > drand48()'
            if cpp.count(uphill) != 1:
                raise ValueError('Upstream acceptance changed; inspect before rebuilding')
            cpp = cpp.replace(uphill, '')
        cpp = cpp.replace(original, name)
        cpp = cpp.replace(f'#include "{name}.h"', f'#include "{name}.h"\n{HELPER}')
        cpp = cpp.replace('../../Utilities/Utils.h', 'Utilities/Utils.h')
        cpp += f'\nextern "C" BaseMove *make_move() {{ return new {name}(); }}\n'
        (output / f'{name}.cpp').write_text(cpp)
        (output / f'{name}.h').write_text(header.replace(original, name))
        subprocess.run([os.environ.get('CXX', 'c++'), '-include', 'string', '-std=c++11', '-O2', '-fPIC', '-shared',
                        '-I'+str(source/'src'), '-I'+str(source/'src/extern'), '-I'+str(moves),
                        str(output/f'{name}.cpp'), '-L'+str(library),
                        '-Wl,-rpath,'+str(library), '-loxdna_common',
                        '-o', str(output/f'{name}.so')], check=True)
    (output/'upstream.json').write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('library', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--downhill', action='store_true')
    a = p.parse_args()
    build(a.source.resolve(), a.library.resolve(), a.output.resolve(), downhill=a.downhill)
