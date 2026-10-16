#pragma once
// Both final eye buffers, before release to OpenXR. This is application output,
// not compositor scanout. GPU fences are polled; disk/compression/export never
// execute on the render thread. Pressure drops a complete stereo pair.
#include <GL/gl.h>
#include <openxr/openxr.h>
#include <zlib.h>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <future>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#include "recording_clock.hpp"
#include "scrywrite_visual.hpp"

extern char** environ;
namespace nadoc_vr {
class StereoRecording {
    struct Slot {
        GLuint pbo = 0;
        GLsync fence = nullptr;
        unsigned eyes = 0;
        bool submitted = false;
        bool warmup = false;
        uint64_t frame = 0;
        std::string metadata;
    };
    struct Frame { uint64_t number; std::string metadata; std::vector<uint8_t> rgb; };
    std::array<Slot,3> slots_{};
    Slot* current_ = nullptr;
    size_t eyeBytes_ = 0;
    int width_ = 0, height_ = 0;
    RecordingClock clock_;
    bool active_ = false, closing_ = false, warmupPending_ = false;
    std::filesystem::path directory_;
    std::string error_, result_ = "Ready", context_;
    std::future<void> writer_;
    std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<Frame> queue_;
    std::atomic<unsigned> saved_{0}, writeErrors_{0};
    unsigned dropped_ = 0, requested_ = 0;
    double readbackCpuMs_ = 0, maximumReadbackCallMs_ = 0;
    std::vector<std::string> skips_;
    static constexpr size_t maxPairBytes = 48U*1024*1024, queueLimit = 4;
    static std::string quote(const std::string& s) { return "\""+scrywrite::visualJson(s)+"\""; }
    static double now() { return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
    static void write(const std::filesystem::path& p, const char* bytes, size_t count) {
        std::ofstream f(p,std::ios::binary); f.exceptions(std::ios::failbit|std::ios::badbit);
        f.write(bytes,static_cast<std::streamsize>(count));
    }
    static int child(std::vector<std::string> args, bool wait) {
        std::vector<char*> argv; for(auto& a:args)argv.push_back(a.data());argv.push_back(nullptr);
        pid_t pid; const int err=posix_spawnp(&pid,argv[0],nullptr,nullptr,argv.data(),environ);
        if(err)return err;
        if(!wait) { std::thread([pid]{int status;while(waitpid(pid,&status,0)<0 && errno==EINTR){}}).detach();return 0; }
        int status=0;while(waitpid(pid,&status,0)<0)if(errno!=EINTR)return -1;
        return WIFEXITED(status)?WEXITSTATUS(status):-1;
    }
    void skip(uint64_t frame,const char* reason) {
        ++dropped_;
        skips_.push_back("{\"frame\":"+std::to_string(frame)+",\"reason\":"+quote(reason)+"}");
    }
    void consume() {
        for(;;) {
            Frame f;
            { std::unique_lock lock(mutex_);ready_.wait(lock,[this]{return closing_||!queue_.empty();});
              if(queue_.empty())return;
              f=std::move(queue_.front());queue_.pop_front(); }
            try {
                uLongf size=compressBound(f.rgb.size());std::vector<uint8_t> packed(size);
                if(compress2(packed.data(),&size,f.rgb.data(),f.rgb.size(),Z_BEST_SPEED)!=Z_OK)throw std::runtime_error("compression failed");
                const auto base=directory_/std::to_string(f.number);
                write(base.string()+".rgbz",reinterpret_cast<char*>(packed.data()),size);
                write(base.string()+".json",f.metadata.data(),f.metadata.size());++saved_;
            } catch(...) {++writeErrors_;}
        }
    }
    void finishWriting() {
        std::thread a([this]{consume();}),b([this]{consume();});a.join();b.join();
        std::ostringstream m;
        m<<"{\"schema\":1,\"source\":\"application_swapchain\",\"compositor_acknowledged\":false,"
         <<"\"duration_seconds\":5,\"countdown_seconds\":2,\"width\":"<<width_<<",\"height\":"<<height_
         <<",\"format\":\"zlib-rgb24-left-then-right-bottom-up\",\"requested_frames\":"<<requested_
         <<",\"saved_frames\":"<<saved_<<",\"dropped_pairs\":"<<dropped_<<",\"write_errors\":"<<writeErrors_
         <<",\"readback_cpu_total_ms\":"<<readbackCpuMs_<<",\"maximum_readback_call_ms\":"<<maximumReadbackCallMs_
         <<",\"context\":"<<context_<<",\"skips\":[";
        for(size_t i=0;i<skips_.size();++i)m<<(i?",":"")<<skips_[i];
        m<<"]}";
        const auto text=m.str();write(directory_/"recording.json",text.data(),text.size());
        if(saved_==0)throw std::runtime_error("No submitted eye frames recorded");
        if(writeErrors_)throw std::runtime_error("Recording disk write failed; partial frames retained");
        if(child({"/usr/bin/python3",std::string(NADOC_SOURCE_ROOT)+"/tools/vr_recording.py",directory_.string()},true)!=0)
            throw std::runtime_error("Video export failed; eye frames retained");
    }
    void retire(Slot& s) {
        if(s.fence)glDeleteSync(s.fence);
        s.fence=nullptr;s.eyes=0;s.submitted=false;s.metadata.clear();
    }
    void drain(bool discard=false) {
        const double started=now();
        GLint previous=0;glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous);
        for(auto& s:slots_) {
            if(!s.fence)continue;
            const GLenum status=glClientWaitSync(s.fence,0,0);
            if(!discard && status==GL_TIMEOUT_EXPIRED)continue;
            if(s.warmup){retire(s);continue;}
            if(discard || status==GL_WAIT_FAILED || !s.submitted || s.eyes!=3) {skip(s.frame,"unavailable_pair");retire(s);continue;}
            bool full;{std::lock_guard lock(mutex_);full=queue_.size()>=queueLimit;}
            if(full) {skip(s.frame,"writer_backpressure");retire(s);continue;}
            glBindBuffer(GL_PIXEL_PACK_BUFFER,s.pbo);
            const void* data=glMapBufferRange(GL_PIXEL_PACK_BUFFER,0,eyeBytes_*2,GL_MAP_READ_BIT);
            if(!data){skip(s.frame,"readback_failed");retire(s);continue;}
            Frame f{s.frame,s.metadata,std::vector<uint8_t>(eyeBytes_*2)};
            std::memcpy(f.rgb.data(),data,f.rgb.size());
            const bool valid=glUnmapBuffer(GL_PIXEL_PACK_BUFFER)==GL_TRUE;
            if(valid) {std::lock_guard lock(mutex_);queue_.push_back(std::move(f));ready_.notify_one();}
            else skip(s.frame,"readback_invalid");
            retire(s);
        }
        glBindBuffer(GL_PIXEL_PACK_BUFFER,previous);
        const double ms=(now()-started)*1000;readbackCpuMs_+=ms;maximumReadbackCallMs_=std::max(maximumReadbackCallMs_,ms);
    }
    void closeQueue() {
        {std::lock_guard lock(mutex_);closing_=true;}ready_.notify_all();active_=false;clock_.armed=false;
    }
public:
    static std::filesystem::path root() {
        if(const char* p=std::getenv("NADOC_VR_RECORDINGS_DIR"))return std::filesystem::path(p);
        return std::filesystem::path(NADOC_SOURCE_ROOT)/".development-artifacts/vr-recordings";
    }
    bool busy() const {return active_ || writer_.valid();}
    std::string label() const {return active_?(clock_.finished(now())?"Saving stereo clip...":clock_.label(now())):writer_.valid()?"Saving stereo clip...":"Record app eyes 5s";}
    std::string status() const {return busy()?"Both eyes - menu stays as you leave it":result_;}
    void openFolder() {
        try {std::filesystem::create_directories(root());if(child({"xdg-open",root().string()},false))result_="Could not open recordings folder";}
        catch(const std::exception& e){result_="Could not open recordings folder: "+std::string(e.what());}
    }
    void start(int width,int height,std::string context="{}") {
        if(busy())return;
        try {
            const size_t bytes=size_t(std::max(width,0))*size_t(std::max(height,0))*3;
            if(!bytes || bytes*2>maxPairBytes)throw std::runtime_error("Eye resolution exceeds recording memory limit");
            std::filesystem::create_directories(root());
            if(std::filesystem::space(root()).available<2ULL*1024*1024*1024)throw std::runtime_error("Recording needs 2 GB free space");
            const auto stamp=std::chrono::system_clock::now().time_since_epoch();
            directory_=root()/("stereo-"+std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(stamp).count())+"-"+std::to_string(getpid()));
            if(!std::filesystem::create_directory(directory_))throw std::runtime_error("Recording path already exists");
            width_=width;height_=height;eyeBytes_=bytes;context_=std::move(context);
            saved_=0;writeErrors_=0;dropped_=requested_=0;skips_.clear();error_.clear();closing_=false;
            readbackCpuMs_=maximumReadbackCallMs_=0;
            GLint previous=0;glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous);
            for(auto& s:slots_){if(!s.pbo)glGenBuffers(1,&s.pbo);glBindBuffer(GL_PIXEL_PACK_BUFFER,s.pbo);glBufferData(GL_PIXEL_PACK_BUFFER,eyeBytes_*2,nullptr,GL_STREAM_READ);}
            glBindBuffer(GL_PIXEL_PACK_BUFFER,previous);
            if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("Could not allocate eye recording buffers");
            writer_=std::async(std::launch::async,[this]{finishWriting();});clock_.arm(now());active_=true;warmupPending_=true;result_="Recording armed";
        } catch(const std::exception& e){error_=e.what();result_="Record failed - "+error_;}
    }
    void poll() {
        if(active_) {
            drain();
            if(clock_.finished(now())) {
                const bool pending=std::any_of(slots_.begin(),slots_.end(),[](auto& s){return s.fence;});
                if(pending && now()<clock_.start+RecordingClock::duration+1)return;
                if(pending)drain(true);
                closeQueue();
            }
        }
        if(!active_ && writer_.valid() && writer_.wait_for(std::chrono::seconds(0))==std::future_status::ready) {
            try{writer_.get();result_=dropped_?"Saved - "+std::to_string(dropped_)+" pairs skipped":"Saved stereo clip";}
            catch(const std::exception& e){error_=e.what();result_="Record failed - "+error_;}
        }
    }
    void begin(uint64_t frame,int64_t predicted,int64_t period,bool leftMenu,bool rightMenu,const std::string& representation) {
        current_=nullptr;
        if(!active_ || clock_.finished(now()))return;
        const bool warming=!clock_.collecting(now());
        if(warming && !warmupPending_)return;
        if(!warming)++requested_;
        for(auto& s:slots_)if(!s.fence && !s.eyes){current_=&s;break;}
        if(!current_){if(!warming)skip(frame,"gpu_backpressure");return;}
        current_->frame=frame;current_->submitted=false;current_->warmup=warming;
        if(warming)warmupPending_=false;
        std::ostringstream j;j.precision(17);
        j<<"{\"frame\":"<<frame<<",\"elapsed_seconds\":"<<now()-clock_.start
         <<",\"predicted_display_time_ns\":"<<predicted<<",\"display_period_ns\":"<<period
         <<",\"menus_open\":["<<(leftMenu?"true":"false")<<','<<(rightMenu?"true":"false")
         <<"],\"representation\":"<<quote(representation)<<",\"eyes\":[";
        current_->metadata=j.str();
    }
    void eye(unsigned index,const XrView& view,int width,int height) {
        if(!current_ || index>1 || width!=width_ || height!=height_)return;
        const double started=now();
        // render order can be right-first; associate each pose and offset by eye ID.
        GLint previous=0,alignment=0,buffer=0,rowLength=0,skipRows=0,skipPixels=0;
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous);
        glGetIntegerv(GL_PACK_ALIGNMENT,&alignment);glGetIntegerv(GL_READ_BUFFER,&buffer);
        glGetIntegerv(GL_PACK_ROW_LENGTH,&rowLength);glGetIntegerv(GL_PACK_SKIP_ROWS,&skipRows);glGetIntegerv(GL_PACK_SKIP_PIXELS,&skipPixels);
        glPixelStorei(GL_PACK_ROW_LENGTH,0);glPixelStorei(GL_PACK_SKIP_ROWS,0);glPixelStorei(GL_PACK_SKIP_PIXELS,0);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,current_->pbo);glPixelStorei(GL_PACK_ALIGNMENT,1);glReadBuffer(GL_COLOR_ATTACHMENT0);
        glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,reinterpret_cast<void*>(eyeBytes_*index));
        glBindBuffer(GL_PIXEL_PACK_BUFFER,previous);glPixelStorei(GL_PACK_ALIGNMENT,alignment);glReadBuffer(buffer);
        glPixelStorei(GL_PACK_ROW_LENGTH,rowLength);glPixelStorei(GL_PACK_SKIP_ROWS,skipRows);glPixelStorei(GL_PACK_SKIP_PIXELS,skipPixels);
        const double ms=(now()-started)*1000;readbackCpuMs_+=ms;maximumReadbackCallMs_=std::max(maximumReadbackCallMs_,ms);
        if(glGetError()!=GL_NO_ERROR)return;
        std::ostringstream j;j.precision(9);j<<(current_->eyes?",":"")<<"{\"eye\":"<<index<<",\"position\":["<<view.pose.position.x<<','<<view.pose.position.y<<','<<view.pose.position.z
         <<"],\"orientation_xyzw\":["<<view.pose.orientation.x<<','<<view.pose.orientation.y<<','<<view.pose.orientation.z<<','<<view.pose.orientation.w
         <<"],\"fov\":["<<view.fov.angleLeft<<','<<view.fov.angleRight<<','<<view.fov.angleUp<<','<<view.fov.angleDown<<"]}";
        current_->metadata+=j.str();current_->eyes|=1U<<index;
    }
    void submitted(bool ok) {
        if(!current_)return;
        current_->metadata+="],\"xr_end_frame_succeeded\":"+std::string(ok?"true":"false")+"}";
        current_->submitted=ok;current_->fence=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);glFlush();
        if(!current_->fence){if(!current_->warmup)skip(current_->frame,"fence_failed");retire(*current_);}
        current_=nullptr;
    }
    std::string json() const {
        return "{\"busy\":"+std::string(busy()?"true":"false")+",\"recording\":"+(active_&&clock_.collecting(now())?"true":"false")+
          ",\"label\":"+quote(label())+",\"status\":"+quote(result_)+",\"directory\":"+quote(directory_.string())+
          ",\"saved_frames\":"+std::to_string(saved_)+",\"dropped_pairs\":"+std::to_string(dropped_)+",\"error\":"+quote(error_)+"}";
    }
    void shutdown() {
        if(active_){drain(true);closeQueue();}
        if(writer_.valid()){try{writer_.get();}catch(...) {}}
        for(auto& s:slots_){retire(s);if(s.pbo)glDeleteBuffers(1,&s.pbo);s.pbo=0;}
    }
};
}
