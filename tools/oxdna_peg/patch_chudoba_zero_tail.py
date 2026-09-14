"""Explicit outer-tail removal reconstructed from the published Figure 4(b)."""
from pathlib import Path
import sys

root=Path(sys.argv[1]);header=root/'src/Interactions/DNAInteraction.h'
if 'NADOC_PEG_ZERO_TAIL' not in header.read_text():
    changes={}
    def edit(name,old,new):
        p=root/name;s=changes.get(p,p.read_text())
        assert old in s,(name,old)
        changes[p]=s.replace(old,new,1)
    edit('src/Interactions/DNAInteraction.h','bool _peg_shift = false;',
         'bool _peg_zero_tail = false; // NADOC_PEG_ZERO_TAIL\n    bool _peg_shift = false;')
    edit('src/Interactions/DNAInteraction.cpp','getInputBool(&inp, "peg_chudoba_shift", &_peg_shift, 0);',
         '''getInputBool(&inp, "peg_chudoba_shift", &_peg_shift, 0);
        getInputBool(&inp, "peg_chudoba_zero_tail", &_peg_zero_tail, 0);
        if(_peg_shift && _peg_zero_tail) throw oxDNAException("PEG shift and zero-tail conventions are mutually exclusive");''')
    edit('src/Interactions/DNAInteraction.cpp','chudoba::pair(r*.8518, _T*3000., derivative)',
         'chudoba::pair(r*.8518, _T*3000., derivative, true, _peg_zero_tail)')
    edit('src/CUDA/Interactions/CUDA_DNA.cuh','__constant__ float MD_chudoba_shift;',
         '__constant__ float MD_chudoba_shift;\n__constant__ int MD_chudoba_zero_tail;')
    edit('src/CUDA/Interactions/CUDA_DNA.cuh','chudoba::pair(length*c_number(.8518),c_number(MD_chudoba_temperature),derivative)',
         'chudoba::pair(length*c_number(.8518),c_number(MD_chudoba_temperature),derivative,true,MD_chudoba_zero_tail!=0)')
    edit('src/CUDA/Interactions/CUDADNAInteraction.cu','float chudoba_temperature=_T*3000.;',
         '''int zero_tail=_peg_zero_tail ? 1 : 0;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_chudoba_zero_tail,&zero_tail,sizeof(int)));
    float chudoba_temperature=_T*3000.;''')
    for p,s in changes.items():p.write_text(s)
