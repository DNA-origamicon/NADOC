#pragma once
// Opt-in VR-menu routing to a prepared compositor capture process. The viewer
// never reads compositor pixels and performs no filesystem I/O on render frames.
#include "scrywrite_visual.hpp"
#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <future>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;
namespace nadoc_vr {

struct CompositorRecordingStatus {
    std::string phase="ready",label="Record final output 2s";
    std::string status="Final compositor frames - 2 second countdown",directory;
    uint64_t request=0,saved=0,drops=0;
};

inline CompositorRecordingStatus parseCompositorRecordingStatus(const std::string& line) {
    if(line.size()>8192)throw std::runtime_error("Oversized capture status");
    std::istringstream input(line);std::string magic,trailing;int version=0;
    CompositorRecordingStatus value;
    if(!(input>>magic>>version>>std::quoted(value.phase)>>std::quoted(value.label)
              >>std::quoted(value.status)>>std::quoted(value.directory)
              >>value.request>>value.saved>>value.drops) || magic!="NADOC_CAPTURE_UI" || version!=1 || (input>>trailing))
        throw std::runtime_error("Invalid compositor capture status");
    if(value.phase!="countdown" && value.phase!="awaiting_ack" && value.phase!="recording"
       && value.phase!="saving" && value.phase!="saved" && value.phase!="partial" && value.phase!="error")
        throw std::runtime_error("Unknown compositor capture phase");
    return value;
}

class CompositorRecording {
    std::string directory_;
    bool enabled_=false;
    unsigned seconds_=2;
    CompositorRecordingStatus pending_,visible_;
    std::mutex mutex_;
    std::future<void> worker_;
    std::atomic<pid_t> child_{0};
    std::atomic<bool> stopping_{false};
    static std::string quote(const std::string& s) {return "\""+scrywrite::visualJson(s)+"\"";}
    void update(CompositorRecordingStatus value) {std::lock_guard lock(mutex_);pending_=std::move(value);}
    void fail(const std::string& error) {
        CompositorRecordingStatus value;value.phase="error";value.label=idleLabel();value.status=error;value.directory=directory_;update(std::move(value));
    }
    void run(const std::string& context,unsigned seconds) {
        int pipes[2];if(pipe(pipes))throw std::runtime_error("Cannot create recording status pipe");
        posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions,pipes[1],STDOUT_FILENO);
        posix_spawn_file_actions_addclose(&actions,pipes[0]);
        posix_spawn_file_actions_addclose(&actions,pipes[1]);
        std::vector<std::string> args={"/usr/bin/python3",std::string(NADOC_QR_ROOT)+"/tools/vr_capture/viewer_record.py",
            "--directory",directory_,"--viewer-pid",std::to_string(getpid()),"--context",context,
            "--seconds",std::to_string(seconds)};
        std::vector<char*> argv;for(auto& arg:args)argv.push_back(arg.data());argv.push_back(nullptr);
        pid_t pid=0;const int result=posix_spawn(&pid,argv[0],&actions,nullptr,argv.data(),environ);
        posix_spawn_file_actions_destroy(&actions);close(pipes[1]);
        if(result){close(pipes[0]);throw std::runtime_error("Cannot start compositor recording helper");}
        child_=pid;if(stopping_)kill(pid,SIGTERM);
        FILE* input=fdopen(pipes[0],"r");
        bool terminal=false;
        if(input) {
            char* line=nullptr;size_t size=0;
            while(getline(&line,&size,input)>=0) {
                try {
                    auto state=parseCompositorRecordingStatus(line);
                    terminal=state.phase=="saved" || state.phase=="partial" || state.phase=="error";
                    update(std::move(state));
                } catch(const std::exception& error){fail(error.what());kill(pid,SIGTERM);break;}
            }
            free(line);fclose(input);
        } else {close(pipes[0]);kill(pid,SIGTERM);}
        int status=0;pid_t waited;
        do{waited=waitpid(pid,&status,0);}while(waited<0 && errno==EINTR);
        child_=0;
        if(!terminal || waited<0 || !WIFEXITED(status))fail("Capture helper stopped; recording not confirmed");
        else if(WEXITSTATUS(status)!=0) {
            std::lock_guard lock(mutex_);
            if(pending_.phase!="error"){pending_.phase="error";pending_.status="Capture helper failed; files may be partial";}
        }
    }
public:
    CompositorRecording() {
        if(const char* directory=std::getenv("NADOC_VR_COMPOSITOR_CAPTURE_DIR")) {
            directory_=directory;enabled_=!directory_.empty();
            pending_.directory=visible_.directory=directory_;
        }
    }
    ~CompositorRecording(){shutdown();}
    bool enabled() const {return enabled_;}
    bool busy() const {return worker_.valid();}
    unsigned seconds() const {return seconds_;}
    std::string idleLabel() const {return "Record final output "+std::to_string(seconds_)+"s";}
    std::string durationLabel() const {return "Duration: "+std::to_string(seconds_)+" seconds";}
    bool setSeconds(unsigned seconds) {
        if(!enabled_ || busy() || (seconds!=2 && seconds!=5))return false;
        seconds_=seconds;
        std::lock_guard lock(mutex_);
        pending_.label=visible_.label=idleLabel();
        return true;
    }
    void toggleDuration() {setSeconds(seconds_==2?5:2);}
    std::string label() const {return visible_.label;}
    std::string status() const {return visible_.status;}
    void start(const std::string& context="{}") {
        if(!enabled_ || busy())return;
        stopping_=false;
        CompositorRecordingStatus initial;initial.phase="awaiting_ack";initial.label="Preparing final output...";
        initial.status="Checking compositor capture";initial.directory=directory_;visible_=initial;update(std::move(initial));
        try {
            worker_=std::async(std::launch::async,[this,context,seconds=seconds_] {
                try {run(context,seconds);}catch(const std::exception& error){fail(error.what());}
            });
        } catch(const std::exception& error){fail(error.what());}
    }
    void poll() {
        if(!enabled_)return;
        if(worker_.valid() && worker_.wait_for(std::chrono::seconds(0))==std::future_status::ready)worker_.get();
        // Never wait for helper I/O or for its status lock on the render thread.
        std::unique_lock lock(mutex_,std::try_to_lock);if(lock.owns_lock())visible_=pending_;
    }
    void openFolder() {
        if(!enabled_)return;
        std::vector<std::string> args={"xdg-open",directory_};
        std::vector<char*> argv;for(auto& arg:args)argv.push_back(arg.data());argv.push_back(nullptr);
        pid_t pid=0;
        if(posix_spawnp(&pid,argv[0],nullptr,nullptr,argv.data(),environ)){fail("Could not open final-output folder");return;}
        std::thread([pid]{int status;while(waitpid(pid,&status,0)<0 && errno==EINTR){}}).detach();
    }
    std::string json() const {
        return "{\"source\":\"final_compositor_swapchain\",\"capture_boundary\":\"before_queue_present\","
            "\"optical_output_verified\":false,\"refresh_mapping_verified\":false,\"pixel_integrity_verified\":false,\"headset_identity_verified\":false,"
            "\"application_eye_recording\":false,\"duration_seconds\":"+std::to_string(seconds_)+",\"busy\":"+std::string(busy()?"true":"false")+
            ",\"recording\":"+(visible_.phase=="recording"?"true":"false")+
            ",\"phase\":"+quote(visible_.phase)+",\"label\":"+quote(visible_.label)+",\"status\":"+quote(visible_.status)+
            ",\"directory\":"+quote(visible_.directory)+",\"request\":"+std::to_string(visible_.request)+
            ",\"saved_frames\":"+std::to_string(visible_.saved)+",\"dropped_frames\":"+std::to_string(visible_.drops)+"}";
    }
    void shutdown() {
        stopping_=true;const pid_t pid=child_.load();if(pid>0)kill(pid,SIGTERM);
        if(worker_.valid()){try{worker_.get();}catch(...){}}
    }
};
} // namespace nadoc_vr
