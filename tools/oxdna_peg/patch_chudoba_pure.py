"""Use the PEG cutoff for explicitly PEG-only benchmark systems."""
from pathlib import Path


def patch(source):
    h=source/'src/Interactions/DNAInteraction.h'
    text=h.read_text()
    if 'NADOC_PEG_PURE_V1' in text:return
    text=text.replace('bool _peg_shift = false;', 'bool _peg_pure = false; // NADOC_PEG_PURE_V1\n    bool _peg_shift = false;',1)
    text=text.replace('public:\n','public:\n    number get_rcut() const override { return _peg_pure ? .9/.8518 : BaseInteraction::get_rcut(); }\n',1)
    cpp=source/'src/Interactions/DNAInteraction.cpp'
    body=cpp.read_text()
    body=body.replace('getInputBool(&inp, "peg_chudoba_shift", &_peg_shift, 0);', '''getInputBool(&inp, "peg_chudoba_shift", &_peg_shift, 0);
        getInputBool(&inp, "peg_chudoba_pure", &_peg_pure, 0);
        if(_peg_pure && !_peg_chudoba) throw oxDNAException("peg_chudoba_pure requires peg_chudoba");''',1)
    body=body.replace('*N_strands = parser.N_strands();','''if(_peg_pure) for(auto p:particles) if(!_peg_particle(p))
        throw oxDNAException("PEG-only cutoff requires all particles to be PEG");
    *N_strands = parser.N_strands();''',1)
    h.write_text(text);cpp.write_text(body)


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
