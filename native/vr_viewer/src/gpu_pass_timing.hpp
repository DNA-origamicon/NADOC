#pragma once
// Opt-in GPU timeline intervals. GL_TIMESTAMP queries never nest the existing
// GL_TIME_ELAPSED total. Results are read only after each query is available.
#ifndef GL_GLEXT_PROTOTYPES
#define GL_GLEXT_PROTOTYPES
#endif
#include <GL/gl.h>
#include <GL/glext.h>
#include "async_trace.hpp"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <time.h>

namespace nadoc_vr {
struct GpuPassSample {
    uint64_t frame=0,hostBeginNs=0,hostCollectedNs=0;
    uint32_t viewToolsVersion=0,viewToolsFlags=0;
    bool menuOpen=false,valid=false,shadowBoundary=false,motionDetailReduced=false;
    unsigned shadowScope=0; // 0 skipped,1 canonical,2 exported inspection
    unsigned issued=0;
    std::array<int,2> eyeOrder{-1,-1};
    std::array<uint64_t,4> timestamps{};
    uint64_t shadowNs=0,leftNs=0,rightNs=0,totalNs=0;
    const char* reason="incomplete_boundaries";
};
inline bool gpuPassTimingRequested(std::string_view value) {
    if(value.empty() || value=="0")return false;
    if(value=="1")return true;
    throw std::runtime_error("NADOC_VR_GPU_PASS_TIMING requires 0 or 1");
}
inline GpuPassSample resolveGpuPassSample(GpuPassSample result,bool invalid) {
    if(invalid){result.reason="invalid_boundary_order";return result;}
    if(result.issued!=4 || result.eyeOrder[0]<0 || result.eyeOrder[1]<0 || result.eyeOrder[0]==result.eyeOrder[1])return result;
    for(unsigned i=1;i<4;++i)if(result.timestamps[i]<result.timestamps[i-1]) {
        result.reason="timestamp_discontinuity_or_wrap";return result;
    }
    result.shadowNs=result.timestamps[1]-result.timestamps[0];
    const auto first=result.timestamps[2]-result.timestamps[1],second=result.timestamps[3]-result.timestamps[2];
    result.leftNs=result.eyeOrder[0]==0?first:second;result.rightNs=result.eyeOrder[0]==1?first:second;
    result.totalNs=result.timestamps[3]-result.timestamps[0];result.valid=true;result.reason="observed";return result;
}
// Driver-injected ring lets tests prove that an unavailable result is never read
// and that saturation preserves rendering rather than waiting for the GPU.
template<class Driver,size_t Slots=32>
class GpuPassTimingRing {
public:
    static_assert(Slots>0 && Slots<=128);
    using Sink=void(*)(const GpuPassSample&,void*);
    explicit GpuPassTimingRing(Driver& driver,Sink sink=nullptr,void* sinkContext=nullptr):driver_(driver),sink_(sink),sinkContext_(sinkContext){}
    void initialize(bool enabled) {
        if(initialized_)throw std::runtime_error("GPU pass timer already initialized");
        initialized_=true;enabled_=enabled;if(!enabled)return;
        counterBits_=driver_.counterBits();
        if(counterBits_<=0 || counterBits_>64)return;
        driver_.allocate(ids_.size(),ids_.data());
        supported_=true;for(auto id:ids_)if(!id)supported_=false;
    }
    void begin(uint64_t frame,bool menuOpen,uint32_t viewVersion,uint32_t viewFlags,unsigned shadowScope,uint64_t hostNs) {
        if(!enabled_)return;
        ++attempted_;if(!supported_){++unsupported_;return;}
        if(active_) {slots_[*active_].invalid=true;end();}
        collect(hostNs);
        for(size_t offset=0;offset<Slots;++offset) {
            const size_t i=(next_+offset)%Slots;
            if(slots_[i].pending)continue;
            auto& slot=slots_[i];slot={};slot.pending=true;slot.sample.frame=frame;slot.sample.menuOpen=menuOpen;
            slot.sample.viewToolsVersion=viewVersion;slot.sample.viewToolsFlags=viewFlags;slot.sample.shadowScope=shadowScope;
            slot.sample.hostBeginNs=hostNs;active_=i;next_=(i+1)%Slots;++issuedFrames_;
            mark();return;
        }
        ++ringSkipped_;
    }
    void afterShadow(bool executed,bool motionDetailReduced=false) {
        if(!active_)return;
        auto& slot=slots_[*active_];if(slot.sample.issued!=1){slot.invalid=true;return;}
        slot.sample.shadowBoundary=true;slot.sample.motionDetailReduced=motionDetailReduced;
        if(!executed)slot.sample.shadowScope=0;
        mark();
    }
    void afterEye(unsigned eye) {
        if(!active_)return;
        auto& slot=slots_[*active_];const auto issued=slot.sample.issued;
        if(eye>1 || issued<2 || issued>=4){slot.invalid=true;return;}
        slot.sample.eyeOrder[issued-2]=int(eye);
        if(issued==3 && slot.sample.eyeOrder[0]==int(eye))slot.invalid=true;
        mark();
    }
    void end() {if(active_)active_.reset();}
    void collect(uint64_t hostNs) {
        if(!enabled_ || !supported_)return;
        for(size_t i=0;i<Slots;++i) {
            auto& slot=slots_[i];if(!slot.pending || active_==i)continue;
            bool ready=true;
            for(unsigned j=slot.sample.issued;j>0;--j){++availabilityQueries_;if(!driver_.available(ids_[i*4+j-1])){ready=false;break;}}
            if(!ready)continue;
            for(unsigned j=0;j<slot.sample.issued;++j){slot.sample.timestamps[j]=driver_.result(ids_[i*4+j]);++resultReads_;}
            slot.sample.hostCollectedNs=hostNs;const auto sample=resolveGpuPassSample(slot.sample,slot.invalid);
            slot.pending=false;++completed_;if(sample.valid)++valid_;else ++invalid_;
            last_=sample;
            if(sink_)try{sink_(sample,sinkContext_);}catch(...){++sinkFailures_;}
        }
    }
    void shutdown() {
        if(!initialized_)return;
        for(const auto& slot:slots_)if(slot.pending)++shutdownUnobserved_;
        if(enabled_) {bool any=false;for(auto id:ids_)any=any||id;if(any)driver_.release(ids_.size(),ids_.data());}
        ids_.fill(0);slots_={};active_.reset();supported_=false;initialized_=false;
    }
    bool enabled()const{return enabled_;}
    uint64_t ringSkipped()const{return ringSkipped_;}
    uint64_t completed()const{return completed_;}
    uint64_t invalid()const{return invalid_;}
    uint64_t sinkFailures()const{return sinkFailures_;}
    size_t pending()const{size_t n=0;for(const auto& slot:slots_)if(slot.pending)++n;return n;}
    const GpuPassSample& last()const{return last_;}
    std::string json()const {
        return "{\"enabled\":"+std::string(enabled_?"true":"false")+",\"supported\":"+(supported_?"true":"false")+
            ",\"query\":\"GL_TIMESTAMP\",\"counter_bits\":"+std::to_string(counterBits_)+",\"ring_slots\":"+std::to_string(Slots)+
            ",\"attempted_frames\":"+std::to_string(attempted_)+",\"issued_frames\":"+std::to_string(issuedFrames_)+
            ",\"completed_frames\":"+std::to_string(completed_)+",\"valid_frames\":"+std::to_string(valid_)+",\"invalid_frames\":"+std::to_string(invalid_)+
            ",\"ring_full_frames\":"+std::to_string(ringSkipped_)+",\"unsupported_frames\":"+std::to_string(unsupported_)+
            ",\"availability_queries\":"+std::to_string(availabilityQueries_)+",\"result_reads\":"+std::to_string(resultReads_)+
            ",\"timestamp_commands\":"+std::to_string(timestampCommands_)+",\"sink_failures\":"+std::to_string(sinkFailures_)+",\"pending_frames\":"+std::to_string(pending())+
            ",\"shutdown_unobserved_frames\":"+std::to_string(shutdownUnobserved_)+
            ",\"record_delivery\":\"existing bounded TraceSink; VR_TRACE_DROPPED invalidates coverage\",\"duration_semantics\":\"GPU timeline elapsed; includes queue idle/submission gaps, not pure busy time\""
            ",\"scope\":\"ordinary scene shadow after Witness-only work, then full renderView in actual eye order; excludes xrEndFrame\"}";
    }
private:
    struct Slot {bool pending=false,invalid=false;GpuPassSample sample;};
    Driver& driver_;Sink sink_;void* sinkContext_;
    std::array<GLuint,Slots*4> ids_{};std::array<Slot,Slots> slots_{};
    std::optional<size_t> active_;size_t next_=0;
    bool initialized_=false,enabled_=false,supported_=false;int counterBits_=0;
    uint64_t attempted_=0,issuedFrames_=0,completed_=0,valid_=0,invalid_=0,ringSkipped_=0,unsupported_=0,sinkFailures_=0,shutdownUnobserved_=0;
    uint64_t availabilityQueries_=0,resultReads_=0,timestampCommands_=0;
    GpuPassSample last_;
    void mark(){auto& slot=slots_[*active_];driver_.timestamp(ids_[*active_*4+slot.sample.issued]);++slot.sample.issued;++timestampCommands_;}
};
struct GlPassTimestampDriver {
    int counterBits(){GLint value=0;glGetQueryiv(GL_TIMESTAMP,GL_QUERY_COUNTER_BITS,&value);return value;}
    void allocate(size_t count,GLuint* ids){glGenQueries(GLsizei(count),ids);}
    void release(size_t count,const GLuint* ids){glDeleteQueries(GLsizei(count),ids);}
    void timestamp(GLuint id){glQueryCounter(id,GL_TIMESTAMP);}
    bool available(GLuint id){GLint value=0;glGetQueryObjectiv(id,GL_QUERY_RESULT_AVAILABLE,&value);return value==GL_TRUE;}
    uint64_t result(GLuint id){GLuint64 value=0;glGetQueryObjectui64v(id,GL_QUERY_RESULT,&value);return value;}
};
class GpuPassTiming {
public:
    GpuPassTiming():ring_(driver_,emit,nullptr){}
    void initialize(){const auto* v=std::getenv("NADOC_VR_GPU_PASS_TIMING");ring_.initialize(gpuPassTimingRequested(v?v:""));if(ring_.enabled())status("initialized");}
    void shutdown(){ring_.shutdown();if(ring_.enabled())status("shutdown");}
    void begin(uint64_t frame,bool menuOpen,uint32_t viewVersion,uint32_t viewFlags,unsigned shadowScope) {
        if(ring_.enabled())ring_.begin(frame,menuOpen,viewVersion,viewFlags,shadowScope,stamp());
    }
    void afterShadow(bool executed,bool motionDetailReduced){ring_.afterShadow(executed,motionDetailReduced);}
    void afterEye(unsigned eye){ring_.afterEye(eye);}
    void end(){ring_.end();}
    void collect(){if(ring_.enabled())ring_.collect(stamp());}
    std::string json()const{return ring_.json();}
private:
    GlPassTimestampDriver driver_;GpuPassTimingRing<GlPassTimestampDriver> ring_;
    static uint64_t stamp(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return uint64_t(t.tv_sec)*1000000000+t.tv_nsec;}
    void status(const char* phase)const {try{writeTrace(std::string("VR_GPU_PASS_STATUS phase=")+phase+" status="+ring_.json()+"\n");}catch(...){} }
    static void emit(const GpuPassSample& sample,void*) {
        std::ostringstream out;out<<"VR_GPU_PASS frame="<<sample.frame<<" host_begin_monotonic_ns="<<sample.hostBeginNs
            <<" host_collected_monotonic_ns="<<sample.hostCollectedNs<<" valid="<<sample.valid<<" reason="<<sample.reason
            <<" view_tools_version="<<sample.viewToolsVersion<<" view_tools_flags="<<sample.viewToolsFlags<<" menu_open="<<sample.menuOpen
            <<" shadow_scope="<<(!sample.shadowBoundary?"unknown":sample.shadowScope==2?"exported_inspection":sample.shadowScope==1?"canonical":"skipped")
            <<" shadow_calls="<<(sample.shadowBoundary?(sample.shadowScope?"1":"0"):"unknown")<<" motion_detail_reduced="<<sample.motionDetailReduced
            <<" left_calls="<<(int(sample.eyeOrder[0]==0)+int(sample.eyeOrder[1]==0))<<" right_calls="<<(int(sample.eyeOrder[0]==1)+int(sample.eyeOrder[1]==1))
            <<" boundaries="<<sample.issued<<" first_eye="<<sample.eyeOrder[0]<<" second_eye="<<sample.eyeOrder[1];
        for(unsigned i=0;i<sample.issued;++i)out<<" timestamp"<<i<<"_ns="<<sample.timestamps[i];
        if(sample.valid)out<<" shadow_ns="<<sample.shadowNs<<" left_ns="<<sample.leftNs<<" right_ns="<<sample.rightNs<<" total_ns="<<sample.totalNs;
        out<<"\n";writeTrace(out.str());
    }
};
} // namespace nadoc_vr
