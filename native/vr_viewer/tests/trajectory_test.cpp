#include "trajectory.hpp"

#include <sstream>
#include <string>

namespace {

void appendU32(std::string& bytes, std::uint32_t value) {
    for (unsigned shift = 0; shift < 32; shift += 8) {
        bytes.push_back(static_cast<char>((value >> shift) & 0xffU));
    }
}

void appendU64(std::string& bytes, std::uint64_t value) {
    appendU32(bytes, static_cast<std::uint32_t>(value));
    appendU32(bytes, static_cast<std::uint32_t>(value >> 32U));
}

void appendFloat(std::string& bytes, float value) {
    appendU32(bytes, std::bit_cast<std::uint32_t>(value));
}

}  // namespace

int main() {
    std::istringstream stateInput(
        "NADOCVR_TRAJECTORY 1 9 1 41 100 1 1 0 0.5 2\n");
    const auto state = nadoc_vr::loadTrajectoryState(stateInput);
    if (!(state.sequence == 9 && state.active && state.frameIndex == 41 &&
          state.frameCount == 100 && state.playing && state.loop && !state.live &&
          state.speed == 0.5F && state.stride == 2)) return 1;

    std::string bytes("NVRCOORD", 8);
    appendU32(bytes, 1);
    appendU32(bytes, 36);
    appendU64(bytes, 12);
    appendU32(bytes, 4);
    appendU32(bytes, 10);
    appendU32(bytes, 2);
    appendFloat(bytes, 1.0F); appendFloat(bytes, 2.0F); appendFloat(bytes, 3.0F);
    appendFloat(bytes, -4.0F); appendFloat(bytes, 5.0F); appendFloat(bytes, 6.5F);
    std::istringstream coordinateInput(bytes);
    const auto frame = nadoc_vr::loadCoordinateFrame(coordinateInput);
    if (!(frame.sequence == 12 && frame.frameIndex == 4 && frame.frameCount == 10 &&
          frame.positions.size() == 2 && frame.positions[0][1] == 2.0F &&
          frame.positions[1][2] == 6.5F)) return 2;

    // The viewer reuses this destination on every frame so steady-state
    // playback does not allocate or fault a new multi-megabyte atom buffer.
    nadoc_vr::CoordinateFrame reusableFrame;
    std::istringstream reusableInput(bytes);
    nadoc_vr::loadCoordinateFrame(reusableInput, reusableFrame);
    const auto* reusedStorage = reusableFrame.positions.data();
    std::istringstream secondReusableInput(bytes);
    nadoc_vr::loadCoordinateFrame(secondReusableInput, reusableFrame);
    if (reusableFrame.positions.data() != reusedStorage) return 3;

    bool rejected = false;
    try {
        std::istringstream truncated(bytes.substr(0, bytes.size() - 1));
        (void)nadoc_vr::loadCoordinateFrame(truncated);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    if (!rejected) return 4;
    rejected = false;
    try {
        std::istringstream trailing(bytes + "x");
        (void)nadoc_vr::loadCoordinateFrame(trailing);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    if (!rejected) return 5;

    rejected = false;
    try {
        std::istringstream invalid("NADOCVR_TRAJECTORY 1 1 1 10 10 0 0 0 1 1\n");
        (void)nadoc_vr::loadTrajectoryState(invalid);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    if (!rejected) return 6;
    rejected = false;
    try {
        std::istringstream invalid(
            "NADOCVR_TRAJECTORY 1 1 1 0 10 0 0 0 nan 1\n");
        (void)nadoc_vr::loadTrajectoryState(invalid);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    return rejected ? 0 : 7;
}
