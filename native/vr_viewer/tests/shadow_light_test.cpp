#include "shadow_light.hpp"
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>
#include <cmath>
#include <iostream>
#include <stdexcept>

void check(bool ok,const char* message) {if(!ok)throw std::runtime_error(message);}
glm::mat4 camera(glm::quat head) {
    const auto light=nadoc_vr::headRelativeShadowLight(head);
    check(std::abs(glm::length(glm::cross(light.direction,light.up))-std::sqrt(2.F/3.F))<1e-5F,
          "Light frame became degenerate");
    const auto view=glm::lookAt(light.direction*2.F,glm::vec3(0),light.up);
    for(int c=0;c<4;++c)for(int r=0;r<4;++r)check(std::isfinite(view[c][r]),"Nonfinite shadow camera");
    return view;
}
float difference(glm::mat4 a,glm::mat4 b) {
    float d=0;for(int c=0;c<4;++c)for(int r=0;r<4;++r)d=std::max(d,std::abs(a[c][r]-b[c][r]));return d;
}
int main() {try {
    const auto key=glm::normalize(glm::vec3(-1,1,1));
    for(float sign:{-1.F,1.F}) {
        auto head=[&](float y) {
            return glm::rotation(key,glm::vec3(std::sqrt(1-y*y)*.70710678F,sign*y,std::sqrt(1-y*y)*.70710678F));
        };
        check(difference(camera(head(.94999F)),camera(head(.95001F)))<.001F,
              "Shadow camera jumps at old up-axis threshold");
        camera(glm::rotation(key,glm::vec3(0,sign,0))); // Exact world poles.
    }
    glm::mat4 previous=camera(glm::quat(1,0,0,0));
    for(int i=1;i<=3600;++i) {
        const auto q=glm::angleAxis(glm::radians(i*.1F),glm::normalize(glm::vec3(1,2,3)));
        const auto next=camera(q);
        check(difference(previous,next)<.005F,"Shadow camera discontinuity during full head rotation");
        check(difference(next,camera(-q))<1e-6F,"Quaternion sign changed shadow camera");
        previous=next;
    }
    // Direction conventions: light points from the surface toward the source.
    // In eye space it must stay upper-left/front, regardless of the head pose.
    // Rays travelling away from the source must preserve shadow UV and increase
    // shadow depth. These checks catch inverse/double rotation and sign errors.
    for(int i=0;i<360;++i) {
        const auto head=glm::angleAxis(glm::radians(float(i)),glm::normalize(glm::vec3(1,2,3)));
        const auto light=nadoc_vr::headRelativeShadowLight(head);
        check(glm::length(glm::inverse(head)*light.direction-key)<1e-5F,
              "Light does not stay in the intended head-local direction");
        const auto view=camera(head);
        check(glm::length(glm::vec3(view*glm::vec4(light.direction,0))-glm::vec3(0,0,1))<1e-5F,
              "Shadow camera looks away from the diffuse light source");
        const auto projection=glm::ortho(-1.F,1.F,-1.F,1.F,.05F,4.F)*view;
        const glm::vec3 caster(.1F,.2F,.3F);
        const auto a=projection*glm::vec4(caster,1);
        const auto b=projection*glm::vec4(caster-light.direction*.4F,1);
        check(glm::length(glm::vec2(a-b))<1e-5F && b.z>a.z,
              "Cast-shadow ray has the wrong UV or depth direction");
    }
    nadoc_vr::AnchoredShadowLight anchored;
    const auto initial=glm::angleAxis(.7F,glm::normalize(glm::vec3(1,2,3)));
    anchored.update(glm::quat(1,0,0,0),false); // Invalid tracking must not initialize.
    const auto expected=nadoc_vr::headRelativeShadowLight(initial);
    const auto captured=anchored.update(initial);
    check(glm::length(captured.direction-expected.direction)<1e-6F,"Initial light frame wrong");
    for(int i=0;i<3600;++i) {
        const auto moved=glm::angleAxis(i*.01F,glm::normalize(glm::vec3(3,2,1)));
        const auto light=anchored.update(moved,i%2==0);
        check(light.direction==captured.direction && light.up==captured.up,
              "Head motion or tracking loss moved the anchored light");
    }
    anchored.anchor(glm::quat(1,0,0,0));
    check(glm::length(anchored.update(initial).direction-key)<1e-6F,
          "Explicit placement did not reanchor lighting");
    nadoc_vr::AnchoredShadowLight witness;
    witness.anchor(initial);
    check(glm::length(anchored.update(initial).direction-key)<1e-6F,
          "Witness changed physical lighting");
    check(!anchored.headFollowing(),"Dynamic lighting must default off");
    anchored.setHeadFollowing(true);
    for(int i=0;i<360;++i) {
        const auto head=glm::angleAxis(i*.01F,glm::normalize(glm::vec3(3,2,1)));
        const auto actual=anchored.update(head);
        const auto expected=nadoc_vr::headRelativeShadowLight(head);
        check(actual.direction==expected.direction && actual.up==expected.up,
              "Dynamic mode did not follow head orientation");
    }
    const auto last=anchored.update(initial);
    const auto lost=anchored.update(glm::quat(1,0,0,0),false);
    check(lost.direction==last.direction,"Tracking loss moved dynamic light");
    anchored.setHeadFollowing(false);
    const auto frozen=anchored.update(glm::quat(1,0,0,0));
    check(frozen.direction==last.direction && frozen.up==last.up,
          "Disabling dynamic mode jumped or continued following the head");
    std::cout<<"Anchored lighting: tracking validity, head motion, loss, placement and separate views passed\n";
    std::cout<<"Continuous shadow frame: both thresholds, world poles and full head rotation passed\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
