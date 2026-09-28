#include "ligation.hpp"
#include "quiver_gesture.hpp"
#include <cassert>
#include <iostream>
using namespace nadoc_vr;
int main() {
    assert(std::string(kRadialEditLabels[0])=="LIGATE");
    for(size_t i=0;i<4;++i)assert(radialEditEnabled(i));
    Ligation l;l.version=1;l.setActive(true);
    l.ends={{3,0,"a",{0,0,0},{0,0,1},{}},{5,1,"b",{.1F,0,0},{0,0,1},{}},
            {3,2,"c",{0,.1F,0},{0,0,1},{}},{5,0,"d",{.1F,.1F,0},{0,0,1},{}}};
    std::array<HandPose,2> hands{};hands[0].valid=true;
    std::array<glm::vec3,2> centers{};
    std::array<bool,2> clicked{true,false},pressed{true,false},blocked{};
    int selected=0,commits=0;
    auto step=[&](bool enabled=true){blocked={};l.input(hands,centers,{.02F,.02F},clicked,pressed,blocked,glm::mat4(1),enabled,
        [&](const auto&,size_t){++selected;},[&]{++commits;});};
    step();assert(l.hand && selected==1);clicked[0]=false;
    centers[0]={.05F,0,.04F};step();assert(!l.target && l.previewEnd(glm::mat4(1))==centers[0]);
    centers[0]={0,.1F,0};step();assert(!l.target && l.incompatible);
    pressed[0]=false;step();assert(!l.hand && commits==0);
    centers[0]={0,0,0};pressed[0]=clicked[0]=true;step();clicked[0]=false;
    centers[0]={.1F,.1F,0};step();assert(!l.target);
    centers[0]={.1F,0,0};step();assert(l.target==1);
    pressed[0]=false;step();assert(commits==1 && l.waiting && l.committedSource==0 && l.committedTarget==1);
    step();assert(commits==1);
    l.waiting=false;centers[0]={.1F,0,0};pressed[0]=clicked[0]=true;step();clicked[0]=false;
    centers[0]={0,0,0};step();assert(l.target==0);step(false);assert(!l.hand && commits==1);
    l.setActive(false);l.nickActive=true;l.waiting=false;
    l.bonds={{{0,0,0},{.1F,0,0},{},{}}};hands[1].valid=true;centers[1]={.05F,0,0};clicked={};
    auto nick=[&](float pressure,bool click,bool enabled=true){blocked={};clicked[1]=click;
        l.nickInput(hands,centers,{.02F,.02F},{0,pressure},clicked,blocked,glm::mat4(1),enabled,[&]{++commits;});};
    centers[0]={.05F,0,0};clicked={true,false};blocked={};
    l.nickInput(hands,centers,{.02F,.02F},{1,0},clicked,blocked,glm::mat4(1),true,[&]{++commits;});
    assert(commits==1 && !l.nickHover[0] && !blocked[0]);clicked={};
    nick(.2F,false);assert(l.nickHover[1]==0 && commits==1);
    nick(.7F,false);assert(l.nickHover[1]==0 && commits==1);
    assert(Ligation::scissorAngle(.7F)<Ligation::scissorAngle(.2F));
    assert(Ligation::scissorAngle(1)==0);
    nick(1,true);assert(commits==2 && l.waiting && l.committedAction=="nick");
    nick(1,false);assert(commits==2);
    l.waiting=false;nick(1,true,false);assert(commits==2 && !l.nickHover[1]);
    l.request("undo",0,[&]{++commits;});assert(commits==3 && l.committedAction=="undo");
    l.request("redo",0,[&]{++commits;});assert(commits==3);
    l.waiting=false;l.request("redo",0,[&]{++commits;});assert(commits==4 && l.committedAction=="redo");
    QuiverGesture q;std::array<HandPose,2> qs{};qs[1].valid=true;
    auto gesture=[&](double time,bool enabled=true){return q.update(qs,{0,1.6F,0},glm::quat(1,0,0,0),time,enabled);};
    qs[1].position={.25F,1.6F,.25F};assert(!gesture(0));assert(!gesture(1)); // starts behind: no toggle
    qs[1].position={.25F,1.4F,-.35F};gesture(2);gesture(2.2);assert(q.armed[1]);
    qs[1].position={.25F,1.6F,.25F};assert(!gesture(3));assert(!gesture(3.2));assert(gesture(3.4)==1);
    assert(q.sequence==1);assert(!gesture(4));assert(!gesture(5)); // held behind: no repeat
    qs[1].position={.25F,1.4F,-.35F};gesture(6);gesture(6.2);
    qs[1].position={.25F,1.6F,.25F};gesture(7);gesture(7.2,false);assert(!gesture(8));
    qs[1].position={.25F,1.4F,-.35F};gesture(9);gesture(9.2);
    qs[1].position={.25F,1.6F,.25F};gesture(10);qs[1].valid=false;gesture(10.2);qs[1].valid=true;assert(!gesture(11));
    q.reset();qs[1].position={.25F,1.6F,-.25F};gesture(12);gesture(12.2);
    auto turned=glm::angleAxis(glm::pi<float>(),glm::vec3(0,1,0));
    assert(!q.update(qs,{0,1.6F,0},turned,13,true));
    assert(!q.update(qs,{0,1.6F,0},turned,14,true)); // turning the head alone is not a reach
    q.reset();qs[0].valid=true;qs[1].valid=false;qs[0].position={-.25F,1.6F,-.35F};
    gesture(15);gesture(15.2);qs[0].position={-.25F,1.6F,.25F};gesture(16);assert(gesture(16.4)==0);
    const auto yaw=glm::angleAxis(glm::half_pi<float>(),glm::vec3(0,1,0));
    const auto rel=QuiverGesture::local(glm::vec3(3,2,1)+yaw*glm::vec3(.25F,0,.25F),{3,2,1},yaw);
    assert(glm::distance(rel,glm::vec3(.25F,0,.25F))<1e-5F);
    std::cout<<"Ligation: both polarities, stretch, invalid targets, cancellation, single commit passed\n";
}
