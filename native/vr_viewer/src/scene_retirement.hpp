#pragma once
// CPU scene deletion can itself take hundreds of milliseconds. Keep cancelled
// parse results off the XR thread. One disposer, at most two queued snapshots.
class SceneRetirement {
    std::mutex mutex_;
    std::condition_variable changed_;
    std::deque<std::shared_ptr<void>> queue_;
    bool stopping_=false;
    std::thread worker_;
public:
    SceneRetirement():worker_([this]{
        for(;;){
            std::shared_ptr<void> obsolete;
            {std::unique_lock lock(mutex_);changed_.wait(lock,[this]{return stopping_ || !queue_.empty();});
                if(queue_.empty() && stopping_)return;
                obsolete=std::move(queue_.front());queue_.pop_front();}
            obsolete.reset();
        }
    }){}
    ~SceneRetirement(){ {std::lock_guard lock(mutex_);stopping_=true;}changed_.notify_one();worker_.join(); }
    bool full(){std::lock_guard lock(mutex_);return queue_.size()>=2;}
    // Payloads must contain CPU data only: GL resources stay on the context thread.
    template<class T> void retire(T scene){auto payload=std::make_shared<T>(std::move(scene));
        std::lock_guard lock(mutex_);queue_.push_back(std::move(payload));changed_.notify_one();}
};
