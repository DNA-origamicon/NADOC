"""Install inexpensive per-frame chain-shape diagnostics for CPU and CUDA."""
from pathlib import Path
import shutil
import sys

root=Path(sys.argv[1]);here=Path(__file__).parent
shutil.copyfile(here/'PEGChainShape.h',root/'src/Observables/PEGChainShape.h')
p=root/'src/Observables/ObservableFactory.cpp';s=p.read_text()
if '#include "PEGChainShape.h"' not in s:
    s=s.replace('#include "Density.h"','#include "Density.h"\n#include "PEGChainShape.h"')
    needle='else if(!strncasecmp(obs_type, "density", 512))'
    assert needle in s
    s=s.replace(needle,'else if(!strncasecmp(obs_type, "peg_chain_shape", 512)) res = std::make_shared<PEGChainShape>();\n\t'+needle)
    p.write_text(s)
