"""Explicit energy convention for comparisons of MD and Metropolis sampling."""
from pathlib import Path


def patch(source):
    header=source/'src/Interactions/DNAInteraction.h'
    if 'NADOC_PEG_SHIFT_V1' in header.read_text():return
    changes={}
    def edit(name,old,new):
        text=changes.get(name,(source/name).read_text())
        if old not in text:raise RuntimeError(f'Missing cutoff patch anchor {name}: {old[:60]}')
        changes[name]=text.replace(old,new,1)
    edit('src/Interactions/DNAInteraction.h','bool _peg_chudoba = false;',
        'bool _peg_chudoba = false;\n    bool _peg_shift = false; // NADOC_PEG_SHIFT_V1')
    cpp='src/Interactions/DNAInteraction.cpp'
    edit(cpp,'getInputBool(&inp, "peg_chudoba", &_peg_chudoba, 0);',
        'getInputBool(&inp, "peg_chudoba", &_peg_chudoba, 0);\n        getInputBool(&inp, "peg_chudoba_shift", &_peg_shift, 0);')
    edit(cpp,'number energy = chudoba::pair(r*.8518, _T*3000., derivative)/24.943387854;',
        '''number energy = chudoba::pair(r*.8518, _T*3000., derivative)/24.943387854;
        if(_peg_shift && r*.8518 < .9) {
            number ignored;
            energy -= chudoba::pair(number(.9), _T*3000., ignored, false)/24.943387854;
        }''')
    kernel='src/CUDA/Interactions/CUDA_DNA.cuh'
    edit(kernel,'__constant__ float MD_chudoba_temperature;',
        '__constant__ float MD_chudoba_temperature;\n__constant__ float MD_chudoba_shift;')
    edit(kernel,'f.w=energy/c_number(24.943387854);',
        'f.w=(energy-(length*c_number(.8518)<c_number(.9) ? c_number(MD_chudoba_shift) : c_number(0)))/c_number(24.943387854);')
    cuda='src/CUDA/Interactions/CUDADNAInteraction.cu'
    edit(cuda,'float chudoba_temperature=_T*3000.;','''number ignored;
    float chudoba_shift=_peg_shift ? chudoba::pair(number(.9),_T*3000.,ignored,false) : 0.;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_chudoba_shift,&chudoba_shift,sizeof(float)));
    float chudoba_temperature=_T*3000.;''')
    for name,text in changes.items():(source/name).write_text(text)


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
