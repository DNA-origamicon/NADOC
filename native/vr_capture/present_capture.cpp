// Process-local explicit Vulkan layer. No SteamVR files or global settings change.
// Pixels are the image queued to presentation, NOT proof of panel scanout.
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>
#include <zlib.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <unistd.h>
#include "lossless_codec.hpp"
#include "fd_route.hpp"
#include "priority_mutex.hpp"
#include "compressed_spool.hpp"
#include "archive_batch.hpp"

#define EXPORTED extern "C" __attribute__((visibility("default"))) VKAPI_ATTR
#define DEV_FUNCTIONS(X) \
 X(DestroyDevice) X(GetDeviceQueue) X(GetDeviceQueue2) X(CreateSwapchainKHR) \
 X(DestroySwapchainKHR) X(GetSwapchainImagesKHR) X(AcquireNextImageKHR) X(AcquireNextImage2KHR) \
 X(QueuePresentKHR) X(QueueSubmit) X(DeviceWaitIdle) X(CreateBuffer) X(DestroyBuffer) \
 X(GetBufferMemoryRequirements) X(AllocateMemory) X(FreeMemory) X(BindBufferMemory) \
 X(MapMemory) X(UnmapMemory) X(InvalidateMappedMemoryRanges) X(CreateFence) X(DestroyFence) \
 X(ResetFences) X(GetFenceStatus) X(CreateSemaphore) X(DestroySemaphore) \
 X(CreateCommandPool) X(DestroyCommandPool) X(AllocateCommandBuffers) X(BeginCommandBuffer) \
 X(EndCommandBuffer) X(CmdPipelineBarrier) X(CmdCopyImageToBuffer) X(CreateQueryPool) \
 X(DestroyQueryPool) X(CmdResetQueryPool) X(CmdWriteTimestamp) X(GetQueryPoolResults) \
 X(GetSwapchainCounterEXT) X(WaitForPresentKHR)

namespace {
using Clock = std::chrono::steady_clock;
using PriorityMutex = nadoc_capture::PriorityMutex;
uint64_t nowNs() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count(); }
template<class T> uint64_t id(T v) { return (uint64_t)v; }
const char* env(const char* key, const char* fallback="") { const char* v=std::getenv(key); return v?v:fallback; }
const VkBaseInStructure* chain(const void* p, VkStructureType t) {
  for (auto b=static_cast<const VkBaseInStructure*>(p); b; b=b->pNext) if(b->sType==t) return b;
  return nullptr;
}
std::string fields(std::initializer_list<std::pair<const char*,uint64_t>> xs) {
  std::ostringstream o; for(auto x:xs) o<<",\""<<x.first<<"\":"<<x.second; return o.str();
}
struct Instance {
  VkInstance handle{}; PFN_vkGetInstanceProcAddr gipa{};
  bool displayCounter=false;
  PFN_vkDestroyInstance destroy{};
  PFN_vkEnumeratePhysicalDevices enumerate{};
  PFN_vkEnumeratePhysicalDeviceGroups groups{};
  PFN_vkCreateDisplayPlaneSurfaceKHR displaySurface{};
  PFN_vkDestroySurfaceKHR destroySurface{};
  PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR surfaceCaps{};
  PFN_vkGetPhysicalDeviceSurfaceCapabilities2EXT surfaceCaps2{};
  PFN_vkGetPhysicalDeviceMemoryProperties memoryProps{};
  PFN_vkGetPhysicalDeviceQueueFamilyProperties queueProps{};
  PFN_vkGetPhysicalDeviceProperties properties{};
};
struct Device;
struct Slot {
  VkBuffer buffer{}; VkDeviceMemory memory{}; void* mapped{};
  bool coherent=false;
  VkSemaphore done{}; VkFence fence{}; VkCommandBuffer command{}; VkQueryPool query{};
  // 0 available, 1 GPU pending, 2 worker reading. Never overwrite an unread slot.
  std::atomic<int> state{0};
  std::atomic<uint64_t> generation{0};
  uint64_t capturedGeneration=0, present=0, request=0, submitNs=0;
  bool retryPresent=false;
  std::vector<VkSemaphore> consumedWaits;
};
struct Swapchain {
  VkSwapchainKHR handle{}; uint64_t serial=0; VkExtent2D extent{}; VkFormat format{};
  VkPresentModeKHR mode{}; bool direct=false, test=false, transfer=false, counter=false;
  VkImageUsageFlags usage{}; VkSharingMode sharing{}; std::vector<uint32_t> families;
  std::vector<VkImage> images; std::vector<std::unique_ptr<Slot>> slots;
  VkCommandPool pool{}; uint32_t family=UINT32_MAX, timestampBits=0; size_t bytes=0;
  std::atomic<bool> retired{false}, prepared{false}, disabled{false}, presentCompleted{false};
  std::mutex setup;
};
struct Device {
  VkDevice handle{}; VkPhysicalDevice physical{}; std::shared_ptr<Instance> instance;
  PFN_vkGetDeviceProcAddr gdpa{}; PFN_vkSetDeviceLoaderData setLoaderData{};
#define DECLARE(name) PFN_vk##name name{};
  DEV_FUNCTIONS(DECLARE)
#undef DECLARE
  VkPhysicalDeviceMemoryProperties memory{}; VkPhysicalDeviceProperties properties{};
  bool displayControl=false;
  std::vector<VkQueueFamilyProperties> families;
  std::vector<std::shared_ptr<Swapchain>> allSwaps;
  std::mutex lifetime; std::atomic<bool> alive{true};
};
struct Queue { std::shared_ptr<Device> device; uint32_t family; VkDeviceQueueCreateFlags flags; };
struct Frame { std::vector<unsigned char> bytes; uint64_t present=0,request=0,swapchain=0,queuedNs=0; uint32_t width=0,height=0; VkFormat format{}; size_t size=0; };
struct WaitRecord {
  uint64_t swapchain=0,presentId=0,entry=0,begin=0,returned=0,timeout=0;
  uint64_t deviceLookupBegin=0,deviceLockAcquired=0,deviceLookupEnd=0,registryBegin=0,registryAcquired=0,registryEnd=0;
  uint64_t sampleBegin=0,sampleEnd=0,vblank=0,enqueueBegin=0,enqueueAcquired=0,exitSample=0;
  bool registryComplete=false,vblankValid=false,retainAtEntry=false;
  VkResult result=VK_ERROR_UNKNOWN;
};
struct Global {
  PriorityMutex mapMutex;
  std::unordered_map<uint64_t,std::shared_ptr<Instance>> instances, physicals;
  std::unordered_map<uint64_t,std::shared_ptr<Device>> devices;
  std::unordered_map<uint64_t,Queue> queues;
  std::unordered_map<uint64_t,std::shared_ptr<Swapchain>> swaps;
  std::unordered_map<uint64_t,VkDisplaySurfaceCreateInfoKHR> surfaces;
  std::unordered_map<uint64_t,VkDisplayModeParametersKHR> modes;
  std::atomic<uint64_t> serial{0}, present{0}, request{0}, until{0}, droppedEvents{0};
  std::atomic<size_t> largestBytes{0};
  std::string directory; bool pixels=false, test=false; std::atomic<bool> enabled{false};
  PriorityMutex eventsMutex, waitMutex; std::mutex framesMutex;
  // Preallocated queue slots: producers never allocate while owning these locks.
  std::array<std::string,16384> events; size_t eventsFirst=0,eventsCount=0;
  std::array<WaitRecord,2048> waitRecords; size_t waitFirst=0,waitCount=0;
  std::atomic<uint64_t> waitMetadataSkipped{0},waitRecordDrops{0},pendingCopies{0};
  std::atomic<bool> cleanupPending{false};
  std::vector<std::shared_ptr<Device>> readbackDevices;
  std::vector<std::shared_ptr<Swapchain>> readbackSwaps;
  std::deque<std::unique_ptr<Frame>> freeFrames, pendingFrames;
  std::condition_variable frameReady; std::atomic<bool> stop{false};
  std::thread worker,spoolWriter; std::vector<std::thread> compressors;
  std::array<std::unique_ptr<nadoc_capture::LosslessCodec::Worker>,2> encoders;
  nadoc_capture::CompressedSpool spool;
  size_t spoolBudget=1024ULL*1024*1024;
  static constexpr uint64_t memoryReserve=2ULL*1024*1024*1024,settleNs=1000000000;
  std::mutex spoolMutex; std::condition_variable spoolReady;
  std::atomic<bool> writerStop{false},writerRequest{false},writerDone{true},writerBusy{false};
  std::atomic<uint64_t> spooledFrames{0},spoolOverflows{0},archiveErrors{0};
  std::atomic<bool> directorySynced{false};
  uint64_t rawReleasedBeforeWrite=0;
  static constexpr size_t archiveChunkBytes=1024*1024;
  static constexpr uint64_t archiveBytesPerSecond=32ULL*1024*1024;
  nadoc_capture::ArchiveOps archiveOps;
  uint64_t (*availableMemory)()=nadoc_capture::availableMemoryBytes;
  bool spoolSession=false,spoolSealed=false;
  uint64_t preparingToken=0,preparingDuration=0,readyAt=0,endedRequest=0,completedRequest=0;
  size_t budget=256ULL*1024*1024, allocatedBytes=0, frameCapacity=0;
  std::atomic<uint64_t> inCompression{0}, frameDrops{0}, saved{0};
  std::atomic<uint64_t> activePresents{0}, copiedFrames{0}, activeHooks{0};
  std::atomic<bool> fdSnapshotTaken{false};
  std::atomic<bool> detailedActive{false};
  std::atomic<uint64_t> detailedUntil{0},idlePresentSuppressed{0},idleWaitSuppressed{0};
  static constexpr uint64_t detailTailNs=2000000000,heartbeatNs=1000000000;
  uint64_t lastHeartbeat=0;
  nadoc_capture::LosslessCodec codec{env("NADOC_VR_CAPTURE_CODEC","zstd")};
  std::ofstream log;
  Global(); void event(const std::string& type,const std::string& tail="");
  bool detailedRecords(uint64_t now) const { return detailedActive.load() || now<detailedUntil.load(); }
  void beginDetails() { detailedActive=true; }
  void endDetails() { detailedUntil=nowNs()+detailTailNs; detailedActive=false; }
  void heartbeat(uint64_t);
  void enqueueWait(WaitRecord&) noexcept; void flushEvents();
  void run(); void compress(size_t); void writeSpool(); void readback(); void control();
  bool prepareRecording(uint64_t,uint64_t); size_t releaseRawBuffers(); void releaseRecordingBuffers(); bool pipelineIdle(); void finishRecording();
};
Global& global() { static Global* g=new Global; return *g; }
void destroyReadbackResources(Device&,Swapchain&);
Global::Global() {
  directory=env("NADOC_VR_CAPTURE_DIR"); pixels=std::string(env("NADOC_VR_CAPTURE_MODE","metadata"))=="pixels";
  test=std::string(env("NADOC_VR_CAPTURE_TEST_SURFACES"))=="1";
  std::ifstream proc("/proc/self/comm"); std::string process; std::getline(proc,process);
  enabled=!directory.empty() && directory[0]=='/' && std::string(env("NADOC_VR_CAPTURE_MODE","metadata"))!="off" && (process=="vrcompositor" || test);
  if(!enabled) return;
  detailedUntil=nowNs()+detailTailNs;
  try {
    std::filesystem::create_directories(directory);
    log.open(directory+"/events-"+std::to_string(getpid())+".jsonl",std::ios::app);
    if(!log) { enabled=false; return; }
    const auto b=std::strtoull(env("NADOC_VR_CAPTURE_MAX_BYTES","268435456"),nullptr,10);
    budget=std::clamp<size_t>(b,16ULL*1024*1024,512ULL*1024*1024);
    spoolBudget=std::clamp<size_t>(std::strtoull(env("NADOC_VR_CAPTURE_COMPRESSED_BYTES","1073741824"),nullptr,10),16ULL*1024*1024,nadoc_capture::maximumSpoolBytes);
    for(auto& encoder:encoders) encoder=std::make_unique<nadoc_capture::LosslessCodec::Worker>(codec);
    event("layer_start",fields({{"pid",uint64_t(getpid())},{"pixel_mode",pixels},{"test_surfaces",test},{"memory_budget",budget},{"compressed_spool_budget_bytes",spoolBudget},{"compressed_budget_full_duration_ns",5000000000ULL},{"preparation_settle_ns",settleNs},{"memory_reserve_bytes",memoryReserve},{"archive_pack_files_per_capture",1},{"archive_write_chunk_bytes",archiveChunkBytes},{"archive_direct_scratch_max_bytes",archiveChunkBytes},{"idle_heartbeat_ns",heartbeatNs},{"detail_tail_ns",detailTailNs},{"archive_max_bytes_per_second",archiveBytesPerSecond},{"registry_priority_inheritance",mapMutex.priorityInheritance()},{"registry_mutex_init_error",uint64_t(mapMutex.initializationError())},{"events_priority_inheritance",eventsMutex.priorityInheritance()},{"events_mutex_init_error",uint64_t(eventsMutex.initializationError())},{"wait_priority_inheritance",waitMutex.priorityInheritance()},{"wait_mutex_init_error",uint64_t(waitMutex.initializationError())}})+",\"duration_scaled_compressed_budget\":true,\"idle_detail_records\":false,\"archive_direct_io\":true,\"pixel_storage\":\"independent_frames_in_capture_pack\",\"persistence_scope\":\"pixel_files_and_directory\",\"durable_pixel_files\":true,\"deferred_pixel_writes\":true,\"deferred_metadata_during_capture\":true,\"capture_boundary\":\"queued_present_image\",\"physical_scanout_verified\":false,\"codec\":\""+codec.name()+"\",\"codec_version\":\""+codec.version()+"\",\"codec_level\":1");
    worker=std::thread([this]{ pthread_setname_np(pthread_self(),"nadoc-readback"); try { run(); } catch(...) { until=0; enabled=false; std::fputs("NADOC capture disabled: reader worker exception\n",stderr); } });
    for(int i=0;i<2;i++) compressors.emplace_back([this,i]{ pthread_setname_np(pthread_self(),i?"nadoc-codec-1":"nadoc-codec-0"); try { compress(size_t(i)); } catch(...) { until=0; enabled=false; std::fputs("NADOC capture disabled: compression worker exception\n",stderr); } });
    spoolWriter=std::thread([this]{ pthread_setname_np(pthread_self(),"nadoc-archive"); try { writeSpool(); } catch(...) { until=0; enabled=false; writerDone=true; std::fputs("NADOC capture disabled: archive worker exception\n",stderr); } });
  } catch(...) { enabled=false; }
}
void Global::event(const std::string& type,const std::string& tail) {
  if(!enabled) return;
  std::string s="{\"event\":\""+type+"\",\"host_ns\":"+std::to_string(nowNs())+tail+"}";
  std::lock_guard<PriorityMutex> l(eventsMutex);
  if(eventsCount==events.size()) { droppedEvents++; return; }
  events[(eventsFirst+eventsCount)%events.size()]=std::move(s); ++eventsCount;
}
void Global::enqueueWait(WaitRecord& record) noexcept {
  if(!enabled) return;
  // Retain a wait that entered during the detailed period even if its driver
  // call returns after the final tail. Completion/counter queries still ran.
  if(!record.retainAtEntry && !detailedRecords(nowNs()) && record.result==VK_SUCCESS) { idleWaitSuppressed++; return; }
  record.enqueueBegin=nowNs();
  if(!waitMutex.try_lock()) { droppedEvents++; waitRecordDrops++; return; }
  record.enqueueAcquired=nowNs();
  if(waitCount==waitRecords.size()) { waitMutex.unlock(); droppedEvents++; waitRecordDrops++; return; }
  auto& stored=waitRecords[(waitFirst+waitCount)%waitRecords.size()];
  stored=record; ++waitCount;
  // Last observation before releasing the queue lock and returning to caller.
  // The log explicitly excludes that small unlock/return tail from its bound.
  stored.exitSample=nowNs();
  waitMutex.unlock();
}
void Global::heartbeat(uint64_t now) {
  if(now-lastHeartbeat<heartbeatNs) return;
  lastHeartbeat=now;
  event("layer_heartbeat",fields({{"pid",uint64_t(getpid())},{"request",request.load()},{"idle_present_records_suppressed",idlePresentSuppressed.load()},{"idle_wait_records_suppressed",idleWaitSuppressed.load()}})+",\"detailed_records\":"+(detailedRecords(now)?"true":"false"));
}
void Global::flushEvents() {
  for(;;) {
    std::array<std::string,128> batch;
    std::array<WaitRecord,128> waits;
    size_t eventN=0,waitN=0;
    { std::lock_guard<PriorityMutex> l(eventsMutex);
      eventN=std::min(eventsCount,batch.size());
      for(size_t n=0;n<eventN;n++) batch[n].swap(events[(eventsFirst+n)%events.size()]);
      eventsFirst=(eventsFirst+eventN)%events.size(); eventsCount-=eventN;
    }
    { std::lock_guard<PriorityMutex> l(waitMutex);
      waitN=std::min(waitCount,waits.size());
      for(size_t n=0;n<waitN;n++) waits[n]=waitRecords[(waitFirst+n)%waitRecords.size()];
      waitFirst=(waitFirst+waitN)%waitRecords.size(); waitCount-=waitN;
    }
    for(size_t n=0;n<eventN;n++) log<<batch[n]<<'\n';
    for(size_t n=0;n<waitN;n++) {
      const auto& w=waits[n];
      log<<"{\"event\":\"wait_for_present\",\"host_ns\":"<<w.exitSample
         <<fields({{"swapchain",w.swapchain},{"present_id",w.presentId},{"entry_ns",w.entry},{"begin_ns",w.begin},{"return_ns",w.returned},{"timeout_ns",w.timeout},
                   {"device_lookup_begin_ns",w.deviceLookupBegin},{"device_lookup_end_ns",w.deviceLookupEnd},{"device_lookup_ns",w.deviceLookupEnd-w.deviceLookupBegin},
                   {"device_lock_acquired_ns",w.deviceLockAcquired},{"device_lock_wait_ns",w.deviceLockAcquired-w.deviceLookupBegin},{"device_lock_hold_ns",w.deviceLookupEnd-w.deviceLockAcquired},
                   {"registry_lookup_begin_ns",w.registryBegin},{"registry_lock_acquired_ns",w.registryAcquired},{"registry_lookup_end_ns",w.registryEnd},
                   {"registry_lock_wait_ns",(w.registryComplete?w.registryAcquired:w.registryEnd)-w.registryBegin},{"registry_lock_hold_ns",w.registryComplete?w.registryEnd-w.registryAcquired:0},
                   {"registry_lookup_complete",w.registryComplete},{"metadata_skipped",!w.registryComplete},{"vblank_sample",w.vblank},{"vblank_sample_valid",w.vblankValid},
                   {"vblank_sample_begin_ns",w.sampleBegin},{"vblank_sample_end_ns",w.sampleEnd},{"counter_query_ns",w.sampleEnd-w.sampleBegin},
                   {"event_enqueue_begin_ns",w.enqueueBegin},{"event_lock_acquired_ns",w.enqueueAcquired},{"event_lock_wait_ns",w.enqueueAcquired-w.enqueueBegin},
                   {"hook_exit_sample_ns",w.exitSample},{"hook_total_to_exit_sample_ns",w.exitSample-w.entry},{"post_driver_to_exit_sample_ns",w.exitSample-w.returned},
                   {"layer_host_through_exit_sample_ns",(w.begin-w.entry)+(w.exitSample-w.returned)}})
         <<",\"result\":"<<w.result<<",\"driver_reports_present_complete\":"<<(w.result==VK_SUCCESS?"true":"false")
         <<",\"exit_sample_excludes_unlock_and_return\":true}"<<'\n';
    }
    if(!eventN && !waitN) break;
  }
  log.flush();
}
std::shared_ptr<Device> device(VkDevice h) { auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); auto i=g.devices.find(id(h)); return i==g.devices.end()?nullptr:i->second; }
std::shared_ptr<Instance> instance(VkInstance h) { auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); auto i=g.instances.find(id(h)); return i==g.instances.end()?nullptr:i->second; }
bool Global::pipelineIdle() {
  if(pendingCopies.load() || inCompression.load() || activeHooks.load()) return false;
  std::lock_guard<std::mutex> l(framesMutex); return pendingFrames.empty();
}
size_t Global::releaseRawBuffers() {
  std::deque<std::unique_ptr<Frame>> released;
  size_t bytes=0;
  { std::lock_guard<std::mutex> l(framesMutex);
    released.swap(freeFrames); bytes=allocatedBytes; allocatedBytes=0; frameCapacity=0;
  }
  // Destruction may unmap hundreds of MiB: never hold a shared lock here.
  released.clear(); return bytes;
}
void Global::releaseRecordingBuffers() {
  spool.release(); releaseRawBuffers();
}
bool Global::prepareRecording(uint64_t token,uint64_t duration) {
  beginDetails();
  struct DetailPreparation {
    Global& owner; bool accepted=false;
    ~DetailPreparation() { if(!accepted) owner.endDetails(); }
  } details{*this};
  const uint64_t begin=nowNs();
  const size_t selectedBudget=pixels?nadoc_capture::recordingSpoolBytes(spoolBudget,duration):0;
  event("capture_preparing",fields({{"request",token},{"begin_ns",begin},{"requested_duration_ns",duration},{"configured_compressed_spool_budget_bytes",pixels?spoolBudget:0},{"selected_compressed_spool_budget_bytes",selectedBudget},{"compressed_spool_budget_bytes",selectedBudget},{"memory_reserve_bytes",memoryReserve}}));
  flushEvents(); // Acknowledge preparation before potentially expensive prefault.
  const size_t bytes=largestBytes.load();
  if(pixels && !bytes) { event("capture_rejected_no_prepared_surface",fields({{"request",token}})); return false; }
  const size_t desiredRaw=pixels?std::min<size_t>(48,budget/bytes)*bytes:0;
  // Account conservatively for new codec working/output buffers as well.
  const uint64_t extra=pixels?(frameCapacity==bytes?0:desiredRaw)+(spool.capacity()==selectedBudget?0:selectedBudget)+2*(bytes+8ULL*1024*1024)+archiveChunkBytes:0;
  const uint64_t before=availableMemory();
  if(pixels && !nadoc_capture::memoryHeadroom(before,extra,memoryReserve)) {
    event("capture_rejected_memory",fields({{"request",token},{"mem_available_bytes",before},{"additional_bytes",extra},{"selected_compressed_spool_budget_bytes",selectedBudget},{"reserve_bytes",memoryReserve}})); return false;
  }
  try {
    if(pixels) {
      if(bytes!=frameCapacity) {
        std::lock_guard<std::mutex> l(framesMutex);
        freeFrames.clear(); allocatedBytes=0; frameCapacity=bytes;
        for(size_t n=0;n<desiredRaw/bytes;n++) { auto frame=std::make_unique<Frame>(); frame->bytes.resize(bytes); freeFrames.emplace_back(std::move(frame)); allocatedBytes+=bytes; }
      }
      if(freeFrames.empty() || !selectedBudget || !spool.allocate(selectedBudget)) throw std::runtime_error("capture buffer allocation failed");
      const size_t page=size_t(sysconf(_SC_PAGESIZE));
      for(auto& frame:freeFrames) for(size_t offset=0;offset<frame->bytes.size();offset+=page) frame->bytes[offset]=0;
      // All pipeline workers are idle here. Warm their retained contexts and
      // maximum output buffers using an already resident raw frame.
      for(auto& encoder:encoders) {
        encoder->compress(freeFrames.front()->bytes.data(),bytes);
        for(size_t offset=0;offset<encoder->buffer.size();offset+=page) encoder->buffer[offset]=0;
      }
      if(!spool.resident()) throw std::runtime_error("compressed spool is not resident");
    }
  } catch(...) {
    releaseRecordingBuffers(); event("capture_rejected_preparation",fields({{"request",token}})); return false;
  }
  const uint64_t after=availableMemory();
  if(pixels && after<memoryReserve) {
    releaseRecordingBuffers(); event("capture_rejected_memory",fields({{"request",token},{"mem_available_bytes",after},{"selected_compressed_spool_budget_bytes",selectedBudget},{"reserve_bytes",memoryReserve}})); return false;
  }
  preparingToken=token; preparingDuration=duration; readyAt=nowNs()+settleNs;
  event("capture_buffers_ready",fields({{"request",token},{"preparation_begin_ns",begin},{"preparation_end_ns",nowNs()},{"requested_duration_ns",duration},{"configured_compressed_spool_budget_bytes",pixels?spoolBudget:0},{"selected_compressed_spool_budget_bytes",selectedBudget},{"allocated_raw_bytes",allocatedBytes},{"allocated_compressed_bytes",spool.capacity()},{"mem_available_before_bytes",before},{"mem_available_after_bytes",after},{"spool_resident",pixels},{"spool_no_huge_pages",spool.noHugePages()},{"spool_dontfork",spool.noFork()},{"settle_until_ns",readyAt}}));
  details.accepted=true;
  return true;
}
void Global::finishRecording() {
  const uint64_t ended=endedRequest; auto& completed=completedRequest;
  if(ended && completed!=ended && writerDone.load() && !writerBusy.load() && !writerRequest.load() && (!pixels || saved.load()+frameDrops.load()>=activePresents.load()) && pipelineIdle()) {
    const uint64_t compressedBytes=spool.used(),rawAllocation=allocatedBytes+rawReleasedBeforeWrite,compressedAllocation=spool.capacity(),discardedPrefix=spool.discardedPrefix(),discardedTail=spool.discardedTail(),releaseBegin=nowNs();
    releaseRecordingBuffers();
    const uint64_t releaseEnd=nowNs();
    completed=ended; spoolSession=false;
    event("capture_buffers_released",fields({{"request",completed},{"begin_ns",releaseBegin},{"end_ns",releaseEnd},{"released_raw_bytes",rawAllocation},{"released_compressed_bytes",compressedAllocation}}));
    event("capture_complete",fields({{"request",completed},{"active_presents",activePresents.load()},{"copied_frames",copiedFrames.load()},{"saved",saved.load()},{"pixel_drops",frameDrops.load()},{"event_drops",droppedEvents.load()},{"wait_metadata_skipped",waitMetadataSkipped.load()},{"wait_record_drops",waitRecordDrops.load()},{"spooled_frames",spooledFrames.load()},{"compressed_spool_bytes",compressedBytes},{"spool_overflows",spoolOverflows.load()},{"archive_errors",archiveErrors.load()},{"buffer_release_begin_ns",releaseBegin},{"buffer_release_end_ns",releaseEnd},{"raw_released_before_write_bytes",rawReleasedBeforeWrite},{"discarded_copied_spool_bytes",discardedPrefix},{"discarded_unused_spool_bytes",discardedTail},{"released_raw_bytes",rawAllocation},{"released_compressed_bytes",compressedAllocation}})+",\"persistence_scope\":\"pixel_files_and_directory\",\"persistence_applicable\":"+(pixels?"true":"false")+",\"directory_synced\":"+(directorySynced.load()?"true":"false")+",\"persistence_ok\":"+(!pixels || (directorySynced.load() && !archiveErrors.load())?"true":"false"));
    endDetails();
  }
 }
void Global::control() {
  static uint64_t seen=0,lastCheck=0; auto& ended=endedRequest;
  const uint64_t now=nowNs();
  // No archive file polling while GPU readbacks need a predictable worker.
  if(now<until.load()) return;
  if(until.load() && ended!=request.load()) {
    ended=request.load(); event("capture_interval_end",fields({{"request",ended},{"requested_end_ns",until.load()},{"pixel_drops",frameDrops.load()},{"saved_so_far",saved.load()},{"spooled_frames",spooledFrames.load()}}));
  }
  if(spoolSession && !spoolSealed && ended==request.load() && pipelineIdle() && spooledFrames.load()+frameDrops.load()>=activePresents.load()) {
    spoolSealed=true;
    { std::lock_guard<std::mutex> l(spoolMutex); writerDone=false; writerRequest=true; }
    spoolReady.notify_one();
  }
  finishRecording();
  if(preparingToken) {
    if(now<readyAt) return;
    const uint64_t available=availableMemory();
    if(pixels && (available<memoryReserve || !spool.resident())) {
      const uint64_t token=preparingToken,selectedBudget=spool.capacity(); preparingToken=0; releaseRecordingBuffers(); endDetails();
      event("capture_rejected_memory",fields({{"request",token},{"mem_available_bytes",available},{"selected_compressed_spool_budget_bytes",selectedBudget},{"reserve_bytes",memoryReserve}})); return;
    }
    frameDrops=0; saved=0; activePresents=0; copiedFrames=0; spooledFrames=0; spoolOverflows=0;
    archiveErrors=0; directorySynced=false; rawReleasedBeforeWrite=0;
    request=preparingToken; preparingToken=0; spoolSession=pixels; spoolSealed=false;
    const uint64_t start=nowNs(); until=start+preparingDuration;
    event("capture_start",fields({{"request",request.load()},{"start_ns",start},{"end_ns",until.load()},{"requested_duration_ns",preparingDuration},{"configured_compressed_spool_budget_bytes",pixels?spoolBudget:0},{"selected_compressed_spool_budget_bytes",spool.capacity()},{"allocated_raw_bytes",allocatedBytes},{"allocated_compressed_bytes",spool.capacity()},{"mem_available_bytes",available}}));
    flushEvents(); // One small acknowledgment at the boundary; bulk writes wait.
    return;
  }
  if(now-lastCheck<50000000) return;
  lastCheck=now;
  std::ifstream f(directory+"/control.txt"); uint64_t token=0; double seconds=0;
  if(!(f>>token>>seconds) || !token || token==seen) return;
  seen=token;
  if(seconds<=0) { until=0; event("capture_cancelled",fields({{"request",request.load()}})); return; }
  bool pending=false; { std::lock_guard<std::mutex> l(framesMutex); pending=!pendingFrames.empty(); }
  if(spoolSession || !writerDone.load() || writerBusy.load() || writerRequest.load() || inCompression.load() || activeHooks.load() || pendingCopies.load() || pending) { event("capture_rejected_busy",fields({{"request",token}})); return; }
  prepareRecording(token,uint64_t(std::clamp(seconds,0.05,10.0)*1e9));
}
void Global::compress(size_t workerIndex) {
  auto& encoder=*encoders[workerIndex];
  for(;;) {
    std::unique_ptr<Frame> f;
    { std::unique_lock<std::mutex> l(framesMutex); frameReady.wait(l,[this]{return stop.load() || !pendingFrames.empty();}); if(pendingFrames.empty()) return; f=std::move(pendingFrames.front()); pendingFrames.pop_front(); inCompression++; }
    const uint64_t begin=nowNs();
    const size_t n=encoder.compress(f->bytes.data(),f->size);
    const uint64_t compressedAt=nowNs(); size_t index=0,offset=0;
    auto reservation=spool.reserve(n,index,offset);
    if(reservation==nadoc_capture::CompressedSpool::Reservation::Success) {
      const uint64_t copyBegin=nowNs(); std::memcpy(spool.data()+offset,encoder.buffer.data(),n); const uint64_t copiedAt=nowNs();
      auto& entry=spool.entries[index];
      entry.frame={f->present,f->request,f->swapchain,f->size,begin,compressedAt,f->queuedNs,copiedAt,copiedAt-copyBegin,f->width,f->height,uint32_t(f->format),offset,n};
      entry.ready=true; spooledFrames++;
      event("frame_spooled",fields({{"present",f->present},{"request",f->request},{"compressed_bytes",n},{"compression_ns",compressedAt-begin},{"spool_memcpy_ns",copiedAt-copyBegin},{"spool_used_bytes",spool.used()}}));
    } else {
      frameDrops++; spoolOverflows++;
      event("pixel_drop",fields({{"present",f->present},{"request",f->request},{"compressed_bytes",n}})+",\"reason\":\""+(reservation==nadoc_capture::CompressedSpool::Reservation::BytesFull?"compressed_spool_full":"compressed_spool_descriptors_full")+"\"");
    }
    { std::lock_guard<std::mutex> l(framesMutex); freeFrames.emplace_back(std::move(f)); inCompression--; }
  }
}
void Global::writeSpool() {
  for(;;) {
    { std::unique_lock<std::mutex> l(spoolMutex); spoolReady.wait(l,[this]{return writerStop.load() || writerRequest.load();}); if(!writerRequest.load()) return; writerRequest=false; writerBusy=true; }
    const uint64_t begin=nowNs();
    event("spool_drain_start",fields({{"request",request.load()},{"begin_ns",begin},{"compressed_bytes",spool.used()},{"spooled_frames",spooledFrames.load()}}));
    const std::string name="capture-"+std::to_string(getpid())+"-"+std::to_string(request.load())+".frames"+(std::string(codec.name())=="zstd"?".zst":".z");
    nadoc_capture::ArchiveResult packResult;
    bool layout=spool.completeLayout();
    for(size_t index=0;index<spool.count();index++) if(spool.entries[index].ready.load() && spool.entries[index].frame.request!=request.load()) layout=false;
    if(layout) {
      const uint64_t releaseBegin=nowNs();
      rawReleasedBeforeWrite=releaseRawBuffers();
      const bool tailReleased=spool.discardUnusedTail();
      const int releaseError=tailReleased?0:errno;
      event("capture_save_memory_released",fields({{"request",request.load()},{"begin_ns",releaseBegin},{"end_ns",nowNs()},{"released_raw_bytes",rawReleasedBeforeWrite},{"discarded_unused_spool_bytes",spool.discardedTail()},{"io_errno",uint64_t(releaseError)}}));
      nadoc_capture::ArchiveBatch batch(archiveOps);
      if(tailReleased) {
        nadoc_capture::ArchiveWritePolicy policy;
        policy.direct=true; policy.sourceDontFork=spool.noFork(); policy.chunkBytes=archiveChunkBytes; policy.bytesPerSecond=archiveBytesPerSecond; policy.context=&spool;
        policy.consumed=[](void* context,size_t copied){return static_cast<nadoc_capture::CompressedSpool*>(context)->discardCopiedPrefix(copied);};
        batch.append((directory+"/"+name).c_str(),spool.data(),spool.used(),0,policy);
        batch.flush([&](size_t,const nadoc_capture::ArchiveResult& result){packResult=result;});
      } else {
        packResult.begin=packResult.writeEnd=packResult.end=nowNs(); packResult.error=releaseError; packResult.stage="unused_source_release";
      }
    } else {
      packResult.begin=packResult.writeEnd=packResult.end=nowNs(); packResult.error=EINVAL; packResult.stage="incomplete_spool_layout";
      event("capture_persistence_failed",fields({{"request",request.load()}})+",\"io_error_stage\":\"incomplete_spool_layout\"");
    }
    for(size_t index=0;index<spool.count();index++) {
      const auto& entry=spool.entries[index]; if(!entry.ready.load()) continue;
      const auto& f=entry.frame; const auto& result=packResult;
      if(result.success()) saved++; else { frameDrops++; archiveErrors++; }
      event(result.success()?"frame_saved":"frame_write_failed",fields({{"present",f.present},{"request",f.request},{"swapchain",f.swapchain},{"width",f.width},{"height",f.height},{"format",f.format},{"raw_bytes",f.rawBytes},{"compressed_bytes",f.size},{"file_offset",f.offset},{"pack_bytes",spool.used()},{"compression_ns",f.compressionEnd-f.compressionBegin},{"disk_write_ns",result.end-result.begin},{"compression_queue_ns",f.compressionBegin-f.queued},{"compression_write_ns",result.end-f.compressionBegin},{"spool_memcpy_ns",f.spoolCopyNs},{"spool_wait_ns",result.begin-f.spooled},{"write_begin_ns",result.begin},{"write_data_end_ns",result.writeEnd},{"write_end_ns",result.end},{"data_sync_begin_ns",result.syncBegin},{"data_sync_end_ns",result.syncEnd},{"data_sync_ns",result.syncEnd-result.syncBegin},{"write_calls",result.writeCalls},{"write_max_requested_bytes",result.maxWriteBytes},{"written_bytes",result.writtenBytes},{"physical_written_bytes",result.physicalWrittenBytes},{"padding_bytes",result.paddingBytes},{"direct_memory_alignment",result.directMemoryAlignment},{"direct_offset_alignment",result.directOffsetAlignment},{"truncate_ns",result.truncateNs},{"source_release_ns",result.sourceReleaseNs},{"writer_pacing_ns",result.pacingNs},{"discarded_copied_spool_bytes",spool.discardedPrefix()},{"io_errno",uint64_t(result.error)},{"close_errno",uint64_t(result.closeError)}})+",\"file\":\""+name+"\",\"codec\":\""+codec.name()+"\",\"codec_level\":1,\"io_scope\":\"capture_pack\",\"bulk_write_deferred\":true,\"direct_io\":"+(result.direct?"true":"false")+",\"logical_truncate_succeeded\":"+(result.truncated?"true":"false")+",\"file_fdatasynced\":"+(result.synced?"true":"false")+",\"file_closed\":"+(result.closed?"true":"false")+",\"io_error_stage\":\""+result.stage+"\"");
    }
    const auto synced=nadoc_capture::syncArchiveDirectory(archiveOps,directory.c_str());
    directorySynced=synced.success();
    if(!directorySynced) archiveErrors++;
    event(directorySynced?"capture_directory_synced":"capture_persistence_failed",fields({{"request",request.load()},{"begin_ns",synced.begin},{"end_ns",synced.end},{"io_errno",uint64_t(synced.error)},{"close_errno",uint64_t(synced.closeError)}})+",\"io_error_stage\":\""+synced.stage+"\"");
    event("spool_drain_complete",fields({{"request",request.load()},{"begin_ns",begin},{"end_ns",nowNs()},{"saved",saved.load()},{"pixel_drops",frameDrops.load()},{"archive_errors",archiveErrors.load()}})+",\"directory_synced\":"+(directorySynced.load()?"true":"false"));
    writerBusy=false; writerDone=true;
  }
}
void Global::readback() {
  const bool cleanup=cleanupPending.exchange(false);
  if(!pendingCopies.load() && !cleanup) return;
  // Construct storage outside the registry lock (including its first touch),
  // then only assign into empty shared_ptr slots while holding it. Reference
  // destruction also occurs outside the lock at the end of each snapshot.
  size_t deviceCount=0;
  for(;;) {
    size_t needed=0;
    { std::lock_guard<PriorityMutex> l(mapMutex);
      needed=devices.size();
      if(needed<=readbackDevices.size()) { for(auto& p:devices) readbackDevices[deviceCount++]=p.second; break; }
    }
    readbackDevices.resize(std::max<size_t>(needed,16));
  }
  for(size_t deviceIndex=0;deviceIndex<deviceCount;deviceIndex++) {
    auto& d=readbackDevices[deviceIndex];
    std::lock_guard<std::mutex> life(d->lifetime); if(!d->alive) continue;
    size_t swapCount=0;
    for(;;) {
      size_t needed=0;
      { std::lock_guard<PriorityMutex> l(mapMutex);
        needed=d->allSwaps.size();
        if(needed<=readbackSwaps.size()) { for(auto& s:d->allSwaps) readbackSwaps[swapCount++]=s; break; }
      }
      readbackSwaps.resize(std::max<size_t>(needed,32));
    }
    for(size_t swapIndex=0;swapIndex<swapCount;swapIndex++) {
      auto& s=readbackSwaps[swapIndex];
      if(!s->prepared) continue;
      for(auto& sp:s->slots) {
        auto& slot=*sp; if(slot.state.load()!=1) continue;
        auto ready=d->GetFenceStatus(d->handle,slot.fence);
        if(ready==VK_NOT_READY) continue;
        if(ready!=VK_SUCCESS) { s->disabled=true; slot.state=0; pendingCopies--; frameDrops++; event("pixel_drop",fields({{"present",slot.present},{"request",slot.request},{"result",uint64_t(int64_t(ready))}})+",\"reason\":\"copy_fence_error\""); continue; }
        slot.state=2;
        uint64_t ticks[2]={}; auto qr=slot.query?d->GetQueryPoolResults(d->handle,slot.query,0,2,sizeof(ticks),ticks,sizeof(uint64_t),VK_QUERY_RESULT_64_BIT):VK_NOT_READY;
        uint64_t mask=s->timestampBits==64?UINT64_MAX:((1ULL<<s->timestampBits)-1);
        uint64_t gpuNs=qr==VK_SUCCESS?uint64_t(((ticks[1]-ticks[0])&mask)*d->properties.limits.timestampPeriod):0;
        std::unique_ptr<Frame> f;
        { std::lock_guard<std::mutex> l(framesMutex); if(!freeFrames.empty()) { f=std::move(freeFrames.front()); freeFrames.pop_front(); } }
        if(!f || f->bytes.size()<s->bytes) { frameDrops++; event("pixel_drop",fields({{"present",slot.present},{"request",slot.request}})+",\"reason\":\"raw_queue_full\""); }
        else {
          if(!slot.coherent) {
            VkMappedMemoryRange range{VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE}; range.memory=slot.memory; range.size=VK_WHOLE_SIZE;
            if(d->InvalidateMappedMemoryRanges(d->handle,1,&range)!=VK_SUCCESS) {
              frameDrops++; event("pixel_drop",fields({{"present",slot.present},{"request",slot.request}})+",\"reason\":\"invalidate_failed\"");
              { std::lock_guard<std::mutex> l(framesMutex); freeFrames.emplace_back(std::move(f)); }
              slot.state=0; pendingCopies--; continue;
            }
          }
          auto copyBegin=nowNs(); std::memcpy(f->bytes.data(),slot.mapped,s->bytes);
          f->present=slot.present; f->request=slot.request; f->swapchain=s->serial; f->width=s->extent.width; f->height=s->extent.height; f->format=s->format; f->size=s->bytes; f->queuedNs=nowNs();
          event("copy_complete",fields({{"present",slot.present},{"request",slot.request},{"copy_gpu_ns",gpuNs},{"gpu_timestamp_valid",qr==VK_SUCCESS},{"host_memcpy_ns",nowNs()-copyBegin},{"submit_to_poll_ns",nowNs()-slot.submitNs}}));
          { std::lock_guard<std::mutex> l(framesMutex); pendingFrames.emplace_back(std::move(f)); } frameReady.notify_one();
        }
        slot.state.store(0); pendingCopies--;
      }
      if(s->retired && std::all_of(s->slots.begin(),s->slots.end(),[](const auto& a){return a->state.load()==0;})) {
        destroyReadbackResources(*d,*s); s->prepared=false;
      }
    }
    for(size_t n=0;n<swapCount;n++) readbackSwaps[n].reset();
  }
  for(size_t n=0;n<deviceCount;n++) readbackDevices[n].reset();
}
void Global::run() {
  while(!stop.load()) {
    control(); readback();
    const uint64_t now=nowNs();
    if(now>=until.load()) { heartbeat(now); flushEvents(); }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}
bool prepare(Device& d,Swapchain& s,uint32_t family) {
  if(s.disabled || !s.transfer) return false;
  std::lock_guard<std::mutex> setup(s.setup); if(s.prepared) return s.family==family;
  s.family=family; s.timestampBits=d.families[family].timestampValidBits;
  VkCommandPoolCreateInfo pc{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pc.queueFamilyIndex=family;
  if(d.CreateCommandPool(d.handle,&pc,nullptr,&s.pool)!=VK_SUCCESS) { s.disabled=true; return false; }
  for(auto image:s.images) {
    auto slot=std::make_unique<Slot>(); auto& a=*slot;
    s.slots.emplace_back(std::move(slot));
    VkBufferCreateInfo bc{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO}; bc.size=s.bytes; bc.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT; bc.sharingMode=VK_SHARING_MODE_EXCLUSIVE;
    if(d.CreateBuffer(d.handle,&bc,nullptr,&a.buffer)!=VK_SUCCESS) goto failed;
    { VkMemoryRequirements mr{}; d.GetBufferMemoryRequirements(d.handle,a.buffer,&mr);
      uint32_t type=UINT32_MAX; int best=-1;
      for(uint32_t i=0;i<d.memory.memoryTypeCount;i++) {
        auto flags=d.memory.memoryTypes[i].propertyFlags;
        if(!(mr.memoryTypeBits&(1u<<i)) || !(flags&VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) continue;
        int score=((flags&VK_MEMORY_PROPERTY_HOST_CACHED_BIT)?8:0)+((flags&VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)?2:0);
        if(score>best) { best=score; type=i; }
      }
      if(type==UINT32_MAX) goto failed;
      a.coherent=d.memory.memoryTypes[type].propertyFlags&VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
      VkMemoryAllocateInfo ma{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; ma.allocationSize=mr.size; ma.memoryTypeIndex=type;
      if(d.AllocateMemory(d.handle,&ma,nullptr,&a.memory)!=VK_SUCCESS || d.BindBufferMemory(d.handle,a.buffer,a.memory,0)!=VK_SUCCESS || d.MapMemory(d.handle,a.memory,0,VK_WHOLE_SIZE,0,&a.mapped)!=VK_SUCCESS) goto failed;
    }
    { VkSemaphoreCreateInfo sc{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO}; VkFenceCreateInfo fc{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
      if(d.CreateSemaphore(d.handle,&sc,nullptr,&a.done)!=VK_SUCCESS || d.CreateFence(d.handle,&fc,nullptr,&a.fence)!=VK_SUCCESS) goto failed;
      VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; ca.commandPool=s.pool; ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ca.commandBufferCount=1;
      if(d.AllocateCommandBuffers(d.handle,&ca,&a.command)!=VK_SUCCESS) goto failed;
      if(d.setLoaderData && d.setLoaderData(d.handle,a.command)!=VK_SUCCESS) goto failed;
      if(s.timestampBits) { VkQueryPoolCreateInfo qc{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO}; qc.queryType=VK_QUERY_TYPE_TIMESTAMP; qc.queryCount=2; if(d.CreateQueryPool(d.handle,&qc,nullptr,&a.query)!=VK_SUCCESS) goto failed; }
      VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
      if(d.BeginCommandBuffer(a.command,&begin)!=VK_SUCCESS) goto failed;
      if(a.query) { d.CmdResetQueryPool(a.command,a.query,0,2); d.CmdWriteTimestamp(a.command,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,a.query,0); }
      VkImageMemoryBarrier bar{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER}; bar.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT; bar.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
      bar.oldLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR; bar.newLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL; bar.srcQueueFamilyIndex=bar.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
      bar.image=image; bar.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
      d.CmdPipelineBarrier(a.command,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&bar);
      VkBufferImageCopy copy{}; copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}; copy.imageExtent={s.extent.width,s.extent.height,1};
      d.CmdCopyImageToBuffer(a.command,image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,a.buffer,1,&copy);
      bar.srcAccessMask=VK_ACCESS_TRANSFER_READ_BIT; bar.dstAccessMask=0; bar.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL; bar.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
      VkBufferMemoryBarrier host{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER}; host.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; host.dstAccessMask=VK_ACCESS_HOST_READ_BIT; host.srcQueueFamilyIndex=host.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED; host.buffer=a.buffer; host.size=VK_WHOLE_SIZE;
      d.CmdPipelineBarrier(a.command,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT|VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,1,&host,1,&bar);
      if(a.query) d.CmdWriteTimestamp(a.command,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,a.query,1);
      if(d.EndCommandBuffer(a.command)!=VK_SUCCESS) goto failed;
    }
  }
  s.prepared=true;
  global().largestBytes=std::max(global().largestBytes.load(),s.bytes);
  global().event("capture_prepared",fields({{"swapchain",s.serial},{"queue_family",family},{"readback_slots",s.slots.size()},{"raw_bytes_per_frame",s.bytes},{"timestamp_bits",s.timestampBits}}));
  return true;
failed:
  s.disabled=true; global().event("capture_prepare_failed",fields({{"swapchain",s.serial}})); return false;
}
void destroyReadbackResources(Device& d,Swapchain& s) {
  for(auto& sp:s.slots) { auto& a=*sp;
    if(a.mapped) { d.UnmapMemory(d.handle,a.memory); a.mapped=nullptr; }
    if(a.buffer) { d.DestroyBuffer(d.handle,a.buffer,nullptr); a.buffer=VK_NULL_HANDLE; }
    if(a.memory) { d.FreeMemory(d.handle,a.memory,nullptr); a.memory=VK_NULL_HANDLE; }
    if(a.fence) { d.DestroyFence(d.handle,a.fence,nullptr); a.fence=VK_NULL_HANDLE; }
    if(a.query) { d.DestroyQueryPool(d.handle,a.query,nullptr); a.query=VK_NULL_HANDLE; }
  }
  if(s.pool) { d.DestroyCommandPool(d.handle,s.pool,nullptr); s.pool=VK_NULL_HANDLE; }
}
void destroyResources(Device& d,Swapchain& s) {
  destroyReadbackResources(d,s);
  for(auto& sp:s.slots) if(sp->done) d.DestroySemaphore(d.handle,sp->done,nullptr);
}
} // namespace

EXPORTED PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance,const char*);
EXPORTED PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice,const char*);

EXPORTED VkResult VKAPI_CALL vkCreateInstance(const VkInstanceCreateInfo* ci,const VkAllocationCallbacks* a,VkInstance* out) {
  auto link=(VkLayerInstanceCreateInfo*)chain(ci->pNext,VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO);
  while(link && link->function!=VK_LAYER_LINK_INFO) link=(VkLayerInstanceCreateInfo*)chain(link->pNext,VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO);
  if(!link || !link->u.pLayerInfo) return VK_ERROR_INITIALIZATION_FAILED;
  auto next=link->u.pLayerInfo->pfnNextGetInstanceProcAddr; auto create=(PFN_vkCreateInstance)next(nullptr,"vkCreateInstance"); link->u.pLayerInfo=link->u.pLayerInfo->pNext;
  VkResult r=create(ci,a,out); if(r!=VK_SUCCESS) return r;
  auto i=std::make_shared<Instance>(); i->handle=*out; i->gipa=next;
  for(uint32_t k=0;k<ci->enabledExtensionCount;k++) if(std::strcmp(ci->ppEnabledExtensionNames[k],VK_EXT_DISPLAY_SURFACE_COUNTER_EXTENSION_NAME)==0) i->displayCounter=true;
#define LOAD_I(field,name) i->field=(PFN_vk##name)next(*out,"vk" #name)
  LOAD_I(destroy,DestroyInstance); LOAD_I(enumerate,EnumeratePhysicalDevices); LOAD_I(groups,EnumeratePhysicalDeviceGroups);
  LOAD_I(displaySurface,CreateDisplayPlaneSurfaceKHR); LOAD_I(destroySurface,DestroySurfaceKHR); LOAD_I(surfaceCaps,GetPhysicalDeviceSurfaceCapabilitiesKHR); LOAD_I(surfaceCaps2,GetPhysicalDeviceSurfaceCapabilities2EXT);
  LOAD_I(memoryProps,GetPhysicalDeviceMemoryProperties); LOAD_I(queueProps,GetPhysicalDeviceQueueFamilyProperties); LOAD_I(properties,GetPhysicalDeviceProperties);
#undef LOAD_I
  auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); g.instances[id(*out)]=i; return r;
}
EXPORTED void VKAPI_CALL vkDestroyInstance(VkInstance h,const VkAllocationCallbacks* a) {
  auto i=instance(h); if(!i) return; auto& g=global();
  bool last=false;
  { std::lock_guard<PriorityMutex> l(g.mapMutex); for(auto it=g.physicals.begin();it!=g.physicals.end();) { if(it->second==i) it=g.physicals.erase(it); else ++it; } g.instances.erase(id(h)); last=g.instances.empty(); }
  if(last) {
    // Loader can dlclose this .so immediately after the last instance vanishes.
    // All threads executing layer code must exit before returning to it.
    g.until=0;
    { std::lock_guard<std::mutex> l(g.framesMutex); g.stop=true; }
    g.frameReady.notify_all();
    for(auto& t:g.compressors) if(t.joinable()) t.join();
    if(g.worker.joinable()) g.worker.join();
    { std::lock_guard<std::mutex> l(g.spoolMutex);
      if(g.spoolSession && !g.spoolSealed) { g.spoolSealed=true; g.writerDone=false; g.writerRequest=true; }
      g.writerStop=true;
    }
    g.spoolReady.notify_all();
    if(g.spoolWriter.joinable()) g.spoolWriter.join();
    // A long durable drain may outlive the reader thread. Complete accounting
    // after join without polling control files or accidentally arming new work.
    g.finishRecording();
    if(g.spoolSession) {
      g.event("capture_aborted",fields({{"request",g.request.load()},{"active_presents",g.activePresents.load()},{"saved",g.saved.load()},{"pixel_drops",g.frameDrops.load()}}));
      g.releaseRecordingBuffers(); g.spoolSession=false;
    }
    g.flushEvents(); g.enabled=false;
  }
  i->destroy(h,a);
}
EXPORTED VkResult VKAPI_CALL vkEnumeratePhysicalDevices(VkInstance h,uint32_t* count,VkPhysicalDevice* out) {
  auto i=instance(h); auto r=i->enumerate(h,count,out); if(out && (r==VK_SUCCESS || r==VK_INCOMPLETE)) { auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); for(uint32_t n=0;n<*count;n++) g.physicals[id(out[n])]=i; } return r;
}
EXPORTED VkResult VKAPI_CALL vkEnumeratePhysicalDeviceGroups(VkInstance h,uint32_t* count,VkPhysicalDeviceGroupProperties* out) {
  auto i=instance(h); auto r=i->groups(h,count,out); if(out && (r==VK_SUCCESS || r==VK_INCOMPLETE)) { auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); for(uint32_t n=0;n<*count;n++) for(uint32_t k=0;k<out[n].physicalDeviceCount;k++) g.physicals[id(out[n].physicalDevices[k])]=i; } return r;
}
EXPORTED VkResult VKAPI_CALL vkCreateDevice(VkPhysicalDevice p,const VkDeviceCreateInfo* ci,const VkAllocationCallbacks* a,VkDevice* out) {
  auto& g=global(); std::shared_ptr<Instance> i;
  { std::lock_guard<PriorityMutex> l(g.mapMutex); auto it=g.physicals.find(id(p)); if(it!=g.physicals.end()) i=it->second; }
  auto link=(VkLayerDeviceCreateInfo*)chain(ci->pNext,VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO);
  while(link && link->function!=VK_LAYER_LINK_INFO) link=(VkLayerDeviceCreateInfo*)chain(link->pNext,VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO);
  if(!i || !link || !link->u.pLayerInfo) return VK_ERROR_INITIALIZATION_FAILED;
  auto nextGipa=link->u.pLayerInfo->pfnNextGetInstanceProcAddr; auto nextGdpa=link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
  auto create=(PFN_vkCreateDevice)nextGipa(i->handle,"vkCreateDevice"); link->u.pLayerInfo=link->u.pLayerInfo->pNext;
  auto r=create(p,ci,a,out); if(r!=VK_SUCCESS) return r;
  auto d=std::make_shared<Device>(); d->handle=*out; d->physical=p; d->instance=i; d->gdpa=nextGdpa;
  for(uint32_t k=0;k<ci->enabledExtensionCount;k++) if(std::strcmp(ci->ppEnabledExtensionNames[k],VK_EXT_DISPLAY_CONTROL_EXTENSION_NAME)==0) d->displayControl=true;
  auto callback=(const VkLayerDeviceCreateInfo*)chain(ci->pNext,VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO);
  while(callback && callback->function!=VK_LOADER_DATA_CALLBACK) callback=(const VkLayerDeviceCreateInfo*)chain(callback->pNext,VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO);
  if(callback) d->setLoaderData=callback->u.pfnSetDeviceLoaderData;
#define LOAD_D(name) d->name=(PFN_vk##name)nextGdpa(*out,"vk" #name);
  DEV_FUNCTIONS(LOAD_D)
#undef LOAD_D
  i->memoryProps(p,&d->memory); i->properties(p,&d->properties); uint32_t n=0; i->queueProps(p,&n,nullptr); d->families.resize(n); i->queueProps(p,&n,d->families.data());
  { std::lock_guard<PriorityMutex> l(g.mapMutex); g.devices[id(*out)]=d; }
  g.event("device",fields({{"vendor_id",d->properties.vendorID},{"device_id",d->properties.deviceID}})); return r;
}
EXPORTED void VKAPI_CALL vkDestroyDevice(VkDevice h,const VkAllocationCallbacks* a) {
  auto d=device(h); if(!d) return; auto& g=global();
  { std::lock_guard<std::mutex> life(d->lifetime); d->alive=false;
    // Teardown only. Capture never uses wait-idle in the presentation path.
    d->DeviceWaitIdle(h);
    for(auto& s:d->allSwaps) {
      for(auto& slot:s->slots) if(slot->state.exchange(0)) { g.pendingCopies--; g.frameDrops++; }
      destroyResources(*d,*s);
    }
  }
  { std::lock_guard<PriorityMutex> l(g.mapMutex); g.devices.erase(id(h)); for(auto it=g.queues.begin();it!=g.queues.end();) { if(it->second.device==d) it=g.queues.erase(it); else ++it; } }
  g.event("device_destroy",fields({{"saved",g.saved.load()},{"pixel_drops",g.frameDrops.load()},{"event_drops",g.droppedEvents.load()}})); d->DestroyDevice(h,a);
}
EXPORTED void VKAPI_CALL vkGetDeviceQueue(VkDevice h,uint32_t f,uint32_t n,VkQueue* out) { auto d=device(h); d->GetDeviceQueue(h,f,n,out); auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); g.queues[id(*out)]={d,f,0}; }
EXPORTED void VKAPI_CALL vkGetDeviceQueue2(VkDevice h,const VkDeviceQueueInfo2* ci,VkQueue* out) { auto d=device(h); d->GetDeviceQueue2(h,ci,out); auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); g.queues[id(*out)]={d,ci->queueFamilyIndex,ci->flags}; }
EXPORTED VkResult VKAPI_CALL vkCreateDisplayPlaneSurfaceKHR(VkInstance h,const VkDisplaySurfaceCreateInfoKHR* ci,const VkAllocationCallbacks* a,VkSurfaceKHR* out) {
  auto i=instance(h); auto r=i->displaySurface(h,ci,a,out);
  if(r==VK_SUCCESS) {
    auto& g=global(); uint64_t refresh=0;
    { std::lock_guard<PriorityMutex> l(g.mapMutex); g.surfaces[id(*out)]=*ci; g.surfaces[id(*out)].pNext=nullptr; auto m=g.modes.find(id(ci->displayMode)); if(m!=g.modes.end()) refresh=m->second.refreshRate; }
    g.event("direct_surface",fields({{"surface",id(*out)},{"display_mode",id(ci->displayMode)},{"width",ci->imageExtent.width},{"height",ci->imageExtent.height},{"transform",ci->transform},{"refresh_millihz",refresh}}));
  }
  return r;
}
EXPORTED VkResult VKAPI_CALL vkGetDisplayModePropertiesKHR(VkPhysicalDevice p,VkDisplayKHR display,uint32_t* count,VkDisplayModePropertiesKHR* out) {
  auto& g=global(); std::shared_ptr<Instance> i; { std::lock_guard<PriorityMutex> l(g.mapMutex); i=g.physicals.at(id(p)); }
  auto fn=(PFN_vkGetDisplayModePropertiesKHR)i->gipa(i->handle,"vkGetDisplayModePropertiesKHR"); auto r=fn(p,display,count,out);
  if(out && (r==VK_SUCCESS || r==VK_INCOMPLETE)) { std::lock_guard<PriorityMutex> l(g.mapMutex); for(uint32_t n=0;n<*count;n++) g.modes[id(out[n].displayMode)]=out[n].parameters; } return r;
}
EXPORTED VkResult VKAPI_CALL vkCreateDisplayModeKHR(VkPhysicalDevice p,VkDisplayKHR display,const VkDisplayModeCreateInfoKHR* ci,const VkAllocationCallbacks* a,VkDisplayModeKHR* out) {
  auto& g=global(); std::shared_ptr<Instance> i; { std::lock_guard<PriorityMutex> l(g.mapMutex); i=g.physicals.at(id(p)); }
  auto fn=(PFN_vkCreateDisplayModeKHR)i->gipa(i->handle,"vkCreateDisplayModeKHR"); auto r=fn(p,display,ci,a,out);
  if(r==VK_SUCCESS) { std::lock_guard<PriorityMutex> l(g.mapMutex); g.modes[id(*out)]=ci->parameters; } return r;
}
EXPORTED void VKAPI_CALL vkDestroySurfaceKHR(VkInstance h,VkSurfaceKHR s,const VkAllocationCallbacks* a) { auto i=instance(h); { auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); g.surfaces.erase(id(s)); } i->destroySurface(h,s,a); }
EXPORTED VkResult VKAPI_CALL vkCreateSwapchainKHR(VkDevice h,const VkSwapchainCreateInfoKHR* ci,const VkAllocationCallbacks* a,VkSwapchainKHR* out) {
  auto d=device(h); auto& g=global(); auto s=std::make_shared<Swapchain>(); s->serial=++g.serial; s->extent=ci->imageExtent; s->format=ci->imageFormat; s->mode=ci->presentMode; s->sharing=ci->imageSharingMode;
  if(ci->queueFamilyIndexCount && ci->pQueueFamilyIndices) s->families.assign(ci->pQueueFamilyIndices,ci->pQueueFamilyIndices+ci->queueFamilyIndexCount);
  { std::lock_guard<PriorityMutex> l(g.mapMutex); s->direct=g.surfaces.count(id(ci->surface)); }
  s->test=g.test && !s->direct; VkSwapchainCreateInfoKHR copy=*ci;
  const bool format=ci->imageFormat==VK_FORMAT_B8G8R8A8_UNORM || ci->imageFormat==VK_FORMAT_B8G8R8A8_SRGB || ci->imageFormat==VK_FORMAT_R8G8B8A8_UNORM || ci->imageFormat==VK_FORMAT_R8G8B8A8_SRGB;
  const bool safe=!(ci->flags&VK_SWAPCHAIN_CREATE_PROTECTED_BIT_KHR) && ci->imageArrayLayers==1 && format && ci->presentMode!=VK_PRESENT_MODE_SHARED_DEMAND_REFRESH_KHR && ci->presentMode!=VK_PRESENT_MODE_SHARED_CONTINUOUS_REFRESH_KHR;
  if(g.enabled && g.pixels && (s->direct || s->test) && safe) { VkSurfaceCapabilitiesKHR caps{}; if(d->instance->surfaceCaps(d->physical,ci->surface,&caps)==VK_SUCCESS && (caps.supportedUsageFlags&VK_IMAGE_USAGE_TRANSFER_SRC_BIT)) { copy.imageUsage|=VK_IMAGE_USAGE_TRANSFER_SRC_BIT; s->transfer=true; } }
  const auto* counter=(const VkSwapchainCounterCreateInfoEXT*)chain(ci->pNext,VK_STRUCTURE_TYPE_SWAPCHAIN_COUNTER_CREATE_INFO_EXT); s->counter=counter && (counter->surfaceCounters&VK_SURFACE_COUNTER_VBLANK_BIT_EXT);
  VkSwapchainCounterCreateInfoEXT enableCounter{VK_STRUCTURE_TYPE_SWAPCHAIN_COUNTER_CREATE_INFO_EXT};
  if(g.enabled && s->direct && !counter && d->displayControl && d->instance->displayCounter && d->instance->surfaceCaps2) {
    VkSurfaceCapabilities2EXT caps{VK_STRUCTURE_TYPE_SURFACE_CAPABILITIES_2_EXT};
    if(d->instance->surfaceCaps2(d->physical,ci->surface,&caps)==VK_SUCCESS && (caps.supportedSurfaceCounters&VK_SURFACE_COUNTER_VBLANK_BIT_EXT)) {
      enableCounter.pNext=copy.pNext; enableCounter.surfaceCounters=VK_SURFACE_COUNTER_VBLANK_BIT_EXT; copy.pNext=&enableCounter; s->counter=true;
    }
  }
  auto r=d->CreateSwapchainKHR(h,&copy,a,out);
  // If augmenting usage prevents creation, retry original contract once, disabled.
  if(r!=VK_SUCCESS && (copy.imageUsage!=ci->imageUsage || copy.pNext!=ci->pNext)) { s->transfer=false; s->counter=counter && (counter->surfaceCounters&VK_SURFACE_COUNTER_VBLANK_BIT_EXT); r=d->CreateSwapchainKHR(h,ci,a,out); g.event("capture_swapchain_retry_original",fields({{"swapchain",s->serial}})); }
  if(r!=VK_SUCCESS) return r;
  s->handle=*out; s->usage=s->transfer?copy.imageUsage:ci->imageUsage; s->bytes=size_t(ci->imageExtent.width)*ci->imageExtent.height*4;
  uint32_t n=0; d->GetSwapchainImagesKHR(h,*out,&n,nullptr); s->images.resize(n); d->GetSwapchainImagesKHR(h,*out,&n,s->images.data());
  { std::lock_guard<PriorityMutex> l(g.mapMutex); g.swaps[id(*out)]=s; d->allSwaps.push_back(s); }
  g.event("swapchain",fields({{"swapchain",s->serial},{"handle",id(*out)},{"surface",id(ci->surface)},{"width",ci->imageExtent.width},{"height",ci->imageExtent.height},{"format",uint64_t(ci->imageFormat)},{"mode",uint64_t(ci->presentMode)},{"images",n},{"direct_display",s->direct},{"test_surface",s->test},{"transfer_src",s->transfer},{"vblank_counter_enabled",s->counter}}));
  if(g.enabled && s->direct && std::strcmp(env("NADOC_VR_CAPTURE_DIAGNOSTIC_FDS"),"1")==0 && !g.fdSnapshotTaken.exchange(true)) {
    try { g.event("fd_route_snapshot",fields({{"swapchain",s->serial}})+nadoc_capture::fdRouteSnapshot()); }
    catch(...) { /* Optional route diagnostics must never affect creation. */ }
  }
  return r;
}
EXPORTED void VKAPI_CALL vkDestroySwapchainKHR(VkDevice h,VkSwapchainKHR swap,const VkAllocationCallbacks* a) {
  auto d=device(h); auto& g=global(); uint64_t serial=0;
  { std::lock_guard<PriorityMutex> l(g.mapMutex); auto it=g.swaps.find(id(swap)); if(it!=g.swaps.end()) { it->second->retired=true; serial=it->second->serial; g.swaps.erase(it); g.cleanupPending=true; } }
  if(serial) g.event("swapchain_retired",fields({{"swapchain",serial}}));
  // Per-image presentation semaphores retained until device destruction, since
  // a copy fence alone cannot prove presentation's semaphore wait completed.
  d->DestroySwapchainKHR(h,swap,a);
}
void acquired(VkSwapchainKHR h,uint32_t index,VkResult result) {
  if(result!=VK_SUCCESS && result!=VK_SUBOPTIMAL_KHR) return;
  auto& g=global(); std::lock_guard<PriorityMutex> l(g.mapMutex); auto it=g.swaps.find(id(h)); if(it!=g.swaps.end() && it->second->prepared && index<it->second->slots.size()) ++it->second->slots[index]->generation;
}
EXPORTED VkResult VKAPI_CALL vkAcquireNextImageKHR(VkDevice h,VkSwapchainKHR s,uint64_t t,VkSemaphore sem,VkFence f,uint32_t* out) { auto d=device(h); auto r=d->AcquireNextImageKHR(h,s,t,sem,f,out); if(out && (r==VK_SUCCESS || r==VK_SUBOPTIMAL_KHR)) acquired(s,*out,r); return r; }
EXPORTED VkResult VKAPI_CALL vkAcquireNextImage2KHR(VkDevice h,const VkAcquireNextImageInfoKHR* ci,uint32_t* out) { auto d=device(h); auto r=d->AcquireNextImage2KHR(h,ci,out); if(out && (r==VK_SUCCESS || r==VK_SUBOPTIMAL_KHR)) acquired(ci->swapchain,*out,r); return r; }

EXPORTED VkResult VKAPI_CALL vkQueuePresentKHR(VkQueue queue,const VkPresentInfoKHR* info) {
  uint64_t enter=nowNs(); auto& g=global(); const bool detailsAtEntry=g.detailedRecords(enter); Queue q{};
  { std::lock_guard<PriorityMutex> l(g.mapMutex); auto it=g.queues.find(id(queue));
    if(it!=g.queues.end()) q=it->second;
    else {
      // Unknown retrieval path: forward through the matching loader dispatch
      // table; never introduce an application error merely to skip capture.
      for(auto& item:g.devices) if(*reinterpret_cast<void**>(queue)==*reinterpret_cast<void**>(item.second->handle)) { q={item.second,UINT32_MAX,0}; break; }
    }
  }
  if(!q.device) return VK_ERROR_DEVICE_LOST; // Invalid dispatchable handle.
  // Register before deciding whether this call is armed. End-of-interval
  // sealing cannot race a previously armed but not-yet-counted presentation.
  g.activeHooks++;
  auto& d=*q.device; const uint64_t sequence=++g.present; VkPresentInfoKHR modified=*info;
  std::shared_ptr<Swapchain> selected; uint32_t selectedIndex=0, entry=0;
  bool copied=false,armed=false,called=false,retryExpanding=false; VkResult result=VK_ERROR_UNKNOWN;
  uint64_t requestID=g.request.load();
  Slot* bridgeSlot=nullptr; std::vector<VkSemaphore> bridgeWaits;
  try {
  for(uint32_t n=0;n<info->swapchainCount;n++) {
    std::lock_guard<PriorityMutex> l(g.mapMutex); auto it=g.swaps.find(id(info->pSwapchains[n]));
    if(it!=g.swaps.end() && (it->second->direct || it->second->test)) { if(selected) { selected.reset(); break; } selected=it->second; selectedIndex=info->pImageIndices[n]; entry=n; }
  }
  const char* reason="not_armed"; uint64_t copySubmitNs=0, vblank=0,counterBegin=0,counterEnd=0; VkResult vblankResult=VK_ERROR_EXTENSION_NOT_PRESENT;
  if(selected) {
    auto& s=*selected;
    bool queueSafe=q.family<d.families.size() && (d.families[q.family].queueFlags&(VK_QUEUE_GRAPHICS_BIT|VK_QUEUE_COMPUTE_BIT|VK_QUEUE_TRANSFER_BIT)) && !(q.flags&VK_DEVICE_QUEUE_CREATE_PROTECTED_BIT);
    bool pnextSafe=!chain(info->pNext,VK_STRUCTURE_TYPE_DEVICE_GROUP_PRESENT_INFO_KHR);
    if(queueSafe && pnextSafe && g.pixels && s.transfer && !s.disabled) prepare(d,s,q.family);
    armed=g.enabled && nowNs()<g.until.load(); requestID=g.request.load();
    if(armed) g.activePresents++;
    if(s.prepared && selectedIndex<s.slots.size() && s.slots[selectedIndex]->retryPresent) {
      bridgeSlot=s.slots[selectedIndex].get();
      modified.waitSemaphoreCount=1; modified.pWaitSemaphores=&bridgeSlot->done;
      retryExpanding=true; bridgeWaits.push_back(bridgeSlot->done);
      for(uint32_t k=0;k<info->waitSemaphoreCount;k++) if(std::find(bridgeSlot->consumedWaits.begin(),bridgeSlot->consumedWaits.end(),info->pWaitSemaphores[k])==bridgeSlot->consumedWaits.end()) bridgeWaits.push_back(info->pWaitSemaphores[k]);
      modified.waitSemaphoreCount=uint32_t(bridgeWaits.size()); modified.pWaitSemaphores=bridgeWaits.data();
      retryExpanding=false;
      g.event("present_retry_bridge",fields({{"present",sequence},{"retry_of_present",bridgeSlot->present},{"swapchain",s.serial}}));
    }
    if(armed && g.pixels && !bridgeSlot) {
      reason="unsupported_surface_or_queue";
      if(queueSafe && pnextSafe && s.prepared && !s.disabled && s.family==q.family && selectedIndex<s.slots.size()) {
        auto& slot=*s.slots[selectedIndex]; reason="readback_slot_busy";
        if(slot.state.load()==0) {
          reason="image_not_reacquired";
          if(slot.generation>slot.capturedGeneration) {
            auto reset=d.ResetFences(d.handle,1,&slot.fence);
            if(reset==VK_SUCCESS) {
              std::vector<VkPipelineStageFlags> stages(info->waitSemaphoreCount,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT);
              VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.waitSemaphoreCount=info->waitSemaphoreCount; submit.pWaitSemaphores=info->pWaitSemaphores; submit.pWaitDstStageMask=stages.data(); submit.commandBufferCount=1; submit.pCommandBuffers=&slot.command; submit.signalSemaphoreCount=1; submit.pSignalSemaphores=&slot.done;
              slot.consumedWaits.clear();
              if(info->waitSemaphoreCount) slot.consumedWaits.assign(info->pWaitSemaphores,info->pWaitSemaphores+info->waitSemaphoreCount);
              uint64_t begin=nowNs(); auto r=d.QueueSubmit(queue,1,&submit,slot.fence); copySubmitNs=nowNs()-begin;
              if(r==VK_SUCCESS) {
                slot.present=sequence; slot.request=requestID; slot.submitNs=begin; slot.capturedGeneration=slot.generation.load(); g.pendingCopies++; slot.state.store(1); g.copiedFrames++;
                bridgeSlot=&slot;
                modified.waitSemaphoreCount=1; modified.pWaitSemaphores=&slot.done; copied=true; reason="submitted";
              } else { s.disabled=true; reason="queue_submit_failed"; }
            } else { s.disabled=true; reason="reset_fence_failed"; }
          }
        }
      }
      if(!copied) { g.frameDrops++; g.event("pixel_drop",fields({{"present",sequence},{"request",requestID},{"swapchain",s.serial}})+",\"reason\":\""+reason+"\""); }
    } else if(armed && g.pixels && bridgeSlot) {
      g.frameDrops++; g.event("pixel_drop",fields({{"present",sequence},{"request",requestID},{"swapchain",s.serial}})+",\"reason\":\"present_retry_reuses_prior_capture\"");
    }
    if(s.counter && s.presentCompleted && d.GetSwapchainCounterEXT) { counterBegin=nowNs(); vblankResult=d.GetSwapchainCounterEXT(d.handle,s.handle,VK_SURFACE_COUNTER_VBLANK_BIT_EXT,&vblank); counterEnd=nowNs(); }
  }
  const uint64_t call=nowNs(); result=d.QueuePresentKHR(queue,&modified); called=true; const uint64_t end=nowNs();
  if(bridgeSlot) bridgeSlot->retryPresent=result==VK_ERROR_OUT_OF_HOST_MEMORY || result==VK_ERROR_OUT_OF_DEVICE_MEMORY;
  if(selected && (detailsAtEntry || armed || g.detailedRecords(end) || result!=VK_SUCCESS || (info->pResults && info->pResults[entry]!=VK_SUCCESS))) {
    const auto* presentId=(const VkPresentIdKHR*)chain(info->pNext,VK_STRUCTURE_TYPE_PRESENT_ID_KHR);
    uint64_t pid=presentId && presentId->swapchainCount>entry?presentId->pPresentIds[entry]:0;
    g.event("present",fields({{"present",sequence},{"request",requestID},{"armed",armed},{"swapchain",selected->serial},{"image",selectedIndex},{"present_id",pid},{"enter_ns",enter},{"driver_call_ns",call},{"return_ns",end},{"hook_before_driver_ns",call-enter},{"copy_submit_host_ns",copySubmitNs},{"driver_duration_ns",end-call},{"copied",copied},{"vblank_sample",vblank},{"vblank_sample_valid",vblankResult==VK_SUCCESS},{"counter_query_begin_ns",counterBegin},{"counter_query_end_ns",counterEnd},{"counter_query_ns",counterEnd-counterBegin}})+",\"result\":"+std::to_string(result)+",\"image_result\":"+std::to_string(info->pResults?info->pResults[entry]:result)+",\"display_observed\":false");
  } else if(selected) g.idlePresentSuppressed++;
  g.activeHooks--;
  return result;
  } catch(...) {
    // In particular, never escape after consuming the application's waits.
    // modified already points at our completion semaphore after successful copy.
    g.until=0; g.enabled=false;
    if(retryExpanding) {
      // No work was enqueued on this retry. Report allocation failure while
      // retaining the bridge for a later retry, rather than omit new app waits.
      result=VK_ERROR_OUT_OF_HOST_MEMORY;
      if(info->pResults) for(uint32_t n=0;n<info->swapchainCount;n++) info->pResults[n]=result;
    } else if(!called) result=d.QueuePresentKHR(queue,&modified);
    if(bridgeSlot) bridgeSlot->retryPresent=result==VK_ERROR_OUT_OF_HOST_MEMORY || result==VK_ERROR_OUT_OF_DEVICE_MEMORY;
    g.activeHooks--;
    return result;
  }
}
EXPORTED VkResult VKAPI_CALL vkWaitForPresentKHR(VkDevice h,VkSwapchainKHR s,uint64_t presentId,uint64_t timeout) {
  WaitRecord w; w.entry=nowNs(); w.presentId=presentId; w.timeout=timeout;
  auto& g=global(); w.retainAtEntry=g.detailedRecords(w.entry); std::shared_ptr<Device> d;
  w.deviceLookupBegin=nowNs();
  { std::lock_guard<PriorityMutex> l(g.mapMutex);
    w.deviceLockAcquired=nowNs();
    auto it=g.devices.find(id(h)); if(it!=g.devices.end()) d=it->second;
  }
  w.deviceLookupEnd=nowNs();
  w.begin=nowNs(); w.result=d->WaitForPresentKHR(h,s,presentId,timeout); w.returned=nowNs();
  if(!g.enabled) return w.result;
  bool counter=false;
  w.registryBegin=nowNs();
  // Enrichment is optional telemetry. Never delay a successful runtime wait
  // behind a lower-priority worker, allocator or driver setup operation.
  if(g.mapMutex.try_lock()) {
    w.registryAcquired=nowNs(); w.registryComplete=true;
    auto it=g.swaps.find(id(s));
    if(it!=g.swaps.end()) {
      w.swapchain=it->second->serial;
      if(w.result==VK_SUCCESS) it->second->presentCompleted=true;
      counter=it->second->counter && it->second->presentCompleted;
    }
    g.mapMutex.unlock();
  } else g.waitMetadataSkipped++;
  w.registryEnd=nowNs();
  if(counter && d->GetSwapchainCounterEXT) {
    w.sampleBegin=nowNs();
    w.vblankValid=d->GetSwapchainCounterEXT(h,s,VK_SURFACE_COUNTER_VBLANK_BIT_EXT,&w.vblank)==VK_SUCCESS;
    w.sampleEnd=nowNs();
  }
  g.enqueueWait(w);
  return w.result;
}
EXPORTED PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice h,const char* name) {
  if(!name) return nullptr;
  auto d=device(h);
  if(std::strcmp(name,"vkGetDeviceQueue2")==0 && (!d || !d->GetDeviceQueue2)) return nullptr;
  if(std::strcmp(name,"vkWaitForPresentKHR")==0 && (!d || !d->WaitForPresentKHR)) return nullptr;
  if(std::strcmp(name,"vkAcquireNextImage2KHR")==0 && (!d || !d->AcquireNextImage2KHR)) return nullptr;
#define RETURN(name_) if(std::strcmp(name,"vk" #name_)==0) return (PFN_vkVoidFunction)vk##name_
  RETURN(GetDeviceProcAddr); RETURN(DestroyDevice); RETURN(GetDeviceQueue); RETURN(GetDeviceQueue2); RETURN(CreateSwapchainKHR); RETURN(DestroySwapchainKHR); RETURN(AcquireNextImageKHR); RETURN(AcquireNextImage2KHR); RETURN(QueuePresentKHR); RETURN(WaitForPresentKHR);
#undef RETURN
  return d?d->gdpa(h,name):nullptr;
}
EXPORTED PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance h,const char* name) {
  if(!name) return nullptr;
#define RETURN(name_) if(std::strcmp(name,"vk" #name_)==0) return (PFN_vkVoidFunction)vk##name_
  RETURN(GetInstanceProcAddr); RETURN(GetDeviceProcAddr); RETURN(CreateInstance); RETURN(DestroyInstance); RETURN(EnumeratePhysicalDevices); RETURN(EnumeratePhysicalDeviceGroups); RETURN(CreateDevice); RETURN(CreateDisplayPlaneSurfaceKHR); RETURN(DestroySurfaceKHR); RETURN(GetDisplayModePropertiesKHR); RETURN(CreateDisplayModeKHR);
  RETURN(DestroyDevice); RETURN(GetDeviceQueue); RETURN(GetDeviceQueue2); RETURN(CreateSwapchainKHR); RETURN(DestroySwapchainKHR); RETURN(AcquireNextImageKHR); RETURN(AcquireNextImage2KHR); RETURN(QueuePresentKHR); RETURN(WaitForPresentKHR);
#undef RETURN
  if(std::strcmp(name,"vkEnumeratePhysicalDeviceGroupsKHR")==0) return (PFN_vkVoidFunction)vkEnumeratePhysicalDeviceGroups;
  auto i=instance(h); return i?i->gipa(h,name):nullptr;
}
EXPORTED VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface* info) {
  if(!info || info->loaderLayerInterfaceVersion<2) return VK_ERROR_INITIALIZATION_FAILED;
  info->loaderLayerInterfaceVersion=2; info->pfnGetInstanceProcAddr=vkGetInstanceProcAddr; info->pfnGetDeviceProcAddr=vkGetDeviceProcAddr; info->pfnGetPhysicalDeviceProcAddr=nullptr; return VK_SUCCESS;
}
