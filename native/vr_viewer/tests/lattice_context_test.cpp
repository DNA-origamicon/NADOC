#include "lattice_context.hpp"
#include "lattice_view.hpp"
#include <cassert>
#include <sstream>

int main() {
    using namespace nadoc_vr;
    LatticeContext context;
    // XY rotated 90 degrees around X and translated; preserve signed cells.
    std::istringstream record("XY 12 -7 4 1 0 0 0 0 1 0 -1 0 8 4 -3 4 -2 4 -1 4 0 4 1 4 2 4 3 4 4");
    context.read(record);
    const auto* plane=context.find("XY");assert(plane && !context.find("XZ"));
    assert(plane->cells.size()==8 && plane->occupied({4,-3}) && !plane->occupied({4,5}));
    assert(context.occupancy("XY")==plane);
    std::istringstream occupied("XY 2 4 -3 4 5");context.readOccupancy(occupied);
    assert(context.occupancy("XY")->occupied({4,5}) && !plane->occupied({4,5}));
    assert(context.occupancy("XY")->cells.size()==2);
    ExtrudeLatticeDraft draft;
    assert(draft.setSelected({4,-3},true) && draft.setSelected({4,5},true));
    assert(plane->discardOccupied(draft));
    assert(draft.cells().size()==1 && draft.selected({4,5}) && !plane->discardOccupied(draft));
    assert(glm::distance(plane->point({4,5},true),glm::vec3(23.25F,-7,13))<1e-5F);
    assert(glm::distance(plane->point({-2,-3},false),glm::vec3(12-3*kHoneycombColumnPitchNanometers,-7,4-6.75F+1.125F))<1e-5F);
    const auto origin=centeredPaintOrigin(plane->cells);
    const auto zoom=fittedPaintZoom(plane->cells,origin,true,.06F);
    assert(zoom<1 && zoom>=.1F);
    for(const auto& cell:plane->cells) {
        const auto position=latticeCellOffsetNanometers(cell,origin,true)*.06F*zoom;
        assert(position.x>- .251F && position.x<.251F && position.y>-.150F && position.y<.168F);
    }
    int lines=0;glm::vec3 low(1e6F),high(-1e6F);
    plane->preview({{4,5},{4,4}},true,-24,glm::mat4(1),{1,2,3},.1F,{0,0,-2},
        [&](const glm::vec3& a,const glm::vec3& b,const glm::vec3&) {
            ++lines;low=glm::min(low,glm::min(a,b));high=glm::max(high,glm::max(a,b));
        });
    assert(lines==44); // Occupied cells never generate a new ghost.
    assert(std::abs(low.y-(-7-2)*.1F)<1e-5F);
    assert(std::abs(high.y-(-7+24*.334F-2)*.1F)<1e-5F);
    for(const auto* bad:{"XY 0 0 0 2 0 0 0 1 0 0 0 1 0",
                         "XY 0 0 0 1 0 0 0 1 0 0 0 1 2 0 0 0 0",
                         "XY 0 0 0 1 0 0 0 1 0 0 0 1 1 100001 0"}) {
        bool rejected=false;try{LatticeContext invalid;std::istringstream input(bad);invalid.read(input);}
        catch(const std::runtime_error&){rejected=true;}assert(rejected);
    }
}
