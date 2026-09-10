"""GPU stage following patch_chudoba.py. All math shares the CPU header."""
from pathlib import Path


def patch(source):
    # Affected owner bonds add remote beads already present in the neighbor
    # list. Deduplicate those candidates before global energy evaluation.
    base=source/'src/Lists/BaseList.cpp'
    text=base.read_text()
    if 'NADOC_PEG_UNIQUE_NEIGHBORS' not in text:
        text=text.replace('#include <cstring>', '#include <cstring>\n#include <algorithm>')
        text=text.replace('\treturn neighs;', """    if(p->btype==500) { // NADOC_PEG_UNIQUE_NEIGHBORS
        std::sort(neighs.begin(),neighs.end());
        neighs.erase(std::unique(neighs.begin(),neighs.end()),neighs.end());
    }
    return neighs;""",1)
        base.write_text(text)
    cuda='src/CUDA/Interactions/CUDADNAInteraction.cu' 
    if 'NADOC_CHUDOBA_CUDA_V1' in (source/cuda).read_text():
        return
    changes={}
    def edit(name,old,new):
        text=changes.get(name,(source/name).read_text())
        if old not in text:
            raise RuntimeError(f'Missing GPU patch anchor {name}: {old[:80]}')
        changes[name]=text.replace(old,new,1)
    edit(cuda,'#include "CUDA_DNA.cuh"','#include "CUDA_DNA.cuh"\n#include "chudoba_cuda.cuh" // NADOC_CHUDOBA_CUDA_V1')
    edit(cuda,'if(_peg_chudoba) throw oxDNAException("Chudoba CUDA integration pending");','''int chudoba_enabled=_peg_chudoba ? 1 : 0;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_chudoba_enabled,&chudoba_enabled,sizeof(int)));
    float chudoba_temperature=_T*3000.;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_chudoba_temperature,&chudoba_temperature,sizeof(float)));''')
    edit(cuda,'\n}\n\nvoid CUDADNAInteraction::_hb_op_precalc','''
    if(_peg_chudoba) {
        chudoba_manybody<<<_launch_cfg.blocks,_launch_cfg.threads_per_block>>>(d_poss,d_forces,d_bonds,_update_st,_d_st);
        CUT_CHECK_ERROR("Chudoba many-body force kernel");
    }
}

void CUDADNAInteraction::_hb_op_precalc''')
    kernel='src/CUDA/Interactions/CUDA_DNA.cuh'
    edit(kernel,'__constant__ int MD_peg_enabled;','''#include "../../Interactions/chudoba_math.h"
__constant__ int MD_chudoba_enabled;
__constant__ float MD_chudoba_temperature;
__constant__ int MD_peg_enabled;''')
    edit(kernel,'if(MD_peg_enabled && (pbtype == 500 || qbtype == 500)) {','''if(MD_peg_enabled && (pbtype == 500 || qbtype == 500)) {
        if(MD_chudoba_enabled && pbtype==500 && qbtype==500) {
            c_number length=sqrt(CUDA_DOT(r,r)),derivative;
            c_number energy=chudoba::pair(length*c_number(.8518),c_number(MD_chudoba_temperature),derivative);
            c_number4 f=r*(derivative*c_number(.8518/24.943387854)/length);
            f.w=energy/c_number(24.943387854);
            F+=f;
            return;
        }''')
    for name,text in changes.items():
        (source/name).write_text(text)
    (source/'src/CUDA/Interactions/chudoba_cuda.cuh').write_text((Path(__file__).parent/'chudoba_cuda.cuh').read_text())


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
