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
    tool.arrows[0].offset={.1F,0,0};tool.expansion=1;
    assert(glm::distance(tool.point(tool.arrows[0],model,.01F,0),glm::vec3(.2F,0,0))<.00001F);
    hands[0].valid=true;hands[0].position={.2F,0,.02F};clicked[0]=true;step();assert(tool.hand);
    clicked[0]=false;tool.expansion=.5F;step();assert(!tool.hand && commits==1);
    std::cout<<"End resize: scaled projection, clamping, one release, focus/tracking cancellation passed\n";
}
