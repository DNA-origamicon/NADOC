#pragma once
#include "interaction.hpp"
#include "extrude_plane.hpp"
#include <cstdint>
#include <istream>
#include <unordered_set>

namespace nadoc_vr {
// Coordinates are serialized scene nm, including desktop view rotation and
// the source frame's rigid placement. Tablet position is deliberately absent.
struct LatticePlaneContext {
    std::string plane;
    glm::vec3 originNanometers{}, u{1,0,0}, v{0,1,0}, normal{0,0,1};
    std::vector<LatticeCell> cells;
    std::unordered_set<uint64_t> occupiedCells;

    static uint64_t key(const LatticeCell& cell) {
        return (uint64_t(uint32_t(cell.row)) << 32) | uint32_t(cell.column);
    }
    bool occupied(const LatticeCell& cell) const { return occupiedCells.contains(key(cell)); }
    bool discardOccupied(ExtrudeLatticeDraft& draft) const {
        bool changed=false;
        const auto selected=draft.cells();
        for(const auto& cell:selected)if(occupied(cell))changed=draft.setSelected(cell,false)||changed;
        return changed;
    }
    glm::vec3 point(const LatticeCell& cell, bool square, float axial = 0) const {
        const auto p=latticeCellOffsetNanometers(cell,{},square);
        return originNanometers+u*p.x+v*p.y+normal*axial;
    }
    template<class Line> void preview(const std::vector<LatticeCell>& selected, bool square,
        int length, const glm::mat4& model, const glm::vec3& center, float scale,
        const glm::vec3& offset, Line line) const {
        if (!length) return;
        auto world = [&](const glm::vec3& source) {
            return glm::vec3(model*glm::vec4(sourceToNormalizedPoint(source,center,scale,offset),1));
        };
        const auto color=length<0?glm::vec3(1.F,.55F,.15F):glm::vec3(.2F,.85F,1.F);
        const float end=length*kDnaBasePairRiseNanometers;
        constexpr int segments=20;
        for (const auto& cell:selected) {
            if (occupied(cell)) continue;
            const auto start=point(cell,square);
            for(int i=0;i<segments;++i) {
                const float a=i*glm::two_pi<float>()/segments,b=(i+1)*glm::two_pi<float>()/segments;
                const auto r1=kDnaHelixRadiusNanometers*(u*std::cos(a)+v*std::sin(a));
                const auto r2=kDnaHelixRadiusNanometers*(u*std::cos(b)+v*std::sin(b));
                for(float z:{0.F,end})line(world(start+r1+normal*z),world(start+r2+normal*z),color);
                if(i%5==0)line(world(start+r1),world(start+r1+normal*end),color);
            }
        }
    }
};

class LatticeContext {
  public:
    const LatticePlaneContext* find(const std::string& plane) const {
        for(const auto& entry:planes_)if(entry.plane==plane)return &entry;
        return nullptr;
    }
    void read(std::istream& input) {
        LatticePlaneContext value;
        input>>value.plane;
        for(auto* vector:{&value.originNanometers,&value.u,&value.v,&value.normal})
            for(int i=0;i<3;++i)input>>(*vector)[i];
        int64_t count=-1;input>>count;
        if(!input || !ExtrudePlane::valid(value.plane) || find(value.plane) || count<0 || count>1000000)
            throw std::runtime_error("Invalid extrusion lattice context");
        const glm::mat3 basis(value.u,value.v,value.normal),gram=glm::transpose(basis)*basis;
        for(int i=0;i<3;++i) {
            if(!std::isfinite(value.originNanometers[i]))throw std::runtime_error("Invalid lattice origin");
            for(int j=0;j<3;++j)if(!std::isfinite(gram[i][j]) || std::abs(gram[i][j]-(i==j?1.F:0.F))>1e-5F)
                throw std::runtime_error("Invalid lattice basis");
        }
        value.cells.reserve(static_cast<size_t>(count));
        for(int64_t i=0;i<count;++i) {
            LatticeCell cell;input>>cell.row>>cell.column;
            if(!input || cell.row < -100000 || cell.row > 100000 || cell.column < -100000 || cell.column > 100000 ||
               !value.occupiedCells.insert(LatticePlaneContext::key(cell)).second)
                throw std::runtime_error("Invalid extrusion lattice cell");
            value.cells.push_back(cell);
        }
        planes_.push_back(std::move(value));
    }
  private:
    std::vector<LatticePlaneContext> planes_;
};
}
