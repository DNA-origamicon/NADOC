// NADOC fixed-cell EW3DC, repulsive walls and harmonic anchors on CUDA.
// No atomic coordinate or force transfers to the host in ordinary dynamics.
#include "CudaGlobalMasterClient.h"
#include "Molecule.h"
#include "SimParameters.h"
#include <cuda_runtime.h>
#include <fstream>
#include <numeric>
#include <stdexcept>
#include <cmath>
#include <iomanip>

namespace {
constexpr int BLOCK=256;
struct Param { double q,x,y,z,k; int mobile; };
__device__ double sumBlock(double v) {
#ifdef NADOC_WARP_REDUCTION
  __shared__ double values[32];int lane=threadIdx.x%32,warp=threadIdx.x/32;
  for(int s=16;s;s/=2)v+=__shfl_down_sync(0xffffffff,v,s);
  if(lane==0)values[warp]=v;__syncthreads();
  if(warp==0){v=lane<BLOCK/32?values[lane]:0;for(int s=16;s;s/=2)v+=__shfl_down_sync(0xffffffff,v,s);}
  if(threadIdx.x==0)values[0]=v;__syncthreads();double result=values[0];__syncthreads();return result;
#else
  __shared__ double values[BLOCK]; values[threadIdx.x]=v; __syncthreads();
  for(int s=BLOCK/2;s;s/=2) { if(threadIdx.x<s)values[threadIdx.x]+=values[threadIdx.x+s]; __syncthreads(); }
  double result=values[0];__syncthreads();return result;
#endif
}
__global__ void dipole(int n,int axis,const double* x,const Param* p,double* partial) {
  int i=blockIdx.x*BLOCK+threadIdx.x;
  double v=sumBlock(i<n?p[i].q*x[axis*n+i]:0.);
  if(!threadIdx.x)partial[blockIdx.x]=v;
}
__global__ void reduce(int n,const double* input,double* output) {
  double v=0;for(int i=threadIdx.x;i<n;i+=BLOCK)v+=input[i];
  v=sumBlock(v);if(!threadIdx.x)*output=v;
}
__global__ void correction(int n,int axis,double c,double low,double high,double wall,
 const double* x,const Param* p,const double* moment,double* force,double* energy,int npartial) {
#ifdef NADOC_FUSED
  double m=0;for(int j=threadIdx.x;j<npartial;j+=BLOCK)m+=moment[j];m=sumBlock(m);
#else
  double m=*moment;
#endif
  int i=blockIdx.x*BLOCK+threadIdx.x;double e=0;
  if(i<n) {
    double z=x[axis*n+i];double d=p[i].mobile?(z<low?z-low:z>high?z-high:0):0;
    for(int j=0;j<3;j++) {
      double ref=j==0?p[i].x:j==1?p[i].y:p[i].z;
      double delta=p[i].k?x[j*n+i]-ref:0;
      force[j*n+i]=-p[i].k*delta-(j==axis?(2*c*p[i].q*m+wall*d):0);
      e+=.5*p[i].k*delta*delta;
    }
    e+=.5*wall*d*d;if(i==0)e+=c*m*m;
  }
  e=sumBlock(e);if(!threadIdx.x)energy[blockIdx.x]=e;
}
void check(cudaError_t e) { if(e!=cudaSuccess)throw std::runtime_error(cudaGetErrorString(e)); }
template<class T> void alloc(T*& p,size_t n){check(cudaMalloc((void**)&p,n*sizeof(T)));}

class Electrode final:public CudaGlobalMaster::CudaGlobalMasterClient {
 int n=0,axis=0,blocks=0;double c=0,low=0,high=0,wall=0;
 cudaStream_t stream{}; std::vector<AtomID> ids,empty;
 double *pos=nullptr,*force=nullptr,*partial=nullptr,*moment=nullptr,*energies=nullptr,*total=nullptr;
 Param *params=nullptr;
 public:
 void initialize(const std::vector<std::string>& a,int device,cudaStream_t s) override {
  CudaGlobalMasterClient::initialize(a,device,s);stream=s;check(cudaSetDevice(device));
  if(a.size()!=3)throw std::runtime_error("NADOC GPU: expected parameter file");
  auto sim=getSimParameters();
  if(!sim->CUDASOAintegrate || sim->langevinPistonOn || sim->berendsenPressureOn || sim->monteCarloPressureOn || sim->multigratorOn)throw std::runtime_error("NADOC GPU: fixed-cell resident mode required");
  std::ifstream f(a[2]);f>>n>>axis>>c>>low>>high>>wall;
  if(!f || !std::isfinite(c) || !std::isfinite(low) || !std::isfinite(high) || !std::isfinite(wall) || n!=getMolecule()->numAtoms || axis<0 || axis>2 || !(c>0) || !(high>low) || !(wall>=0))throw std::runtime_error("NADOC GPU: invalid system parameters");
  std::vector<Param> p(n);double charge=0;
  for(auto& v:p){f>>v.q>>v.mobile>>v.x>>v.y>>v.z>>v.k;charge+=v.q;
   if(!f || !std::isfinite(v.q+v.x+v.y+v.z+v.k) || v.k<0 || (v.mobile!=0&&v.mobile!=1))throw std::runtime_error("NADOC GPU: invalid atom parameters");}
  if(std::abs(charge)>1e-5)throw std::runtime_error("NADOC GPU: neutral cell required");
  ids.resize(n);std::iota(ids.begin(),ids.end(),0);blocks=(n+BLOCK-1)/BLOCK;
  alloc(pos,3*n);alloc(force,3*n);alloc(params,n);alloc(partial,blocks);alloc(moment,1);alloc(energies,blocks);alloc(total,1);
  check(cudaMemcpy(params,p.data(),n*sizeof(Param),cudaMemcpyHostToDevice));
 }
 ~Electrode() override {cudaSetDevice(m_device_id);cudaFree(pos);cudaFree(force);cudaFree(params);cudaFree(partial);cudaFree(moment);cudaFree(energies);cudaFree(total);}
 void calculate() override {
  dipole<<<blocks,BLOCK,0,stream>>>(n,axis,pos,params,partial);
#ifdef NADOC_FUSED
  correction<<<blocks,BLOCK,0,stream>>>(n,axis,c,low,high,wall,pos,params,partial,force,energies,blocks);
#else
  reduce<<<1,BLOCK,0,stream>>>(blocks,partial,moment);
  correction<<<blocks,BLOCK,0,stream>>>(n,axis,c,low,high,wall,pos,params,moment,force,energies,blocks);
#endif
  check(cudaGetLastError());
 }
 int updateFromTCLCommand(const std::vector<std::string>& a) override {
  if(a.size()!=3 || a[1]!="audit")return 1;
  std::vector<double> x(3*n),f(3*n);
  check(cudaMemcpyAsync(x.data(),pos,3*n*sizeof(double),cudaMemcpyDeviceToHost,stream));
  check(cudaMemcpyAsync(f.data(),force,3*n*sizeof(double),cudaMemcpyDeviceToHost,stream));
  check(cudaStreamSynchronize(stream));std::ofstream out(a[2]);out<<std::setprecision(17)<<getEnergy()<<'\n';
  for(int i=0;i<n;i++){for(int j=0;j<3;j++)out<<x[j*n+i]<<' ';for(int j=0;j<3;j++)out<<f[j*n+i]<<' ';out<<'\n';}
  return out?0:1;
 }
 bool requestedAtomsChanged() override{return false;}
 bool requestedTotalForcesAtomsChanged() override{return false;}
 bool requestedForcedAtomsChanged() override{return false;}
 bool requestUpdateAtomPositions() override{return true;}
 bool requestUpdateAtomTotalForces() override{return false;}
 bool requestUpdateForcedAtoms() override{return true;}
 bool requestUpdateMasses() override{return false;}
 bool requestUpdateCharges() override{return false;}
 bool requestUpdateLattice() override{return false;}
 double* getPositions() override{return pos;}
 double* getAppliedForces() const override{return force;}
 float* getMasses() override{return nullptr;}
 float* getCharges() override{return nullptr;}
 double* getTotalForces() override{return nullptr;}
 double* getLattice() override{return nullptr;}
 const std::vector<AtomID>& getRequestedAtoms() const override{return ids;}
 const std::vector<AtomID>& getRequestedForcedAtoms() const override{return ids;}
 const std::vector<AtomID>& getRequestedTotalForcesAtoms() const override{return empty;}
 protected:
 cudaStream_t getStream() override{return stream;}
 bool useDefaultExtForceAndVirial() const override{return false;} // fixed cell; matches existing correction's no-virial contract
 double getEnergy() const override {
  reduce<<<1,BLOCK,0,stream>>>(blocks,energies,total);double e;
  check(cudaMemcpyAsync(&e,total,sizeof(e),cudaMemcpyDeviceToHost,stream));check(cudaStreamSynchronize(stream));return e;
 }
};
}
extern "C" CudaGlobalMaster::CudaGlobalMasterClient* allocator(){return new Electrode;}
extern "C" void deleter(CudaGlobalMaster::CudaGlobalMasterClient* p){delete p;}
