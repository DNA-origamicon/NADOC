#pragma once
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <memory>
#include <sys/mman.h>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

namespace nadoc_capture {
struct ArchiveOps {
  int (*openFile)(const char*,int,mode_t)=[](const char* path,int flags,mode_t mode){return ::open(path,flags,mode);};
  ssize_t (*writeFile)(int,const void*,size_t)=::write;
  int (*syncData)(int)=::fdatasync;
  int (*syncDirectory)(int)=::fsync;
  int (*closeFile)(int)=::close;
  int (*truncateFile)(int,off_t)=::ftruncate;
  int (*directAlignment)(int,uint32_t*,uint32_t*)=[](int fd,uint32_t* memory,uint32_t* offset){
    struct statx information{};
    if(::statx(fd,"",AT_EMPTY_PATH,STATX_DIOALIGN,&information)!=0) return -1;
    if(!(information.stx_mask&STATX_DIOALIGN) || !information.stx_dio_mem_align || !information.stx_dio_offset_align) { errno=EOPNOTSUPP; return -1; }
    *memory=information.stx_dio_mem_align; *offset=information.stx_dio_offset_align; return 0;
  };
};
inline uint64_t archiveNowNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct ArchiveResult {
  uint64_t begin=0,writeEnd=0,syncBegin=0,syncEnd=0,end=0;
  uint64_t writtenBytes=0,writeCalls=0,maxWriteBytes=0,sourceReleaseNs=0,pacingNs=0;
  uint64_t physicalWrittenBytes=0,paddingBytes=0,truncateNs=0;
  uint32_t directMemoryAlignment=0,directOffsetAlignment=0;
  int error=0,closeError=0;
  const char* stage="none";
  bool synced=false,closed=false;
  bool direct=false,truncated=false;
  bool success() const { return !error && !closeError && synced && closed; }
};
struct ArchiveWritePolicy {
  size_t chunkBytes=std::numeric_limits<size_t>::max();
  uint64_t bytesPerSecond=0;
  bool direct=false;
  bool sourceDontFork=false;
  // Called only after successful synchronous write copied these source bytes.
  // A false return stops permanently: discarded input must never be retried.
  bool (*consumed)(void*,size_t)=nullptr;
  void* context=nullptr;
};
// Batches bound open descriptors; an optional policy bounds write syscalls and
// hands off source pages. Only own-file fdatasync is used, never global sync.
class ArchiveBatch {
public:
  static constexpr size_t capacity=16;
  explicit ArchiveBatch(const ArchiveOps& ops):ops_(ops) {}
  ~ArchiveBatch() { for(auto& file:files_) if(file.fd>=0) ops_.closeFile(file.fd); }
  ArchiveBatch(const ArchiveBatch&)=delete;
  ArchiveBatch& operator=(const ArchiveBatch&)=delete;
  size_t size() const { return count_; }
  void append(const char* path,const void* data,size_t bytes,size_t sourceIndex,const ArchiveWritePolicy& policy={}) {
    auto& file=files_.at(count_); ++count_; file.sourceIndex=sourceIndex; auto& r=file.result; r.begin=archiveNowNs();
    r.direct=policy.direct;
    file.fd=ops_.openFile(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|(policy.direct?O_DIRECT:0),0666);
    if(file.fd<0) { r.error=errno; r.stage="open"; r.writeEnd=archiveNowNs(); return; }
    size_t written=0;
    if(!policy.chunkBytes) { r.error=EINVAL; r.stage="write_policy"; r.writeEnd=archiveNowNs(); return; }
    if(policy.direct) { writeDirect(file.fd,data,bytes,policy,r); r.writeEnd=archiveNowNs(); return; }
    while(written<bytes) {
      const size_t requested=std::min(bytes-written,policy.chunkBytes);
      const uint64_t chunkBegin=archiveNowNs();
      ++r.writeCalls; r.maxWriteBytes=std::max<uint64_t>(r.maxWriteBytes,requested);
      const ssize_t n=ops_.writeFile(file.fd,static_cast<const unsigned char*>(data)+written,requested);
      if(n<0 && errno==EINTR) continue;
      if(n<=0 || size_t(n)>requested) { r.error=n<0?errno:EIO; r.stage="write"; break; }
      written+=size_t(n); r.writtenBytes=r.physicalWrittenBytes=written;
      if(policy.consumed) {
        const uint64_t releaseBegin=archiveNowNs();
        const bool released=policy.consumed(policy.context,written);
        r.sourceReleaseNs+=archiveNowNs()-releaseBegin;
        if(!released) { r.error=errno?errno:EIO; r.stage="source_release"; break; }
      }
      if(policy.bytesPerSecond) {
        const uint64_t deadline=chunkBegin+(uint64_t(n)*1000000000ULL+policy.bytesPerSecond-1)/policy.bytesPerSecond;
        const uint64_t before=archiveNowNs();
        if(before<deadline) {
          // No credit accumulates during slow IO, preventing catch-up bursts.
          std::this_thread::sleep_until(std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));
          r.pacingNs+=archiveNowNs()-before;
        }
      }
    }
    r.writeEnd=archiveNowNs();
  }
  template<class Consumer> void flush(Consumer&& consume) {
    for(size_t index=0;index<count_;index++) {
      auto& file=files_[index]; auto& r=file.result;
      if(file.fd>=0) {
        if(!r.error) {
          r.syncBegin=archiveNowNs(); int result;
          do { result=ops_.syncData(file.fd); } while(result<0 && errno==EINTR);
          r.syncEnd=archiveNowNs(); r.synced=result==0;
          if(result<0) { r.error=errno; r.stage="fdatasync"; }
        }
        // Linux releases the descriptor even when close reports an error.
        // Retrying could close a descriptor that another thread just acquired.
        const int result=ops_.closeFile(file.fd); file.fd=-1; r.closed=result==0;
        if(result<0) { r.closeError=errno; if(!r.error) { r.error=errno; r.stage="close"; } }
      }
      r.end=archiveNowNs(); consume(file.sourceIndex,r);
    }
    for(size_t index=0;index<count_;index++) files_[index]=Pending{};
    count_=0;
  }
private:
  void writeDirect(int fd,const void* data,size_t bytes,const ArchiveWritePolicy& policy,ArchiveResult& r) {
    // Linux forbids concurrent fork with private direct-IO source mappings,
    // unless the dedicated mappings have explicitly opted out of inheritance.
    if(!policy.sourceDontFork) { r.error=EINVAL; r.stage="direct_source_fork_policy"; return; }
    if(ops_.directAlignment(fd,&r.directMemoryAlignment,&r.directOffsetAlignment)!=0) { r.error=errno; r.stage="direct_alignment_query"; return; }
    const size_t memory=r.directMemoryAlignment,offset=r.directOffsetAlignment,block=std::max(memory,offset);
    // Limit scratch to 1 MiB and reject unknown/non-power-of-two requirements.
    // Stronger common alignment also keeps both buffer and file offset valid
    // after a supported short write. No buffered fallback is ever attempted.
    if(!memory || !offset || (memory&(memory-1)) || (offset&(offset-1)) || memory>size_t(sysconf(_SC_PAGESIZE)) || block>1024*1024 || policy.chunkBytes%block || reinterpret_cast<uintptr_t>(data)%memory || bytes>size_t(std::numeric_limits<off_t>::max())) {
      r.error=EINVAL; r.stage="direct_alignment"; return;
    }
    const size_t body=bytes/block*block,tail=bytes-body;
    const auto unmap=[block](void* pointer){if(pointer) munmap(pointer,block);};
    std::unique_ptr<void,decltype(unmap)> scratch(nullptr,unmap);
    if(tail) {
      void* allocated=mmap(nullptr,block,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
      if(allocated==MAP_FAILED) { r.error=errno; r.stage="direct_tail_allocation"; return; }
      scratch.reset(allocated);
      if(madvise(scratch.get(),block,MADV_DONTFORK)!=0) { r.error=errno; r.stage="direct_tail_fork_policy"; return; }
      std::memset(scratch.get(),0,block);
      std::memcpy(scratch.get(),static_cast<const unsigned char*>(data)+body,tail);
      r.paddingBytes=block-tail;
    }
    const size_t physical=body+(tail?block:0);
    size_t written=0;
    while(written<physical) {
      const bool finalBlock=written>=body;
      const size_t requested=finalBlock?block:std::min(body-written,policy.chunkBytes);
      const void* source=finalBlock?scratch.get():static_cast<const unsigned char*>(data)+written;
      const uint64_t chunkBegin=archiveNowNs();
      ++r.writeCalls; r.maxWriteBytes=std::max<uint64_t>(r.maxWriteBytes,requested);
      const ssize_t count=ops_.writeFile(fd,source,requested);
      if(count<0 && errno==EINTR) continue;
      if(count<=0 || size_t(count)>requested) { r.error=count<0?errno:EIO; r.stage="direct_write"; return; }
      written+=size_t(count); r.physicalWrittenBytes=written; r.writtenBytes=std::min(written,bytes);
      if(size_t(count)%block) { r.error=EIO; r.stage="direct_short_write_alignment"; return; }
      if(policy.consumed) {
        const uint64_t releaseBegin=archiveNowNs();
        const bool released=policy.consumed(policy.context,r.writtenBytes);
        r.sourceReleaseNs+=archiveNowNs()-releaseBegin;
        if(!released) { r.error=errno?errno:EIO; r.stage="source_release"; return; }
      }
      if(policy.bytesPerSecond) {
        const uint64_t deadline=chunkBegin+(uint64_t(count)*1000000000ULL+policy.bytesPerSecond-1)/policy.bytesPerSecond;
        const uint64_t before=archiveNowNs();
        if(before<deadline) {
          std::this_thread::sleep_until(std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));
          r.pacingNs+=archiveNowNs()-before;
        }
      }
    }
    const uint64_t truncateBegin=archiveNowNs(); int truncated;
    do { truncated=ops_.truncateFile(fd,off_t(bytes)); } while(truncated<0 && errno==EINTR);
    r.truncateNs=archiveNowNs()-truncateBegin; r.truncated=truncated==0;
    if(truncated<0) { r.error=errno; r.stage="direct_truncate"; }
  }
  struct Pending { int fd=-1; size_t sourceIndex=0; ArchiveResult result; };
  const ArchiveOps& ops_; std::array<Pending,capacity> files_; size_t count_=0;
};
inline ArchiveResult syncArchiveDirectory(const ArchiveOps& ops,const char* path) {
  ArchiveResult r; r.begin=archiveNowNs();
  const int fd=ops.openFile(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC,0);
  if(fd<0) { r.error=errno; r.stage="directory_open"; r.end=archiveNowNs(); return r; }
  r.syncBegin=archiveNowNs(); int result;
  do { result=ops.syncDirectory(fd); } while(result<0 && errno==EINTR);
  r.syncEnd=archiveNowNs(); r.synced=result==0;
  if(result<0) { r.error=errno; r.stage="directory_fsync"; }
  result=ops.closeFile(fd); r.closed=result==0;
  if(result<0) { r.closeError=errno; if(!r.error) { r.error=errno; r.stage="directory_close"; } }
  r.end=archiveNowNs(); return r;
}
}
