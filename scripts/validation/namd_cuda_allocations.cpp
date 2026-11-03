// Optional CUPTI allocation trace for an unchanged NAMD executable.
// Build against the locally installed CUPTI headers/library. Load only into
// the bounded diagnostic process, with NADOC_CUDA_TRACE pointing at its log.
// Requested live bytes exclude CUDA context/library internals and do not claim
// an exact driver-memory high-water mark. Async frees are API observations.
// Optional NADOC_CUDA_HOST_TRACE records pinned host allocations separately;
// these bytes must not be added to the device allocation total or to RSS.
#include <cupti_callbacks.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <execinfo.h>
#include <dlfcn.h>
#include <mutex>
#include <unordered_map>
#include <time.h>

static double seconds() { struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9; }

struct State {
  std::mutex lock;
  std::unordered_map<void*, size_t> allocations;
  std::unordered_map<void*, size_t> generations, pendingFrees;
  size_t live=0, peak=0, sequence=0;
  FILE* file=nullptr;
};
static State& state() { static State* s=new State; return *s; }
static State& hostState() { static State* s=new State; return *s; }
static CUpti_SubscriberHandle subscriber;

static void emit(State& s,const char* name,void* pointer,size_t bytes,bool allocation,
                 bool reused=false) {
  void* stack[24];int frames=allocation ? backtrace(stack,24) : 0;
  fprintf(s.file,"{\"sequence\":%zu,\"monotonic_s\":%.9f,\"api\":\"%s\",\"pointer\":\"%p\",\"bytes\":%zu,\"live_bytes\":%zu,\"peak_bytes\":%zu,\"stack\":[",
          ++s.sequence,seconds(),name,pointer,bytes,s.live,s.peak);
  for (int i=0;i<frames;++i) fprintf(s.file,"%s\"%p\"",i?",":"",stack[i]);
  fprintf(s.file,"],\"namd_offsets\":[");
  int emitted=0;
  for (int i=0;i<frames;++i) {
    Dl_info info;
    if (dladdr(stack[i],&info) && info.dli_fname && strstr(info.dli_fname,"namd3")) {
      fprintf(s.file,"%s\"0x%zx\"",emitted++?",":"",size_t(static_cast<char*>(stack[i])-static_cast<char*>(info.dli_fbase)));
    }
  }
  fprintf(s.file,"],\"release_observed_by_address_reuse\":%s}\n",reused?"true":"false");fflush(s.file);
}

static void CUPTIAPI callback(void*, CUpti_CallbackDomain domain,
                             CUpti_CallbackId, const void* data) {
  if (domain!=CUPTI_CB_DOMAIN_RUNTIME_API) return;
  const auto* cb=static_cast<const CUpti_CallbackData*>(data);
  const char* name=cb->functionName;
  const bool hostAllocation=!strcmp(name,"cudaMallocHost") || !strcmp(name,"cudaHostAlloc");
  const bool hostRelease=!strcmp(name,"cudaFreeHost");
  const bool allocation=!strcmp(name,"cudaMalloc") || !strcmp(name,"cudaMallocManaged") ||
                        !strcmp(name,"cudaMallocAsync") || !strcmp(name,"cudaMallocAsync_ptsz") || hostAllocation;
  const bool release=!strcmp(name,"cudaFree") || !strcmp(name,"cudaFreeAsync") || !strcmp(name,"cudaFreeAsync_ptsz") || hostRelease;
  if (!allocation && !release) return;
  // Common leading ABI fields of these stable CUDA runtime allocation APIs.
  struct Allocate { void** pointer; size_t bytes; };
  struct Release { void* pointer; };
  State& s=(hostAllocation || hostRelease) ? hostState() : state();
  std::lock_guard<std::mutex> guard(s.lock);
  if (!s.file) return;
  if (cb->callbackSite==CUPTI_API_ENTER) {
    if (release && cb->correlationData) {
      void* pointer=static_cast<const Release*>(cb->functionParams)->pointer;
      auto it=s.generations.find(pointer);
      *cb->correlationData=it==s.generations.end()?0:it->second;
      s.pendingFrees[pointer]=*cb->correlationData;
    }
    return;
  }
  if (!cb->functionReturnValue || *static_cast<const int*>(cb->functionReturnValue)!=0) return;
  if (allocation) {
    const auto* p=static_cast<const Allocate*>(cb->functionParams);
    void* pointer=*p->pointer;size_t bytes=p->bytes;
    auto old=s.allocations.find(pointer);
    if (old!=s.allocations.end()) {
      // Another thread can reuse an address before the old free's EXIT callback
      // acquires this lock. Successful reuse proves that allocation was freed.
      auto pending=s.pendingFrees.find(pointer);
      if (pending==s.pendingFrees.end() || pending->second!=s.generations[pointer]) {
        fprintf(s.file,"{\"trace_error\":\"unexplained live address reuse\"}\n");fflush(s.file);
      }
      const size_t oldBytes=old->second;
      s.live-=oldBytes;s.allocations.erase(old);s.pendingFrees.erase(pointer);
      emit(s,hostAllocation?"cudaFreeHost":"cudaFree",pointer,oldBytes,false,true);
    }
    s.allocations[pointer]=bytes;s.generations[pointer]=s.sequence+1;s.live+=bytes;
    if (s.live>s.peak) s.peak=s.live;
    emit(s,name,pointer,bytes,true);
  } else {
    void* pointer=static_cast<const Release*>(cb->functionParams)->pointer;
    auto it=s.allocations.find(pointer);
    const size_t generation=cb->correlationData?*cb->correlationData:0;
    // Do not free a NEW allocation that has already reused this address.
    if (it==s.allocations.end() || s.generations[pointer]!=generation) return;
    const size_t bytes=it->second;s.live-=bytes;s.allocations.erase(it);
    s.generations.erase(pointer);s.pendingFrees.erase(pointer);
    emit(s,name,pointer,bytes,false);
  }
}

__attribute__((constructor)) static void initialize() {
  const char* path=getenv("NADOC_CUDA_TRACE");
  const char* hostPath=getenv("NADOC_CUDA_HOST_TRACE");
  if (!path && !hostPath) return;
  if (path) state().file=fopen(path,"w");
  if (hostPath) hostState().file=fopen(hostPath,"w");
  if (!state().file && !hostState().file) return;
  const auto result=cuptiSubscribe(&subscriber,callback,nullptr);
  const auto enabled=result==CUPTI_SUCCESS ? cuptiEnableDomain(1,subscriber,CUPTI_CB_DOMAIN_RUNTIME_API) : result;
  for (State* s : {&state(), &hostState()}) {
    if (!s->file) continue;
    fprintf(s->file,"{\"event\":\"initialize\",\"monotonic_s\":%.9f,\"memory_kind\":\"%s\",\"subscribe\":%d,\"enable\":%d}\n",
            seconds(),s==&state()?"device":"host_pinned",int(result),int(enabled));fflush(s->file);
  }
}

__attribute__((destructor)) static void finish() {
  for (State* s : {&state(), &hostState()}) {
    std::lock_guard<std::mutex> guard(s->lock);
    if(s->file){fprintf(s->file,"{\"finished_monotonic_s\":%.9f,\"live_bytes\":%zu}\n",seconds(),s->live);fclose(s->file);s->file=nullptr;}
  }
}
