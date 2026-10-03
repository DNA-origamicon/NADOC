#pragma once
#include <atomic>
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

namespace nadoc_vr {
// Event snapshots contain command sequences: unlike poses, never coalesce them.
// Filesystem work happens without the queue lock. Bound memory with backpressure
// only if a persistently stalled writer accumulates 256 pending publications.
class OrderedAtomicFile {
public:
    using Writer=std::function<void(const std::string&,const std::string&)>;
private:
    std::mutex mutex_;
    std::condition_variable changed_, space_;
    std::deque<std::pair<std::string,std::string>> pending_;
    bool stopped_=false;
    Writer writer_;
    std::atomic<unsigned long> failures_{0};
    std::thread worker_;
    static void write(const std::string& path,const std::string& bytes) {
        const auto temporary=path+".events-next";
        std::ofstream output(temporary,std::ios::binary|std::ios::trunc);
        output.write(bytes.data(),static_cast<std::streamsize>(bytes.size()));output.close();
        if(!output)throw std::runtime_error("Cannot publish VR event state");
        std::filesystem::rename(temporary,path);
    }
public:
    explicit OrderedAtomicFile(Writer writer=write):writer_(std::move(writer)),worker_([this] {
        for(;;) {
            std::pair<std::string,std::string> next;
            { std::unique_lock lock(mutex_);
              changed_.wait(lock,[this]{return stopped_ || !pending_.empty();});
              if(pending_.empty())return;
              next=std::move(pending_.front());pending_.pop_front(); }
            space_.notify_one();
            try { writer_(next.first,next.second); } catch(...) { ++failures_; }
        }
    }) {}
    ~OrderedAtomicFile() {
        {std::lock_guard lock(mutex_);stopped_=true;}
        changed_.notify_one();worker_.join();
    }
    void publish(std::string path,std::string bytes) {
        {std::unique_lock lock(mutex_);
         space_.wait(lock,[this]{return pending_.size()<256;});
         pending_.emplace_back(std::move(path),std::move(bytes));}
        changed_.notify_one();
    }
    unsigned long failures()const{return failures_.load();}
};
}
