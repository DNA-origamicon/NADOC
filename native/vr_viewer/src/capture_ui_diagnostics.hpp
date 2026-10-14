#pragma once
// Capture-only POD evidence: no allocation, disk IO, GL query or clock when idle.
// Host elapsed durations include driver blocking/descheduling, not GPU busy time.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <string_view>
#include <time.h>
#include <type_traits>

namespace nadoc_vr {
struct CaptureUiFrame {
    static constexpr size_t eventCapacity=16, hoverBytes=96;
    struct Haptic {
        uint32_t hand=0,callsiteLine=0;
        float amplitude=0;
        uint64_t requestNs=0,beginNs=0,endNs=0;
        bool dispatched=false;
        int32_t result=0;
    };
    struct Sidebar {
        std::array<char,hoverBytes+1> hover{};
        bool open=false,truncated=false,previousKnown=false,changeValid=false,changed=false;
        uint64_t updates=0,hits=0,textureHostNs=0,drawCalls=0,drawHostNs=0;
    };
    struct Eye {uint64_t menuCalls=0,menuHostNs=0,copyCalls=0,copyHostNs=0;};
    bool enabled=false;
    uint64_t clockQueries=0,clockErrors=0,eventCount=0,eventOverflow=0;
    std::array<uint64_t,2> requested{},dispatched{},failed{},totalNs{},maxNs{};
    std::array<Haptic,eventCapacity> events{};
    std::array<Sidebar,2> sidebars{};
    std::array<Eye,2> eyes{};
};
static_assert(std::is_trivially_copyable_v<CaptureUiFrame>);

class CaptureUiDiagnostics {
public:
    using Clock=uint64_t(*)();
    enum class Kind {sidebarDraw,menuDraw,backdropCopy};
    static uint64_t monotonic() noexcept {
        timespec value{};
        return clock_gettime(CLOCK_MONOTONIC,&value)==0?
            uint64_t(value.tv_sec)*1000000000+uint64_t(value.tv_nsec):0;
    }
    explicit CaptureUiDiagnostics(Clock clock=monotonic):clock_(clock){}
    void begin(CaptureUiFrame* frame) {
        frame_=frame;
        if(frame_){*frame_={};frame_->enabled=true;}
        else previousKnown_.fill(false);
    }
    void end(){frame_=nullptr;}
    bool active()const{return frame_!=nullptr;}
    uint64_t stamp() {
        if(!frame_)return 0;
        ++frame_->clockQueries;
        const auto value=clock_();if(!value)++frame_->clockErrors;return value;
    }
    int request(size_t hand,float amplitude,uint32_t line) {
        if(!frame_ || hand>=2)return -1;
        ++frame_->requested[hand];
        if(frame_->eventCount==CaptureUiFrame::eventCapacity){++frame_->eventOverflow;return -1;}
        const auto index=frame_->eventCount++;
        auto& e=frame_->events[index];e.hand=hand;e.amplitude=amplitude;e.callsiteLine=line;e.requestNs=stamp();
        return int(index);
    }
    void dispatched(int token,size_t hand,uint64_t begin,int32_t result) {
        if(!frame_ || hand>=2)return;
        const auto end=stamp(),elapsed=duration(begin,end);
        ++frame_->dispatched[hand];if(result<0)++frame_->failed[hand];
        frame_->totalNs[hand]+=elapsed;frame_->maxNs[hand]=std::max(frame_->maxNs[hand],elapsed);
        if(token>=0 && size_t(token)<frame_->eventCount) {
            auto& e=frame_->events[token];e.dispatched=true;e.beginNs=begin;e.endNs=end;e.result=result;
        }
    }
    void sidebar(size_t hand,bool open,std::string_view hover) {
        if(!frame_ || hand>=2)return;
        auto& s=frame_->sidebars[hand];s.open=open;
        size_t size=std::min(hover.size(),CaptureUiFrame::hoverBytes);s.truncated=size<hover.size();
        // Do not split a UTF-8 sequence at the bounded string boundary.
        if(s.truncated)while(size && (uint8_t(hover[size])&0xc0)==0x80)--size;
        if(size)std::memcpy(s.hover.data(),hover.data(),size);
        s.hover[size]=0;
        s.previousKnown=previousKnown_[hand];
        s.changeValid=s.previousKnown && !s.truncated && !previousTruncated_[hand];
        s.changed=s.changeValid && (s.hover!=previous_[hand] || open!=previousOpen_[hand]);
        previous_[hand]=s.hover;previousKnown_[hand]=true;previousTruncated_[hand]=s.truncated;previousOpen_[hand]=open;
    }
    void texture(size_t hand,bool updated,uint64_t begin) {
        if(!frame_ || hand>=2)return;
        auto& s=frame_->sidebars[hand];
        if(updated){++s.updates;s.textureHostNs+=duration(begin,stamp());}else ++s.hits;
    }
    class Scope {
        CaptureUiDiagnostics* owner_;Kind kind_;int index_;uint64_t start_;
    public:
        Scope(CaptureUiDiagnostics* owner,Kind kind,int index):owner_(owner && owner->active() && index>=0 && index<2?owner:nullptr),kind_(kind),index_(index),start_(owner_?owner_->stamp():0){}
        Scope(const Scope&)=delete;Scope& operator=(const Scope&)=delete;
        ~Scope(){if(owner_)owner_->finish(kind_,index_,start_);}
    };
    static std::string json(const CaptureUiFrame& f) {
        auto boolean=[](bool v){return v?"true":"false";};
        auto quote=[](std::string_view text) {
            std::ostringstream out;out<<'"';
            for(unsigned char c:text) {
                if(c=='"'||c=='\\')out<<'\\'<<char(c);
                else if(c<32)out<<"\\u00"<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(c)<<std::dec;
                else out<<char(c);
            }
            out<<'"';return out.str();
        };
        std::ostringstream out;
        auto pair=[&](const auto& a){out<<'['<<a[0]<<','<<a[1]<<']';};
        out<<"{\"version\":1,\"enabled\":"<<boolean(f.enabled)
            <<",\"clock\":\"CLOCK_MONOTONIC\",\"clock_queries\":"<<f.clockQueries<<",\"clock_errors\":"<<f.clockErrors
            <<",\"gpu_timing_available\":false,\"onscreen_visibility_available\":false"
            <<",\"haptics\":{\"requested\":";pair(f.requested);
        out<<",\"dispatched\":";pair(f.dispatched);out<<",\"failed\":";pair(f.failed);
        out<<",\"host_total_ns\":";pair(f.totalNs);out<<",\"host_max_ns\":";pair(f.maxNs);
        out<<",\"events_overflow\":"<<f.eventOverflow<<",\"events\":[";
        for(size_t i=0;i<f.eventCount;++i){if(i)out<<',';const auto& e=f.events[i];
            out<<"{\"hand\":"<<e.hand<<",\"callsite_line\":"<<e.callsiteLine<<",\"amplitude\":"<<e.amplitude
                <<",\"request_ns\":"<<e.requestNs<<",\"dispatch_begin_ns\":"<<e.beginNs<<",\"dispatch_end_ns\":"<<e.endNs
                <<",\"dispatched\":"<<boolean(e.dispatched)<<",\"xr_result\":"<<(e.dispatched?std::to_string(e.result):"null")<<'}';}
        out<<"]},\"sidebars\":[";
        for(size_t i=0;i<2;++i){if(i)out<<',';const auto& s=f.sidebars[i];
            out<<"{\"hand\":"<<i<<",\"open\":"<<boolean(s.open)<<",\"hover_id\":"<<quote(s.hover.data())
                <<",\"hover_truncated\":"<<boolean(s.truncated)<<",\"hover_previous_known\":"<<boolean(s.previousKnown)
                <<",\"hover_change_valid\":"<<boolean(s.changeValid)<<",\"hover_changed\":"<<boolean(s.changed)
                <<",\"texture_updates\":"<<s.updates<<",\"texture_cache_hits\":"<<s.hits<<",\"texture_update_host_ns\":"<<s.textureHostNs
                <<",\"draw_calls\":"<<s.drawCalls<<",\"draw_host_ns\":"<<s.drawHostNs<<'}';}
        out<<"],\"eyes\":[";
        for(size_t i=0;i<2;++i){if(i)out<<',';const auto& e=f.eyes[i];
            out<<"{\"eye\":\""<<(i?"right":"left")<<"\",\"menu_draw_calls\":"<<e.menuCalls<<",\"menu_host_ns\":"<<e.menuHostNs
                <<",\"backdrop_copy_calls\":"<<e.copyCalls<<",\"backdrop_host_ns\":"<<e.copyHostNs<<'}';}
        out<<"]}";return out.str();
    }
private:
    CaptureUiFrame* frame_=nullptr;Clock clock_;
    std::array<std::array<char,CaptureUiFrame::hoverBytes+1>,2> previous_{};
    std::array<bool,2> previousKnown_{},previousTruncated_{},previousOpen_{};
    uint64_t duration(uint64_t start,uint64_t end) {
        if(!start || end<start){++frame_->clockErrors;return 0;}return end-start;
    }
    void finish(Kind kind,size_t index,uint64_t start) {
        if(!frame_)return;
        const auto elapsed=duration(start,stamp());
        if(kind==Kind::sidebarDraw){auto& s=frame_->sidebars[index];++s.drawCalls;s.drawHostNs+=elapsed;}
        else if(kind==Kind::menuDraw){auto& e=frame_->eyes[index];++e.menuCalls;e.menuHostNs+=elapsed;}
        else {auto& e=frame_->eyes[index];++e.copyCalls;e.copyHostNs+=elapsed;}
    }
};
}
