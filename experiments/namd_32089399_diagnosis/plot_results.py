from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path(__file__).resolve().parent
bad=np.loadtxt(p/'trace/energies.csv',delimiter=',')
good=np.loadtxt(p/'piston10ps/energies.csv',delimiter=',')
fig,axes=plt.subplots(3,2,figsize=(11,8),layout='constrained')
for col,(data,label) in enumerate([(bad,'Original piston: 1 ps / 0.5 ps'),(good,'Corrected piston: 10 ps / 5 ps')]):
    time=data[:,0]*.004
    axes[0,col].plot(time,data[:,7],color='#b33b32' if col==0 else '#237c58')
    axes[0,col].set_title(label)
    axes[0,col].set_ylabel('Wall restraint energy (kcal/mol)')
    axes[0,col].set_yscale('log')
    valid=data[:,15]>-1e10
    axes[1,col].plot(time[valid],data[valid,15])
    axes[1,col].set_ylabel('Pressure (bar)')
    axes[2,col].plot(time,100*(data[:,17]/data[0,17]-1))
    axes[2,col].set_ylabel('Volume change (%)')
    axes[2,col].set_xlabel('Time from checkpoint (ps)')
    for row in range(3):axes[row,col].grid(alpha=.2)
fig.suptitle('small_plate: barostat–restrained-wall instability at 4 fs\nSame checkpoint, force field, restraints, seed and GPU-resident integrator')
fig.savefig(p/'piston_comparison.png',dpi=160)
