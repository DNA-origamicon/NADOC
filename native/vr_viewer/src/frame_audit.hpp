#pragma once
#include "async_trace.hpp"
#include <array>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <string_view>

namespace nadoc_vr {
class FrameAudit;
inline thread_local FrameAudit* activeFrameAudit = nullptr;
// Opt-in, exclusive CPU wall intervals; no GPU synchronization or readback.
// One bounded asynchronous record per outer loop, including pre-render work.
class FrameAudit {
    using Clock = std::chrono::steady_clock;
    struct Phase { std::string_view name; double ms = 0; unsigned calls = 0; };
    std::array<Phase, 96> phases_{}, calculations_{};
    size_t calculationCount_ = 0;
    size_t count_ = 0;
    bool enabled_ = [] { const char* v = std::getenv("NADOC_VR_FRAME_AUDIT"); return v && std::string_view(v) == "1"; }();
    Clock::time_point start_{}, last_{};
    double epoch_ = 0;
    unsigned overflow_ = 0;
public:
    void begin() {
        if (!enabled_) return;
        count_ = 0; calculationCount_ = 0; overflow_ = 0;
        activeFrameAudit = this;
        start_ = last_ = Clock::now();
        epoch_ = std::chrono::duration<double, std::milli>(std::chrono::system_clock::now().time_since_epoch()).count();
    }
    void mark(std::string_view name) {
        if (!enabled_) return;
        const auto now = Clock::now();
        const auto ms = std::chrono::duration<double, std::milli>(now-last_).count();
        last_ = now;
        size_t index = 0;
        while (index < count_ && phases_[index].name != name) ++index;
        if (index == phases_.size()) { ++overflow_; return; }
        if (index == count_) { phases_[count_++] = {name, 0, 0}; }
        phases_[index].ms += ms; ++phases_[index].calls;
    }
    void calculation(std::string_view name, double ms) {
        size_t index=0;
        while(index<calculationCount_ && calculations_[index].name!=name)++index;
        if(index==calculations_.size()){++overflow_;return;}
        if(index==calculationCount_)calculations_[calculationCount_++]={name,0,0};
        calculations_[index].ms+=ms; ++calculations_[index].calls;
    }
    ~FrameAudit(){if(activeFrameAudit==this)activeFrameAudit=nullptr;}
    void finish(uint64_t frame, std::string_view representation, std::string_view tool,
                double period, bool submitted, bool focused) {
        if (!enabled_) return;
        mark("tail");
        activeFrameAudit=nullptr;
        std::ostringstream out;
        out << std::fixed << std::setprecision(6) << "VR_FRAME_AUDIT epoch_ms=" << epoch_
            << " frame=" << frame << " representation=" << representation << " tool=" << tool
            << " period_ms=" << period << " submitted=" << submitted << " focused=" << focused
            << " total_ms=" << std::chrono::duration<double, std::milli>(last_-start_).count()
            << " overflow=" << overflow_;
        for (size_t i=0; i<count_; ++i)
            out << ' ' << phases_[i].name << "_ms=" << phases_[i].ms
                << ' ' << phases_[i].name << "_calls=" << phases_[i].calls;
        for(size_t i=0;i<calculationCount_;++i)
            out << " calc_" << calculations_[i].name << "_ms=" << calculations_[i].ms
                << " calc_" << calculations_[i].name << "_calls=" << calculations_[i].calls;
        out << '\n'; writeTrace(out.str());
    }
};
// Inclusive diagnostic subscopes overlap parent phases and must not be summed.
class CalculationScope {
    using Clock=std::chrono::steady_clock;
    FrameAudit* audit_=activeFrameAudit;
    std::string_view name_;
    Clock::time_point started_{};
public:
    explicit CalculationScope(std::string_view name):name_(name){if(audit_)started_=Clock::now();}
    ~CalculationScope(){if(audit_)audit_->calculation(name_,std::chrono::duration<double,std::milli>(Clock::now()-started_).count());}
};
}
