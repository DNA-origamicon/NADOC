// CPU-only regression: CUPTI callback ordering, without creating a CUDA context.
#include "namd_cuda_allocations.cpp"
#include <cassert>
#include <string>

static void allocate(const char* api,void* address,size_t size) {
  struct {void** pointer;size_t bytes;} args{&address,size};
  int success=0;uint64_t correlation=0;CUpti_CallbackData cb{};
  cb.functionName=api;cb.functionParams=&args;cb.functionReturnValue=&success;
  cb.correlationData=&correlation;cb.callbackSite=CUPTI_API_EXIT;
  callback(nullptr,CUPTI_CB_DOMAIN_RUNTIME_API,0,&cb);
}
static void release(const char* api,void* address,uint64_t& correlation,CUpti_ApiCallbackSite site) {
  struct {void* pointer;} args{address};int success=0;CUpti_CallbackData cb{};
  cb.functionName=api;cb.functionParams=&args;cb.functionReturnValue=&success;
  cb.correlationData=&correlation;cb.callbackSite=site;
  callback(nullptr,CUPTI_CB_DOMAIN_RUNTIME_API,0,&cb);
}
int main() {
  State& s=hostState();s.file=tmpfile();assert(s.file);
  void* address=reinterpret_cast<void*>(0x12340000);uint64_t old=0,current=0;
  allocate("cudaHostAlloc",address,128);
  release("cudaFreeHost",address,old,CUPTI_API_ENTER);
  allocate("cudaHostAlloc",address,256); // recycled before the old EXIT callback
  release("cudaFreeHost",address,old,CUPTI_API_EXIT);
  assert(s.live==256 && s.peak==256 && s.allocations.size()==1);
  release("cudaFreeHost",address,current,CUPTI_API_ENTER);
  release("cudaFreeHost",address,current,CUPTI_API_EXIT);
  assert(s.live==0 && s.allocations.empty() && s.sequence==4);
  rewind(s.file);char line[8192];std::string output;
  while(fgets(line,sizeof(line),s.file))output+=line;
  assert(output.find("trace_error")==std::string::npos);
  assert(output.find("release_observed_by_address_reuse\":true")!=std::string::npos);
  State& d=state();d.file=tmpfile();assert(d.file);
  allocate("cudaMalloc",address,512);
  assert(d.live==512 && s.live==0); // host/device accounting stays separate
  release("cudaFree",address,current,CUPTI_API_ENTER);
  release("cudaFree",address,current,CUPTI_API_EXIT);
  assert(d.live==0 && d.peak==512 && d.sequence==2);
  puts("PASS: reused host address, late free, device separation, ordinary free");
}
