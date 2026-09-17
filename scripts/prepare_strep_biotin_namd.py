"""Write isolated gold-free molecular preparation; does not launch NAMD."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from backend.core.models import Design
from backend.core.strep_biotin_namd import write_preparation

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    manifest = write_preparation(Design.from_json(a.source.read_text()), a.output)
    print({'output': str(a.output), 'simulation_ready': manifest['simulation_ready'],
           'blocked_by': manifest['blocked_by']})
