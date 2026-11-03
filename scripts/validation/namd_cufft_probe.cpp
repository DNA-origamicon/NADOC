// Compile with the SAME static cuFFT archive used by the qualified NAMD build.
// Plan with workspace auto-allocation disabled: no grid or workspace is allocated.
#include <cufft.h>
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
static void check(cufftResult r) {if(r!=CUFFT_SUCCESS){fprintf(stderr,"cuFFT error %d\n",r);exit(2);}}
int main(int argc,char** argv) {
  if(argc!=5)return 2;
  int x=atoi(argv[1]),y=atoi(argv[2]),z=atoi(argv[3]),dev=atoi(argv[4]);
  if(x<1||y<1||z<1||cudaSetDevice(dev)!=cudaSuccess)return 2;
  size_t sizes[2]={0,0};cufftHandle plans[2];
  for(int i=0;i<2;i++) {
    check(cufftCreate(&plans[i]));check(cufftSetAutoAllocation(plans[i],0));
    check(cufftMakePlan3d(plans[i],z,y,x,i?CUFFT_C2R:CUFFT_R2C,&sizes[i]));
    check(cufftGetSize(plans[i],&sizes[i]));
  }
  int version=0;check(cufftGetVersion(&version));cudaDeviceProp p;
  if(cudaGetDeviceProperties(&p,dev)!=cudaSuccess)return 2;
  printf("{\"grid\":[%d,%d,%d],\"forward_bytes\":%zu,\"backward_bytes\":%zu,\"cufft_version\":%d,\"texture_alignment\":%zu,\"device\":\"%s\"}\n",x,y,z,sizes[0],sizes[1],version,p.textureAlignment,p.name);
  check(cufftDestroy(plans[0]));check(cufftDestroy(plans[1]));return 0;
}
