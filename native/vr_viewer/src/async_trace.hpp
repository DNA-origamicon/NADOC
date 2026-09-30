#pragma once
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <chrono>

namespace nadoc_vr {
// Profiling must not reintroduce disk-write stalls on the XR thread. Bounded
// FIFO preserves samples; any overflow is explicit and invalidates timing gates.
class TraceSink {
    std::mutex mutex_;
    std::condition_variable changed_;
    std::deque<std::string> queue_;
    bool stopping_=false;
    size_t dropped_=0;
    std::thread worker_;
public:
    TraceSink():worker_([this]{for(;;){
        std::string line;size_t dropped=0;
        {std::unique_lock lock(mutex_);changed_.wait(lock,[this]{return stopping_ || !queue_.empty();});
            if(queue_.empty() && stopping_)return;
            line=std::move(queue_.front());queue_.pop_front();dropped=std::exchange(dropped_,0);}
        if(dropped)std::cout<<"VR_TRACE_DROPPED epoch_ms="<<std::fixed
            <<std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count()<<" count="<<dropped<<'\n';
        std::cout<<line;
    }}){}
    ~TraceSink(){ {std::lock_guard lock(mutex_);stopping_=true;}changed_.notify_one();worker_.join();std::cout.flush(); }
    void push(std::string line){
        {std::lock_guard lock(mutex_);if(queue_.size()>=16384){++dropped_;return;}queue_.push_back(std::move(line));}
        changed_.notify_one();
    }
};
inline void writeTrace(std::string line){static TraceSink sink;sink.push(std::move(line));}
class TraceRecord {
    std::ostringstream line_;
public:
    template<class T> TraceRecord& operator<<(const T& value){line_<<value;return *this;}
    TraceRecord& operator<<(std::ostream&(*value)(std::ostream&)){value(line_);return *this;}
    ~TraceRecord(){writeTrace(line_.str());}
};
}
