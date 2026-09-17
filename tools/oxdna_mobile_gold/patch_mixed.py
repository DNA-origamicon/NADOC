"""Mass/inertia corrections for mixed-precision CUDA integration."""
from pathlib import Path

def patch(root):
    root=Path(root)
    p=root/'src/Interactions/DNAInteraction.h'
    p.write_text(p.read_text().replace('public:', 'public:\n    bool is_mobile_gold() const { return _gold_model; }',1))
    p=root/'src/Backends/MDBackend.cpp'
    s=p.read_text().replace('#include "MDBackend.h"','#include "MDBackend.h"\n#include "../Interactions/DNAInteraction.h"')
    s=s.replace('else if(!_refresh_velocities && p->L.module() < 1.e-10)', 'else if(!_refresh_velocities && p->L.module() < 1.e-10 && !(dynamic_cast<DNAInteraction *>(_interaction.get()) && dynamic_cast<DNAInteraction *>(_interaction.get())->is_mobile_gold()))')
    p.write_text(s)
    h=root/'src/CUDA/Backends/MD_CUDAMixedBackend.h'
    h.write_text(h.read_text().replace('\tvoid init();','\tvoid get_settings(input_file &inp) override;\n\tvoid init();'))
    p=root/'src/CUDA/Backends/MD_CUDAMixedBackend.cu'
    s=p.read_text().replace('#include "CUDA_mixed.cuh"','#include "../cuda_utils/gold_dynamics.cuh"\n#include "CUDA_mixed.cuh"')
    s+='\nvoid CUDAMixedBackend::get_settings(input_file &inp) { MD_CUDABackend::get_settings(inp); gold_dynamics_settings(inp); }\n'
    p.write_text(s)
    p=root/'src/CUDA/Backends/CUDA_mixed.cuh';s=p.read_text()
    for a in 'xyz':
        s=s.replace(f'F.{a} * MD_dt[0]',f'F.{a} * gold_inv_mass(IND) * MD_dt[0]')
        s=s.replace(f'T.{a} * MD_dt[0]',f'T.{a} * gold_inv_inertia(IND) * MD_dt[0]')
    p.write_text(s)

if __name__=='__main__':
    import sys
    patch(sys.argv[1])
