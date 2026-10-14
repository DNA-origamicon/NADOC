#pragma once
// Explicit diagnostic only: preallocated POD records on the render thread,
// serialization and durable writes only after the acknowledged capture window.
#include "frame_identity.hpp"
#include "capture_ui_diagnostics.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <future>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <type_traits>
#include <fcntl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

namespace nadoc_vr {
class PoseJournal {
public:
    static constexpr int64_t tailNs = 100000000;
    static constexpr size_t maximumFrames = 8192;
    using ClockMapper = std::function<std::optional<int64_t>(int64_t)>;
    struct Pose {
        std::array<float,3> position{};
        std::array<float,4> orientation{0,0,0,1};
    };
    struct Eye {
        Pose pose;
        std::array<float,4> fov{}; // left, right, up, down (radians)
        std::array<float,16> model{}; // row-major, at this eye's draw
        uint32_t width=0,height=0,swapchainImage=0;
        bool rendered=false;
        frame_identity::Receipt frameIdentity;
    };
    struct Hand {
        Pose applied, runtime;
        uint64_t locationFlags=0;
        int64_t locateStart=0,locateEnd=0;
        bool poseActionActive=false,queried=false,valid=false,grip=false;
        unsigned provider=0; // 0 physical, 1 live transactions/control, 2 witness
    };
    struct Frame {
        uint64_t id=0,commandSequence=0;
        int64_t predicted=0,period=0,mapped=0,hostStart=0,hostEnd=0;
        int64_t locateViewsStart=0,locateViewsEnd=0,actionsStart=0,actionsEnd=0;
        int64_t endFrameStart=0,endFrameEnd=0;
        bool mappedValid=false,submitted=false,shouldRender=false;
        int32_t endFrameResult=0;
        uint64_t viewFlags=0;
        std::array<Eye,2> eyes{};
        std::array<Hand,2> hands{};
        std::array<float,16> model{};
        std::array<float,3> sourceCenter{},offset{};
        float normalizationScale=0;
        uint64_t sceneRevision=0,visualizationSequence=0,coordinateSequence=0;
        uint64_t viewToolsVersion=0,viewToolsSequence=0,viewToolsFlags=0;
        std::array<char,32> representation{};
        unsigned manipulationMode=0;
        std::array<bool,2> menuOpen{};
        bool viewToolsOpen=false,desktopOpen=false,motionDetailReduced=false,sceneHidden=false;
        CaptureUiFrame captureUi;
    };
    static uint64_t parseRequest(const std::string& text) {
        uint64_t value=0;
        if(text.empty() || text.find_first_not_of("0123456789")!=std::string::npos)
            throw std::runtime_error("Pose journal request must be positive decimal digits");
        const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
        if(parsed.ec!=std::errc{} || parsed.ptr!=text.data()+text.size() || !value)
            throw std::runtime_error("Pose journal request exceeds uint64 or is zero");
        return value;
    }
    static int64_t monotonicNs() {
        timespec value{};
        if(clock_gettime(CLOCK_MONOTONIC,&value))throw std::runtime_error("CLOCK_MONOTONIC unavailable");
        return int64_t(value.tv_sec)*1000000000+value.tv_nsec;
    }
    template<class P,class Q> static Pose pose(const P& p,const Q& q) {
        return {{p.x,p.y,p.z},{q.x,q.y,q.z,q.w}};
    }
    template<class M> static std::array<float,16> matrix(const M& m) {
        std::array<float,16> out{};
        for(size_t r=0;r<4;++r)for(size_t c=0;c<4;++c)out[r*4+c]=m[c][r];
        return out;
    }
    explicit PoseJournal(size_t capacity=maximumFrames):capacity_(capacity) {
        if(!capacity || capacity>maximumFrames)throw std::runtime_error("Invalid pose journal capacity");
    }
    ~PoseJournal(){if(writer_.valid())writer_.wait();}
    void enable(const std::string& directory,const std::string& session) {
        if(directory.empty() || session.empty())throw std::runtime_error("Pose journal requires a directory and live session");
        if(enabled())throw std::runtime_error("Pose journal already enabled");
        const auto path=std::filesystem::absolute(directory);
        std::filesystem::create_directories(path);
        struct stat st{};
        if(lstat(path.c_str(),&st) || !S_ISDIR(st.st_mode) || st.st_uid!=getuid())
            throw std::runtime_error("Pose journal directory must be owned and not a symlink");
        if(chmod(path.c_str(),0700))throw std::runtime_error("Cannot protect pose journal directory");
        directory_=path.string();session_=session;phase_="ready";
    }
    bool enabled() const {return !directory_.empty();}
    void setFrameIdentityConfig(std::string value) {
        if(collecting_ || writer_.valid())throw std::runtime_error("Cannot change frame marker during journaling");
        frameIdentityConfig_=std::move(value);
    }
    void frameIdentity(size_t eye,frame_identity::Receipt receipt) {
        if(draftActive_ && eye<2)draft_.eyes[eye].frameIdentity=receipt;
    }
    void setClockMapper(ClockMapper value){mapper_=std::move(value);}
    bool mappingAvailable() const {return bool(mapper_);}
    bool collecting() const {return collecting_;}
    Frame* frame(){return draftActive_?&draft_:nullptr;}
    // Called only when collecting, so disabled mode performs no clock queries.
    int64_t stamp() const {return collecting_?monotonicNs():0;}
    void arm(uint64_t request,double seconds,int64_t now=monotonicNs()) {
        requireEnabled();poll(now);
        if(!request || !std::isfinite(seconds) || seconds<0.1 || seconds>30)
            throw std::runtime_error("Pose journal arm requires a request and 0.1..30 seconds");
        if(collecting_ || writer_.valid() || phase_=="ready_to_flush" || phase_=="expired")
            throw std::runtime_error("Pose journal busy; flush or cancel first");
        request_=request;armStart_=now;deadline_=now+int64_t(seconds*1e9);
        windowStart_=windowEnd_=0;bound_=false;count_=overflow_=mappingFailures_=0;
        // Value-initialize and touch all storage before the compositor is armed.
        frames_=std::vector<Frame>(capacity_);draft_={};draftActive_=false;
        path_.clear();error_.clear();phase_="armed";collecting_=true;
    }
    void window(uint64_t request,int64_t start,int64_t end,int64_t now=monotonicNs()) {
        checkRequest(request);
        if(!collecting_ || bound_ || start<armStart_ || end<=start || end-start>10000000000LL || end+tailNs>deadline_)
            throw std::runtime_error("Invalid or late pose journal capture window");
        windowStart_=start;windowEnd_=end;bound_=true;phase_="recording";poll(now);
    }
    void cancel(uint64_t request) {
        checkRequest(request);
        if(writer_.valid())throw std::runtime_error("Pose journal is writing");
        collecting_=draftActive_=false;phase_="cancelled";
        // Preserve bounded RAM until a new explicit arm; do not write on cancel.
    }
    void begin(uint64_t id,int64_t predicted,int64_t period,bool shouldRender,int64_t hostStart) {
        if(!collecting_)return;
        poll(hostStart);
        if(!collecting_)return;
        draft_={};draftActive_=true;draft_.id=id;draft_.predicted=predicted;
        draft_.period=period;draft_.shouldRender=shouldRender;draft_.hostStart=hostStart;
        if(mapper_) {
            const auto mapped=mapper_(predicted);
            if(mapped){draft_.mapped=*mapped;draft_.mappedValid=true;}
            else ++mappingFailures_;
        }
    }
    template<class V,class M> void eye(size_t index,uint32_t width,uint32_t height,uint32_t image,const V& view,const M& model) {
        if(!draftActive_ || index>=2)return;
        auto& eye=draft_.eyes[index];eye.pose=pose(view.pose.position,view.pose.orientation);
        eye.fov={view.fov.angleLeft,view.fov.angleRight,view.fov.angleUp,view.fov.angleDown};
        eye.width=width;eye.height=height;eye.swapchainImage=image;eye.rendered=true;eye.model=matrix(model);
    }
    void finish(int32_t endResult,bool submitted,int64_t now=monotonicNs()) {
        if(!draftActive_)return;
        draft_.endFrameResult=endResult;draft_.submitted=submitted && endResult>=0;
        draft_.endFrameEnd=draft_.hostEnd=now;
        if(count_<frames_.size())frames_[count_++]=draft_;else ++overflow_;
        draftActive_=false;poll(now);
    }
    void poll() {if(enabled())poll(monotonicNs());}
    void poll(int64_t now) {
        if(collecting_ && now>=(bound_?windowEnd_+tailNs:deadline_)) {
            collecting_=false;phase_=bound_?"ready_to_flush":"expired";
        }
        if(writer_.valid() && writer_.wait_for(std::chrono::seconds(0))==std::future_status::ready) {
            const auto result=writer_.get();error_=result;
            phase_=error_.empty()?(overflow_?"partial":"saved"):"error";
        }
    }
    void flush(uint64_t request,int64_t now=monotonicNs()) {
        checkRequest(request);poll(now);
        if(!bound_ || collecting_ || draftActive_ || now<windowEnd_+tailNs || writer_.valid() || phase_!="ready_to_flush")
            throw std::runtime_error("Pose journal cannot flush before the capture window and tail finish");
        path_=(std::filesystem::path(directory_)/("pose-journal-"+std::to_string(getpid())+"-"+std::to_string(request_)+".jsonl")).string();
        phase_="writing";
        const auto header=headerJson();
        const auto path=path_;
        const auto start=windowStart_,end=windowEnd_;
        const auto count=count_,overflow=overflow_,mappingFailures=mappingFailures_;
        try {
            writer_=std::async(std::launch::async,[data=std::move(frames_),header,path,start,end,count,overflow,mappingFailures]() {
                return write(path,header,data,count,start,end,overflow,mappingFailures);
            });
        } catch(const std::exception& error) {
            phase_="error";error_=std::string("Cannot start pose journal writer: ")+error.what();throw;
        }
    }
    std::string contextJson(const std::string& socket) const {
        return "{\"enabled\":"+boolean(enabled())+",\"socket\":"+quote(socket)+",\"session\":"+quote(session_)+",\"directory\":"+quote(directory_)+
            ",\"tail_ns\":"+std::to_string(tailNs)+",\"clock_mapping_available\":"+boolean(mappingAvailable())+"}";
    }
    std::string json() const {
        return "{\"enabled\":"+boolean(enabled())+",\"phase\":"+quote(phase_)+",\"request\":"+std::to_string(request_)+
            ",\"frame_count\":"+std::to_string(count_)+",\"overflow_frames\":"+std::to_string(overflow_)+
            ",\"mapping_failures\":"+std::to_string(mappingFailures_)+",\"clock_mapping_available\":"+boolean(mappingAvailable())+
            ",\"window_bound\":"+boolean(bound_)+",\"capture_start_monotonic_ns\":"+std::to_string(windowStart_)+
            ",\"capture_end_monotonic_ns\":"+std::to_string(windowEnd_)+",\"path\":"+quote(path_)+",\"error\":"+quote(error_)+"}";
    }
private:
    size_t capacity_,count_=0,overflow_=0,mappingFailures_=0;
    std::vector<Frame> frames_;
    Frame draft_{};
    bool collecting_=false,draftActive_=false,bound_=false;
    int64_t armStart_=0,deadline_=0,windowStart_=0,windowEnd_=0;
    uint64_t request_=0;
    std::string directory_,session_,path_,phase_="disabled",error_;
    std::string frameIdentityConfig_="{\"enabled\":false}";
    ClockMapper mapper_;
    std::future<std::string> writer_;
    void requireEnabled() const {if(!enabled())throw std::runtime_error("Pose journal requires --pose-journal DIRECTORY");}
    void checkRequest(uint64_t request) const {requireEnabled();if(!request || request!=request_)throw std::runtime_error("Pose journal request mismatch");}
    static std::string boolean(bool value){return value?"true":"false";}
    static std::string quote(const std::string& text) {
        std::ostringstream out;out<<'"';
        for(unsigned char c:text) {if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(c)<<std::dec;else out<<c;}
        out<<'"';return out.str();
    }
    template<class T,size_t N> static void array(std::ostream& out,const std::array<T,N>& values) {
        out<<'[';for(size_t i=0;i<N;++i){if(i)out<<',';if constexpr(std::is_floating_point_v<T>){if(std::isfinite(values[i]))out<<values[i];else out<<"null";}else out<<values[i];}out<<']';
    }
    static void rows(std::ostream& out,const std::array<float,16>& values) {
        out<<'[';for(size_t r=0;r<4;++r){if(r)out<<',';std::array<float,4> row{};std::copy_n(values.begin()+r*4,4,row.begin());array(out,row);}out<<']';
    }
    static void poseJson(std::ostream& out,const Pose& pose) {
        out<<"\"position\":";array(out,pose.position);out<<",\"orientation_xyzw\":";array(out,pose.orientation);
    }
    static const char* relation(int64_t value,int64_t start,int64_t end){return value<start?"preroll":value>=end?"tail":"capture";}
    std::string headerJson() const {
        std::ostringstream out;out<<"{\"event\":\"pose_journal_start\",\"schema\":1,\"source\":\"application_projection\",\"session\":"<<quote(session_)
            <<",\"pid\":"<<getpid()<<",\"request\":"<<request_<<",\"space\":\"OpenXR_LOCAL\",\"units\":\"meters\",\"clock\":\"CLOCK_MONOTONIC\""
            <<",\"clock_mapping\":"<<quote(mappingAvailable()?"XR_KHR_convert_timespec_time":"unavailable")
            <<",\"capture_start_monotonic_ns\":"<<windowStart_<<",\"capture_end_monotonic_ns\":"<<windowEnd_
            <<",\"armed_monotonic_ns\":"<<armStart_<<",\"tail_ns\":"<<tailNs<<",\"capacity_frames\":"<<capacity_
            <<",\"frame_identity\":"<<frameIdentityConfig_
            <<",\"capture_ui_diagnostics\":{\"version\":1,\"enabled\":true,\"haptic_events_per_frame\":16,\"hover_id_max_bytes\":96,\"gpu_queries\":false,\"idle_clock_queries\":false,\"timing_semantics\":\"host elapsed including driver waits and descheduling; nested spans overlap; menu submission is not onscreen visibility\"}"
            <<",\"active_disk_writes\":false,\"pixel_readback\":false,\"final_present_association_verified\":false}";
        return out.str();
    }
    static std::string frameJson(const Frame& f,int64_t start,int64_t end) {
        std::ostringstream out;out<<std::setprecision(std::numeric_limits<float>::max_digits10);
        out<<"{\"event\":\"application_frame\",\"source\":\"application_projection\",\"frame\":"<<f.id<<",\"command_sequence\":"<<f.commandSequence
            <<",\"predicted_display_time_ns\":"<<f.predicted<<",\"predicted_display_period_ns\":"<<f.period
            <<",\"predicted_display_monotonic_ns\":"<<(f.mappedValid?std::to_string(f.mapped):"null")
            <<",\"clock_mapping\":"<<quote(f.mappedValid?"XR_KHR_convert_timespec_time":"unavailable")
            <<",\"predicted_window_relation\":"<<(f.mappedValid?quote(relation(f.mapped,start,end)):"null")
            <<",\"host_window_relation\":"<<quote(relation(f.hostEnd,start,end))
            <<",\"host_frame_start_ns\":"<<f.hostStart<<",\"host_frame_end_ns\":"<<f.hostEnd
            <<",\"host_actions_start_ns\":"<<f.actionsStart<<",\"host_actions_end_ns\":"<<f.actionsEnd
            <<",\"host_locate_views_start_ns\":"<<f.locateViewsStart<<",\"host_locate_views_end_ns\":"<<f.locateViewsEnd
            <<",\"host_end_frame_start_ns\":"<<f.endFrameStart<<",\"host_end_frame_end_ns\":"<<f.endFrameEnd
            <<",\"xr_end_frame_result\":"<<f.endFrameResult<<",\"xr_end_frame_succeeded\":"<<boolean(f.endFrameResult>=0)
            <<",\"submitted\":"<<boolean(f.submitted)<<",\"should_render\":"<<boolean(f.shouldRender)<<",\"view_state_flags\":"<<f.viewFlags<<",\"eyes\":[";
        for(size_t i=0;i<2;++i) {
            if(i)out<<',';
            const auto& e=f.eyes[i];out<<"{\"eye\":"<<quote(i?"right":"left")<<",\"width\":"<<e.width<<",\"height\":"<<e.height<<',';poseJson(out,e.pose);
            out<<",\"fov_left_right_up_down\":";array(out,e.fov);out<<",\"rendered\":"<<boolean(e.rendered)<<",\"swapchain_image_index\":"<<e.swapchainImage<<",\"model_to_tracking_rows\":";rows(out,e.model);out<<",\"frame_identity\":"<<frame_identity::receiptJson(e.frameIdentity)<<'}';
        }
        out<<"],\"presentation\":{\"model_to_tracking_rows\":";rows(out,f.model);
        out<<",\"source_center_nm\":";array(out,f.sourceCenter);out<<",\"normalization_model_per_nm\":"<<f.normalizationScale<<",\"normalized_offset_model\":";array(out,f.offset);out<<"},\"hands\":[";
        for(size_t i=0;i<2;++i) {
            if(i)out<<',';
            const auto& h=f.hands[i];out<<'{';poseJson(out,h.applied);
            out<<",\"valid\":"<<boolean(h.valid)<<",\"grip\":"<<boolean(h.grip)<<",\"input_source\":"<<quote(h.provider==1?"live":h.provider==2?"witness":"physical")
                <<",\"runtime_pose_queried\":"<<boolean(h.queried)<<",\"runtime_pose_action_active\":"<<boolean(h.poseActionActive)<<",\"runtime_location_flags\":"<<h.locationFlags
                <<",\"host_locate_start_ns\":"<<h.locateStart<<",\"host_locate_end_ns\":"<<h.locateEnd<<",\"runtime_pose\":{";poseJson(out,h.runtime);out<<"}}";
        }
        out<<"],\"representation\":"<<quote(f.representation.data())<<",\"scene_revision\":"<<f.sceneRevision<<",\"visualization_sequence\":"<<f.visualizationSequence
            <<",\"coordinate_sequence\":"<<f.coordinateSequence<<",\"view_tools\":{\"version\":"<<f.viewToolsVersion<<",\"flags\":"<<f.viewToolsFlags<<",\"sequence\":"<<f.viewToolsSequence<<",\"open\":"<<boolean(f.viewToolsOpen)<<'}'
            <<",\"menu_open\":["<<boolean(f.menuOpen[0])<<','<<boolean(f.menuOpen[1])<<"],\"desktop_open\":"<<boolean(f.desktopOpen)<<",\"manipulation_mode\":"<<f.manipulationMode
            <<",\"motion_detail_reduced\":"<<boolean(f.motionDetailReduced)<<",\"scene_hidden\":"<<boolean(f.sceneHidden)
            <<",\"capture_ui_diagnostics\":"<<CaptureUiDiagnostics::json(f.captureUi)<<'}';return out.str();
    }
    static std::string write(const std::string& path,const std::string& header,const std::vector<Frame>& data,size_t count,int64_t start,int64_t end,size_t overflow,size_t failures) {
        const int fd=open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
        if(fd<0)return "Cannot exclusively create pose journal";
        FILE* file=fdopen(fd,"w");if(!file){close(fd);return "Cannot open pose journal stream";}
        bool okay=true;
        auto line=[&](const std::string& text){if(fwrite(text.data(),1,text.size(),file)!=text.size() || fputc('\n',file)==EOF)okay=false;};
        try {
            line(header);for(size_t i=0;i<count;++i)line(frameJson(data[i],start,end));
            line("{\"event\":\"pose_journal_complete\",\"frames\":"+std::to_string(count)+",\"overflow_frames\":"+std::to_string(overflow)+",\"mapping_failures\":"+std::to_string(failures)+",\"complete\":"+boolean(!overflow)+"}");
        }catch(...){okay=false;}
        if(fflush(file) || fdatasync(fd))okay=false;
        if(fclose(file))okay=false;
        const int directory=open(std::filesystem::path(path).parent_path().c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
        if(directory<0)okay=false;
        else {
            if(fsync(directory))okay=false;
            if(close(directory))okay=false;
        }
        return okay?"":"Pose journal write or sync failed; file may be partial";
    }
};
} // namespace nadoc_vr
