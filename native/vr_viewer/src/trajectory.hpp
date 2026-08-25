#pragma once

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <istream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_vr {

struct TrajectoryState {
    std::uint64_t sequence = 0;
    bool active = false;
    std::uint32_t frameIndex = 0;
    std::uint32_t frameCount = 0;
    bool playing = false;
    bool loop = false;
    bool live = false;
    float speed = 1.0F;
    std::uint32_t stride = 1;
};

struct CoordinateFrame {
    std::uint64_t sequence = 0;
    std::uint32_t frameIndex = 0;
    std::uint32_t frameCount = 0;
    std::vector<std::array<float, 3>> positions;
};

inline TrajectoryState loadTrajectoryState(std::istream& input) {
    std::string magic;
    unsigned version = 0;
    unsigned active = 0;
    unsigned playing = 0;
    unsigned loop = 0;
    unsigned live = 0;
    TrajectoryState state;
    if (!(input >> magic >> version >> state.sequence >> active >> state.frameIndex
          >> state.frameCount >> playing >> loop >> live >> state.speed >> state.stride) ||
        magic != "NADOCVR_TRAJECTORY" || version != 1 || active > 1 ||
        playing > 1 || loop > 1 || live > 1 || !std::isfinite(state.speed) ||
        state.speed < 0.1F || state.speed > 8.0F || state.stride == 0 ||
        state.stride > 100'000 ||
        (state.frameCount == 0 && state.frameIndex != 0) ||
        (state.frameCount > 0 && state.frameIndex >= state.frameCount)) {
        throw std::runtime_error("invalid VR trajectory state");
    }
    state.active = active != 0;
    state.playing = playing != 0;
    state.loop = loop != 0;
    state.live = live != 0;
    return state;
}

inline std::uint32_t coordinateU32(
    const std::uint8_t* data, size_t size, size_t offset) {
    if (offset + 4 > size) throw std::runtime_error("truncated coordinate frame");
    return static_cast<std::uint32_t>(data[offset]) |
        (static_cast<std::uint32_t>(data[offset + 1]) << 8U) |
        (static_cast<std::uint32_t>(data[offset + 2]) << 16U) |
        (static_cast<std::uint32_t>(data[offset + 3]) << 24U);
}

inline std::uint64_t coordinateU64(
    const std::uint8_t* data, size_t size, size_t offset) {
    const auto low = static_cast<std::uint64_t>(coordinateU32(data, size, offset));
    const auto high = static_cast<std::uint64_t>(coordinateU32(data, size, offset + 4));
    return low | (high << 32U);
}

inline void loadCoordinateFrame(std::istream& input, CoordinateFrame& frame) {
    constexpr size_t headerSize = 36;
    constexpr size_t maximumAtoms = 1'000'000;
    static_assert(sizeof(std::array<float, 3>) == 12);
    std::array<std::uint8_t, headerSize> header{};
    if (!input.read(
            reinterpret_cast<char*>(header.data()),
            static_cast<std::streamsize>(header.size())) ||
        std::memcmp(header.data(), "NVRCOORD", 8) != 0 ||
        coordinateU32(header.data(), header.size(), 8) != 1 ||
        coordinateU32(header.data(), header.size(), 12) != headerSize) {
        throw std::runtime_error("invalid coordinate frame header");
    }
    frame.sequence = coordinateU64(header.data(), header.size(), 16);
    frame.frameIndex = coordinateU32(header.data(), header.size(), 24);
    frame.frameCount = coordinateU32(header.data(), header.size(), 28);
    const auto count = static_cast<size_t>(
        coordinateU32(header.data(), header.size(), 32));
    if (count > maximumAtoms ||
        (frame.frameCount == 0 && frame.frameIndex != 0) ||
        (frame.frameCount > 0 && frame.frameIndex >= frame.frameCount)) {
        throw std::runtime_error("invalid coordinate frame payload");
    }
    frame.positions.resize(count);
    const size_t payloadBytes = count * sizeof(std::array<float, 3>);
    if (payloadBytes > 0 && !input.read(
            reinterpret_cast<char*>(frame.positions.data()),
            static_cast<std::streamsize>(payloadBytes))) {
        throw std::runtime_error("truncated coordinate frame payload");
    }
    if (input.peek() != std::char_traits<char>::eof()) {
        throw std::runtime_error("invalid coordinate frame payload length");
    }
    for (auto& position : frame.positions) {
        for (float& value : position) {
            if constexpr (std::endian::native != std::endian::little) {
                auto bits = std::bit_cast<std::uint32_t>(value);
                bits = ((bits & 0x000000ffU) << 24U) |
                    ((bits & 0x0000ff00U) << 8U) |
                    ((bits & 0x00ff0000U) >> 8U) |
                    ((bits & 0xff000000U) >> 24U);
                value = std::bit_cast<float>(bits);
            }
            if (!std::isfinite(value) || std::abs(value) > 1.0e9F) {
                throw std::runtime_error("invalid coordinate value");
            }
        }
    }
}

inline CoordinateFrame loadCoordinateFrame(std::istream& input) {
    CoordinateFrame frame;
    loadCoordinateFrame(input, frame);
    return frame;
}

}  // namespace nadoc_vr
