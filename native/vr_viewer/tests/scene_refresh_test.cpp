#include "scene_refresh.hpp"
#include <cassert>
#include <cerrno>
#include <filesystem>
#include <thread>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>

int main() {
    namespace fs = std::filesystem;
    const auto root=fs::temp_directory_path()/("nadoc-refresh-test-"+std::to_string(getpid()));
    fs::create_directory(root);
    struct Cleanup { fs::path path; ~Cleanup(){fs::remove_all(path);} } cleanup{root};
    const auto path=(root/"events").string();
    auto publish=[&](int rev){std::ofstream(path+".scene")<<"NADOCVR_SCENE 1 "<<rev<<" "<<path<<".scene-"<<rev;};
    // Integration regression: a full stdout pipe must not block scene activation
    // on the context thread. The former std::endl acknowledgement blocked here.
    publish(1);
    int output[2],ack[2];assert(pipe(output)==0 && pipe(ack)==0);
    assert(fcntl(output[1],F_SETFL,O_NONBLOCK)==0);
    const char padding[4096]={};
    while(write(output[1],padding,sizeof(padding))>0){}
    assert(errno==EAGAIN);
    assert(fcntl(output[1],F_SETFL,0)==0);
    const auto child=fork();assert(child>=0);
    if(child==0) {
        close(output[0]);close(ack[0]);
        if(dup2(output[1],STDOUT_FILENO)<0)_exit(2);
        nadoc_vr::SceneRefreshInbox<int> blockedOutputInbox;
        while(blockedOutputInbox.revision()!=1) {
            blockedOutputInbox.poll(path,[](const std::string&){return 42;},[](int scene){assert(scene==42);});
            std::this_thread::yield();
        }
        const char ready=1;
        if(write(ack[1],&ready,1)!=1)_exit(3);
        _exit(0); // The intentionally blocked writer cannot drain on shutdown.
    }
    close(output[1]);close(ack[1]);
    pollfd readiness{ack[0],POLLIN,0};
    const bool responsive=poll(&readiness,1,2000)>0 && (readiness.revents&POLLIN);
    if(!responsive)kill(child,SIGKILL);
    int status=0;assert(waitpid(child,&status,0)==child);
    close(output[0]);close(ack[0]);
    assert(responsive && WIFEXITED(status) && WEXITSTATUS(status)==0);
    nadoc_vr::SceneRefreshInbox<int> inbox;
    const auto caller=std::this_thread::get_id();
    std::promise<void> release;
    const auto gate=release.get_future().share();
    bool applied=false;
    auto load=[&](const std::string& p){assert(std::this_thread::get_id()!=caller);assert(p==path+".scene-1");gate.wait();return 42;};
    auto apply=[&](int scene){assert(std::this_thread::get_id()==caller);assert(scene==42);applied=true;};
    publish(1);
    for(int i=0;i<15;++i)inbox.poll(path,load,apply);
    // A blocked parser must never block polling or publish an incomplete scene.
    for(int i=0;i<100;++i)inbox.poll(path,load,apply);
    assert(!applied && inbox.revision()==0);
    release.set_value();
    auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(!applied && std::chrono::steady_clock::now()<deadline){inbox.poll(path,load,apply);std::this_thread::yield();}
    assert(applied && inbox.revision()==1);
    publish(2);
    std::atomic<int> attempts=0;
    auto retryLoad=[&](const std::string&){if(++attempts==1)throw std::runtime_error("transient parse failure");return 43;};
    auto retryApply=[&](int scene){assert(scene==43);assert(inbox.revision()==1);};
    while(inbox.revision()!=2 && std::chrono::steady_clock::now()<deadline){inbox.poll(path,retryLoad,retryApply);std::this_thread::yield();}
    assert(inbox.revision()==2 && attempts==2);
    // Replayed, malformed and unrelated paths never reach the parser.
    for(auto record:{"NADOCVR_SCENE 1 1 "+path+".scene-1", std::string("NADOCVR_SCENE 1 3 /unrelated"), "NADOCVR_SCENE 1 3 "+path+".scene-3 trailing"}){
        std::ofstream(path+".scene")<<record;
        for(int i=0;i<30;++i)inbox.poll(path,retryLoad,retryApply);
    }
    assert(attempts==2);
    // Multi-frame GPU staging never acknowledges a partially visible revision.
    publish(3);
    int begins=0, advances=0;
    auto begin=[&](int scene){assert(scene==44);++begins;};
    auto advance=[&]{assert(inbox.revision()==2);return ++advances==4;};
    while(inbox.revision()!=3 && std::chrono::steady_clock::now()<deadline){
        inbox.pollStaged(path,[](const std::string&){return 44;},begin,advance);
        std::this_thread::yield();
    }
    assert(inbox.revision()==3 && begins==1 && advances==4);
    publish(4);begins=0;advances=0;
    auto failOnce=[&]{assert(inbox.revision()==3);if(++advances==1)throw std::runtime_error("upload failure");return true;};
    while(inbox.revision()!=4 && std::chrono::steady_clock::now()<deadline){
        inbox.pollStaged(path,[](const std::string&){return 44;},begin,failOnce);
        std::this_thread::yield();
    }
    assert(inbox.revision()==4 && begins==2 && advances==2);
}
