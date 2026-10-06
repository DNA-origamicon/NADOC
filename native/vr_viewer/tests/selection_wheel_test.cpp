#include "selection_wheel.hpp"
#include <cassert>
#include <limits>
using nadoc_vr::SelectionWheel;
int main() {
    nadoc_vr::HandPose hand{true,false,{0,1,-.5F},{1,0,0,0}};
    SelectionWheel wheel;
    const std::array<glm::vec2,6> axes{{{0,1},{.8660254F,.5F},{.8660254F,-.5F},{0,-1},{-.8660254F,-.5F},{-.8660254F,.5F}}};
    for(size_t i=0;i<6;++i) {
        assert(SelectionWheel::sector(axes[i])==i);
        assert(!wheel.update(true,{0,0},hand).commit && wheel.open());
        auto r=wheel.update(true,axes[i],hand);assert(r.hoverChanged && !r.commit);
        assert(!wheel.update(true,axes[i]*.9F,hand).hoverChanged);
        auto moved=hand;moved.position.x+=.2F;
        wheel.update(true,axes[i],moved);assert(wheel.hovered()==i);
        r=wheel.update(false,{0,0},moved);assert(r.commit==i && !wheel.open() && wheel.blocksInput());
        assert(!wheel.update(false,{0,0},hand).commit && !wheel.blocksInput());
    }
    assert(SelectionWheel::sector({.49F,.8660254F})==0);
    assert(SelectionWheel::sector({.51F,.8660254F})==1);
    assert(SelectionWheel::sector({-.51F,.8660254F})==5);
    assert(!SelectionWheel::sector({.1F,.1F}));
    assert(!SelectionWheel::sector({std::numeric_limits<float>::quiet_NaN(),1}));
    wheel.update(true,axes[1],hand);wheel.update(true,{0,0},hand);
    assert(!wheel.update(false,axes[1],hand).commit); // Center cancels, release cannot retarget.
    wheel.update(true,axes[2],hand);wheel.update(true,axes[2],hand,false);
    assert(!wheel.open());wheel.update(true,axes[2],hand);assert(!wheel.open());
    assert(!wheel.update(false,axes[2],hand).commit);
    wheel.update(true,axes[3],hand);auto invalid=hand;invalid.valid=false;
    assert(!wheel.update(false,axes[3],invalid).commit && !wheel.open());
    wheel.update(true,{0,0},hand);int cold=0,hot=0;
    wheel.draw([&](auto,auto,auto color){if(color.x>.9F&&color.z<.3F)++cold;},"default");
    wheel.update(true,axes[5],hand);
    wheel.draw([&](auto,auto,auto color){if(color.x>.9F&&color.z<.3F)++hot;},"default");
    assert(hot>cold+100);
    assert(!wheel.filter(std::array<bool,2>{true,true})[0]);
    assert(wheel.filter(std::array<bool,2>{true,true})[1]);
}
