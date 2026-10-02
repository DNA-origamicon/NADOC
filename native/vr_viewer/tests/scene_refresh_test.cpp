#include "scene_refresh.hpp"
#include <cassert>
#include <filesystem>
#include <thread>
#include <unistd.h>

int main() {
    namespace fs = std::filesystem;
    const auto root=fs::temp_directory_path()/("nadoc-refresh-test-"+std::to_string(getpid()));
    fs::create_directory(root);
    struct Cleanup { fs::path path; ~Cleanup(){fs::remove_all(path);} } cleanup{root};
    const auto path=(root/"events").string();
    auto publish=[&](int rev){std::ofstream(path+".scene")<<"NADOCVR_SCENE 1 "<<rev<<" "<<path<<".scene-"<<rev;};
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
}
