#include "view_volume_interaction.hpp"
#include <cassert>
using namespace nadoc_vr;
static bool near(glm::vec3 a,glm::vec3 b,float epsilon=1e-4F){return glm::length(a-b)<epsilon;}
struct Fixture {
    ViewVolumeInteraction grab;
    std::vector<ViewVolumeRecord> volumes;
    std::array<HandPose,2> hands{};
    std::array<bool,2> clicked{},pressed{};
    glm::mat4 frame=glm::scale(glm::mat4(1),glm::vec3(.01F));
    int changes=0,pulses=0;
    Fixture(size_t sides=4) {
        ViewVolumeRecord v;v.id="volume";v.editable=true;v.sides=sides;v.center={3,4,5};v.half={10,20,30};v.rebuild();volumes.push_back(v);
        for(auto& h:hands){h.valid=true;h.position={3,3,3};}
    }
    auto& v(){return volumes[0];}
    glm::vec3 world(glm::vec3 p){return ViewVolumeInteraction::point(frame,p);}
    std::array<bool,2> tick(bool sceneGrip=false,bool allowed=true) {
        auto claimed=grab.input(volumes,hands,clicked,pressed,frame,allowed,sceneGrip,[&](const auto&){++changes;},[&](size_t){++pulses;});clicked={};return claimed;
    }
    void hold(size_t hand=0){hands[hand].position=world(v().center);clicked[hand]=pressed[hand]=true;tick();assert(grab.hand==hand);}
    void face(size_t face){
        glm::vec3 center{};auto indices=v().face(face);for(auto i:indices)center+=v().points[i];center/=float(indices.size());
        size_t second=1-*grab.hand;hands[second].position=world(center);tick();assert(grab.nearbyFace[second]==int(face));
        clicked[second]=pressed[second]=true;tick();assert(grab.resizeFace==face);
    }
};
int main() {
    // Range uses physical tracking metres even with zoom and rotated scene axes.
    Fixture f;f.frame=glm::translate(glm::mat4(1),{.2F,-.1F,-1.F})*glm::toMat4(glm::angleAxis(.4F,glm::vec3(0,1,0)))*glm::scale(glm::mat4(1),glm::vec3(.02F));
    f.hands[0].position=f.world(f.v().center)+glm::vec3(.074F,0,0);f.tick();assert(f.grab.nearby[0]=="volume");
    f.hands[0].position+=glm::vec3(.002F,0,0);f.tick();assert(f.grab.nearby[0].empty());
    f.hold();const auto old=f.world(f.v().center);
    f.hands[0].position+=glm::vec3(.1F,.02F,0);f.hands[0].orientation=glm::angleAxis(.7F,glm::vec3(0,0,1));f.tick();
    assert(near(f.world(f.v().center),old+glm::vec3(.1F,.02F,0)));
    assert(std::abs(glm::dot(ViewVolumeInteraction::orientation(f.frame)*f.v().rotation,f.hands[0].orientation*ViewVolumeInteraction::orientation(f.frame)))>.9999F);
    f.pressed[0]=false;f.tick();assert(!f.grab.hand);const auto released=f.v().center;f.hands[0].position.x+=.5F;f.tick();assert(near(f.v().center,released));

    // Each box side/end changes only its own dimension; centroid stays fixed.
    for(size_t face=0;face<6;++face) {
        Fixture box;box.hold(face%2);box.face(face);
        auto before=box.v().half,center=box.v().center;auto normal=box.v().normal(face);size_t axis=face>=4?2:std::abs(normal.x)>.5?0:1;
        size_t second=1-*box.grab.hand;box.hands[second].position+=normal*.04F;box.tick();
        auto expected=before;expected[axis]+=4;assert(near(box.v().half,expected));assert(near(box.v().center,center));
        box.hands[second].position-=normal*100.F;box.tick();assert(box.v().half[axis]>0);assert(box.v().half[axis]<before[axis]);
        box.pressed[second]=false;box.tick();assert(!box.grab.resizeFace);assert(box.grab.hand);
    }
    // All hex side faces change the regular radius, both caps change length.
    for(size_t face=0;face<8;++face) {
        Fixture hex(6);hex.v().half={10,10,20};hex.v().rotation=glm::angleAxis(.35F,glm::normalize(glm::vec3(1,2,3)));hex.v().rebuild();hex.hold();hex.face(face);
        hex.hands[1].position+=hex.v().rotation*hex.v().normal(face)*.03F;hex.tick();
        if(face<6){assert(std::abs(hex.v().half.x-(10+3/std::cos(glm::pi<float>()/6)))<1e-3F);assert(hex.v().half.x==hex.v().half.y);assert(hex.v().half.z==20);}
        else {assert(near(hex.v().half,{10,10,23}));}
    }
    // Finite faces: far beyond a face boundary is not a grab target.
    Fixture finite;finite.hold();finite.hands[1].position=finite.world(finite.v().center+glm::vec3(10,100,100));finite.tick();assert(finite.grab.nearbyFace[1]<0);
    finite.hands[1].position=finite.world(finite.v().center+glm::vec3(14.9F,0,0));finite.tick();assert(finite.grab.nearbyFace[1]==1);
    finite.hands[1].position.x+=.002F;finite.tick();assert(finite.grab.nearbyFace[1]<0);

    // Grips retain the document pose, including during two-trigger resizing.
    Fixture grip;grip.hold();grip.face(1);const auto center=grip.v().center,half=grip.v().half;const auto rotation=grip.v().rotation;
    grip.frame=glm::translate(glm::mat4(1),{.4F,.2F,0})*glm::toMat4(glm::angleAxis(.5F,glm::vec3(0,1,0)))*grip.frame;
    grip.tick(true);assert(near(grip.v().center,center)&&near(grip.v().half,half));assert(std::abs(glm::dot(grip.v().rotation,rotation))>.9999F);
    grip.tick();assert(near(grip.v().center,center)&&near(grip.v().half,half));
    grip.hands[0].valid=false;grip.tick();assert(!grip.grab.hand&&!grip.grab.resizeFace);
    grip.hands[0].valid=true;grip.tick();assert(!grip.grab.hand); // needs a fresh press
    Fixture hidden;hidden.v().outline=false;hidden.hands[0].position=hidden.world(hidden.v().center);hidden.clicked[0]=hidden.pressed[0]=true;hidden.tick();assert(!hidden.grab.hand);
    Fixture disabled;disabled.v().enabled=false;disabled.hold();assert(disabled.grab.hand);
    Fixture outside;outside.hands[0].position=outside.world(outside.v().center);outside.clicked[0]=outside.pressed[0]=true;outside.tick(false,false);assert(!outside.grab.hand);
}
