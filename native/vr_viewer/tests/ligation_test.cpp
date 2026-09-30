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
    // Scissor tips follow controller forward, with the cutting center on the
    // closed blades, for both neutral and rotated controller poses.
    for(const auto orientation:{glm::quat(1,0,0,0),glm::angleAxis(.8F,glm::vec3(0,1,0))}) {
        const glm::vec3 center(.2F,1.4F,-.3F);
        std::vector<std::pair<glm::vec3,glm::vec3>> strokes;
        l.scissors(center,orientation,1,[&](glm::vec3 a,glm::vec3 b,glm::vec3){strokes.emplace_back(a,b);});
        const auto inv=glm::inverse(orientation);
        const auto back=inv*(strokes[1].first-center),tip=inv*(strokes[1].second-center);
        assert(glm::distance(tip,glm::vec3(0,0,-.033F))<1e-5F);
        assert(back.z>0 && std::abs(back.x)<1e-5F && std::abs(back.y)<1e-5F);
    }
    // Every accepted pose fires on its first frame, independently for both hands.
    const glm::vec3 head(0,1.6F,0);
    const auto aim=glm::rotation(glm::vec3(0,0,-1),glm::normalize(glm::vec3(0,1,1)));
    for(size_t h=0;h<2;++h)for(float yawAngle:{0.F,glm::half_pi<float>()}) {
        QuiverGesture q;std::array<HandPose,2> qs{};qs[h].valid=true;
        const auto yaw=glm::angleAxis(yawAngle,glm::vec3(0,1,0));
        const float side=h==0?-.28F:.28F;
        auto pose=[&](glm::vec3 p,bool oriented=true){qs[h].position=head+yaw*p;qs[h].orientation=yaw*(oriented?aim:glm::quat(1,0,0,0));};
        auto step=[&](bool enabled=true){return q.update(qs,head,yaw,0,enabled);};
        pose({side,.08F,.28F});assert(!step()); // starting in holster is not a reach
        pose({side,-.1F,-.4F});assert(!step());assert(q.armed[h]);
        pose({side,.08F,.28F},false);assert(!step()); // wrong orientation
        pose({-side,.08F,.28F});assert(!step()); // opposite shoulder
        pose({side,-.2F,.28F});assert(!step()); // below shoulder
        pose({side,.08F,.5F});assert(!step()); // too far behind
        pose({side,.08F,.28F});assert(step()==h);assert(q.sequence==1);
        assert(!step());assert(!step()); // no repeat while held
        pose({side,-.1F,-.4F});step();step(false);
        pose({side,.08F,.28F});assert(!step());
        pose({side,-.1F,-.4F});step();qs[h].valid=false;step();qs[h].valid=true;
        pose({side,.08F,.28F});assert(!step()); // tracking loss disarms
        pose({side,-.1F,-.4F});step();pose({side,.08F,.28F});assert(step()==h);
        q.reset();pose({side,0,-.25F});step();
        assert(!q.update(qs,head,yaw*glm::angleAxis(glm::pi<float>(),glm::vec3(0,1,0)),0,true));
    }
    std::cout<<"Ligation: both polarities, stretch, invalid targets, cancellation, single commit passed\n";
}
