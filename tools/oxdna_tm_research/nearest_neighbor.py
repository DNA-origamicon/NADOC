"""SantaLucia 1998 Table 2 / entropy salt correction; undamaged reference only.

This is a separate empirical model, not an oxDNA sampling estimate or CPD model.
"""
import json
import math
import time

PARAMETERS={'AA':(-7.9,-22.2),'AT':(-7.2,-20.4),'TA':(-7.2,-21.3),
            'CA':(-8.5,-22.7),'GT':(-8.4,-22.4),'CT':(-7.8,-21.0),
            'GA':(-8.2,-22.2),'CG':(-10.6,-27.2),'GC':(-9.8,-24.4),'GG':(-8.0,-19.9)}

def tm(sequence,total_strands_M,sodium_M):
    if len(sequence)<2 or set(sequence)-set('ACGT') or total_strands_M<=0 or sodium_M<=0:
        raise ValueError('Need undamaged DNA, positive concentration and sodium.')
    rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
    h=s=0.
    for i in range(len(sequence)-1):
        pair=sequence[i:i+2]
        dh,ds=PARAMETERS[pair if pair in PARAMETERS else rc(pair)]
        h+=dh;s+=ds
    for end in (sequence[0],sequence[-1]):
        dh,ds=(.1,-2.8) if end in 'GC' else (2.3,4.1)
        h+=dh;s+=ds
    symmetric=sequence==rc(sequence)
    if symmetric:s-=1.4
    s_salt=s+.368*(len(sequence)-1)*math.log(sodium_M)
    value=1000*h/(s_salt+1.987*math.log(total_strands_M/(1 if symmetric else 4)))-273.15
    return dict(sequence=sequence,total_strands_M=total_strands_M,sodium_M=sodium_M,
                enthalpy_kcal_mol=h,entropy_1M_cal_mol_K=s,entropy_salt_cal_mol_K=s_salt,tm_c=value)

if __name__=='__main__':
    start=time.perf_counter();r=tm('GCGTTGCG',.012,.3);r['calculation_seconds']=time.perf_counter()-start
    r['source']='https://doi.org/10.1073/pnas.95.4.1460'
    r['qualification']='Different empirical physical model. No sampling CI; model uncertainty uncalibrated here. No CPD-isomer prediction.'
    print(json.dumps(r,indent=2))
