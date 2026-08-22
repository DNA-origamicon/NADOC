#pragma once

#include <algorithm>
#include <cstdlib>
#include <cstdint>
#include <vector>

namespace nadoc_vr {

enum class SpectatorPixelStatus {
    unavailable,
    baseline,
    changing,
    stable,
    black,
    frozen_suspected,
};

enum class SpectatorCoverageStatus {
    unavailable,
    no_tags,
    design_only,
    grid_only,
    design_and_grid,
};

enum class SpectatorRenderClass : uint8_t {
    background = 0U,
    design = 1U,
    reference_grid = 2U,
    overlay = 3U,
};

struct SpectatorCoverageAssessment {
    SpectatorCoverageStatus status = SpectatorCoverageStatus::unavailable;
    size_t designPixels = 0U;
    size_t gridPixels = 0U;
    size_t overlayPixels = 0U;
    size_t unknownPixels = 0U;
    float designFraction = 0.0F;
    float gridFraction = 0.0F;
    float overlayFraction = 0.0F;
};

struct SpectatorPixelAssessment {
    SpectatorPixelStatus status = SpectatorPixelStatus::unavailable;
    uint64_t signature = 0;
    float meanLuminance = 0.0F;
    float nonBlackFraction = 0.0F;
    float changedFraction = 0.0F;
    bool poseMoved = false;
};

inline const char* spectatorPixelStatusName(SpectatorPixelStatus status) {
    switch (status) {
        case SpectatorPixelStatus::baseline: return "BASELINE";
        case SpectatorPixelStatus::changing: return "CHANGING";
        case SpectatorPixelStatus::stable: return "STABLE";
        case SpectatorPixelStatus::black: return "BLACK";
        case SpectatorPixelStatus::frozen_suspected: return "FROZEN?";
        default: return "N/A";
    }
}

inline const char* spectatorCoverageStatusName(SpectatorCoverageStatus status) {
    switch (status) {
        case SpectatorCoverageStatus::no_tags: return "NO TAGS";
        case SpectatorCoverageStatus::design_only: return "DESIGN ONLY";
        case SpectatorCoverageStatus::grid_only: return "GRID ONLY";
        case SpectatorCoverageStatus::design_and_grid: return "DESIGN+GRID";
        default: return "CLASS N/A";
    }
}

inline SpectatorCoverageAssessment assessSpectatorCoverage(
    const std::vector<uint8_t>& renderClasses) {
    SpectatorCoverageAssessment result;
    if (renderClasses.empty()) return result;
    for (const uint8_t value : renderClasses) {
        switch (static_cast<SpectatorRenderClass>(value)) {
            case SpectatorRenderClass::background: break;
            case SpectatorRenderClass::design: ++result.designPixels; break;
            case SpectatorRenderClass::reference_grid: ++result.gridPixels; break;
            case SpectatorRenderClass::overlay: ++result.overlayPixels; break;
            default: ++result.unknownPixels; break;
        }
    }
    const float count = static_cast<float>(renderClasses.size());
    result.designFraction = static_cast<float>(result.designPixels) / count;
    result.gridFraction = static_cast<float>(result.gridPixels) / count;
    result.overlayFraction = static_cast<float>(result.overlayPixels) / count;
    // Exact stencil classes cannot suffer color noise, but fewer than four samples
    // in the 64x64 diagnostic can still be a subpixel edge rather than usable content.
    constexpr size_t kMinimumMeaningfulSamples = 4U;
    const bool design = result.designPixels >= kMinimumMeaningfulSamples;
    const bool grid = result.gridPixels >= kMinimumMeaningfulSamples;
    if (design && grid) result.status = SpectatorCoverageStatus::design_and_grid;
    else if (design) result.status = SpectatorCoverageStatus::design_only;
    else if (grid) result.status = SpectatorCoverageStatus::grid_only;
    else result.status = SpectatorCoverageStatus::no_tags;
    return result;
}

inline SpectatorPixelAssessment assessSpectatorPixels(
    const std::vector<uint8_t>& rgba,
    const std::vector<uint8_t>* previousRgba,
    float poseTranslationMeters,
    float poseRotationDegrees) {
    SpectatorPixelAssessment result;
    if (rgba.empty() || rgba.size() % 4U != 0U) return result;

    constexpr uint8_t kNonBlackThreshold = 12U;
    constexpr uint8_t kChangedThreshold = 6U;
    constexpr float kBlackFraction = 0.002F;
    // The viewer's nominal empty clear color is approximately 0.023 luma.
    // Treat it as empty while requiring almost no pixels above the color threshold.
    constexpr float kBlackMeanLuminance = 0.030F;
    constexpr float kInvariantFraction = 0.002F;
    constexpr float kPoseTranslationMeters = 0.010F;
    constexpr float kPoseRotationDegrees = 1.0F;

    const size_t pixelCount = rgba.size() / 4U;
    size_t nonBlackCount = 0;
    size_t changedCount = 0;
    double luminanceSum = 0.0;
    uint64_t signature = 1469598103934665603ULL;
    const bool comparable = previousRgba && previousRgba->size() == rgba.size();
    for (size_t offset = 0; offset < rgba.size(); offset += 4U) {
        const uint8_t red = rgba[offset];
        const uint8_t green = rgba[offset + 1U];
        const uint8_t blue = rgba[offset + 2U];
        const uint8_t maximum = std::max({red, green, blue});
        if (maximum >= kNonBlackThreshold) ++nonBlackCount;
        luminanceSum += (54.0 * red + 183.0 * green + 19.0 * blue) /
                        (256.0 * 255.0);
        signature ^= red;
        signature *= 1099511628211ULL;
        signature ^= green;
        signature *= 1099511628211ULL;
        signature ^= blue;
        signature *= 1099511628211ULL;
        if (comparable) {
            const int redDelta = std::abs(
                static_cast<int>(red) - static_cast<int>((*previousRgba)[offset]));
            const int greenDelta = std::abs(
                static_cast<int>(green) -
                static_cast<int>((*previousRgba)[offset + 1U]));
            const int blueDelta = std::abs(
                static_cast<int>(blue) -
                static_cast<int>((*previousRgba)[offset + 2U]));
            if (std::max({redDelta, greenDelta, blueDelta}) >= kChangedThreshold) {
                ++changedCount;
            }
        }
    }

    result.signature = signature;
    result.meanLuminance = static_cast<float>(luminanceSum / pixelCount);
    result.nonBlackFraction = static_cast<float>(nonBlackCount) / pixelCount;
    result.changedFraction = comparable
        ? static_cast<float>(changedCount) / pixelCount
        : 0.0F;
    result.poseMoved = poseTranslationMeters >= kPoseTranslationMeters ||
                       poseRotationDegrees >= kPoseRotationDegrees;
    if (result.nonBlackFraction < kBlackFraction &&
        result.meanLuminance < kBlackMeanLuminance) {
        result.status = SpectatorPixelStatus::black;
    } else if (!comparable) {
        result.status = SpectatorPixelStatus::baseline;
    } else if (result.changedFraction < kInvariantFraction) {
        result.status = result.poseMoved
            ? SpectatorPixelStatus::frozen_suspected
            : SpectatorPixelStatus::stable;
    } else {
        result.status = SpectatorPixelStatus::changing;
    }
    return result;
}

}  // namespace nadoc_vr
