#pragma once

#include "interaction.hpp"
#include <array>
#include <cmath>

namespace nadoc_vr {

// One rectangle drives the visible border, picking, and inspector target export.
struct MenuItem {
    const char* label;
    float x;
    float y;
    float halfWidth;
    float halfHeight = 0.025F;

    [[nodiscard]] MenuPanelBounds bounds() const {
        return {{x - halfWidth, y - halfHeight},
                {x + halfWidth, y + halfHeight}};
    }

    [[nodiscard]] bool contains(const glm::vec2& point) const {
        return std::abs(point.x - x) <= halfWidth &&
               std::abs(point.y - y) <= halfHeight;
    }
};

// Preserve action indices; use the unused lower panel space for larger rows.
inline constexpr std::array<MenuItem, 10> kToolMenuItems = {{
    {"INSPECT", -0.16F, 0.180F, 0.145F, 0.040F},
    {"MOVE ROTATE", -0.16F, 0.090F, 0.145F, 0.040F},
    {"EXTRUDE", -0.16F, 0.000F, 0.145F, 0.040F},
    {"TWIST", -0.16F, -0.090F, 0.145F, 0.040F},
    {"BEND", -0.16F, -0.180F, 0.145F, 0.040F},
    {"PREVIEW", 0.16F, 0.180F, 0.145F, 0.040F},
    {"CONFIRM", 0.16F, 0.090F, 0.145F, 0.040F},
    {"CANCEL", 0.16F, 0.000F, 0.145F, 0.040F},
    {"UNDO", 0.16F, -0.090F, 0.145F, 0.040F},
    {"BACK", 0.0F, -0.410F, 0.305F, 0.035F},
}};

// Settings keep their stable action IDs; primary and secondary adjustments
// share the larger target size. Value labels fit in the space between rows.
inline constexpr std::array<MenuItem, 9> kToolConfigMenuItems = {{
    {"-", -0.16F, 0.135F, 0.145F, 0.040F},
    {"+", 0.16F, 0.135F, 0.145F, 0.040F},
    {"SECONDARY -", -0.16F, 0.025F, 0.145F, 0.040F},
    {"SECONDARY +", 0.16F, 0.025F, 0.145F, 0.040F},
    {"OPTION", -0.16F, -0.085F, 0.145F},
    {"FLAG", 0.16F, -0.085F, 0.145F},
    {"BACK TO TOOLS", 0.0F, -0.260F, 0.305F},
    {"EXTRUDE FROM", 0.0F, -0.325F, 0.305F},
    {"FREEFORM", 0.0F, -0.390F, 0.305F},
}};

}  // namespace nadoc_vr
