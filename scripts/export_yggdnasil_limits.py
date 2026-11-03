#!/usr/bin/env python3
"""Export the native Sweep constants used by the browser's arc atlas."""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core.constants import BDNA_RISE_PER_BP, SQUARE_HELIX_SPACING
from backend.core.loop_skip_calculator import CELL_BP_DEFAULT, MAX_DELTA_PER_CELL, SQ_SKIP_PERIOD_DEFAULT

if __name__ == '__main__':
    sources = ['backend/core/constants.py', 'backend/core/sweep_feasibility.py', 'backend/core/sweep_loop_skips.py', 'backend/core/loop_skip_calculator.py']
    output = dict(rise_nm=BDNA_RISE_PER_BP, helix_pitch_nm=SQUARE_HELIX_SPACING,
                  cell_bp=CELL_BP_DEFAULT, max_delta_per_cell=MAX_DELTA_PER_CELL,
                  square_skip_period=SQ_SKIP_PERIOD_DEFAULT, scaffold_nt=7249, max_angle_deg=360,
                  source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources})
    (ROOT / 'frontend/src/design/yggdnasil_limits.json').write_text(json.dumps(output, indent=2) + '\n')
