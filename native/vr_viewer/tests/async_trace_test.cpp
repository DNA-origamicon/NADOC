#include "async_trace.hpp"
#include <atomic>
#include <cassert>
#include <future>

// Model a disk/pipe writer that stops draining. The render producer must keep
// progressing, including once the bounded trace queue fills.
class BlockedBuffer : public std::stringbuf {
public:
    std::promise<void> entered, release;
    std::shared_future<void> gate=release.get_future().share();
    std::atomic<bool> first=true;
    std::streamsize xsputn(const char* s,std::streamsize n) override {
        if(first.exchange(false)){entered.set_value();gate.wait();}
        return std::stringbuf::xsputn(s,n);
    }
};
class FlushBuffer : public std::stringbuf {
public:
    std::promise<void> flushed;
    bool first=true;
    int sync() override {
        if(first){first=false;flushed.set_value();}
        return std::stringbuf::sync();
    }
};
int main() {
    using namespace std::chrono_literals;
    {
        FlushBuffer buffer;
        std::ostream output(&buffer);
        nadoc_vr::TraceSink sink(output);
        sink.push("VR_SCENE_APPLIED revision=1\n");
        // No following frame record or shutdown is needed to flush a quiet ack.
        assert(buffer.flushed.get_future().wait_for(2s)==std::future_status::ready);
    }
    // Negative control: the former direct logging path waits for the writer.
    {
        BlockedBuffer direct;
        std::ostream output(&direct);
        auto writer=std::async(std::launch::async,[&]{output<<"hover\n";});
        const bool entered=direct.entered.get_future().wait_for(2s)==std::future_status::ready;
        const bool stalled=writer.wait_for(100ms)==std::future_status::timeout;
        direct.release.set_value();writer.get();
        assert(entered && stalled);
    }
    BlockedBuffer buffer;
    std::ostream output(&buffer);
    {
        nadoc_vr::TraceSink sink(output);
        sink.push("first\n");
        const bool blocked=buffer.entered.get_future().wait_for(2s)==std::future_status::ready;
        auto producer=std::async(std::launch::async,[&]{
            for(int i=0;i<20000;++i)sink.push("frame\n");
        });
        const bool responsive=producer.wait_for(1s)==std::future_status::ready;
        buffer.release.set_value(); // Release even on failure; no hung teardown.
        producer.get();
        assert(blocked && responsive);
    }
    const auto records=buffer.str();
    assert(records.starts_with("first\nVR_TRACE_DROPPED epoch_ms="));
    assert(records.find(" count=3616\n")!=std::string::npos);
    size_t frames=0,at=0;
    while((at=records.find("frame\n",at))!=std::string::npos){++frames;at+=6;}
    assert(frames==16384);
    std::cout<<"Blocked output: producer completed 20000 records; 16384 retained, 3616 explicitly dropped\n";
}
