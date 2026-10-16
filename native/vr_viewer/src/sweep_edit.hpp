#pragma once
#include "sweep_draft.hpp"
#include "interaction.hpp"
#include <fstream>
#include <iomanip>

namespace nadoc_vr {
struct SweepEdit {
    uint64_t serial=0;
    int index=-1;
    uint64_t revision=0;
    std::string featureId,designId,plane,filter;
    bool square=false,ligate=true;
    glm::vec3 origin{};
    glm::mat3 rotation{1},basis{1};
    std::vector<LatticeCell> cells;
    SweepDraft draft;
    static std::optional<SweepEdit> read(std::istream& in,uint64_t afterSerial=0) {
        SweepEdit e;std::string magic;int square,ligate,n,p;
        if(!(in>>magic>>e.serial>>e.index>>e.revision>>std::quoted(e.featureId)>>std::quoted(e.designId)) ||
           magic!="NADOC_SWEEP_EDIT_1" || !e.serial || e.index<0 || e.index>99999 ||
           e.featureId.empty() || e.featureId.size()>256 || e.designId.empty() || e.designId.size()>256)return {};
        if(e.serial<=afterSerial)return {};
        if(!(in>>e.plane>>square>>e.filter>>ligate) || (e.plane!="XY"&&e.plane!="XZ"&&e.plane!="YZ") ||
           (e.filter!="both"&&e.filter!="scaffold"&&e.filter!="staples") || square<0||square>1||ligate<0||ligate>1)return {};
        e.square=square;e.ligate=ligate;
        if(!(in>>e.origin.x>>e.origin.y>>e.origin.z) || !finiteSweepPoint(e.origin))return {};
        for(int r=0;r<3;++r)for(int c=0;c<3;++c)if(!(in>>e.rotation[c][r])||!std::isfinite(e.rotation[c][r]))return {};
        for(int r=0;r<3;++r)for(int c=0;c<3;++c)if(!(in>>e.basis[c][r])||!std::isfinite(e.basis[c][r]))return {};
        const auto orthogonal=glm::transpose(e.rotation)*e.rotation;
        for(int r=0;r<3;++r)for(int c=0;c<3;++c)if(std::abs(orthogonal[c][r]-(r==c?1.F:0.F))>1e-4F)return {};
        if(glm::determinant(e.rotation)<.999F)return {};
        if(!(in>>n>>p)||n<1||n>16641||p<2||p>256)return {};
        for(int i=0;i<n;++i){LatticeCell cell;if(!(in>>cell.row>>cell.column)||std::abs(cell.row)>10000||std::abs(cell.column)>10000)return {};e.cells.push_back(cell);}
        e.draft.pointsNm.clear();e.draft.orientations.clear();
        for(int i=0;i<p;++i){glm::vec3 point,angles;int oriented;
            if(!(in>>point.x>>point.y>>point.z>>oriented>>angles.x>>angles.y>>angles.z)||!boundedSweepPoint(point)||
               oriented<0||oriented>1||!finiteSweepPoint(angles)||glm::any(glm::greaterThan(glm::abs(angles),glm::vec3(360))))return {};
            e.draft.pointsNm.push_back(point);e.draft.orientations.push_back(oriented?std::optional<glm::vec3>(angles):std::nullopt);
        }
        std::string extra;if(in>>extra)return {};
        e.draft.step=2;e.draft.selected=1;++e.draft.revision;return e;
    }
};
}
