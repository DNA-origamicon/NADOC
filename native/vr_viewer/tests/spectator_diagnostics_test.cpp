#include "spectator_diagnostics.hpp"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

std::vector<uint8_t> solid(uint8_t value) {
    std::vector<uint8_t> pixels(16U * 16U * 4U, value);
    for (size_t offset = 3; offset < pixels.size(); offset += 4U) pixels[offset] = 255U;
    return pixels;
}

}  // namespace

int main() {
    using nadoc_vr::SpectatorPixelStatus;
    using nadoc_vr::SpectatorCoverageStatus;
    const auto black = solid(0U);
    require(nadoc_vr::assessSpectatorPixels(black, nullptr, 0.0F, 0.0F).status ==
                SpectatorPixelStatus::black,
            "an empty black eye must fail even without pose motion");
    auto emptyClear = black;
    for (size_t offset = 0; offset < emptyClear.size(); offset += 4U) {
        emptyClear[offset] = 4U;
        emptyClear[offset + 1U] = 6U;
        emptyClear[offset + 2U] = 11U;
    }
    require(nadoc_vr::assessSpectatorPixels(
                emptyClear, nullptr, 0.0F, 0.0F).status == SpectatorPixelStatus::black,
            "the viewer's empty dark clear color should be classified as black");

    const auto lit = solid(80U);
    const auto baseline = nadoc_vr::assessSpectatorPixels(lit, nullptr, 0.0F, 0.0F);
    require(baseline.status == SpectatorPixelStatus::baseline &&
                baseline.nonBlackFraction == 1.0F,
            "the first lit frame should establish a baseline");
    require(nadoc_vr::assessSpectatorPixels(lit, &lit, 0.0F, 0.0F).status ==
                SpectatorPixelStatus::stable,
            "identical pixels are legitimate while the pose is stationary");
    require(nadoc_vr::assessSpectatorPixels(lit, &lit, 0.02F, 0.0F).status ==
                SpectatorPixelStatus::frozen_suspected,
            "identical pixels under meaningful translation should be suspicious");
    require(nadoc_vr::assessSpectatorPixels(lit, &lit, 0.0F, 2.0F).status ==
                SpectatorPixelStatus::frozen_suspected,
            "identical pixels under meaningful rotation should be suspicious");

    auto changed = lit;
    for (size_t offset = 0; offset < changed.size() / 2U; offset += 4U) {
        changed[offset] = 200U;
    }
    const auto healthy = nadoc_vr::assessSpectatorPixels(changed, &lit, 0.02F, 2.0F);
    require(healthy.status == SpectatorPixelStatus::changing &&
                healthy.changedFraction > 0.1F,
            "pixel motion accompanying pose motion should remain healthy");
    require(std::string(nadoc_vr::spectatorPixelStatusName(
                SpectatorPixelStatus::frozen_suspected)) == "FROZEN?",
            "the label must retain uncertainty rather than claim a proven freeze");

    std::vector<uint8_t> classes(64U, static_cast<uint8_t>(
        nadoc_vr::SpectatorRenderClass::background));
    require(nadoc_vr::assessSpectatorCoverage({}).status ==
                SpectatorCoverageStatus::unavailable,
            "missing stencil readback must remain unavailable");
    require(nadoc_vr::assessSpectatorCoverage(classes).status ==
                SpectatorCoverageStatus::no_tags,
            "background pixels must not masquerade as design or grid");
    classes[0] = static_cast<uint8_t>(nadoc_vr::SpectatorRenderClass::design);
    require(nadoc_vr::assessSpectatorCoverage(classes).status ==
                SpectatorCoverageStatus::no_tags,
            "one edge sample must not claim meaningful design coverage");
    for (size_t index = 0; index < 4U; ++index) {
        classes[index] = static_cast<uint8_t>(nadoc_vr::SpectatorRenderClass::design);
    }
    require(nadoc_vr::assessSpectatorCoverage(classes).status ==
                SpectatorCoverageStatus::design_only,
            "four exact design samples should establish bounded design presence");
    for (size_t index = 4U; index < 8U; ++index) {
        classes[index] = static_cast<uint8_t>(
            nadoc_vr::SpectatorRenderClass::reference_grid);
    }
    const auto mixedCoverage = nadoc_vr::assessSpectatorCoverage(classes);
    require(mixedCoverage.status == SpectatorCoverageStatus::design_and_grid &&
                mixedCoverage.designPixels == 4U && mixedCoverage.gridPixels == 4U,
            "design and grid tags must remain independently countable");
    for (size_t index = 0; index < 4U; ++index) {
        classes[index] = static_cast<uint8_t>(
            nadoc_vr::SpectatorRenderClass::reference_grid);
    }
    require(nadoc_vr::assessSpectatorCoverage(classes).status ==
                SpectatorCoverageStatus::grid_only,
            "a visible grid without design must be called grid-only");
    classes[0] = 99U;
    require(nadoc_vr::assessSpectatorCoverage(classes).unknownPixels == 1U,
            "unknown stencil values must be surfaced rather than treated as content");

    std::cout << "NADOC VR spectator diagnostics tests passed\n";
    return 0;
}
