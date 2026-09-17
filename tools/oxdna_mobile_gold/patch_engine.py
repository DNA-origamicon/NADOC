"""Pinned, isolated GPU-only DNA2GOLD. Ordinary DNA2 remains unchanged."""
from pathlib import Path
import sys

MARKER = 'NADOC_MOBILE_GOLD_V1'

def patch(root):
    root=Path(root)
    if MARKER in (root/'src/Interactions/DNAInteraction.h').read_text():
        raise RuntimeError('Use a clean checkout when rebuilding mobile gold')
    changes={}
    def edit(name, old, new, count=1):
        text=changes.get(name,(root/name).read_text())
        if text.count(old)<count: raise RuntimeError(f'Patch anchor absent: {name}: {old[:100]}')
        changes[name]=text.replace(old,new,count)
    h='src/Interactions/DNAInteraction.h'
    edit(h,'protected:\n','protected:\n    // '+MARKER+'\n    bool _gold_model=false;\n')
    cpp='src/Interactions/DNAInteraction.cpp'
    edit(cpp,'void DNAInteraction::get_settings(input_file &inp) {', '''void DNAInteraction::get_settings(input_file &inp) {
    std::string gold_type; getInputString(&inp,"interaction_type",gold_type,0);
    _gold_model=gold_type=="DNA2GOLD";
    if(_gold_model) {
        std::string backend,sim,thermostat;
        getInputString(&inp,"backend",backend,1); getInputString(&inp,"sim_type",sim,1);
        getInputString(&inp,"thermostat",thermostat,1);
        int sorting=0; getInputInt(&inp,"CUDA_sort_every",&sorting,0);
        bool refresh=false; getInputBool(&inp,"refresh_vel",&refresh,0);
        bool barostat=false; getInputBool(&inp,"use_barostat",&barostat,0);
        if(backend!="CUDA" || sim!="MD" || (thermostat!="langevin" && thermostat!="no") || sorting || refresh || barostat)
            throw oxDNAException("DNA2GOLD requires CUDA MD, langevin/no thermostat, refresh_vel=false, no sorting/barostat");
        OX_LOG(Logger::LOG_INFO,"NADOC_MOBILE_GOLD_V1: GPU mobile rigid cores and permanent body-fixed grafts");
    }
''')
    # Host pair routines must never index DNA base parameter arrays with marker 499.
    for term in ['_backbone','_bonded_excluded_volume','_stacking','_hydrogen_bonding','_cross_stacking','_coaxial_stacking','_nonbonded_excluded_volume']:
        sig=f'number DNAInteraction::{term}(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {{'
        edit(cpp,sig,sig+'\n    if(_gold_model && ((p != P_VIRTUAL && p->btype==499) || (q != P_VIRTUAL && q->btype==499))) return 0.;\n')
    # GPU energy must be used; host DNA-only pair routines intentionally omit gold.
    for term in ['_coaxial_stacking','_debye_huckel']:
        sig=f'number DNA2Interaction::{term}(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {{'
        edit('src/Interactions/DNA2Interaction.cpp',sig,sig+'\n    if(_gold_model && (p->btype==499 || q->btype==499)) return 0.;\n')
    edit('src/Interactions/InteractionFactory.cpp','else if(inter_type.compare("DNA2") == 0)','else if(inter_type.compare("DNA2") == 0 || inter_type.compare("DNA2GOLD") == 0)')
    edit('src/CUDA/Interactions/CUDAInteractionFactory.cu','!inter_type.compare("DNA2"))','!inter_type.compare("DNA2") || !inter_type.compare("DNA2GOLD"))')
    h='src/CUDA/Interactions/CUDADNAInteraction.h'
    edit(h,'#include "CUDABaseInteraction.h"','#include "CUDABaseInteraction.h"\n#include "../../Interactions/MobileGold.h"')
    edit(h,'protected:\n','protected:\n    GoldModel _gold;\n    GoldGraft *_gold_grafts=nullptr;\n')
    cu='src/CUDA/Interactions/CUDADNAInteraction.cu'
    edit(cu,'#include "CUDA_DNA.cuh"','#include "CUDA_DNA.cuh"\n#include "mobile_gold.cuh"')
    edit(cu,'CUDADNAInteraction::~CUDADNAInteraction() {','CUDADNAInteraction::~CUDADNAInteraction() {\n    if(_gold_grafts) cudaFree(_gold_grafts);')
    edit(cu,'if(inter_type.compare("DNA2") == 0)','if(inter_type.compare("DNA2") == 0 || inter_type.compare("DNA2GOLD") == 0)')
    edit(cu,'DNAInteraction::get_settings(inp);','''DNAInteraction::get_settings(inp);
    if(_gold_model) { std::string file; getInputString(&inp,"gold_file",file,1); _gold.load(file); }
''')
    edit(cu,'void CUDADNAInteraction::cuda_init(int N) {','''void CUDADNAInteraction::cuda_init(int N) {
    int enabled=_gold_model?1:0;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_gold_enabled,&enabled,sizeof(int)));
    if(_gold_model) {
        int ncoat=_gold.coating.size();
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_coating_count,&ncoat,sizeof(int)));
        if(ncoat) CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_coating,_gold.coating.data(),ncoat*sizeof(GoldCoating)));
        int nc=_gold.cores.size();
        if(N!=_gold.dna_count+nc) throw oxDNAException("Mobile gold particle count mismatch");
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_count,&nc,sizeof(int)));
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_dna_count,&_gold.dna_count,sizeof(int)));
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_cores,_gold.cores.data(),nc*sizeof(GoldCore)));
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_clearance,&_gold.clearance,sizeof(float)));
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gold_exclusion_k,&_gold.exclusion_k,sizeof(float)));
        std::vector<GoldGraft> grafts(_gold.dna_count);
        for(auto &g:grafts) g.core=-1;
        for(auto g:_gold.grafts) grafts[g.dna]=g;
        CUDA_SAFE_CALL(cudaMalloc((void**)&_gold_grafts,grafts.size()*sizeof(GoldGraft)));
        CUDA_SAFE_CALL(cudaMemcpy(_gold_grafts,grafts.data(),grafts.size()*sizeof(GoldGraft),cudaMemcpyHostToDevice));
    }
''')
    anchor='\n}\n\nvoid CUDADNAInteraction::_hb_op_precalc'
    edit(cu,anchor,'''
    if(_gold_model) {
        gold_dna_forces<<<(_gold.dna_count+127)/128,128>>>(d_poss,d_orientations,d_forces,d_torques,_gold_grafts,d_box);
        gold_core_forces<<<1,64>>>(d_poss,d_orientations,d_forces,d_torques,d_box);
        CUT_CHECK_ERROR("mobile gold forces");
    }
}

void CUDADNAInteraction::_hb_op_precalc''')
    k='src/CUDA/Interactions/CUDA_DNA.cuh'
    edit(k,'template<bool qIsN3>\n__device__ void _bonded_part','__constant__ int MD_gold_enabled;\n\ntemplate<bool qIsN3>\n__device__ void _bonded_part')
    edit(k,'\tint int_type = pbtype + qbtype;','\tif(MD_gold_enabled && (pbtype==499 || qbtype==499)) return;\n\tint int_type = pbtype + qbtype;')
    # Each core is an unbonded rigid DNA-particle container; no fictitious DNA bonds.
    backend='src/CUDA/Backends/MD_CUDABackend.cu'
    edit(backend,'#include "CUDA_MD.cuh"','#include "../cuda_utils/gold_dynamics.cuh"\n#include "CUDA_MD.cuh"')
    edit(backend,'void MD_CUDABackend::get_settings(input_file &inp) {','void MD_CUDABackend::get_settings(input_file &inp) {\n    gold_dynamics_settings(inp);')
    k='src/CUDA/Backends/CUDA_MD.cuh'
    for axis in 'xyz':
        edit(k,f'F.{axis} * (MD_dt[0] * (c_number) 0.5f)',f'F.{axis} * gold_inv_mass(IND) * (MD_dt[0] * (c_number) 0.5f)')
        edit(k,f'T.{axis} * (MD_dt[0] * (c_number) 0.5f)',f'T.{axis} * gold_inv_inertia(IND) * (MD_dt[0] * (c_number) 0.5f)')
        edit(k,f'F.{axis} * MD_dt[0] * (c_number) 0.5f',f'F.{axis} * gold_inv_mass(IND) * MD_dt[0] * (c_number) 0.5f')
        edit(k,f'T.{axis} * MD_dt[0] * (c_number) 0.5f',f'T.{axis} * gold_inv_inertia(IND) * MD_dt[0] * (c_number) 0.5f')
    edit(k,'v.w = (v.x*v.x + v.y*v.y + v.z*v.z) * (c_number) 0.5f;','v.w = (v.x*v.x + v.y*v.y + v.z*v.z) * (c_number) 0.5f / gold_inv_mass(IND);')
    edit(k,'L.w = (L.x*L.x + L.y*L.y + L.z*L.z) * (c_number) 0.5f;','L.w = (L.x*L.x + L.y*L.y + L.z*L.z) * (c_number) 0.5f / gold_inv_inertia(IND);')
    k='src/CUDA/Thermostats/CUDALangevinThermostat.cu'
    edit(k,'#include <curand_kernel.h>','#include <curand_kernel.h>\n#include "../cuda_utils/gold_dynamics.cuh"')
    edit(k,'LangevinThermostat::get_settings(inp);','LangevinThermostat::get_settings(inp);\n    gold_dynamics_settings(inp);')
    edit(k,'\t\t//Could define operators for GPU_quat','''
        if(gd_count && IND>=gd_start) {
            GoldCore core=gd_cores[IND-gd_start];
            // DNA Langevin noise amplitude = sqrt(2*T*gamma/dt).
            c_number temp=rescale_factor_trans*rescale_factor_trans*_dt/(2*gamma_trans);
            c_number at=exp(-_dt*temp/(core.mass*core.diffusion));
            c_number ar=exp(-_dt*temp/(core.inertia*core.rotation_diffusion));
            c_number st=sqrt(temp/core.mass*(1-at*at)), sr=sqrt(temp/core.inertia*(1-ar*ar));
            v.x=at*v.x+st*f_vx; v.y=at*v.y+st*f_vy; v.z=at*v.z+st*f_vz;
            L.x=ar*L.x+sr*f_Lx; L.y=ar*L.y+sr*f_Ly; L.z=ar*L.z+sr*f_Lz;
            v.w=0.5f*core.mass*(v.x*v.x+v.y*v.y+v.z*v.z);
            L.w=0.5f*core.inertia*(L.x*L.x+L.y*L.y+L.z*L.z);
            vels[IND]=v; Ls[IND]=L; return;
        }
        //Could define operators for GPU_quat''')
    for name,text in changes.items(): (root/name).write_text(text)
    here=Path(__file__).parent
    for filename,target in [('MobileGold.h','src/Interactions'),('mobile_gold.cuh','src/CUDA/Interactions'),('gold_dynamics.cuh','src/CUDA/cuda_utils')]:
        (root/target/filename).write_text((here/filename).read_text())

if __name__=='__main__': patch(sys.argv[1])
