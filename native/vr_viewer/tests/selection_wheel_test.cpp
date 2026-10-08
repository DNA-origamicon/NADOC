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
    wheel.update(true,{0,1},hand);
    const auto up=wheel.worldPoint({0,1,0})-wheel.worldPoint({0,0,0});
    assert(glm::distance(up,glm::vec3(0,std::sqrt(.75F),-.5F))<1e-6F);
    wheel.update(false,{0,0},hand);
    nadoc_vr::EditWheel edit;
    const std::array<glm::vec2,4> editAxes{{{1,0},{0,1},{-1,0},{0,-1}}};
    for(size_t i=0;i<4;++i) {
        assert(nadoc_vr::EditWheel::sector(editAxes[i])==i);
        edit.update(true,{0,0},hand);assert(edit.open() && !edit.hovered());
        const auto r=edit.update(true,editAxes[i],hand);assert(r.hoverChanged && !r.commit);
        assert(!edit.update(true,editAxes[i],hand).hoverChanged);
        const auto previous=edit.worldPoint({0,0,0});auto moved=hand;moved.position.x+=1;
        moved.orientation=glm::angleAxis(1.F,glm::vec3(0,1,0));
        edit.update(true,editAxes[i],moved);
        assert(edit.hovered()==i && glm::distance(previous,edit.worldPoint({0,0,0}))>.5F);
        assert(edit.update(false,{0,0},moved).commit==i && edit.blocksInput());
        assert(edit.filter(std::array<bool,2>{true,true})[0] && !edit.filter(std::array<bool,2>{true,true})[1]);
        assert(!edit.update(false,editAxes[i],hand).commit && !edit.blocksInput());
    }
    edit.update(true,editAxes[2],hand);edit.update(true,{0,0},hand);
    assert(!edit.update(false,editAxes[2],hand).commit);
    edit.update(true,editAxes[1],hand);edit.update(true,editAxes[1],hand,false);
    assert(!edit.open());edit.update(true,editAxes[1],hand);assert(!edit.open());
    assert(!edit.update(false,editAxes[1],hand).commit);
    edit.update(true,editAxes[0],hand);auto lost=hand;lost.valid=false;
    assert(!edit.update(false,editAxes[0],lost).commit && !edit.open());
    edit.update(true,editAxes[0],hand);edit.update(true,editAxes[3],hand);
    assert(edit.update(false,editAxes[0],hand).commit==3);
    edit.setWorkflow(true);
    assert(edit.itemCount()==2 && std::string(edit.itemLabel(0))=="BACK" && std::string(edit.itemLabel(1))=="NEXT");
    for(auto axis:std::array<glm::vec2,4>{{{-.8F,.5F},{-.8F,-.5F},{.8F,.5F},{.8F,-.5F}}}) {
        edit.update(true,axis,hand);
        assert(edit.update(false,{0,0},hand).commit==(axis.x<0?0U:1U));
    }
    edit.setWorkflow(true,true);
    assert(std::string(edit.itemLabel(1))=="CONFIRM");
    edit.update(true,{-1,0},hand);
    edit.setWorkflow(false);
    assert(!edit.update(false,{0,0},hand).commit && edit.itemCount()==4);
    edit.setSweep(true);
    assert(edit.itemCount()==2 && std::string(edit.itemLabel(0))=="DELETE LAST" && std::string(edit.itemLabel(1))=="ADD POINT");
    edit.update(true,{1,0},hand);
    assert(edit.update(false,{0,0},hand).commit==1); // Release axes reset, retained Add is committed.
    edit.update(true,{-1,0},hand);
    edit.update(true,{0,0},hand);
    assert(!edit.update(false,{-1,0},hand).commit); // Center cancels a destructive point edit.
    edit.update(true,{-1,0},hand);
    edit.setSweep(false);
    assert(!edit.update(false,{0,0},hand).commit && edit.itemCount()==4); // Switching tools never leaks Delete.
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
