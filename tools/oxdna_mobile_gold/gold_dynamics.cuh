#pragma once
#include "../../Interactions/MobileGold.h"
// Private per translation-unit constants, populated from the same immutable model file.
static __constant__ GoldCore gd_cores[64];
static __constant__ int gd_start, gd_count;
static void gold_dynamics_settings(input_file &inp) {
    std::string type; getInputString(&inp,"interaction_type",type,0);
    int n=0,start=0,device=0;
    getInputInt(&inp,"CUDA_device",&device,0);
    CUDA_SAFE_CALL(cudaSetDevice(device));
    if(type=="DNA2GOLD") {
        std::string path; getInputString(&inp,"gold_file",path,1);
        GoldModel model; model.load(path); n=model.cores.size(); start=model.dna_count;
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(gd_cores,model.cores.data(),n*sizeof(GoldCore)));
    }
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(gd_start,&start,sizeof(int)));
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(gd_count,&n,sizeof(int)));
}
static __device__ float gold_inv_mass(int i) { return gd_count && i>=gd_start ? 1.f/gd_cores[i-gd_start].mass:1.f; }
static __device__ float gold_inv_inertia(int i) { return gd_count && i>=gd_start ? 1.f/gd_cores[i-gd_start].inertia:1.f; }
