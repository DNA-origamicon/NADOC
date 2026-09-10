// Included after CUDA_DNA.cuh: adds only angle/torsion contributions.
__global__ void chudoba_manybody(const c_number4 *pos,c_number4 *forces,
        const LR_bonds *bonds,bool update_st,CUDAStressTensor *stress) {
    if(IND>=MD_N[0] || get_particle_btype(pos[IND])!=500) return;
    using R=c_number;
    using V=chudoba::Vec<R>;
    c_number4 total=make_c_number4(0,0,0,0);
    CUDAStressTensor st;
    int start=IND;
    // Each thread gathers its own force; no atomics or shared write races.
    for(int back=0;back<4 && start!=P_INVALID;back++,start=bonds[start].n5) {
        int ids[4]={start,P_INVALID,P_INVALID,P_INVALID},count=1;
        for(int j=1;j<4;j++) {
            ids[j]=bonds[ids[j-1]].n3;
            if(ids[j]==P_INVALID) break;
            count++;
        }
        V u[3],f[4];
        for(int j=0;j<count-1;j++) {
            auto r=pos[ids[j+1]]-pos[ids[j]];
            u[j]=V(r.x*R(.8518),r.y*R(.8518),r.z*R(.8518));
        }
        for(int n=3;n<=count;n++) {
            if(back>=n) continue;
            R e=n==3 ? chudoba::angle(u[0],u[1],f) : chudoba::torsion(u[0],u[1],u[2],f);
            V g=f[back]*R(.8518/24.943387854);
            total.x+=g.x;total.y+=g.y;total.z+=g.z;
            total.w+=R(2)*e/R(n*24.943387854);
            if(update_st && back) {
                auto r=pos[IND]-pos[start];
                // CUDA helper uses -r*force; many-body virial is +r_i*f_i.
                auto minus_f=make_c_number4(-g.x,-g.y,-g.z,0);
                _update_stress_tensor<false>(st,r,minus_f);
            }
        }
    }
    forces[IND]+=total;
    if(update_st) stress[IND]+=st;
}
