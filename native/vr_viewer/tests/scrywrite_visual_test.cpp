#include "scrywrite_visual.hpp"

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    constexpr int width = 64;
    constexpr int height = 36;
    std::vector<uint8_t> baseline(static_cast<size_t>(width) * height * 3U, 8U);
    for (int y = 8; y < 28; ++y) {
        for (int x = 16; x < 48; ++x) {
            const size_t offset = (static_cast<size_t>(y) * width + x) * 3U;
            baseline[offset] = 40U;
            baseline[offset + 1U] = 180U;
            baseline[offset + 2U] = 220U;
        }
    }
    const auto fingerprint = nadoc_vr::scrywrite::fingerprintActorEye(
        baseline, width, height);
    std::istringstream serialized(
        nadoc_vr::scrywrite::serializeVisualFingerprint(fingerprint));
    const auto parsed = nadoc_vr::scrywrite::loadVisualFingerprint(serialized);
    require(parsed.luminance == fingerprint.luminance,
            "visual fingerprints should round-trip without loss");
    require(nadoc_vr::scrywrite::compareActorEyeFingerprints(
                fingerprint, parsed).passed,
            "an identical actor-eye fingerprint should pass");

    auto smallNoise = parsed;
    smallNoise.luminance[0] += 5U;
    require(nadoc_vr::scrywrite::compareActorEyeFingerprints(
                fingerprint, smallNoise).passed,
            "minor raster noise should remain within tolerance");

    auto brokenComposition = parsed;
    brokenComposition.luminance.fill(245U);
    require(!nadoc_vr::scrywrite::compareActorEyeFingerprints(
                 fingerprint, brokenComposition).passed,
            "a materially different actor-eye composition should fail");

    auto occluded = baseline;
    for (int y = 8; y < 28; ++y) {
        for (int x = 16; x < 40; ++x) {
            const size_t offset = (static_cast<size_t>(y) * width + x) * 3U;
            occluded[offset] = occluded[offset + 1U] = occluded[offset + 2U] = 8U;
        }
    }
    require(!nadoc_vr::scrywrite::compareActorEyeFingerprints(
                 fingerprint,
                 nadoc_vr::scrywrite::fingerprintActorEye(occluded, width, height)).passed,
            "a large occluder over the subject should trip the visual oracle");

    const auto png = nadoc_vr::scrywrite::encodeActorEyePng(
        baseline, width, height);
    require(png.size() > 32U && png[0] == 137U && png[1] == 80U &&
                png[2] == 78U && png[3] == 71U,
            "actor-eye capture should encode a PNG stream");

    const auto metadata = nadoc_vr::scrywrite::serializeActorEyeSnapshotMetadata({
        "tools_hover", 42U, 12U, "snapshot tools_hover", "options", "tools",
        "none", "none", "valid", "valid: 22 text, 21 controls",
    });
    require(metadata.find("\"snapshot\": \"tools_hover\"") != std::string::npos &&
                metadata.find("\"hover\": \"tools\"") != std::string::npos,
            "snapshot metadata should preserve semantic replay state");

    std::cout << "ScryWrite visual regression tests passed\n";
    return 0;
}
