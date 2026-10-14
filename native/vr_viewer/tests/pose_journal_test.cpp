#include "pose_journal.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <thread>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <openxr/openxr.h>

using nadoc_vr::PoseJournal;
template<class F> void rejects(F action) {
    bool rejected=false;try{action();}catch(const std::runtime_error&){rejected=true;}assert(rejected);
}
std::string read(const std::filesystem::path& path) {
    std::ifstream input(path);return {std::istreambuf_iterator<char>(input),{}};
}
void saved(PoseJournal& journal) {
    for(int i=0;i<200 && journal.json().find("\"phase\":\"writing\"")!=std::string::npos;++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));journal.poll();
    }
    assert(journal.json().find("\"phase\":\"writing\"")==std::string::npos);
}
int main(int argc,char** argv) {
    assert(argc==2);
    assert(PoseJournal::parseRequest("18446744073709551615")==std::numeric_limits<uint64_t>::max());
    for(const auto* invalid:{"-1","+1","0","1x"," 1","18446744073709551616",""})
        rejects([&]{PoseJournal::parseRequest(invalid);});
    const auto base=std::filesystem::path(argv[1])/std::to_string(getpid());
    assert(!std::filesystem::exists(base));std::filesystem::create_directories(base);
    PoseJournal disabled;assert(!disabled.enabled());assert(disabled.stamp()==0);
    rejects([&]{disabled.arm(1,2,100);});assert(disabled.frame()==nullptr);
    PoseJournal journal(4);journal.enable((base/"coherent").string(),"test-session");
    journal.setFrameIdentityConfig(nadoc_vr::frame_identity::configJson(nadoc_vr::frame_identity::Mode::recording,{123,456}));
    const int64_t now=1000000000,start=now+100000000,end=start+200000000;
    journal.setClockMapper([&](int64_t xr)->std::optional<int64_t>{if(xr==999)return std::nullopt;return xr+start;});
    rejects([&]{journal.arm(0,2,now);});rejects([&]{journal.arm(1,31,now);});
    journal.arm(123,2,now);
    rejects([&]{journal.arm(124,2,now);});rejects([&]{journal.window(124,start,end,now);});
    rejects([&]{journal.window(123,start,start,now);});
    journal.window(123,start,end,now);
    rejects([&]{journal.flush(123,start);});assert(std::filesystem::is_empty(base/"coherent"));
    const auto model=glm::translate(glm::mat4(1),{.3F,.4F,.5F});
    XrView eye{};eye.type=XR_TYPE_VIEW;eye.pose.orientation.w=1;eye.pose.position={.1F,.2F,.3F};eye.fov={-.7F,.8F,.9F,-.6F};
    for(int i=0;i<3;++i) {
        const int64_t host= i==0?now+1 : i==1?start+1:end+1;
        journal.begin(10+i,i==2?999:i==0?-1:1,11111111,true,host);
        auto* frame=journal.frame();assert(frame);frame->model=PoseJournal::matrix(model);
        nadoc_vr::CaptureUiDiagnostics ui;ui.begin(&frame->captureUi);ui.sidebar(0,true,"tools:record");
        const auto event=ui.request(1,.3F,42);const auto begin=ui.stamp();ui.dispatched(event,1,begin,-1);ui.end();
        frame->sourceCenter={5,6,7};frame->normalizationScale=.02F;frame->offset={0,0,-1.3F};
        frame->viewFlags=15;frame->hands[1].provider=1;frame->hands[1].valid=true;frame->hands[1].grip=true;
        frame->hands[1].locationFlags=3;frame->hands[1].queried=true;
        frame->hands[1].runtime.position={1,2,3};frame->hands[1].applied.position={4,5,6};
        std::snprintf(frame->representation.data(),frame->representation.size(),"stick");
        journal.eye(0,1852,2056,2,eye,model);
        nadoc_vr::frame_identity::Receipt marker;marker.rendered=true;marker.frame=10+i;
        marker.packetCrc32=nadoc_vr::frame_identity::packetCrc(nadoc_vr::frame_identity::encode({123,456},10+i,0));
        marker.rect=nadoc_vr::frame_identity::rectangle(1852,2056);marker.hostStartNs=host;marker.hostEndNs=host+1;
        journal.frameIdentity(0,marker);
        auto other=model;other[3].x=.35F;eye.pose.position.x=.17F;journal.eye(1,1852,2056,1,eye,other);
        journal.finish(i==2?-1:0,true,host+1);
    }
    assert(std::filesystem::is_empty(base/"coherent"));
    journal.poll(end+PoseJournal::tailNs);assert(!journal.collecting());
    journal.flush(123,end+PoseJournal::tailNs);rejects([&]{journal.flush(123,end+PoseJournal::tailNs);});saved(journal);
    assert(journal.json().find("\"phase\":\"saved\"")!=std::string::npos);
    const auto file=base/"coherent"/("pose-journal-"+std::to_string(getpid())+"-123.jsonl");
    const auto text=read(file);
    assert(text.find("\"session\":\"test-session\"")!=std::string::npos);
    assert(text.find("\"capture_ui_diagnostics\":{\"version\":1,\"enabled\":true")!=std::string::npos);
    assert(text.find("\"hover_id\":\"tools:record\"")!=std::string::npos);
    assert(text.find("\"callsite_line\":42")!=std::string::npos && text.find("\"xr_result\":-1")!=std::string::npos);
    assert(text.find("\"frame_identity\":{\"enabled\":true,")!=std::string::npos);
    assert(text.find("\"protocol\":\"nadoc-frame-v2\"")!=std::string::npos);
    assert(text.find("\"activation_mode\":\"recording\"")!=std::string::npos);
    assert(text.find("\"frame_identity\":{\"rendered\":true,\"frame\":11,")!=std::string::npos);
    assert(text.find("\"rectangle_xywh\":[830,726,192,192]")!=std::string::npos);
    assert(text.find("\"frame_identity\":{\"rendered\":false,")!=std::string::npos);
    assert(text.find("\"predicted_display_monotonic_ns\":1100000001")!=std::string::npos);
    assert(text.find("\"predicted_display_monotonic_ns\":null")!=std::string::npos);
    assert(text.find("\"predicted_window_relation\":\"preroll\"")!=std::string::npos);
    assert(text.find("\"host_window_relation\":\"tail\"")!=std::string::npos);
    assert(text.find("\"runtime_location_flags\":3")!=std::string::npos);
    assert(text.find("\"xr_end_frame_succeeded\":false,\"submitted\":false")!=std::string::npos);
    assert(text.find("\"mapping_failures\":1,\"complete\":true")!=std::string::npos);
    assert(journal.contextJson("/test.sock").find("\"session\":\"test-session\"")!=std::string::npos);

    PoseJournal bounded(1);bounded.enable((base/"bounded").string(),"test-bounded");bounded.arm(456,2,now);bounded.window(456,start,end,now);
    for(int i=0;i<3;++i){bounded.begin(i,1,1,true,start+i);bounded.finish(0,true,start+i+1);}
    bounded.flush(456,end+PoseJournal::tailNs);saved(bounded);
    assert(bounded.json().find("\"phase\":\"partial\"")!=std::string::npos);
    const auto partial=read(base/"bounded"/("pose-journal-"+std::to_string(getpid())+"-456.jsonl"));
    assert(partial.find("\"overflow_frames\":2")!=std::string::npos);
    assert(partial.find("\"clock_mapping\":\"unavailable\"")!=std::string::npos);
    assert(partial.find("\"frame\":1,")==std::string::npos); // no overwrite
    bounded.arm(789,1,now);bounded.poll(now+1000000000);assert(!bounded.collecting());
    rejects([&]{bounded.flush(789,now+1000000000);});
    rejects([&]{bounded.arm(999,1,now+1000000000);});
    bounded.cancel(789);bounded.arm(999,1,now+1000000000);bounded.cancel(999);

    // Existing evidence is never overwritten, and failed writes are explicit.
    journal.arm(123,2,now);journal.window(123,start,end,now);journal.flush(123,end+PoseJournal::tailNs);saved(journal);
    assert(journal.json().find("\"phase\":\"error\"")!=std::string::npos);assert(read(file)==text);
    std::cout<<base.string()<<'\n';
}
