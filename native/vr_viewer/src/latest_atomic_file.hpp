#pragma once
#include <condition_variable>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <atomic>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <utility>

namespace nadoc_vr {
// One in-flight write + one latest value. Filesystem stalls never hold the queue
// mutex. Coalescing is appropriate for poses, not ordered edit/command streams.
class LatestAtomicFile {
public:
    using Writer=std::function<void(const std::string&,const std::string&)>;
private:
    std::mutex mutex_;
    std::condition_variable changed_;
    std::optional<std::pair<std::string,std::string>> pending_;
    bool stopped_=false;
    Writer writer_;
    std::atomic<uint64_t> failures_{0};
    std::atomic<double> maxWriteMs_{0};
    std::thread worker_;
    static void write(const std::string& path,const std::string& bytes){
        const auto temporary=path+".next";
        std::ofstream output(temporary,std::ios::binary|std::ios::trunc);
        output.write(bytes.data(),static_cast<std::streamsize>(bytes.size()));output.close();
        if(!output)throw std::runtime_error("Cannot publish latest pose");
        std::filesystem::rename(temporary,path);
    }
public:
    explicit LatestAtomicFile(Writer writer=write):writer_(std::move(writer)),worker_([this]{
        for(;;){
            std::optional<std::pair<std::string,std::string>> next;
            {std::unique_lock lock(mutex_);changed_.wait(lock,[this]{return stopped_ || pending_.has_value();});
                if(!pending_ && stopped_)return;
                next.swap(pending_);}
            const auto begin=std::chrono::steady_clock::now();
            try{writer_(next->first,next->second);}catch(...){++failures_;}
            maxWriteMs_=std::max(maxWriteMs_.load(),std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count());
        }
    }){}
    ~LatestAtomicFile(){ {std::lock_guard lock(mutex_);stopped_=true;}changed_.notify_one();worker_.join(); }
    void publish(std::string path,std::string bytes){
        {std::lock_guard lock(mutex_);pending_=std::make_pair(std::move(path),std::move(bytes));}
        changed_.notify_one();
    }
    double maxWriteMs()const{return maxWriteMs_.load();}
    uint64_t failures()const{return failures_.load();}
};
}
