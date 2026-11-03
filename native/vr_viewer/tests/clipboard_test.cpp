#include "clipboard.hpp"
#include <cassert>
using namespace nadoc_vr;
int main() {
    ClipboardPreview c;
    HandPose h{true,false,{0,1,-.5F},{1,0,0,0}};
    const auto frame=glm::translate(glm::mat4(1),glm::vec3(2,0,0))*glm::scale(glm::mat4(1),glm::vec3(.01F));
    assert(!c.paste(h,frame));
    assert(c.copy({{{1,0,0},{3,0,0}}},{"owner"},h,frame));
    assert(glm::distance(glm::vec3(c.placement*glm::vec4(c.center,1)),glm::vec3(0,1,-.62F))<1e-5F);
    assert(!c.paste(h,frame));
    c.acknowledge(false,"created");
    h.position.x+=.3F;h.orientation=glm::angleAxis(.7F,glm::vec3(0,1,0));c.update(h);
    const auto visible=c.placement*glm::vec4(1,0,0,1);
    assert(c.paste(h,frame));
    assert(glm::distance(frame*c.committed*glm::inverse(frame)*glm::vec4(1,0,0,1),visible)<1e-4F);
    h.position.x+=1;c.update(h);assert(c.placement*glm::vec4(1,0,0,1)==visible);
    c.acknowledge(false,"failed");assert(c.active && !c.awaiting);
    assert(c.paste(h,frame));c.acknowledge(false,"created");assert(!c.active);
    assert(c.copy({{{1,0,0},{3,0,0}}},{"owner"},h,frame));c.acknowledge(false,"refused");assert(!c.active);
    // Resolved domain geometry arrives asynchronously, even when the picked
    // primitive is absent from the current representation.
    assert(c.copy({}, {"base-owner"}, h, frame));
    assert(c.segments.empty() && !c.paste(h,frame));
    h.position.x+=.2F;
    c.confirm({{{0,0,0},{0,0,10}}},h);
    assert(c.segments.size()==1);
    assert(glm::distance(c.segments[0].second,glm::vec3(frame*glm::vec4(0,0,10,1)))<1e-5F);
    assert(glm::distance(glm::vec3(c.placement*glm::vec4(c.center,1)),h.position+h.orientation*glm::vec3(0,0,-.12F))<1e-5F);
    c.acknowledge(false,"created");assert(c.paste(h,frame));
}
