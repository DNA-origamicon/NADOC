#pragma once

#include <zlib.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_vr::scrywrite {

inline constexpr int kVisualGridWidth = 32;
inline constexpr int kVisualGridHeight = 18;

struct VisualFingerprint {
    int sourceWidth = 0;
    int sourceHeight = 0;
    std::array<uint8_t, kVisualGridWidth * kVisualGridHeight> luminance{};
};

struct VisualComparison {
    float meanAbsoluteDifference = 0.0F;
    float changedCellFraction = 0.0F;
    bool passed = false;
};

struct ActorEyeSnapshotMetadata {
    std::string snapshot;
    uint64_t frame = 0;
    size_t line = 0;
    std::string command;
    std::string menu;
    std::string hover;
    std::string tool;
    std::string status;
    std::string layout;
    std::string layoutDetail;
};

inline std::string visualJson(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        if (character == '"') output << "\\\"";
        else if (character == '\\') output << "\\\\";
        else if (character == '\n') output << "\\n";
        else if (character == '\r') output << "\\r";
        else if (character == '\t') output << "\\t";
        else if (character < 0x20U) {
            output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                   << static_cast<unsigned int>(character)
                   << std::dec << std::setfill(' ');
        } else {
            output << static_cast<char>(character);
        }
    }
    return output.str();
}

inline std::string serializeActorEyeSnapshotMetadata(
    const ActorEyeSnapshotMetadata& value) {
    std::ostringstream output;
    output << "{\n"
           << "  \"snapshot\": \"" << visualJson(value.snapshot) << "\",\n"
           << "  \"frame\": " << value.frame << ",\n"
           << "  \"line\": " << value.line << ",\n"
           << "  \"command\": \"" << visualJson(value.command) << "\",\n"
           << "  \"menu\": \"" << visualJson(value.menu) << "\",\n"
           << "  \"hover\": \"" << visualJson(value.hover) << "\",\n"
           << "  \"tool\": \"" << visualJson(value.tool) << "\",\n"
           << "  \"status\": \"" << visualJson(value.status) << "\",\n"
           << "  \"layout\": \"" << visualJson(value.layout) << "\",\n"
           << "  \"layout_detail\": \"" << visualJson(value.layoutDetail)
           << "\"\n}\n";
    return output.str();
}

inline VisualFingerprint fingerprintActorEye(
    const std::vector<uint8_t>& bottomUpRgb, int width, int height) {
    if (width <= 0 || height <= 0 ||
        bottomUpRgb.size() != static_cast<size_t>(width) * height * 3U) {
        throw std::invalid_argument("actor-eye RGB dimensions do not match the buffer");
    }
    VisualFingerprint result;
    result.sourceWidth = width;
    result.sourceHeight = height;
    for (int gridY = 0; gridY < kVisualGridHeight; ++gridY) {
        const int top = gridY * height / kVisualGridHeight;
        const int bottom = (gridY + 1) * height / kVisualGridHeight;
        for (int gridX = 0; gridX < kVisualGridWidth; ++gridX) {
            const int left = gridX * width / kVisualGridWidth;
            const int right = (gridX + 1) * width / kVisualGridWidth;
            uint64_t sum = 0;
            uint64_t count = 0;
            for (int y = top; y < bottom; ++y) {
                const int sourceY = height - 1 - y;
                for (int x = left; x < right; ++x) {
                    const size_t offset =
                        (static_cast<size_t>(sourceY) * width + x) * 3U;
                    const uint32_t luma =
                        54U * bottomUpRgb[offset] +
                        183U * bottomUpRgb[offset + 1U] +
                        19U * bottomUpRgb[offset + 2U];
                    sum += (luma + 128U) / 256U;
                    ++count;
                }
            }
            result.luminance[static_cast<size_t>(gridY) * kVisualGridWidth + gridX] =
                static_cast<uint8_t>(count > 0 ? sum / count : 0U);
        }
    }
    return result;
}

inline VisualComparison compareActorEyeFingerprints(
    const VisualFingerprint& expected, const VisualFingerprint& actual,
    float maximumMeanAbsoluteDifference = 0.035F,
    float maximumChangedCellFraction = 0.12F,
    uint8_t changedCellThreshold = 20U) {
    if (expected.sourceWidth != actual.sourceWidth ||
        expected.sourceHeight != actual.sourceHeight) {
        return {1.0F, 1.0F, false};
    }
    uint64_t absoluteDifference = 0;
    size_t changed = 0;
    for (size_t index = 0; index < expected.luminance.size(); ++index) {
        const int difference = std::abs(
            static_cast<int>(expected.luminance[index]) -
            static_cast<int>(actual.luminance[index]));
        absoluteDifference += static_cast<uint64_t>(difference);
        if (difference > changedCellThreshold) ++changed;
    }
    const float mean = static_cast<float>(absoluteDifference) /
        static_cast<float>(expected.luminance.size() * 255U);
    const float changedFraction = static_cast<float>(changed) /
        static_cast<float>(expected.luminance.size());
    return {
        mean, changedFraction,
        mean <= maximumMeanAbsoluteDifference &&
            changedFraction <= maximumChangedCellFraction,
    };
}

inline std::string serializeVisualFingerprint(const VisualFingerprint& value) {
    std::ostringstream output;
    output << "SCRYWRITE_VISUAL 1\n"
           << "source " << value.sourceWidth << ' ' << value.sourceHeight << "\n"
           << "grid " << kVisualGridWidth << ' ' << kVisualGridHeight << "\n"
           << "luma ";
    for (uint8_t sample : value.luminance) {
        output << std::hex << std::setw(2) << std::setfill('0')
               << static_cast<unsigned int>(sample);
    }
    output << "\n";
    return output.str();
}

inline VisualFingerprint loadVisualFingerprint(std::istream& input) {
    std::string header;
    int version = 0;
    if (!(input >> header >> version) || header != "SCRYWRITE_VISUAL" || version != 1) {
        throw std::runtime_error("expected SCRYWRITE_VISUAL 1 header");
    }
    VisualFingerprint result;
    std::string field;
    int gridWidth = 0;
    int gridHeight = 0;
    std::string samples;
    if (!(input >> field >> result.sourceWidth >> result.sourceHeight) ||
        field != "source" || result.sourceWidth <= 0 || result.sourceHeight <= 0) {
        throw std::runtime_error("invalid visual source dimensions");
    }
    if (!(input >> field >> gridWidth >> gridHeight) || field != "grid" ||
        gridWidth != kVisualGridWidth || gridHeight != kVisualGridHeight) {
        throw std::runtime_error("unsupported visual fingerprint grid");
    }
    if (!(input >> field >> samples) || field != "luma" ||
        samples.size() != result.luminance.size() * 2U) {
        throw std::runtime_error("invalid visual luminance samples");
    }
    for (size_t index = 0; index < result.luminance.size(); ++index) {
        const std::string byte = samples.substr(index * 2U, 2U);
        size_t consumed = 0;
        unsigned long parsed = 0;
        try {
            parsed = std::stoul(byte, &consumed, 16);
        } catch (const std::exception&) {
            throw std::runtime_error("invalid visual luminance samples");
        }
        if (consumed != 2U || parsed > 255U) {
            throw std::runtime_error("invalid visual luminance samples");
        }
        result.luminance[index] = static_cast<uint8_t>(parsed);
    }
    return result;
}

inline void appendPngUint32(std::vector<uint8_t>& output, uint32_t value) {
    output.push_back(static_cast<uint8_t>((value >> 24U) & 0xffU));
    output.push_back(static_cast<uint8_t>((value >> 16U) & 0xffU));
    output.push_back(static_cast<uint8_t>((value >> 8U) & 0xffU));
    output.push_back(static_cast<uint8_t>(value & 0xffU));
}

inline void appendPngChunk(
    std::vector<uint8_t>& output, const char type[4],
    const std::vector<uint8_t>& payload) {
    appendPngUint32(output, static_cast<uint32_t>(payload.size()));
    const size_t crcStart = output.size();
    output.insert(output.end(), type, type + 4);
    output.insert(output.end(), payload.begin(), payload.end());
    const uLong checksum = crc32(
        0L, output.data() + crcStart,
        static_cast<uInt>(4U + payload.size()));
    appendPngUint32(output, static_cast<uint32_t>(checksum));
}

inline std::vector<uint8_t> encodeActorEyePng(
    const std::vector<uint8_t>& bottomUpRgb, int width, int height) {
    if (width <= 0 || height <= 0 ||
        bottomUpRgb.size() != static_cast<size_t>(width) * height * 3U) {
        throw std::invalid_argument("actor-eye RGB dimensions do not match the buffer");
    }
    const size_t rowBytes = static_cast<size_t>(width) * 3U;
    std::vector<uint8_t> scanlines((rowBytes + 1U) * static_cast<size_t>(height));
    for (int y = 0; y < height; ++y) {
        const size_t destination = static_cast<size_t>(y) * (rowBytes + 1U);
        scanlines[destination] = 0U;
        const size_t source = static_cast<size_t>(height - 1 - y) * rowBytes;
        std::copy_n(bottomUpRgb.data() + source, rowBytes,
                    scanlines.data() + destination + 1U);
    }
    uLongf compressedSize = compressBound(static_cast<uLong>(scanlines.size()));
    std::vector<uint8_t> compressed(compressedSize);
    const int compression = compress2(
        compressed.data(), &compressedSize, scanlines.data(),
        static_cast<uLong>(scanlines.size()), Z_BEST_COMPRESSION);
    if (compression != Z_OK) throw std::runtime_error("PNG compression failed");
    compressed.resize(compressedSize);

    std::vector<uint8_t> output{137U, 80U, 78U, 71U, 13U, 10U, 26U, 10U};
    std::vector<uint8_t> header;
    appendPngUint32(header, static_cast<uint32_t>(width));
    appendPngUint32(header, static_cast<uint32_t>(height));
    header.insert(header.end(), {8U, 2U, 0U, 0U, 0U});
    appendPngChunk(output, "IHDR", header);
    appendPngChunk(output, "IDAT", compressed);
    appendPngChunk(output, "IEND", {});
    return output;
}

struct ActorEyeCaptureResult {
    std::filesystem::path pngPath;
    std::filesystem::path fingerprintPath;
    std::filesystem::path metadataPath;
    std::optional<VisualComparison> comparison;
};

inline ActorEyeCaptureResult writeActorEyeCapture(
    const std::filesystem::path& outputDirectory,
    const std::string& name,
    const std::vector<uint8_t>& bottomUpRgb,
    int width, int height,
    const std::optional<std::filesystem::path>& expectationDirectory = std::nullopt,
    const std::optional<ActorEyeSnapshotMetadata>& metadata = std::nullopt) {
    std::filesystem::create_directories(outputDirectory);
    const auto pngPath = outputDirectory / (name + ".png");
    const auto fingerprintPath = outputDirectory / (name + ".scry-visual");
    const auto metadataPath = outputDirectory / (name + ".json");
    const auto png = encodeActorEyePng(bottomUpRgb, width, height);
    std::ofstream image(pngPath, std::ios::binary | std::ios::trunc);
    image.write(reinterpret_cast<const char*>(png.data()),
                static_cast<std::streamsize>(png.size()));
    if (!image) throw std::runtime_error("could not write " + pngPath.string());
    const VisualFingerprint fingerprint =
        fingerprintActorEye(bottomUpRgb, width, height);
    std::ofstream fingerprintOutput(fingerprintPath, std::ios::trunc);
    fingerprintOutput << serializeVisualFingerprint(fingerprint);
    if (!fingerprintOutput) {
        throw std::runtime_error("could not write " + fingerprintPath.string());
    }
    if (metadata) {
        std::ofstream metadataOutput(metadataPath, std::ios::trunc);
        metadataOutput << serializeActorEyeSnapshotMetadata(*metadata);
        if (!metadataOutput) {
            throw std::runtime_error("could not write " + metadataPath.string());
        }
    }

    ActorEyeCaptureResult result{
        pngPath, fingerprintPath, metadata ? metadataPath : std::filesystem::path{},
        std::nullopt,
    };
    if (expectationDirectory) {
        const auto expectedPath = *expectationDirectory / (name + ".scry-visual");
        std::ifstream expectedInput(expectedPath);
        if (!expectedInput) {
            throw std::runtime_error("could not open visual expectation " +
                                     expectedPath.string());
        }
        result.comparison = compareActorEyeFingerprints(
            loadVisualFingerprint(expectedInput), fingerprint);
    }
    return result;
}

}  // namespace nadoc_vr::scrywrite
