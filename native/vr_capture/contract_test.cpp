// Fault-injection contract tests use fake downstream Vulkan entry points. They
// deliberately exercise failures a healthy live driver cannot reproduce safely.
#include <atomic>
#include <cstdlib>
#include <new>
static std::atomic<bool> failAllocation{false};
__attribute__((noinline)) void* operator new(std::size_t n) { if(failAllocation.exchange(false)) throw std::bad_alloc(); void* p=std::malloc(n); if(!p) throw std::bad_alloc(); return p; }
__attribute__((noinline)) void operator delete(void* p) noexcept { std::free(p); }
__attribute__((noinline)) void operator delete(void* p,std::size_t) noexcept { std::free(p); }
#include "present_capture.cpp"
#include <cassert>
#include <sys/wait.h>
// Contract checks must execute even when the layer is built in Release mode.
#undef assert
#define assert(condition) do { if(!(condition)) throw std::runtime_error(#condition); } while(0)

namespace {
int submits=0,presents=0,counters=0;
bool holdRegistryInWait=false,holdTelemetryInWait=false;
bool endDetailsInPresent=false,endDetailsInWait=false;
int archiveOpen=0,archiveLive=0,archivePeak=0,archiveWrite=0,archiveSync=0,archiveClose=0;
bool archiveFailSync=false,archiveFailClose=false,archiveFailDirectory=false;
uint64_t injectedAvailable=0;
int archiveOpenFlags=0;
int fakeArchiveOpen(const char*,int flags,mode_t) { archiveOpenFlags=flags; archivePeak=std::max(archivePeak,++archiveLive); return ++archiveOpen; }
ssize_t fakeArchiveWrite(int,const void*,size_t bytes) { if(++archiveWrite==1) { errno=EINTR; return -1; } return ssize_t(std::min<size_t>(7,bytes)); }
int fakeArchiveSync(int) { if(++archiveSync==1) { errno=EINTR; return -1; } if(archiveFailSync) { errno=ENOSPC; return -1; } return 0; }
int fakeArchiveDirectory(int) { if(archiveFailDirectory) { errno=EIO; return -1; } return 0; }
int fakeArchiveClose(int) { archiveClose++; archiveLive--; if(archiveFailClose) { errno=EIO; return -1; } return 0; }
std::vector<unsigned char> copiedOracle,copiedOutput;
size_t copiedLimit=SIZE_MAX,copiedCalls=0,copiedMaximum=0;
ssize_t copyAwareWrite(int,const void* data,size_t bytes) {
  copiedMaximum=std::max(copiedMaximum,bytes);
  if(++copiedCalls==1) { errno=EINTR; return -1; }
  if(copiedOutput.size()>=copiedLimit) { errno=ENOSPC; return -1; }
  const size_t amount=std::min({bytes,size_t(4096-13),copiedLimit-copiedOutput.size()});
  const auto* first=static_cast<const unsigned char*>(data);
  assert(std::equal(first,first+amount,copiedOracle.begin()+copiedOutput.size()));
  copiedOutput.insert(copiedOutput.end(),first,first+amount);
  return ssize_t(amount);
}
int directFailure=0,directTruncates=0;
int fakeDirectAlignment(int,uint32_t* memory,uint32_t* offset) {
  if(directFailure==4) { errno=EOPNOTSUPP; return -1; }
  *memory=directFailure==6?3:512; *offset=512; return 0;
}
int fakeDirectTruncate(int,off_t length) {
  if(++directTruncates==1) { errno=EINTR; return -1; }
  if(directFailure==3) { errno=EIO; return -1; }
  assert(size_t(length)==copiedOracle.size());
  copiedOutput.resize(size_t(length)); return 0;
}
ssize_t fakeDirectWrite(int,const void* data,size_t bytes) {
  assert(reinterpret_cast<uintptr_t>(data)%512==0 && bytes%512==0 && bytes<=4096);
  copiedMaximum=std::max(copiedMaximum,bytes);
  if(++copiedCalls==1) { errno=EINTR; return -1; }
  if(directFailure==2 && copiedOutput.size()>=4096) { errno=ENOSPC; return -1; }
  const size_t amount=directFailure==1?137:std::min(bytes,size_t(1024));
  const auto* first=static_cast<const unsigned char*>(data);
  for(size_t n=0;n<amount;n++) {
    const size_t offset=copiedOutput.size()+n;
    assert(first[n]==(offset<copiedOracle.size()?copiedOracle[offset]:0));
  }
  copiedOutput.insert(copiedOutput.end(),first,first+amount); return ssize_t(amount);
}
VkResult nextPresent=VK_SUCCESS;
const void* expectedNext=nullptr;
VkResult* expectedResults=nullptr;
std::vector<VkSemaphore> presentedWaits, submittedWaits;
VKAPI_ATTR VkResult VKAPI_CALL fakeReset(VkDevice,uint32_t,const VkFence*) { return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL fakeSubmit(VkQueue,uint32_t n,const VkSubmitInfo* s,VkFence) {
  assert(n==1); submits++; submittedWaits.assign(s->pWaitSemaphores,s->pWaitSemaphores+s->waitSemaphoreCount); return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL fakePresent(VkQueue,const VkPresentInfoKHR* p) {
  presents++; assert(p->pNext==expectedNext); assert(p->pResults==expectedResults);
  presentedWaits.assign(p->pWaitSemaphores,p->pWaitSemaphores+p->waitSemaphoreCount);
  if(p->pResults) p->pResults[0]=nextPresent;
  if(endDetailsInPresent) { global().detailedActive=false; global().detailedUntil=0; }
  return nextPresent;
}
VKAPI_ATTR VkResult VKAPI_CALL fakeAcquire(VkDevice,VkSwapchainKHR,uint64_t,VkSemaphore,VkFence,uint32_t*) { return VK_TIMEOUT; }
VKAPI_ATTR VkResult VKAPI_CALL fakeWait(VkDevice,VkSwapchainKHR,uint64_t,uint64_t) {
  if(holdRegistryInWait) global().mapMutex.lock();
  if(holdTelemetryInWait) global().waitMutex.lock();
  if(endDetailsInWait) { global().detailedActive=false; global().detailedUntil=0; }
  return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL fakeCounter(VkDevice,VkSwapchainKHR,VkSurfaceCounterFlagBitsEXT,uint64_t* out) { counters++; *out=91; return VK_SUCCESS; }
}
int main(int argc,char** argv) {
  assert(argc==2); // CTest supplies an isolated artifact directory in the build.
  nadoc_capture::ArchiveOps archiveOps;
  archiveOps.openFile=fakeArchiveOpen; archiveOps.writeFile=fakeArchiveWrite;
  archiveOps.syncData=fakeArchiveSync; archiveOps.syncDirectory=fakeArchiveDirectory; archiveOps.closeFile=fakeArchiveClose;
  const std::array<char,31> payload{};
  int reports=0;
  {
    nadoc_capture::ArchiveBatch batch(archiveOps);
    for(size_t n=0;n<batch.capacity;n++) batch.append("test",payload.data(),payload.size(),n);
    assert(reports==0 && archiveSync==0 && archiveLive==16 && archivePeak==16);
    bool bounded=false;
    try { batch.append("overflow",payload.data(),payload.size(),99); } catch(const std::out_of_range&) { bounded=true; }
    assert(bounded && batch.size()==16);
    batch.flush([&](size_t,const nadoc_capture::ArchiveResult& r){ reports++; assert(r.success() && r.synced && r.closed); });
    assert(reports==16 && archiveLive==0 && archiveClose==16 && archiveSync==17);
  }
  // EINTR and short writes were retried; fsync failure and close failure must
  // remain explicit failures, and close is never retried after an error.
  for(int failure=0;failure<2;failure++) {
    archiveFailSync=failure==0; archiveFailClose=failure==1;
    const int beforeClose=archiveClose;
    nadoc_capture::ArchiveBatch batch(archiveOps); batch.append("failed",payload.data(),payload.size(),0);
    batch.flush([&](size_t,const nadoc_capture::ArchiveResult& r){ assert(!r.success()); assert(std::string(r.stage)==(failure?"close":"fdatasync")); assert(r.error==(failure?EIO:ENOSPC)); });
    assert(archiveLive==0 && archiveClose==beforeClose+1);
  }
  archiveFailSync=false; archiveFailClose=false; archiveFailDirectory=true;
  auto directoryResult=nadoc_capture::syncArchiveDirectory(archiveOps,"test");
  assert(!directoryResult.success() && directoryResult.closed && directoryResult.error==EIO && archiveLive==0);
  archiveFailDirectory=false;
  assert(nadoc_capture::syncArchiveDirectory(archiveOps,"test").success());
  assert(nadoc_capture::memoryHeadroom(500,300,200));
  assert(!nadoc_capture::memoryHeadroom(499,300,200));
  assert(!nadoc_capture::memoryHeadroom(0,0,200));
  assert(!nadoc_capture::memoryHeadroom(500,UINT64_MAX,200));
  // Duration scaling is conservative and restores the exact configured cap at
  // five seconds. Very short recordings retain a bounded minimum, not zero.
  constexpr size_t configured=960ULL*1024*1024;
  assert(nadoc_capture::recordingSpoolBytes(configured,2000000000)==384ULL*1024*1024);
  assert(nadoc_capture::recordingSpoolBytes(configured,1000000000)==192ULL*1024*1024);
  assert(nadoc_capture::recordingSpoolBytes(configured,50000000)==16ULL*1024*1024);
  assert(nadoc_capture::recordingSpoolBytes(configured,1)==16ULL*1024*1024);
  for(uint64_t duration:std::array<uint64_t,3>{5000000000ULL,10000000000ULL,UINT64_MAX}) assert(nadoc_capture::recordingSpoolBytes(configured,duration)==configured);
  assert(nadoc_capture::recordingSpoolBytes(configured-17,5000000000)==configured-17);
  assert(nadoc_capture::recordingSpoolBytes(65536,2000000000)==65536);
  assert(nadoc_capture::recordingSpoolBytes(configured,0)==0);
  assert(nadoc_capture::recordingSpoolBytes(SIZE_MAX,2000000000)==0);
  // More detailed scenes can need >1 GiB at five seconds. The enlarged public
  // bound must preserve short-window scaling and reject overflow inputs.
  constexpr size_t sceneCap=1280ULL*1024*1024;
  constexpr size_t maximumCap=2ULL*1024*1024*1024;
  assert(nadoc_capture::maximumSpoolBytes==maximumCap);
  assert(nadoc_capture::recordingSpoolBytes(sceneCap,2000000000)==512ULL*1024*1024);
  assert(nadoc_capture::recordingSpoolBytes(sceneCap,5000000000)==sceneCap);
  assert(nadoc_capture::recordingSpoolBytes(maximumCap,4999999999)==maximumCap);
  assert(nadoc_capture::recordingSpoolBytes(maximumCap,UINT64_MAX)==maximumCap);
  assert(nadoc_capture::recordingSpoolBytes(maximumCap+1,2000000000)==0);
  assert(nadoc_capture::recordingSpoolBytes(maximumCap+1,5000000000)==0);
  const size_t maximumShort=nadoc_capture::recordingSpoolBytes(maximumCap,2000000000);
  assert(maximumShort<=maximumCap);
  assert(uint64_t(maximumShort)*5000000000ULL>=uint64_t(maximumCap)*2000000000ULL);

  const size_t fractional=nadoc_capture::recordingSpoolBytes(configured,1234567890);
  assert(fractional%size_t(sysconf(_SC_PAGESIZE))==0);
  assert(uint64_t(fractional)*5000000000ULL>=uint64_t(configured)*1234567890ULL);
  // Concurrent reservations are disjoint, bounded and fully resident before
  // recording. Overflow consumes no out-of-range memory and cannot spill to IO.
  nadoc_capture::CompressedSpool spool;
  assert(spool.allocate(65536) && spool.resident());
  std::array<std::array<size_t,128>,2> offsets{};
  std::array<std::thread,2> writers;
  for(size_t worker=0;worker<writers.size();worker++) writers[worker]=std::thread([&,worker]{
    for(size_t n=0;n<128;n++) {
      size_t index=0,offset=0;
      assert(spool.reserve(128,index,offset)==nadoc_capture::CompressedSpool::Reservation::Success);
      offsets[worker][n]=offset; std::memset(spool.data()+offset,int(worker+1),128);
      spool.entries[index].frame.offset=offset; spool.entries[index].frame.size=128; spool.entries[index].ready=true;
    }
  });
  for(auto& thread:writers) thread.join();
  assert(spool.used()==32768 && spool.count()==256 && spool.completeLayout());
  std::vector<size_t> ordered;
  for(size_t worker=0;worker<2;worker++) for(auto offset:offsets[worker]) {
    ordered.push_back(offset);
    for(size_t n=0;n<128;n++) assert(spool.data()[offset+n]==worker+1);
  }
  std::sort(ordered.begin(),ordered.end());
  assert(std::adjacent_find(ordered.begin(),ordered.end())==ordered.end());
  size_t index=0,offset=0;
  assert(spool.reserve(65536,index,offset)==nadoc_capture::CompressedSpool::Reservation::BytesFull);
  assert(spool.used()==32768 && spool.completeLayout()); spool.reset();
  for(size_t n=0;n<spool.descriptorCapacity;n++) assert(spool.reserve(1,index,offset)==nadoc_capture::CompressedSpool::Reservation::Success);
  assert(spool.reserve(1,index,offset)==nadoc_capture::CompressedSpool::Reservation::DescriptorsFull);
  assert(!spool.completeLayout()); // Reserved bytes without published frames cannot be packed.
  spool.reset(); assert(spool.used()==0 && spool.count()==0);
  // The writer must hand off byte-exact data before releasing source pages.
  // The independent oracle is retained outside the discarded anonymous map.
  // Short writes cross page boundaries; EINTR consumes nothing; a partial tail
  // remains intact until its last byte is copied. Failed output is never saved.
  for(int failure=0;failure<3;failure++) {
    nadoc_capture::CompressedSpool handoff;
    assert(handoff.allocate(65536));
    const size_t payloadBytes=5*4096+137;
    assert(handoff.reserve(payloadBytes,index,offset)==nadoc_capture::CompressedSpool::Reservation::Success);
    copiedOracle.resize(payloadBytes);
    for(size_t n=0;n<payloadBytes;n++) copiedOracle[n]=static_cast<unsigned char>((n*37+19)%251);
    std::memcpy(handoff.data(),copiedOracle.data(),payloadBytes);
    handoff.entries[index].frame.offset=0; handoff.entries[index].frame.size=payloadBytes; handoff.entries[index].ready=true;
    assert(handoff.completeLayout() && handoff.discardUnusedTail());
    assert(handoff.discardedTail()==65536-6*4096);
    assert(!handoff.discardCopiedPrefix(payloadBytes+1) && errno==EINVAL);
    assert(std::memcmp(handoff.data(),copiedOracle.data(),payloadBytes)==0);
    copiedOutput.clear(); copiedCalls=0; copiedMaximum=0;
    copiedLimit=failure==1?size_t(4096+99):SIZE_MAX;
    auto copyOps=archiveOps; copyOps.writeFile=copyAwareWrite;
    archiveFailSync=failure==2;
    nadoc_capture::ArchiveWritePolicy policy; policy.chunkBytes=4096; policy.bytesPerSecond=80*1024*1024; policy.context=&handoff;
    policy.consumed=[](void* context,size_t copied){
      auto& h=*static_cast<nadoc_capture::CompressedSpool*>(context);
      assert(copied==copiedOutput.size());
      const bool result=h.discardCopiedPrefix(copied);
      assert(h.discardedPrefix()==copied/4096*4096);
      assert(std::memcmp(h.data()+copied,copiedOracle.data()+copied,copiedOracle.size()-copied)==0);
      return result;
    };
    nadoc_capture::ArchiveBatch batch(copyOps);
    batch.append("handoff",handoff.data(),payloadBytes,0,policy);
    batch.flush([&](size_t,const nadoc_capture::ArchiveResult& result){
      assert(result.success()==(failure==0));
      assert(result.writtenBytes==copiedOutput.size());
      assert(result.maxWriteBytes<=4096 && copiedMaximum<=4096);
      if(failure) assert(result.error==ENOSPC && std::string(result.stage)==(failure==1?"write":"fdatasync"));
      else assert(result.pacingNs>0);
    });
    assert(copiedOutput==std::vector<unsigned char>(copiedOracle.begin(),copiedOracle.begin()+copiedOutput.size()));
    assert(copiedOutput.size()==(failure==1?copiedLimit:payloadBytes));
    assert(handoff.completeLayout()); // Metadata survives payload consumption.
    unsigned char resident=1;
    assert(mincore(handoff.data(),4096,&resident)==0 && !(resident&1));
  }
  archiveFailSync=false;
  // Direct IO never falls back to buffered writes. Partial successful writes
  // preserve BOTH address and file-offset alignment. Padding is discarded only
  // by successful exact-length truncate, before durable sync can be claimed.
  for(directFailure=0;directFailure<8;directFailure++) {
    nadoc_capture::CompressedSpool handoff; assert(handoff.allocate(65536) && handoff.noFork());
    const size_t payloadBytes=4*4096+137;
    assert(handoff.reserve(payloadBytes,index,offset)==nadoc_capture::CompressedSpool::Reservation::Success);
    copiedOracle.resize(payloadBytes);
    for(size_t n=0;n<payloadBytes;n++) copiedOracle[n]=static_cast<unsigned char>((n*13+11)%251);
    std::memcpy(handoff.data(),copiedOracle.data(),payloadBytes);
    copiedOutput.clear(); copiedCalls=0; copiedMaximum=0; directTruncates=0;
    auto directOps=archiveOps; directOps.directAlignment=fakeDirectAlignment; directOps.truncateFile=fakeDirectTruncate; directOps.writeFile=fakeDirectWrite;
    nadoc_capture::ArchiveWritePolicy policy; policy.direct=true; policy.sourceDontFork=directFailure!=5; policy.chunkBytes=4096; policy.context=&handoff;
    policy.consumed=[](void* context,size_t consumed){return static_cast<nadoc_capture::CompressedSpool*>(context)->discardCopiedPrefix(consumed);};
    const int beforeOpen=archiveOpen;
    archiveFailSync=directFailure==7;
    nadoc_capture::ArchiveBatch batch(directOps);
    batch.append("direct",handoff.data(),payloadBytes,0,policy);
    batch.flush([&](size_t,const nadoc_capture::ArchiveResult& result){
      assert(result.direct && result.success()==(directFailure==0));
      assert(archiveOpen==beforeOpen+1 && (archiveOpenFlags&O_DIRECT));
      if(directFailure==0 || directFailure==7) {
        assert(result.truncated && result.paddingBytes==375 && result.writtenBytes==payloadBytes);
        assert(result.physicalWrittenBytes==payloadBytes+375 && copiedOutput==copiedOracle);
      }
      else assert(!result.synced);
      if(directFailure==1) assert(std::string(result.stage)=="direct_short_write_alignment" && copiedCalls==2);
      if(directFailure==2) assert(std::string(result.stage)=="direct_write" && result.error==ENOSPC);
      if(directFailure==3) assert(std::string(result.stage)=="direct_truncate" && !result.truncated);
      if(directFailure==4) assert(std::string(result.stage)=="direct_alignment_query" && copiedCalls==0);
      if(directFailure==5) assert(std::string(result.stage)=="direct_source_fork_policy" && copiedCalls==0);
      if(directFailure==6) assert(std::string(result.stage)=="direct_alignment" && copiedCalls==0);
      if(directFailure==7) assert(std::string(result.stage)=="fdatasync" && result.error==ENOSPC);
    });
    if(directFailure==0) {
      // This is a dedicated mapping: a concurrent process fork must not inherit
      // the direct-IO source, as required by Linux's private-buffer contract.
      const pid_t child=fork(); assert(child>=0);
      if(child==0) { unsigned char resident=0; errno=0; _exit(mincore(handoff.data(),4096,&resident)<0 && errno==ENOMEM?0:3); }
      int status=0; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    }
  }
  archiveFailSync=false;
  // PI activation is explicit and its fallback is inspectable. A busy lock
  // must admit a nonblocking failure without ownership or scheduler changes.
  PriorityMutex mutex;
  assert(mutex.priorityInheritance()==(mutex.initializationError()==0));
  std::atomic<bool> locked{false},release{false};
  std::thread holder([&]{ mutex.lock(); locked=true; while(!release.load()) std::this_thread::yield(); mutex.unlock(); });
  while(!locked.load()) std::this_thread::yield();
  assert(!mutex.try_lock()); release=true; holder.join();
  assert(mutex.try_lock()); mutex.unlock();
  // Route evidence is strictly allowlisted; plausible path prefix attacks and
  // unrelated fdinfo values must never appear in persisted diagnostics.
  for(const char* target:{"/dev/nvidia0","/dev/nvidiactl","/dev/nvidia-modeset","/dev/nvidia-uvm","/dev/nvidia-caps/nvidia-cap2","/dev/dri/card0","/dev/dri/renderD128","anon_inode:[sync_file]","anon_inode:dmabuf"}) assert(nadoc_capture::allowedFdTarget(target));
  for(const char* target:{"/home/user/private","/dev/nvidia0/private","/dev/nvidia-not-a-device","/dev/dri/renderD128.bak","/dev/dri/by-path/private","anon_inode:[eventpoll]","socket:[42]"}) assert(!nadoc_capture::allowedFdTarget(target));
  const auto filteredInfo=nadoc_capture::selectedFdInfo("pos:\t123\ndrm-driver:\tnvidia\ndrm-client-id:\t42\ndrm-pdev:\t0000:01:00.0\nprivate-path:\t/home/user/private\nlease-id:\t9\n");
  assert(filteredInfo=="{\"drm-driver\":\"nvidia\",\"drm-client-id\":\"42\",\"drm-pdev\":\"0000:01:00.0\",\"lease-id\":\"9\"}");
  // Lossless codec roundtrip with incompressible bytes, independently decoded
  // through each library's public decompression ABI. Worker context is reused.
  std::vector<unsigned char> source(16384),decoded(source.size()); uint32_t random=123;
  for(auto& byte:source) { random^=random<<13; random^=random>>17; random^=random<<5; byte=random&255; }
  for(const char* selected:{"zstd","zlib"}) {
    nadoc_capture::LosslessCodec codec(selected); nadoc_capture::LosslessCodec::Worker encoder(codec);
    for(int iteration=0;iteration<2;iteration++) {
      source[0]^=127; size_t size=encoder.compress(source.data(),source.size());
      if(std::string(codec.name())=="zstd") {
        void* lib=dlopen("libzstd.so.1",RTLD_NOW|RTLD_LOCAL); assert(lib);
        auto decode=reinterpret_cast<size_t(*)(void*,size_t,const void*,size_t)>(dlsym(lib,"ZSTD_decompress")); assert(decode);
        assert(decode(decoded.data(),decoded.size(),encoder.buffer.data(),size)==source.size()); dlclose(lib);
      } else {
        uLongf n=decoded.size(); assert(uncompress(decoded.data(),&n,encoder.buffer.data(),size)==Z_OK); assert(n==source.size());
      }
      assert(decoded==source);
    }
  }
  // The global starts disabled, with no background threads or output files.
  unsetenv("NADOC_VR_CAPTURE_DIR"); unsetenv("NADOC_VR_CAPTURE_TEST_SURFACES");
  auto& g=global(); assert(!g.enabled); g.enabled=true; g.beginDetails(); g.pixels=true; g.until=nowNs()+10000000000ULL; g.request=7;
  int dispatch=1; struct Handle { void* dispatch; } dh{&dispatch},qh{&dispatch},unknown{&dispatch};
  VkDevice dev=reinterpret_cast<VkDevice>(&dh); VkQueue queue=reinterpret_cast<VkQueue>(&qh);
  auto d=std::make_shared<Device>(); d->handle=dev; d->ResetFences=fakeReset; d->QueueSubmit=fakeSubmit; d->QueuePresentKHR=fakePresent; d->AcquireNextImageKHR=fakeAcquire; d->WaitForPresentKHR=fakeWait; d->GetSwapchainCounterEXT=fakeCounter;
  d->families.resize(1); d->families[0].queueFlags=VK_QUEUE_GRAPHICS_BIT;
  g.devices[id(dev)]=d; g.queues[id(queue)]={d,0,0};
  auto s=std::make_shared<Swapchain>(); s->handle=reinterpret_cast<VkSwapchainKHR>(100); s->serial=1; s->direct=true; s->transfer=true; s->prepared=true; s->family=0; s->counter=true;
  auto slot=std::make_unique<Slot>(); slot->generation=1; slot->done=reinterpret_cast<VkSemaphore>(200); slot->fence=reinterpret_cast<VkFence>(201); slot->command=reinterpret_cast<VkCommandBuffer>(202); s->slots.emplace_back(std::move(slot)); g.swaps[id(s->handle)]=s;
  uint32_t imageIndex=0; VkSemaphore appWait=reinterpret_cast<VkSemaphore>(300); uint64_t presentId=43;
  VkPresentIdKHR ids{VK_STRUCTURE_TYPE_PRESENT_ID_KHR}; ids.swapchainCount=1; ids.pPresentIds=&presentId;
  VkResult perSwap=VK_SUCCESS; VkPresentInfoKHR info{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR}; info.pNext=&ids; info.waitSemaphoreCount=1; info.pWaitSemaphores=&appWait; info.swapchainCount=1; info.pSwapchains=&s->handle; info.pImageIndices=&imageIndex; info.pResults=&perSwap;
  expectedNext=&ids; expectedResults=&perSwap;

  // A failed present after successful copy must keep the synthetic semaphore:
  // the original application semaphore was already consumed by our copy.
  nextPresent=VK_ERROR_OUT_OF_HOST_MEMORY;
  assert(vkQueuePresentKHR(queue,&info)==VK_ERROR_OUT_OF_HOST_MEMORY);
  assert(submits==1 && presents==1 && submittedWaits==std::vector<VkSemaphore>{appWait});
  assert(presentedWaits==std::vector<VkSemaphore>{s->slots[0]->done});
  assert(s->slots[0]->retryPresent && perSwap==VK_ERROR_OUT_OF_HOST_MEMORY);
  assert(counters==0); // Counter cannot be queried before a processed present.
  // An allocation failure during retry must leave both the bridge semaphore
  // and application waits untouched, so a subsequent retry remains possible.
  failAllocation=true;
  assert(vkQueuePresentKHR(queue,&info)==VK_ERROR_OUT_OF_HOST_MEMORY);
  assert(presents==1 && submits==1 && s->slots[0]->retryPresent);
  g.enabled=true; g.until=nowNs()+10000000000ULL;
  nextPresent=VK_SUCCESS;
  assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS);
  assert(submits==1 && presents==2); // No second wait on the consumed app semaphore.
  assert(presentedWaits==std::vector<VkSemaphore>{s->slots[0]->done});
  assert(!s->slots[0]->retryPresent && info.pWaitSemaphores==&appWait && info.pNext==&ids);

  // Failed image acquisition must not interpret the caller's output index.
  uint32_t untouched=0xfefefefe;
  assert(vkAcquireNextImageKHR(dev,s->handle,0,appWait,VK_NULL_HANDLE,&untouched)==VK_TIMEOUT);
  assert(untouched==0xfefefefe && s->slots[0]->generation==1);

  // Successful existing application wait provides the prerequisite for counters.
  assert(vkWaitForPresentKHR(dev,s->handle,43,0)==VK_SUCCESS);
  assert(s->presentCompleted && counters==1);
  assert(g.waitCount==1 && g.waitRecords[0].registryComplete);
  assert(g.waitRecords[0].vblankValid && g.waitRecords[0].vblank==91);
  assert(g.waitRecords[0].exitSample>=g.waitRecords[0].sampleEnd);

  // Holding the post-driver registry lock cannot delay the runtime return or
  // invent a counter observation. Queue insertion performs no C++ allocation.
  holdRegistryInWait=true; failAllocation=true;
  assert(vkWaitForPresentKHR(dev,s->handle,44,0)==VK_SUCCESS);
  assert(failAllocation.exchange(false));
  g.mapMutex.unlock(); holdRegistryInWait=false;
  assert(g.waitMetadataSkipped==1 && g.waitCount==2 && counters==1);
  assert(!g.waitRecords[1].registryComplete && !g.waitRecords[1].vblankValid);
  assert(g.waitRecords[1].swapchain==0 && g.waitRecords[1].result==VK_SUCCESS);

  // Contention/full telemetry queues lose only an explicitly counted record;
  // they do not block or alter the Vulkan wait's result.
  const auto beforeDrops=g.droppedEvents.load();
  holdTelemetryInWait=true;
  assert(vkWaitForPresentKHR(dev,s->handle,45,0)==VK_SUCCESS);
  g.waitMutex.unlock(); holdTelemetryInWait=false;
  assert(g.waitCount==2 && g.waitRecordDrops==1 && g.droppedEvents==beforeDrops+1);
  g.waitCount=g.waitRecords.size();
  assert(vkWaitForPresentKHR(dev,s->handle,46,0)==VK_SUCCESS);
  assert(g.waitRecordDrops==2 && g.droppedEvents==beforeDrops+2);
  g.waitCount=2;

  // A legitimate queue obtained along an untracked route still forwards by its
  // dispatch table, without injecting copy work or inventing an application error.
  g.until=0;
  assert(vkQueuePresentKHR(reinterpret_cast<VkQueue>(&unknown),&info)==VK_SUCCESS);
  assert(submits==1 && presentedWaits==std::vector<VkSemaphore>{appWait});
  assert(g.activeHooks==0);
  // Neither metadata-only nor disabled capture may consume/replace app waits.
  g.until=nowNs()+10000000000ULL; g.pixels=false;
  assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS);
  assert(submits==1 && presentedWaits==std::vector<VkSemaphore>{appWait});
  g.pixels=true; g.enabled=false;
  assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS);
  assert(submits==1 && presentedWaits==std::vector<VkSemaphore>{appWait});
  assert(!vkGetDeviceProcAddr(dev,"vkGetDeviceQueue2"));
  assert(!vkGetDeviceProcAddr(dev,"vkAcquireNextImage2KHR"));
  assert(vkGetDeviceProcAddr(dev,"vkWaitForPresentKHR"));
  // Idle record suppression must preserve downstream calls, successful-present
  // bookkeeping and every counter query, without adding false drop counts.
  g.enabled=true; g.pixels=false; g.until=0; g.detailedActive=false; g.detailedUntil=0;
  const auto idleEvents=g.eventsCount,idleWaits=g.waitCount;
  const auto drops=g.droppedEvents.load(),waitDrops=g.waitRecordDrops.load();
  const int beforePresents=presents,beforeCounters=counters;
  for(int n=0;n<1000;n++) {
    assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS);
    assert(vkWaitForPresentKHR(dev,s->handle,presentId,1000)==VK_SUCCESS);
  }
  assert(g.eventsCount==idleEvents && g.waitCount==idleWaits);
  assert(presents==beforePresents+1000 && counters==beforeCounters+2000 && s->presentCompleted);
  assert(g.idlePresentSuppressed>=1000 && g.idleWaitSuppressed>=1000);
  assert(g.droppedEvents==drops && g.waitRecordDrops==waitDrops);
  // First detailed present and the final in-flight present survive boundary
  // changes. A late successful wait keeps the decision captured at entry.
  g.beginDetails();
  assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS && g.eventsCount==idleEvents+1);
  endDetailsInPresent=true;
  assert(vkQueuePresentKHR(queue,&info)==VK_SUCCESS && g.eventsCount==idleEvents+2);
  endDetailsInPresent=false;
  g.beginDetails(); endDetailsInWait=true;
  assert(vkWaitForPresentKHR(dev,s->handle,presentId,1000)==VK_SUCCESS && g.waitCount==idleWaits+1);
  endDetailsInWait=false;
  assert(vkWaitForPresentKHR(dev,s->handle,presentId,1000)==VK_SUCCESS && g.waitCount==idleWaits+1);
  nextPresent=VK_ERROR_OUT_OF_DATE_KHR;
  assert(vkQueuePresentKHR(queue,&info)==VK_ERROR_OUT_OF_DATE_KHR && g.eventsCount==idleEvents+3);
  nextPresent=VK_SUCCESS;
  g.endDetails(); const uint64_t tail=g.detailedUntil;
  assert(g.detailedRecords(tail-1) && !g.detailedRecords(tail)); g.detailedUntil=0;
  const auto heartbeatEvents=g.eventsCount; g.lastHeartbeat=100;
  g.heartbeat(Global::heartbeatNs+99); assert(g.eventsCount==heartbeatEvents);
  g.heartbeat(Global::heartbeatNs+100); assert(g.eventsCount==heartbeatEvents+1);
  g.heartbeat(2*Global::heartbeatNs+99); assert(g.eventsCount==heartbeatEvents+1);
  g.heartbeat(2*Global::heartbeatNs+100); assert(g.eventsCount==heartbeatEvents+2);
  g.pixels=true; g.beginDetails();
  // Exercise the actual compression->RAM->Archive pipeline. Compression must
  // create no file or saved count; only the separately invoked drain may do so.
  const auto artifacts=std::filesystem::path(argv[1])/std::to_string(getpid());
  std::filesystem::create_directories(artifacts); g.directory=artifacts.string();
  // Real Archive-filesystem O_DIRECT proof: multiple 1 MiB chunks plus a
  // partial final aligned block must round-trip exactly, without extra bytes.
  {
    nadoc_capture::CompressedSpool handoff; const size_t bytes=2*1024*1024+137;
    assert(handoff.allocate(3*1024*1024));
    assert(handoff.reserve(bytes,index,offset)==nadoc_capture::CompressedSpool::Reservation::Success);
    std::vector<unsigned char> expected(bytes); uint32_t random=92381;
    for(auto& byte:expected) { random^=random<<13; random^=random>>17; random^=random<<5; byte=random&255; }
    std::memcpy(handoff.data(),expected.data(),bytes);
    nadoc_capture::ArchiveOps directOps;
    nadoc_capture::ArchiveWritePolicy policy; policy.direct=true; policy.sourceDontFork=handoff.noFork(); policy.chunkBytes=1024*1024; policy.bytesPerSecond=32*1024*1024; policy.context=&handoff;
    policy.consumed=[](void* context,size_t consumed){return static_cast<nadoc_capture::CompressedSpool*>(context)->discardCopiedPrefix(consumed);};
    const auto path=artifacts/"direct-io-oracle.bin";
    nadoc_capture::ArchiveBatch batch(directOps); batch.append(path.c_str(),handoff.data(),bytes,0,policy);
    batch.flush([&](size_t,const nadoc_capture::ArchiveResult& result){assert(result.success() && result.direct && result.truncated && result.writtenBytes==bytes && result.maxWriteBytes<=1024*1024);});
    assert(nadoc_capture::syncArchiveDirectory(directOps,artifacts.c_str()).success());
    assert(std::filesystem::file_size(path)==bytes);
    std::ifstream input(path,std::ios::binary); std::vector<unsigned char> actual((std::istreambuf_iterator<char>(input)),{});
    assert(actual==expected && handoff.discardedPrefix()==2*1024*1024);
  }
  g.enabled=true; g.stop=true; g.saved=0; g.frameDrops=0; g.spooledFrames=0;
  assert(g.spool.allocate(65536));
  g.encoders[0]=std::make_unique<nadoc_capture::LosslessCodec::Worker>(g.codec);
  auto raw=std::make_unique<Frame>(); raw->bytes.assign(128,0x7b); raw->size=128;
  raw->present=99; raw->request=7; raw->swapchain=1; raw->width=8; raw->height=4; raw->format=VK_FORMAT_B8G8R8A8_UNORM; raw->queuedNs=nowNs();
  g.pendingFrames.emplace_back(std::move(raw)); g.compress(0);
  assert(g.spooledFrames==1 && g.saved==0 && g.frameDrops==0);
  assert(std::distance(std::filesystem::directory_iterator(artifacts),std::filesystem::directory_iterator{})==1); // Only the direct-IO oracle exists.
  const std::vector<unsigned char> compressedOracle(g.spool.data(),g.spool.data()+g.spool.used());
  g.allocatedBytes=128; g.frameCapacity=128;
  g.writerRequest=true; g.writerDone=false; g.writerStop=true; g.writeSpool();
  assert(g.saved==1 && g.writerDone && !g.writerBusy);
  assert(g.rawReleasedBeforeWrite==128 && g.allocatedBytes==0 && g.freeFrames.empty());
  const auto output=artifacts/("capture-"+std::to_string(getpid())+"-7.frames"+(std::string(g.codec.name())=="zstd"?".zst":".z"));
  std::ifstream savedFile(output,std::ios::binary);
  std::vector<char> persisted((std::istreambuf_iterator<char>(savedFile)),{});
  const auto& savedEntry=g.spool.entries[0].frame;
  assert(persisted.size()==savedEntry.size && std::memcmp(persisted.data(),compressedOracle.data()+savedEntry.offset,persisted.size())==0);
  // A failed output path is not counted as saved and never triggers a fallback.
  g.directory=(artifacts/"missing"/"directory").string(); g.writerRequest=true; g.writerDone=false; g.saved=0; g.frameDrops=0;
  g.writeSpool(); assert(g.saved==0 && g.frameDrops==1 && g.writerDone);
  assert(!std::filesystem::exists(g.directory));
  assert(!g.directorySynced && g.archiveErrors>=2);

  // Completion waits for every pipeline reference, releases the large capture
  // allocations before becoming reusable, and preserves spool counts in logs.
  g.directory=artifacts.string(); g.request=7; g.until=nowNs()-1;
  g.spoolSession=true; g.spoolSealed=true; g.writerRequest=false; g.writerBusy=false; g.writerDone=true;
  g.saved=1; g.frameDrops=0; g.activePresents=1; g.directorySynced=true; g.archiveErrors=0;
  g.pendingCopies=1; g.control(); assert(g.spool.capacity()!=0 && g.spoolSession);
  g.pendingCopies=0; g.finishRecording(); // Same finalization path used after a late writer join.
  assert(g.spool.capacity()==0 && g.allocatedBytes==0 && g.frameCapacity==0 && g.freeFrames.empty() && !g.spoolSession);
  bool completion=false;
  for(const auto& row:g.events) if(row.find("\"event\":\"capture_complete\"")!=std::string::npos) {
    assert(row.find("\"persistence_ok\":true")!=std::string::npos);
    assert(row.find("\"released_compressed_bytes\":65536")!=std::string::npos); completion=true;
  }
  assert(completion);
  // Exercise the real preparation/arm state machine again, using a tiny pool
  // and injected headroom so this contract is independent of host memory load.
  g.availableMemory=[]()->uint64_t {return 4ULL*1024*1024*1024;};
  g.spoolBudget=65536; g.budget=65536; g.largestBytes=128;
  g.encoders[1]=std::make_unique<nadoc_capture::LosslessCodec::Worker>(g.codec);
  assert(g.prepareRecording(8,100000000));
  assert(g.preparingToken==8 && g.request==7 && g.spool.used()==0 && g.spool.count()==0 && g.frameCapacity==128);
  g.readyAt=nowNs()-1; g.control();
  assert(g.request==8 && g.preparingToken==0 && g.spoolSession && g.until>nowNs() && g.saved==0 && g.activePresents==0);
  g.until=0; g.releaseRecordingBuffers();
  // Run the actual preflight/prepare/arm/release/rearm path with selected
  // duration budgets. A one-byte shortage must reject without allocating;
  // the reduced threshold admits the short request while preserving reserve.
  g.spoolSession=false; g.preparingToken=0; g.writerDone=true; g.writerRequest=false; g.writerBusy=false;
  g.spoolBudget=64ULL*1024*1024;
  const size_t shortBudget=nadoc_capture::recordingSpoolBytes(g.spoolBudget,2000000000);
  const uint64_t extra=48*128+shortBudget+2*(128+8ULL*1024*1024)+Global::archiveChunkBytes;
  g.availableMemory=[]()->uint64_t{return injectedAvailable;};
  injectedAvailable=Global::memoryReserve+extra-1;
  assert(!g.prepareRecording(9,2000000000) && g.spool.capacity()==0 && g.allocatedBytes==0 && !g.detailedActive);
  ++injectedAvailable;
  assert(g.prepareRecording(9,2000000000) && g.spool.capacity()==shortBudget && g.preparingDuration==2000000000);
  assert(g.spool.capacity()<g.spoolBudget && g.spool.resident());
  g.readyAt=nowNs()-1; g.control();
  assert(g.request==9 && g.spool.capacity()==shortBudget && g.spoolSession);
  g.until=nowNs()-1; g.endedRequest=9; g.spoolSealed=true; g.activePresents=0; g.saved=0; g.frameDrops=0;
  g.finishRecording();
  assert(g.spool.capacity()==0 && !g.spoolSession);
  bool shortAccounting=false;
  for(const auto& row:g.events) if(row.find("\"event\":\"capture_complete\"")!=std::string::npos && row.find("\"request\":9,")!=std::string::npos) {
    assert(row.find("\"released_compressed_bytes\":"+std::to_string(shortBudget))!=std::string::npos); shortAccounting=true;
  }
  assert(shortAccounting);
  injectedAvailable=4ULL*1024*1024*1024;
  assert(g.prepareRecording(10,5000000000) && g.spool.capacity()==g.spoolBudget && g.preparingDuration==5000000000);
  g.preparingToken=0; g.releaseRecordingBuffers(); g.endDetails();
  std::puts("capture contract: bounded durable batches, sync/close failures, safe release/rearm, resident spool, memory rejection, PI mutex, nonblocking telemetry, lossless codecs and Vulkan call contracts passed");
}
