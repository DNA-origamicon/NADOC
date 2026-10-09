#include "controller_prompt.hpp"
#include "browser_prompt.hpp"
#include <filesystem>
#include <chrono>
#include <cassert>
#include <limits>
using nadoc_vr::ControllerPrompt;
int main() {
    nadoc_vr::HandPose hand{true,false,{0,1,-.5F},{1,0,0,0}};
    for(size_t n=1;n<=4;++n)for(size_t choice=0;choice<n;++choice) {
        ControllerPrompt p;int pulses=0,answers=0;std::string answer;
        ControllerPrompt::Request r{"Question","Read this message",{},[&](auto id){++answers;answer=id;}};
        for(size_t i=0;i<n;++i)r.options.push_back({std::to_string(i),"Option"});
        p.show(r);
        auto update=[&](bool pressed,glm::vec2 axis,double t){p.update(pressed,axis,hand,t,[&](float a){assert(a>.5F);++pulses;});};
        const auto axis=ControllerPrompt::direction(choice,n);
        // A held input at arrival cannot answer; pulse timing survives a stall.
        update(true,axis,0);update(false,{},.01);assert(answers==0 && pulses==1);
        update(false,{},10);assert(pulses==2);
        update(false,{},10.01);assert(pulses==2);
        update(false,{},10.2);assert(pulses==3);
        assert(p.sector(axis)==choice);
        assert(!p.sector({0,0}));
        assert(!p.sector({std::numeric_limits<float>::quiet_NaN(),0}));
        update(true,axis,11);update(true,{},11.1);update(false,axis,11.2);
        assert(answers==0 && p.active()); // Center aborts gesture, not dialog.
        update(true,axis,12);auto lost=hand;lost.valid=false;
        p.update(false,{},lost,12.1,[](float){assert(false);});
        update(false,{},12.2);assert(answers==0);
        update(true,axis,13);update(false,{},13.1); // Release axis reset retains choice.
        assert(answers==1 && answer==std::to_string(choice) && !p.active());
        update(false,{},14);assert(answers==1 && pulses==3);
    }
    ControllerPrompt p;int answers=0;
    p.show({"One","Queued",{{"ok","OK"}},[&](auto){++answers;p.show({"Three","Callback",{{"ok","OK"}}, {}});}});
    p.show({"Two","Queued",{{"ok","OK"}}, {}});assert(p.queued()==2);
    auto tick=[&](bool held,double time){p.update(held,{0,1},hand,time,[](float){});};
    tick(false,0);tick(false,.2);tick(false,.4);tick(true,.5);tick(false,.6);
    assert(answers==1 && p.queued()==2 && p.request().title=="Two");
    tick(true,1);tick(false,1.2);assert(p.queued()==2); // Fresh gesture per queued dialog.
    for(size_t n:{0U,5U}) {
        ControllerPrompt::Request bad;bad.options.assign(n,{"id","Label"});
        bool rejected=false;try{p.show(bad);}catch(const std::invalid_argument&){rejected=true;}
        assert(rejected && p.queued()==2);
    }
    ControllerPrompt longPrompt;
    longPrompt.show({"Long message",std::string(900,'X'),{{"ok","OK"}}, {}});
    longPrompt.update(false,{},hand,0,[](float){});
    longPrompt.update(true,{},hand,.2,[](float){});
    longPrompt.update(false,{},hand,.4,[](float){});
    assert(longPrompt.active() && longPrompt.page()==1);

    const auto directory=std::filesystem::temp_directory_path()/
        ("nadoc-prompt-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(directory);
    const auto path=(directory/"events").string();
    nadoc_vr::BrowserPrompt browser;ControllerPrompt remote;int publications=0;
    auto write=[&](const std::string& body){std::ofstream(path+".prompt")<<body;};
    auto poll=[&](double now){browser.poll(path,remote,now,[&](auto request){remote.show(std::move(request));},[&]{++publications;});};
    write("NADOC_PROMPT_1 1 1 2 1 \"Delete?\" \"Remove strand S1?\"\n\"0\" \"Cancel\"\n\"1\" \"Delete\"\n");
    poll(0);assert(remote.active() && remote.request().options.size()==2);
    poll(.1);assert(remote.queued()==1);
    remote.update(false,{},hand,0,[](float){});remote.update(false,{},hand,.2,[](float){});
    remote.update(false,{},hand,.4,[](float){});remote.update(true,{1,0},hand,.5,[](float){});
    remote.update(false,{},hand,.6,[](float){});
    assert(!remote.active() && publications==1 && browser.answer=="1" && browser.answerVersion==1);
    write("NADOC_PROMPT_1 1 2 2 1 \"Delete?\" \"Remove strand S1?\"\n\"0\" \"Cancel\"\n\"1\" \"Delete\"\n");
    poll(1);assert(!remote.active()); // Heartbeat cannot reopen an answered request.
    write("NADOC_PROMPT_1 2 3 1 0 \"New\" \"Read me\"\n\"0\" \"OK\"\n");
    poll(2);assert(remote.active() && !browser.detailAllowed);
    poll(8);assert(!remote.active() && publications==2 && browser.answer=="dismiss");
    remote.show({"Local","Keep this",{{"ok","OK"}}, {},"local"});
    write("NADOC_PROMPT_1 3 4 0 1 \"\" \"\"\n");
    poll(9);assert(remote.active() && remote.request().title=="Local");
    // Malformed files cannot replace a valid prompt or inject an extra option.
    write("NADOC_PROMPT_1 4 5 5 1 \"Bad\" \"Bad\"\n");
    poll(10);assert(browser.version==3 && remote.queued()==1);
    std::filesystem::remove_all(directory);

}
