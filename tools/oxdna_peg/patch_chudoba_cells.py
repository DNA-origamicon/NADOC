"""Fix CUDA cell capacity boundary and prevent writes beyond an overflowing cell.

The upstream kernel tests the shared final count after insertion. That treats
exact capacity as overflow and may write one beyond capacity before noticing it.
Use each atomic reservation's prior count and guard the write instead.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1])/'src/CUDA/Lists/CUDA_simple_verlet.cuh'
s=p.read_text()
marker='// NADOC_CUDA_CELL_CAPACITY_RESERVATION'
if marker not in s:
    old='''\tcells[index * verlet_max_N_per_cell[0] + atomicInc((uint32_t *) &counters_cells[index], verlet_max_N_per_cell[0])] = IND;
\tif(counters_cells[index] >= verlet_max_N_per_cell[0]) {
\t\t*cell_overflow = true;
\t}'''
    new='''\t// NADOC_CUDA_CELL_CAPACITY_RESERVATION
\tint slot = atomicAdd(&counters_cells[index], 1);
\tif(slot < verlet_max_N_per_cell[0]) {
\t\tcells[index * verlet_max_N_per_cell[0] + slot] = IND;
\t}
\telse {
\t\t*cell_overflow = true;
\t}'''
    assert old in s, 'CUDA cell fill anchor changed'
    p.write_text(s.replace(old,new,1))
