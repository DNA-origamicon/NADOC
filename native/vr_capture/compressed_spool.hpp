#pragma once
#include <array>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>

namespace nadoc_capture {
inline uint64_t availableMemoryBytes() {
  std::ifstream input("/proc/meminfo"); std::string key,unit; uint64_t value=0;
  while(input>>key>>value>>unit) if(key=="MemAvailable:") return value*1024;
  return 0; // Unknown memory headroom is a rejection, never permission.
}
inline bool memoryHeadroom(uint64_t available,uint64_t additional,uint64_t reserve) {
  return available>=reserve && additional<=available-reserve;
}
inline constexpr size_t maximumSpoolBytes=2ULL*1024*1024*1024;
inline size_t recordingSpoolBytes(size_t configuredCap,uint64_t durationNs) noexcept {
  constexpr uint64_t fullWindowNs=5000000000ULL;
  constexpr size_t minimum=16ULL*1024*1024;
  // The public configuration is bounded to 2 GiB. Reject out-of-contract
  // values before multiplication; the largest valid product fits uint64_t.
  if(!configuredCap || configuredCap>maximumSpoolBytes || !durationNs) return 0;
  if(durationNs>=fullWindowNs) return configuredCap; // Preserve full cap exactly.
  const long pageSize=sysconf(_SC_PAGESIZE); if(pageSize<=0) return 0;
  const size_t page=size_t(pageSize);
  const uint64_t scaled=(uint64_t(configuredCap)*durationNs+fullWindowNs-1)/fullWindowNs;
  const size_t desired=std::max<size_t>(std::min(configuredCap,minimum),size_t(scaled));
  return std::min(configuredCap,(desired+page-1)/page*page);
}
struct SpoolFrame {
  uint64_t present=0,request=0,swapchain=0,rawBytes=0;
  uint64_t compressionBegin=0,compressionEnd=0,queued=0,spooled=0,spoolCopyNs=0;
  uint32_t width=0,height=0,format=0;
  size_t offset=0,size=0;
};
class CompressedSpool {
public:
  enum class Reservation { Success, BytesFull, DescriptorsFull };
  static constexpr size_t descriptorCapacity=2048;
  struct Entry { SpoolFrame frame; std::atomic<bool> ready{false}; };
  std::array<Entry,descriptorCapacity> entries;
  CompressedSpool()=default;
  ~CompressedSpool() { release(); }
  CompressedSpool(const CompressedSpool&)=delete;
  CompressedSpool& operator=(const CompressedSpool&)=delete;
  bool allocate(size_t bytes) {
    if(bytes!=capacity_) {
      release();
      void* memory=mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
      if(memory==MAP_FAILED) return false;
      data_=static_cast<unsigned char*>(memory); capacity_=bytes;
      noHugePages_=madvise(data_,capacity_,MADV_NOHUGEPAGE)==0;
      noFork_=madvise(data_,capacity_,MADV_DONTFORK)==0;
      if(!noFork_) { release(); return false; }
    }
    // First touch and any page-in happen during preparation, before the timer.
    const size_t page=size_t(sysconf(_SC_PAGESIZE));
    for(size_t offset=0;offset<capacity_;offset+=page) data_[offset]=0;
    reset();
    return true;
  }
  bool resident() const {
    if(!data_ || !capacity_) return false;
    const size_t page=size_t(sysconf(_SC_PAGESIZE));
    std::vector<unsigned char> pages((capacity_+page-1)/page);
    if(mincore(data_,capacity_,pages.data())!=0) return false;
    for(auto flag:pages) if(!(flag&1)) return false;
    return true;
  }
  void release() noexcept {
    if(data_) munmap(data_,capacity_);
    data_=nullptr; capacity_=0; noHugePages_=false; noFork_=false; reset();
  }
  void reset() noexcept {
    for(size_t i=0;i<count_.load();i++) entries[i].ready=false;
    used_=0; count_=0; discardedPrefix_=0; discardedTail_=0;
  }
  // Only the sealed writer may call these functions. Descriptor metadata stays
  // valid after source pages are discarded; source bytes do not and cannot be
  // used for a retry after an IO error. Never discard a partly consumed page.
  bool discardCopiedPrefix(size_t copied) noexcept {
    const size_t page=size_t(sysconf(_SC_PAGESIZE));
    if(copied>used() || copied<discardedPrefix_) { errno=EINVAL; return false; }
    const size_t end=copied/page*page;
    if(end>discardedPrefix_) {
      if(madvise(data_+discardedPrefix_,end-discardedPrefix_,MADV_DONTNEED)!=0) return false;
      discardedPrefix_=end;
    }
    return true;
  }
  bool discardUnusedTail() noexcept {
    const size_t page=size_t(sysconf(_SC_PAGESIZE));
    const size_t begin=(used()+page-1)/page*page,end=capacity_/page*page;
    if(begin<end) {
      if(madvise(data_+begin,end-begin,MADV_DONTNEED)!=0) return false;
      discardedTail_=end-begin;
    }
    return true;
  }
  size_t discardedPrefix() const noexcept { return discardedPrefix_; }
  size_t discardedTail() const noexcept { return discardedTail_; }
  Reservation reserve(size_t bytes,size_t& index,size_t& offset) noexcept {
    index=count_.load();
    do { if(index==descriptorCapacity) return Reservation::DescriptorsFull; }
    while(!count_.compare_exchange_weak(index,index+1));
    offset=used_.load();
    do { if(bytes>capacity_-offset) return Reservation::BytesFull; }
    while(!used_.compare_exchange_weak(offset,offset+bytes));
    return Reservation::Success;
  }
  unsigned char* data() noexcept { return data_; }
  size_t capacity() const noexcept { return capacity_; }
  size_t used() const noexcept { return used_.load(); }
  size_t count() const noexcept { return count_.load(); }
  bool noHugePages() const noexcept { return noHugePages_; }
  bool noFork() const noexcept { return noFork_; }
  bool completeLayout() const noexcept {
    // Descriptor order can differ from reservation order across compressors.
    // Verify exact coverage before persisting a shared pack, including on abort.
    std::array<std::pair<size_t,size_t>,descriptorCapacity> spans;
    size_t count=0;
    for(size_t n=0;n<count_.load();n++) if(entries[n].ready.load()) spans[count++]={entries[n].frame.offset,entries[n].frame.size};
    std::sort(spans.begin(),spans.begin()+count);
    size_t cursor=0;
    for(size_t n=0;n<count;n++) {
      if(spans[n].first!=cursor || spans[n].second>used_.load()-cursor) return false;
      cursor+=spans[n].second;
    }
    return cursor==used_.load();
  }
private:
  unsigned char* data_=nullptr; size_t capacity_=0,discardedPrefix_=0,discardedTail_=0; bool noHugePages_=false,noFork_=false;
  std::atomic<size_t> used_{0},count_{0};
};
}
