#pragma once
#include "interaction.hpp"

namespace nadoc_vr {
// View-only origin. Logical cells and source-plane coordinates are never edited.
inline LatticeCell centeredPaintOrigin(const std::vector<LatticeCell>& cells,
                                      LatticeCell fallback = {}) {
    if (cells.empty()) return fallback;
    int minRow=cells.front().row, maxRow=minRow;
    int minCol=cells.front().column, maxCol=minCol;
    for (const auto& c : cells) {
        minRow=std::min(minRow,c.row); maxRow=std::max(maxRow,c.row);
        minCol=std::min(minCol,c.column); maxCol=std::max(maxCol,c.column);
    }
    return {static_cast<int>(std::ceil((double(minRow)+maxRow)/2)),
            static_cast<int>(std::ceil((double(minCol)+maxCol)/2))};
}
// Content stays inside the 25 mm grip rail, with a separate header, grid,
// legend and action row. Use these bounds for drawing AND picking.
inline constexpr MenuPanelBounds kLatticePainterBounds{{-.29F,-.31F},{.29F,.31F}};
inline constexpr MenuPanelBounds kLatticePainterContent{{-.251F,-.271F},{.251F,.271F}};
inline constexpr MenuPanelBounds kLatticePainterGrid{{-.251F,-.150F},{.251F,.168F}};
inline constexpr MenuPanelBounds kCenterPaintBounds{{-.251F,-.268F},{.073F,-.221F}};
inline constexpr MenuPanelBounds kLatticePainterExit{{.095F,-.268F},{.251F,-.221F}};
inline float fittedPaintZoom(const std::vector<LatticeCell>& cells, LatticeCell origin,
                             bool square, float unitsPerNanometer) {
    if(cells.empty() || !std::isfinite(unitsPerNanometer) || unitsPerNanometer<=0)return 1.F;
    glm::vec2 extent{};
    for(const auto& cell:cells)extent=glm::max(extent,glm::abs(latticeCellOffsetNanometers(cell,origin,square)));
    // Include two neighboring rows/columns beyond the existing design.
    extent+=glm::vec2(square?kSquareLatticePitchNanometers:kHoneycombColumnPitchNanometers,
                      square?kSquareLatticePitchNanometers:kHoneycombRowPitchNanometers)*2.F+
            glm::vec2(kDnaHelixRadiusNanometers);
    const auto half=glm::min(glm::abs(kLatticePainterGrid.minimum),glm::abs(kLatticePainterGrid.maximum));
    return glm::clamp(std::min({1.F,half.x/(extent.x*unitsPerNanometer),
                               half.y/(extent.y*unitsPerNanometer)}),.1F,10.F);
}
inline bool centerPaintHit(const glm::vec3& point) {
    return point.x>=kCenterPaintBounds.minimum.x && point.x<=kCenterPaintBounds.maximum.x &&
           point.y>=kCenterPaintBounds.minimum.y && point.y<=kCenterPaintBounds.maximum.y;
}
}
