#include "end_resize.hpp"
#include <cassert>
#include <iostream>
using namespace nadoc_vr;
int main() {
    EndResize tool;
    tool.version=1;tool.minimum=-5;tool.maximum=10;
    tool.arrows.push_back({{0,0,0},{0,0,1}});
    std::array<HandPose,2> hands{};hands[0].valid=true;hands[0].position={0,0,.02F};
    std::array<bool,2> blocked{},clicked{true,false},pressed{true,false};
    const auto model=glm::scale(glm::mat4(1),glm::vec3(2));
    int commits=0;
    auto step=[&](bool enabled=true) {blocked.fill(false);tool.input(hands,clicked,pressed,blocked,model,.01F,enabled,[&]{++commits;});};
    step();assert(tool.hand && blocked[0]);clicked.fill(false);
    // Seven base pairs after a twofold scene scale, with lateral motion ignored.
    hands[0].position+=glm::vec3(.2F,0,7*.334F*.01F*2);
    step();assert(tool.delta==7);
    pressed[0]=false;step();assert(commits==1 && tool.committedDelta==7);
    step();assert(commits==1);
    tool.waitingVersion=0;hands[0].position={0,0,.02F};pressed[0]=clicked[0]=true;
    step();clicked[0]=false;hands[0].position.z=-1;step();assert(tool.delta==-5);
    step(false);assert(!tool.hand && tool.delta==0 && commits==1);
    hands[0].position={0,0,.02F};clicked[0]=true;step();assert(tool.hand);
    hands[0].valid=false;step();assert(!tool.hand && commits==1);
    // Retired wire offsets cannot move natural handles.
    tool.arrows[0].offset={.1F,0,0};
    assert(glm::distance(tool.point(tool.arrows[0],model,.01F,0),glm::vec3(0))<.00001F);
    // Remote pointing highlights only the aimed arrow, then captures a pull.
    EndResize remote;remote.version=2;remote.minimum=-5;remote.maximum=10;
    remote.arrows={{{0,0,-1},{1,0,0}},{{.2F,0,-1},{-1,0,0}}};
    hands={};hands[1].valid=true;hands[1].position={.02F,0,0};
    clicked={};pressed={};blocked={};
    auto remoteStep=[&](bool enabled=true){blocked={};remote.input(hands,clicked,pressed,blocked,glm::mat4(1),.01F,enabled,[&]{++commits;});};
    remoteStep();assert(remote.hoverHand==1 && remote.hovered==0 && !remote.hand);
    int yellow=0,cyan=0;
    remote.draw(glm::mat4(1),.01F,[&](auto,auto,glm::vec3 c){if(c==glm::vec3(1,1,.1F))++yellow;else if(c==glm::vec3(0,.9F,1))++cyan;});
    assert(yellow==9 && cyan==9);
    clicked[1]=pressed[1]=true;remoteStep();assert(remote.hand==1 && blocked[1]);
    clicked={};hands[1].position.x+=7*.334F*.01F;remoteStep();assert(remote.delta==7);
    assert(remote.label()=="+7 bases");
    assert(glm::distance(remote.labelPosition(),(remote.pointerStart+remote.pointerEnd)*.5F)<1e-6F);
    // Opposite-facing selected ends each preview the same seven-base extension.
    assert(std::abs(remote.point(remote.arrows[0],glm::mat4(1),.01F,0).x-7*.334F*.01F)<1e-6F);
    assert(std::abs(remote.point(remote.arrows[1],glm::mat4(1),.01F,0).x-(.2F-7*.334F*.01F))<1e-6F);
    int lines=0,labels=0;
    remote.drawPointer(glm::quat(1,0,0,0),[&](auto a,auto b,auto){++lines;assert(a==remote.pointerStart && b==remote.pointerEnd);},
        [&](const auto& placement,const std::string& value,auto...){++labels;assert(value=="+7 bases");assert(glm::distance(placement.worldPoint({0,0,0}),remote.labelPosition())<1e-6F);});
    assert(lines==1 && labels==1);
    pressed[1]=false;remoteStep();assert(remote.committedDelta==7 && !remote.hand && commits==2);
    remote.waitingVersion=0;hands[1].orientation=glm::angleAxis(glm::pi<float>(),glm::vec3(0,1,0));
    remoteStep();assert(!remote.hoverHand); // Ray facing away cannot acquire.
    hands[1].orientation={1,0,0,0};remoteStep(false);assert(!remote.hoverHand);
    std::cout<<"End resize: scaled projection, clamping, one release, focus/tracking cancellation passed\n";
}
