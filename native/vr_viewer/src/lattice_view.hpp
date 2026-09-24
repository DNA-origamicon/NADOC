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
inline constexpr MenuPanelBounds kCenterPaintBounds{{-0.070F,-0.298F},{0.145F,-0.228F}};
inline bool centerPaintHit(const glm::vec3& point) {
    return point.x>=kCenterPaintBounds.minimum.x && point.x<=kCenterPaintBounds.maximum.x &&
           point.y>=kCenterPaintBounds.minimum.y && point.y<=kCenterPaintBounds.maximum.y;
}
}
