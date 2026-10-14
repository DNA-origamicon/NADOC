#pragma once
#include <mutex>
#include <pthread.h>
#include <system_error>

namespace nadoc_capture {
// The compositor uses real-time threads; capture workers use normal scheduling.
// Protocol setup is process-local. A reported fallback keeps capture usable on
// platforms without PI support without silently claiming priority inheritance.
class PriorityMutex {
  pthread_mutex_t native_{};
  std::mutex fallback_;
  bool inherited_=false;
  int error_=0;
public:
  PriorityMutex() noexcept {
    pthread_mutexattr_t attr;
    error_=pthread_mutexattr_init(&attr);
    if(error_) return;
    error_=pthread_mutexattr_setprotocol(&attr,PTHREAD_PRIO_INHERIT);
    if(!error_) error_=pthread_mutex_init(&native_,&attr);
    pthread_mutexattr_destroy(&attr);
    inherited_=error_==0;
  }
  ~PriorityMutex() { if(inherited_) pthread_mutex_destroy(&native_); }
  PriorityMutex(const PriorityMutex&)=delete;
  PriorityMutex& operator=(const PriorityMutex&)=delete;
  bool priorityInheritance() const noexcept { return inherited_; }
  int initializationError() const noexcept { return error_; }
  void lock() {
    if(!inherited_) { fallback_.lock(); return; }
    const int result=pthread_mutex_lock(&native_);
    if(result) throw std::system_error(result,std::generic_category(),"capture mutex lock");
  }
  bool try_lock() noexcept {
    return inherited_?pthread_mutex_trylock(&native_)==0:fallback_.try_lock();
  }
  void unlock() noexcept {
    if(inherited_) pthread_mutex_unlock(&native_); else fallback_.unlock();
  }
};
}
