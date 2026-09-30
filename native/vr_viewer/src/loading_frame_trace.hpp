#pragma once
#include <chrono>
#include "async_trace.hpp"
#include <iostream>
#include <sstream>
#include <string_view>

namespace nadoc_vr {
// Diagnostic-only CPU wall times. These include work outside renderFrame(); they
// are NOT GPU durations or proof of compositor scanout/drop counts.
class LoadingFrameTrace {
    using Clock=std::chrono::steady_clock;
    Clock::time_point mark_=Clock::now(),lastFrame_=mark_;
    bool enabled_=false;
    const char* prefix_;
    double displayedPercent_=0;
    static double milliseconds(Clock::duration value) {
        return std::chrono::duration<double,std::milli>(value).count();
    }
 public:
    explicit LoadingFrameTrace(const char* prefix="VR_LOAD_TRACE"):prefix_(prefix){}
    void begin(bool enabled) {enabled_=enabled;mark_=Clock::now();if(std::string_view(prefix_)!="VR_LOAD_TRACE")lastFrame_=mark_;}
    void mark(std::string_view phase,double percent,std::string_view target) {
        const auto now=Clock::now();
        if(enabled_) {
            const double elapsed=milliseconds(now-mark_);
            const double gap=milliseconds(now-lastFrame_);
            // Every completed outer frame is needed for unbiased percentiles,
            // including frames whose work happened before renderFrame().
            if(elapsed>=5 || phase=="frame") {
                const double epoch=std::chrono::duration<double,std::milli>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
                std::ostringstream line;
                line<<prefix_<<" epoch_ms="<<std::fixed<<epoch
                         <<" stage="<<phase<<" cpu_wall_ms="<<elapsed
                         <<" frame_gap_ms="<<gap<<" requested="<<target
                         <<" percent="<<percent<<" prior_frame_percent="<<displayedPercent_<<'\n';
                nadoc_vr::writeTrace(line.str());
            }
        }
        mark_=now;
        if(phase=="frame") {lastFrame_=now;displayedPercent_=percent;}
    }
};
}
