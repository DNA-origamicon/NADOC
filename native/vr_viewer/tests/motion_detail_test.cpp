#include "motion_detail.hpp"
#include <cassert>
#include <chrono>
#include <cstdlib>
int main() {
    using Clock=std::chrono::steady_clock;
    using namespace std::chrono_literals;
    setenv("NADOC_VR_MOTION_DETAIL","1",1);
    std::vector<unsigned short> indices(96);
    nadoc_vr::MotionDetail::appendCoarseCylinder(indices);
    assert(indices.size()==144);
    for(size_t i=96;i<indices.size();i+=3) {
        assert(indices[i]<34 && indices[i+1]<34 && indices[i+2]<34);
        assert(indices[i]!=indices[i+1] && indices[i]!=indices[i+2] && indices[i+1]!=indices[i+2]);
    }
    nadoc_vr::MotionDetail detail;
    const auto start=Clock::time_point{}+1s;
    detail.beginFrame(true,start); assert(!detail.reduced);
    detail.changed(start); detail.beginFrame(true,start+50ms); assert(detail.reduced);
    detail.beginFrame(true,start+179ms); assert(detail.reduced);
    detail.beginFrame(true,start+180ms); assert(!detail.reduced);
    detail.changed(start+200ms);detail.beginFrame(false,start+201ms);assert(!detail.reduced);
    detail.beginFrame(true,start+201ms);assert(detail.reduced);
    setenv("NADOC_VR_MOTION_DETAIL","0",1);
    nadoc_vr::MotionDetail full;full.changed(start);full.beginFrame(true,start);assert(!full.reduced);
}
