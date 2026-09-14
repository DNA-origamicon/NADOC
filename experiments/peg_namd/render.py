"""NAMD/VMD input rendering for neutral fixed-slab PEG pilots."""


def build_tcl(spec, row, slab_segments, anchor_identity, top_z_nm):
    lx, ly, lz = [10 * x for x in spec['box_nm']]
    anchor_resid, anchor_name = anchor_identity
    reads = '\n'.join(f'readpsf chains/P{i:03X}.psf pdb chains/P{i:03X}.pdb' for i in range(row['chains']))
    gold = ' '.join(slab_segments)
    peg_segments = ' '.join(f'P{i:03X}' for i in range(row['chains']))
    # TCL code contains generated identifiers and validated numeric inputs only.
    return f'''package require psfgen
package require solvate
package require autoionize
if {{[catch {{
resetpsf
readpsf surface.psf pdb surface.pdb
{reads}
writepsf dry.psf
writepdb dry.pdb
solvate dry.psf dry.pdb -minmax {{{{0 0 {10 * top_z_nm + 1:.5f}}} {{{lx} {ly} {lz}}}}} -o solvated
expr {{srand({row['seed']})}}
autoionize -psf solvated.psf -pdb solvated.pdb -sc {spec['salt_NaCl_M']} -cation SOD -anion CLA -o system
mol new system.psf type psf waitfor all
mol addfile system.pdb type pdb waitfor all
set all [atomselect top all]
$all set beta 0
$all set occupancy 0
set gold [atomselect top "segname {gold}"]
$gold set occupancy 1
set anchors [atomselect top "segname {peg_segments} and resid {anchor_resid} and name {anchor_name}"]
if {{[$anchors num] != {row['chains']}}} {{error "Wrong number of PEG anchors"}}
$anchors set beta {spec['tether_k_kcal_mol_A2']}
$all writepdb masks.pdb
set info [open build_counts.txt w]
puts $info "atoms [$all num]"
puts $info "anchors [$anchors num]"
puts $info "gold [$gold num]"
close $info
set done [open build.complete w]; puts $done success; close $done
}} message]}} {{puts stderr $message; exit 1}}
quit
'''


def common(spec, seed, parameter_count):
    lx, ly, lz = [10 * x for x in spec['box_nm']]
    params = '\n'.join(f'parameters forcefield/p{i:03d}.str' for i in range(parameter_count))
    return f'''# Neutral fixed-gold pilot; harmonic grafts are NOT Au-S bonds.
structure system.psf
coordinates system.pdb
paraTypeCharmm on
{params}
seed {seed}
cellBasisVector1 {lx} 0 0
cellBasisVector2 0 {ly} 0
cellBasisVector3 0 0 {lz}
cellOrigin {lx/2} {ly/2} {lz/2}
PME yes
PMEGridSpacing 1.0
exclude scaled1-4
oneFourScaling 1.0
switching on
switchdist 10
cutoff 12
pairlistdist 14
rigidBonds all
timestep {spec['timestep_fs']}
nonbondedFreq 1
fullElectFrequency 1
stepspercycle 10
langevin on
langevinTemp {spec['temperature_K']}
langevinDamping 1
langevinHydrogen off
langevinPiston off
fixedAtoms on
fixedAtomsFile masks.pdb
fixedAtomsCol O
constraints on
consref masks.pdb
conskfile masks.pdb
conskcol B
consexp 2
wrapAll off
wrapWater on
GPUresident on
outputEnergies 1000
outputTiming 1000
restartfreq 50000
binaryrestart yes
DCDfreq 50000
'''


def configurations(spec, seed, parameter_count):
    header = common(spec, seed, parameter_count)
    result = {}
    result['00_minimize.conf'] = header + f'''outputName output/minimize
temperature {spec['temperature_K']}
minimize 5000
'''
    for name, previous, steps, output in [
        ('01_equilibrate.conf', 'minimize', round(spec['equilibration_ns'] * 1e6 / spec['timestep_fs']), 'equilibrate'),
        ('02_pilot.conf', 'equilibrate', round(spec['pilot_ns'] * 1e6 / spec['timestep_fs']), 'pilot'),
        ('benchmark.conf', 'equilibrate', spec['benchmark_steps'], 'benchmark'),
    ]:
        velocity = f'temperature {spec["temperature_K"]}' if previous == 'minimize' else f'binVelocities output/{previous}.vel'
        result[name] = header + f'''outputName output/{output}
binCoordinates output/{previous}.coor
{velocity}
firsttimestep 0
run {steps}
'''
    result['smoke.conf'] = header + f'''outputName output/smoke
temperature {spec['temperature_K']}
minimize 10
run 0
'''
    return result


RUN_SCRIPT = '''#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
: "${NAMD_BIN:?Set NAMD_BIN to the benchmarked NAMD binary}"
stage=${1:?Use smoke, minimize, equilibrate, pilot, or benchmark}
case "$stage" in
 smoke) conf=smoke.conf; prefix=smoke ;;
 minimize) conf=00_minimize.conf; prefix=minimize ;;
 equilibrate) conf=01_equilibrate.conf; prefix=equilibrate ;;
 pilot) conf=02_pilot.conf; prefix=pilot ;;
 benchmark) conf=benchmark.conf; prefix=benchmark ;;
 *) exit 2 ;;
esac
# Prevent overlapping stages and accidental truncation of previous results.
exec 9>.run.lock
flock -n 9 || { echo "Another stage owns this case" >&2; exit 1; }
[[ -f build.complete ]] || { echo "Run VMD build.tcl first" >&2; exit 1; }
[[ ! -e "output/${prefix}.log" ]] || { echo "Existing stage output; use a new case directory" >&2; exit 1; }
[[ -f built.json ]] || { echo "Run python3 verify_inputs.py --seal first" >&2; exit 1; }
case "$stage" in
 minimize) predecessor=smoke ;;
 equilibrate) predecessor=minimize ;;
 pilot|benchmark) predecessor=equilibrate ;;
 *) predecessor= ;;
esac
if [[ -n "$predecessor" ]]; then
 grep -q 'End of program' "output/${predecessor}.log" || { echo "Predecessor stage incomplete" >&2; exit 1; }
fi
python3 verify_inputs.py
mkdir -p output
"$NAMD_BIN" "+p${NAMD_THREADS:-4}" +setcpuaffinity +devices "${NAMD_DEVICES:-0}" "$conf" > "output/${prefix}.log" 2>&1
# A zero exit alone is insufficient for some builds.
grep -q 'End of program' "output/${prefix}.log"
'''
