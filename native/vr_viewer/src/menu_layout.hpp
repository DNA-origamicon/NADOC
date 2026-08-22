#pragma once

#include "interaction.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <sstream>
#include <string>
#include <vector>

namespace nadoc_vr {

inline constexpr float kMenuLayoutEpsilon = 1.0e-5F;
inline constexpr float kMinimumMenuTextScale = 0.0020F;
inline constexpr glm::vec2 kMinimumMenuControlSize{0.15F, 0.045F};

struct MenuTextLayout {
    std::string owner;
    std::string text;
    MenuPanelBounds bounds{};
    MenuPanelBounds containment{};
    float scale = 0.0F;
    float minimumScale = kMinimumMenuTextScale;
};

struct MenuControlLayout {
    std::string owner;
    MenuPanelBounds visualBounds{};
    MenuPanelBounds hitBounds{};
    glm::vec2 minimumSize{kMinimumMenuControlSize};
};

struct MenuLayoutIssue {
    std::string code;
    std::string owner;
    std::string detail;
};

struct MenuTextPlacement {
    float left = 0.0F;
    float top = 0.0F;
    float scale = 0.0F;
};

struct ActorEyePanelFraming {
    glm::vec2 minimumNdc{1.0F};
    glm::vec2 maximumNdc{-1.0F};
    bool inFront = false;
    bool fullyInFrame = false;

    [[nodiscard]] std::string status() const {
        if (!inFront) return "behind";
        return fullyInFrame ? "valid" : "clipped";
    }
};

inline ActorEyePanelFraming assessActorEyePanelFraming(
    const std::array<glm::vec3, 4>& worldCorners,
    const glm::vec3& headPosition,
    const glm::quat& headOrientation,
    float verticalFovDegrees = 72.0F,
    float aspectRatio = 16.0F / 9.0F,
    float edgeMarginNdc = 0.04F,
    float nearMeters = 0.02F) {
    ActorEyePanelFraming result;
    if (!std::isfinite(verticalFovDegrees) || verticalFovDegrees <= 0.0F ||
        verticalFovDegrees >= 179.0F || !std::isfinite(aspectRatio) ||
        aspectRatio <= 0.0F || !std::isfinite(edgeMarginNdc) ||
        edgeMarginNdc < 0.0F || edgeMarginNdc >= 1.0F ||
        !std::isfinite(nearMeters) || nearMeters <= 0.0F ||
        glm::length(headOrientation) < 1.0e-6F) {
        return result;
    }
    const float tangentY = std::tan(glm::radians(verticalFovDegrees) * 0.5F);
    const float tangentX = tangentY * aspectRatio;
    result.inFront = true;
    for (const glm::vec3& corner : worldCorners) {
        const glm::vec3 local = glm::inverse(glm::normalize(headOrientation)) *
                                (corner - headPosition);
        const float forward = -local.z;
        if (!std::isfinite(local.x) || !std::isfinite(local.y) ||
            !std::isfinite(local.z) || forward <= nearMeters) {
            result.inFront = false;
            result.fullyInFrame = false;
            return result;
        }
        const glm::vec2 ndc{
            local.x / (forward * tangentX),
            local.y / (forward * tangentY),
        };
        result.minimumNdc = glm::min(result.minimumNdc, ndc);
        result.maximumNdc = glm::max(result.maximumNdc, ndc);
    }
    const float limit = 1.0F - edgeMarginNdc;
    result.fullyInFrame =
        result.minimumNdc.x >= -limit && result.maximumNdc.x <= limit &&
        result.minimumNdc.y >= -limit && result.maximumNdc.y <= limit;
    return result;
}

inline bool validMenuLayoutBounds(const MenuPanelBounds& bounds) {
    return std::isfinite(bounds.minimum.x) && std::isfinite(bounds.minimum.y) &&
           std::isfinite(bounds.maximum.x) && std::isfinite(bounds.maximum.y) &&
           bounds.minimum.x <= bounds.maximum.x &&
           bounds.minimum.y <= bounds.maximum.y;
}

inline bool menuLayoutContains(
    const MenuPanelBounds& outer, const MenuPanelBounds& inner,
    float epsilon = kMenuLayoutEpsilon) {
    return validMenuLayoutBounds(outer) && validMenuLayoutBounds(inner) &&
           inner.minimum.x >= outer.minimum.x - epsilon &&
           inner.minimum.y >= outer.minimum.y - epsilon &&
           inner.maximum.x <= outer.maximum.x + epsilon &&
           inner.maximum.y <= outer.maximum.y + epsilon;
}

inline bool menuLayoutIntersects(
    const MenuPanelBounds& first, const MenuPanelBounds& second,
    float epsilon = kMenuLayoutEpsilon) {
    if (!validMenuLayoutBounds(first) || !validMenuLayoutBounds(second)) return false;
    return first.maximum.x > second.minimum.x + epsilon &&
           second.maximum.x > first.minimum.x + epsilon &&
           first.maximum.y > second.minimum.y + epsilon &&
           second.maximum.y > first.minimum.y + epsilon;
}

inline MenuPanelBounds strokeTextLayoutBounds(
    const std::string& text, float left, float top, float scale) {
    return {
        {left, top - 6.0F * scale},
        {left + strokeTextWidth(text.size(), scale), top},
    };
}

inline MenuTextPlacement fitMenuStrokeText(
    const std::string& text, float requestedLeft, float top,
    float maximumScale, const MenuPanelBounds& containment,
    float horizontalMargin = 0.012F) {
    if (!validMenuLayoutBounds(containment) ||
        !std::isfinite(requestedLeft) || !std::isfinite(top) ||
        !std::isfinite(maximumScale) || !std::isfinite(horizontalMargin) ||
        maximumScale <= 0.0F || horizontalMargin < 0.0F) {
        return {};
    }
    const float left = std::clamp(
        requestedLeft, containment.minimum.x + horizontalMargin,
        containment.maximum.x - horizontalMargin);
    const float available = std::max(
        0.0F, containment.maximum.x - horizontalMargin - left);
    return {
        left, top,
        fittedStrokeTextScale(text.size(), maximumScale, available),
    };
}

class MenuLayoutAudit {
  public:
    void reset(const MenuPanelBounds& panelBounds) {
        panelBounds_ = panelBounds;
        texts_.clear();
        controls_.clear();
        issues_.clear();
        if (!validMenuLayoutBounds(panelBounds_)) {
            addIssue("invalid_geometry", "panel", "panel bounds are invalid");
        }
    }

    MenuTextPlacement fitAndAddText(
        const std::string& owner, const std::string& text,
        float requestedLeft, float top, float maximumScale,
        const MenuPanelBounds& containment,
        float minimumScale = kMinimumMenuTextScale,
        float horizontalMargin = 0.012F) {
        const MenuTextPlacement placement = fitMenuStrokeText(
            text, requestedLeft, top, maximumScale, containment, horizontalMargin);
        addText(owner, text, placement.left, placement.top, placement.scale,
                containment, minimumScale);
        return placement;
    }

    void addText(
        const std::string& owner, const std::string& text,
        float left, float top, float scale,
        const MenuPanelBounds& containment,
        float minimumScale = kMinimumMenuTextScale) {
        const MenuTextLayout layout{
            owner, text, strokeTextLayoutBounds(text, left, top, scale),
            containment, scale, minimumScale,
        };
        texts_.push_back(layout);
        if (text.empty()) return;
        if (!std::isfinite(scale) || scale <= 0.0F ||
            !validMenuLayoutBounds(layout.bounds) ||
            !validMenuLayoutBounds(containment)) {
            addIssue("invalid_geometry", owner, "text geometry is invalid");
            return;
        }
        if (!menuLayoutContains(containment, layout.bounds)) {
            addIssue("text_overflow", owner, "text escapes its owning bounds");
        }
        if (!std::isfinite(minimumScale) || minimumScale <= 0.0F) {
            addIssue("invalid_geometry", owner, "minimum text scale is invalid");
        } else if (scale + kMenuLayoutEpsilon < minimumScale) {
            addIssue("text_undersized", owner, "fitted text is below the scale floor");
        }
    }

    void addControl(
        const std::string& owner,
        const MenuPanelBounds& visualBounds,
        const MenuPanelBounds& hitBounds,
        const glm::vec2& minimumSize = kMinimumMenuControlSize) {
        const MenuControlLayout layout{
            owner, visualBounds, hitBounds, minimumSize,
        };
        if (!validMenuLayoutBounds(visualBounds) ||
            !validMenuLayoutBounds(hitBounds) ||
            !std::isfinite(minimumSize.x) || !std::isfinite(minimumSize.y) ||
            minimumSize.x <= 0.0F || minimumSize.y <= 0.0F) {
            addIssue("invalid_geometry", owner, "control geometry is invalid");
            controls_.push_back(layout);
            return;
        }
        if (!menuLayoutContains(panelBounds_, visualBounds)) {
            addIssue("control_overflow", owner, "control escapes the panel");
        }
        if (!menuLayoutContains(hitBounds, visualBounds)) {
            addIssue("hitbox_mismatch", owner, "hit bounds do not contain the drawn control");
        }
        const glm::vec2 hitSize = hitBounds.maximum - hitBounds.minimum;
        if (hitSize.x + kMenuLayoutEpsilon < minimumSize.x ||
            hitSize.y + kMenuLayoutEpsilon < minimumSize.y) {
            addIssue("target_undersized", owner, "hit target is below its size floor");
        }
        for (const auto& other : controls_) {
            if (menuLayoutIntersects(hitBounds, other.hitBounds)) {
                addIssue("hitbox_overlap", owner,
                         "hit bounds overlap " + other.owner);
            }
        }
        controls_.push_back(layout);
    }

    [[nodiscard]] bool valid() const { return issues_.empty(); }
    [[nodiscard]] const MenuPanelBounds& panelBounds() const { return panelBounds_; }
    [[nodiscard]] const std::vector<MenuTextLayout>& texts() const { return texts_; }
    [[nodiscard]] const std::vector<MenuControlLayout>& controls() const {
        return controls_;
    }
    [[nodiscard]] const std::vector<MenuLayoutIssue>& issues() const { return issues_; }

    [[nodiscard]] std::string status() const {
        if (issues_.empty()) return "valid";
        return issues_.front().code;
    }

    [[nodiscard]] std::string summary() const {
        if (issues_.empty()) {
            return "valid: " + std::to_string(texts_.size()) + " text, " +
                   std::to_string(controls_.size()) + " controls";
        }
        std::ostringstream result;
        result << issues_.size() << " issue(s): ";
        for (size_t index = 0; index < issues_.size(); ++index) {
            if (index > 0U) result << "; ";
            result << issues_[index].code << "[" << issues_[index].owner
                   << "] " << issues_[index].detail;
        }
        return result.str();
    }

  private:
    void addIssue(
        const std::string& code, const std::string& owner,
        const std::string& detail) {
        issues_.push_back({code, owner, detail});
    }

    MenuPanelBounds panelBounds_{};
    std::vector<MenuTextLayout> texts_;
    std::vector<MenuControlLayout> controls_;
    std::vector<MenuLayoutIssue> issues_;
};

}  // namespace nadoc_vr
