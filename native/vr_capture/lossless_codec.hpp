#pragma once
// Zstandard's stable public C ABI (no development headers/install required).
// https://facebook.github.io/zstd/zstd_manual.html
#include <dlfcn.h>
#include <zlib.h>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_capture {
class LosslessCodec {
 public:
  using Bound = size_t (*)(size_t);
  using Create = void* (*)();
  using Free = size_t (*)(void*);
  using Compress = size_t (*)(void*,void*,size_t,const void*,size_t,int);
  using IsError = unsigned (*)(size_t);
  using Version = const char* (*)();
  explicit LosslessCodec(const std::string& requested="zstd") {
    if(requested=="zstd") {
      library_=dlopen("libzstd.so.1",RTLD_NOW|RTLD_LOCAL);
      if(library_) {
        bound_=reinterpret_cast<Bound>(dlsym(library_,"ZSTD_compressBound"));
        create_=reinterpret_cast<Create>(dlsym(library_,"ZSTD_createCCtx"));
        free_=reinterpret_cast<Free>(dlsym(library_,"ZSTD_freeCCtx"));
        compress_=reinterpret_cast<Compress>(dlsym(library_,"ZSTD_compressCCtx"));
        error_=reinterpret_cast<IsError>(dlsym(library_,"ZSTD_isError"));
        version_=reinterpret_cast<Version>(dlsym(library_,"ZSTD_versionString"));
        if(!bound_ || !create_ || !free_ || !compress_ || !error_ || !version_) { dlclose(library_); library_=nullptr; }
      }
    }
  }
  ~LosslessCodec() { if(library_) dlclose(library_); }
  LosslessCodec(const LosslessCodec&)=delete;
  LosslessCodec& operator=(const LosslessCodec&)=delete;
  const char* name() const { return library_?"zstd":"zlib"; }
  const char* version() const { return library_?version_():zlibVersion(); }
  const char* suffix() const { return library_?".bgra.zst":".bgra.z"; }
  class Worker {
   public:
    explicit Worker(const LosslessCodec& codec):codec_(codec) {
      if(codec_.library_) { context_=codec_.create_(); if(!context_) throw std::bad_alloc(); }
    }
    ~Worker() { if(context_) codec_.free_(context_); }
    size_t compress(const void* source,size_t bytes) {
      size_t bound=codec_.library_?codec_.bound_(bytes):compressBound(bytes);
      if(buffer.size()<bound) buffer.resize(bound);
      if(codec_.library_) {
        size_t result=codec_.compress_(context_,buffer.data(),buffer.size(),source,bytes,1);
        if(codec_.error_(result)) throw std::runtime_error("Zstandard compression failed");
        return result;
      }
      uLongf result=buffer.size();
      if(compress2(buffer.data(),&result,static_cast<const Bytef*>(source),bytes,Z_BEST_SPEED)!=Z_OK) throw std::runtime_error("zlib compression failed");
      return result;
    }
    std::vector<unsigned char> buffer;
   private:
    const LosslessCodec& codec_;
    void* context_=nullptr;
  };
 private:
  void* library_=nullptr;
  Bound bound_=nullptr; Create create_=nullptr; Free free_=nullptr;
  Compress compress_=nullptr; IsError error_=nullptr; Version version_=nullptr;
};
} // namespace nadoc_capture
