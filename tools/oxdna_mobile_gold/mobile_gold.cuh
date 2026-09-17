// Included in the DNA interaction TU after CUDA_DNA.cuh.
#include "../../Interactions/MobileGold.h"
__constant__ GoldCore gold_cores[64];
__constant__ GoldCoating gold_coating[256];
__constant__ int gold_coating_count;
__constant__ int gold_count, gold_dna_count;
__constant__ float gold_clearance, gold_exclusion_k;
__device__ c_number4 gold_world(c_number4 x, GPU_quat q) {
    c_number4 a,b,c; get_vectors_from_quat(q,a,b,c);
    return a*x.x+b*x.y+c*x.z;
}
__device__ c_number4 gold_body(c_number4 x, GPU_quat q) {
    c_number4 a,b,c; get_vectors_from_quat(q,a,b,c);
    return make_c_number4(CUDA_DOT(x,a),CUDA_DOT(x,b),CUDA_DOT(x,c),0);
}
// Parallel over DNA; direct O(N_DNA * N_core) checks avoid a diameter-sized DNA list.
// Only actual contacts and grafts perform atomic additions to the core.
__global__ void gold_dna_forces(c_number4 *pos, GPU_quat *q, c_number4 *f, c_number4 *t,
                                GoldGraft *grafts, CUDABox *box) {
    int i=IND; if(i>=gold_dna_count) return;
    c_number4 a,b,c; get_vectors_from_quat(q[i],a,b,c);
    c_number4 back=a*POS_MM_BACK1+b*POS_MM_BACK2;
    // POS_MM_BACK1 is negative in oxDNA2.
    c_number4 total=make_c_number4(0,0,0,0), torque=total;
    for(int j=0;j<gold_count;j++) {
        int ci=gold_cores[j].index;
        c_number4 delta=box->minimum_image(pos[ci],pos[i]);
        // CM exclusion proxy, with explicit calibrated clearance.
        c_number r=_module(delta), overlap=gold_cores[j].radius+gold_clearance-r;
        if(overlap>0) {
            c_number4 force=delta*(gold_exclusion_k*overlap/fmaxf(r,1.e-12f));
            c_number energy=0.5f*gold_exclusion_k*overlap*overlap;
            total+=force; total.w+=energy;
            LR_atomicAddXYZ(&f[ci],-force); atomicAdd(&f[ci].w,energy);
        }
    }
    for(int k=0;k<gold_coating_count;k++) {
        GoldCoating s=gold_coating[k]; int ci=gold_cores[s.core].index;
        c_number4 arm=gold_world(make_c_number4(s.x,s.y,s.z,0),q[ci]);
        c_number4 delta=box->minimum_image(pos[ci],pos[i])-arm;
        c_number r=_module(delta), overlap=s.radius+gold_clearance-r;
        if(overlap>0) {
            c_number4 force=delta*(gold_exclusion_k*overlap/fmaxf(r,1.e-12f));
            c_number energy=0.5f*gold_exclusion_k*overlap*overlap;
            total+=force; total.w+=energy;
            LR_atomicAddXYZ(&f[ci],-force); atomicAdd(&f[ci].w,energy);
            LR_atomicAddXYZ(&t[ci],gold_body(_cross(arm,-force),q[ci]));
        }
    }
    GoldGraft g=grafts[i];
    if(g.core>=0) {
        int ci=gold_cores[g.core].index;
        c_number4 arm=gold_world(make_c_number4(g.x,g.y,g.z,0),q[ci]);
        c_number4 delta=box->minimum_image(pos[ci],pos[i])+back-arm;
        c_number r=_module(delta), dr=r-g.length;
        c_number4 force=delta*(-g.k*dr/fmaxf(r,1.e-12f));
        c_number energy=0.5f*g.k*dr*dr;
        total+=force; total.w+=energy;
        torque+=_cross(back,force);
        LR_atomicAddXYZ(&f[ci],-force); atomicAdd(&f[ci].w,energy);
        c_number4 ct=gold_body(_cross(arm,-force),q[ci]);
        LR_atomicAddXYZ(&t[ci],ct);
    }
    f[i]+=total;
    t[i]+=gold_body(torque,q[i]);
}
// Pairwise contacts between rigid composite bodies (never within one coating).
__global__ void gold_core_forces(c_number4 *pos, GPU_quat *q, c_number4 *f, c_number4 *t, CUDABox *box) {
    int j=IND; if(j>=gold_count) return;
    int i=gold_cores[j].index;
    c_number4 total=make_c_number4(0,0,0,0), torque=total;
    for(int a=-1;a<gold_coating_count;a++) {
        if(a>=0 && gold_coating[a].core!=j) continue;
        c_number4 arm=make_c_number4(0,0,0,0);
        c_number radius=gold_cores[j].radius;
        if(a>=0) { auto s=gold_coating[a]; arm=gold_world(make_c_number4(s.x,s.y,s.z,0),q[i]); radius=s.radius; }
        for(int k=0;k<gold_count;k++) if(k!=j) {
            int ci=gold_cores[k].index;
            for(int b=-1;b<gold_coating_count;b++) {
                if(b>=0 && gold_coating[b].core!=k) continue;
                c_number4 other=make_c_number4(0,0,0,0);
                c_number rr=gold_cores[k].radius;
                if(b>=0) { auto s=gold_coating[b]; other=gold_world(make_c_number4(s.x,s.y,s.z,0),q[ci]); rr=s.radius; }
                c_number4 delta=box->minimum_image(pos[ci],pos[i])+arm-other;
                c_number r=_module(delta), overlap=radius+rr-r;
                if(overlap>0) {
                    c_number4 force=delta*(gold_exclusion_k*overlap/fmaxf(r,1.e-12f));
                    total+=force; total.w+=0.5f*gold_exclusion_k*overlap*overlap;
                    torque+=_cross(arm,force);
                }
            }
        }
    }
    f[i]+=total; t[i]+=gold_body(torque,q[i]);
}
