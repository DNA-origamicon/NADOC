"""GPU HMC proposals, corrected against the full literal PEG Hamiltonian."""
from pathlib import Path


def patch(source):
    here=Path(__file__).parent
    base=source/'src/Lists/BaseList.cpp'
    text=base.read_text()
    if '"PEG_HMC"' not in text:
        anchor='if(strncmp("MD", sim_type, 512) == 0) _is_MC = false;'
        assert anchor in text
        base.write_text(text.replace(anchor,anchor+'\n    else if(strncmp("PEG_HMC", sim_type, 512) == 0) _is_MC = false;',1))
    md=source/'src/Backends/MDBackend.cpp'
    text=md.read_text()
    if 'NADOC_PEG_HMC_STEP_UNITS' not in text:
        anchor='\t_obs_output_file->add_observable("type = step\\nunits = MD");'
        assert anchor in text
        text=text.replace(anchor,'''    std::string peg_sim_type; // NADOC_PEG_HMC_STEP_UNITS
    getInputString(&inp,"sim_type",peg_sim_type,0);
    std::string step_description=peg_sim_type=="PEG_HMC" ? "type = step" : "type = step\\nunits = MD";
    _obs_output_file->add_observable(step_description);''',1)
        text=text.replace('_obs_output_stdout->add_observable("type = step\\nunits = MD");','_obs_output_stdout->add_observable(step_description);',1)
        md.write_text(text)
    (source/'src/CUDA/Backends/PEGHMCBackend.h').write_text((here/'PEGHMCBackend.h').read_text())
    mixed=source/'src/CUDA/Backends/MD_CUDAMixedBackend.cu'
    text=mixed.read_text().split('// NADOC_PEG_HMC_V1')[0]
    mixed.write_text(text+'\n'+(here/'peg_hmc_backend.inc').read_text())
    factory=source/'src/Backends/BackendFactory.cpp'
    text=factory.read_text()
    if 'NADOC_PEG_HMC_FACTORY' not in text:
        anchor='#include "../CUDA/Backends/MD_CUDAMixedBackend.h"'
        assert anchor in text
        text=text.replace(anchor,anchor+'\n#include "../CUDA/Backends/PEGHMCBackend.h" // NADOC_PEG_HMC_FACTORY',1)
        anchor='\tif(sim_type == "MD") {'
        assert anchor in text
        text=text.replace(anchor,'''#if !defined(NOCUDA) && !defined(CUDA_DOUBLE_PRECISION)
    if(sim_type == "PEG_HMC") {
        if(backend_opt!="CUDA" || (precision_state==KEY_FOUND && backend_prec!="mixed"))
            throw oxDNAException("PEG_HMC requires CUDA mixed precision");
        return std::make_shared<PEGHMCBackend>();
    }
#endif
'''+anchor,1)
        factory.write_text(text)


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
