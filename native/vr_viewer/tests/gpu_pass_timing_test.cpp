#include "gpu_pass_timing.hpp"
#include <cassert>
#include <iostream>
#include <vector>
struct FakeQueries {
    int bits=64;unsigned apiCalls=0,resultReads=0,timestampCalls=0,releases=0;
    bool allReady=false;std::array<bool,16> ready{};std::array<uint64_t,16> values{};
    int counterBits(){++apiCalls;return bits;}
    void allocate(size_t n,GLuint* ids){++apiCalls;for(size_t i=0;i<n;++i)ids[i]=GLuint(i+1);}
    void release(size_t,const GLuint*){++apiCalls;++releases;}
    void timestamp(GLuint id){++apiCalls;values[id]=++timestampCalls*10;ready[id]=false;}
    bool available(GLuint id){++apiCalls;return allReady || ready[id];}
    uint64_t result(GLuint id){assert(allReady || ready[id]);++apiCalls;++resultReads;return values[id];}
};
using Ring=nadoc_vr::GpuPassTimingRing<FakeQueries,2>;
void saved(const nadoc_vr::GpuPassSample& value,void* context){static_cast<std::vector<nadoc_vr::GpuPassSample>*>(context)->push_back(value);}
void failed(const nadoc_vr::GpuPassSample&,void*){throw std::runtime_error("deliberate sink failure");}
void frame(Ring& ring,uint64_t id,bool rightFirst=false) {
    ring.begin(id,false,123,257,1,1000+id);ring.afterShadow(true);ring.afterEye(rightFirst?1:0);ring.afterEye(rightFirst?0:1);ring.end();
}
int main() {
    assert(!nadoc_vr::gpuPassTimingRequested(""));assert(!nadoc_vr::gpuPassTimingRequested("0"));assert(nadoc_vr::gpuPassTimingRequested("1"));
    bool rejected=false;try{nadoc_vr::gpuPassTimingRequested("yes");}catch(const std::runtime_error&){rejected=true;}assert(rejected);
    FakeQueries offApi;Ring off(offApi);off.initialize(false);frame(off,1);off.collect(100);off.shutdown();assert(offApi.apiCalls==0);
    FakeQueries api;std::vector<nadoc_vr::GpuPassSample> samples;Ring ring(api,saved,&samples);ring.initialize(true);
    frame(ring,1);frame(ring,2,true);frame(ring,3);assert(ring.ringSkipped()==1 && ring.pending()==2 && api.resultReads==0 && api.timestampCalls==8);
    api.ready[1]=true;api.ready[2]=true;api.ready[4]=true;ring.collect(3000);assert(api.resultReads==0); // All four must be ready.
    for(unsigned i=1;i<=8;++i)api.ready[i]=true;
    api.values[1]=100;api.values[2]=130;api.values[3]=180;api.values[4]=250;
    api.values[5]=1000;api.values[6]=1007;api.values[7]=1030;api.values[8]=1050;
    ring.collect(4000);assert(ring.completed()==2 && ring.pending()==0 && samples.size()==2 && api.resultReads==8);
    assert(samples[0].valid && samples[0].frame==1 && samples[0].shadowNs==30 && samples[0].leftNs==50 && samples[0].rightNs==70 && samples[0].totalNs==150);
    assert(samples[1].valid && samples[1].eyeOrder[0]==1 && samples[1].leftNs==20 && samples[1].rightNs==23 && samples[1].totalNs==50);
    assert(samples[0].hostCollectedNs==4000 && samples[0].viewToolsVersion==123 && samples[0].viewToolsFlags==257);
    ring.begin(4,true,7,3,2,5000);ring.afterShadow(false,true);ring.afterEye(0);ring.afterEye(1);ring.end();api.allReady=true;ring.collect(6000);
    assert(ring.last().valid && ring.last().shadowScope==0 && ring.last().motionDetailReduced && ring.last().menuOpen);
    api.allReady=false;ring.begin(5,false,0,0,1,7000);ring.afterShadow(true);ring.afterEye(0);ring.afterEye(0);ring.end();api.allReady=true;ring.collect(8000);
    assert(!ring.last().valid && std::string(ring.last().reason)=="invalid_boundary_order" && ring.invalid()==1);
    api.allReady=false;ring.begin(6,false,0,0,1,9000);ring.end();api.allReady=true;ring.collect(10000);
    assert(!ring.last().valid && std::string(ring.last().reason)=="incomplete_boundaries" && ring.invalid()==2);
    api.allReady=false;ring.begin(7,false,0,0,1,11000);ring.begin(8,false,0,0,1,12000);ring.afterShadow(true);ring.afterEye(1);ring.afterEye(0);ring.end();
    assert(ring.pending()==2);const auto beforeReads=api.resultReads;ring.shutdown();assert(api.resultReads==beforeReads && api.releases==1);
    assert(ring.json().find("\"shutdown_unobserved_frames\":2")!=std::string::npos);
    FakeQueries unsupportedApi;unsupportedApi.bits=0;Ring unsupported(unsupportedApi);unsupported.initialize(true);frame(unsupported,1);assert(unsupportedApi.timestampCalls==0 && unsupportedApi.resultReads==0);
    assert(unsupported.json().find("\"unsupported_frames\":1")!=std::string::npos);unsupported.shutdown();
    FakeQueries sinkApi;Ring sink(sinkApi,failed);sink.initialize(true);frame(sink,1);sinkApi.allReady=true;sink.collect(100);assert(sink.sinkFailures()==1 && sink.completed()==1);sink.shutdown();
    nadoc_vr::GpuPassSample discontinuity;discontinuity.issued=4;discontinuity.eyeOrder={0,1};discontinuity.timestamps={100,90,110,120};
    const auto invalid=nadoc_vr::resolveGpuPassSample(discontinuity,false);assert(!invalid.valid && std::string(invalid.reason)=="timestamp_discontinuity_or_wrap");
    std::cout<<"GPU pass ring: disabled no calls, no unavailable reads, bounded skips, eye order, incomplete/overflow/fallback accounting passed\n";
}
