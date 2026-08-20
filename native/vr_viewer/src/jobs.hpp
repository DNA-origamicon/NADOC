#pragma once

#include <charconv>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace nadoc_vr {

struct JobSnapshotRow {
    int depth = 0;
    int progressPermille = 0;
    bool viewable = false;
    bool stale = false;
    bool archived = false;
    std::string engine;
    std::string status;
    std::string jobId;
    std::string parentJobId;
    std::string label;
    std::string statusText;
};

struct JobSnapshot {
    bool available = false;
    int total = 0;
    uint64_t sequence = 0;
    uint64_t updatedAtMs = 0;
    std::vector<JobSnapshotRow> rows;
};

inline int strictJobInteger(const std::string& token, int minimum, int maximum) {
    int value = 0;
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size() ||
        value < minimum || value > maximum) {
        throw std::runtime_error("invalid VR job integer");
    }
    return value;
}

inline uint64_t strictJobUnsigned(
    const std::string& token, uint64_t minimum, uint64_t maximum) {
    uint64_t value = 0;
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size() ||
        value < minimum || value > maximum) {
        throw std::runtime_error("invalid VR job unsigned integer");
    }
    return value;
}

inline std::string decodeJobField(const std::string& token, size_t maximumLength) {
    std::string result;
    result.reserve(token.size());
    auto hex = [](char value) -> int {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'A' && value <= 'F') return value - 'A' + 10;
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        return -1;
    };
    for (size_t index = 0; index < token.size(); ++index) {
        unsigned char value = static_cast<unsigned char>(token[index]);
        if (value == '%') {
            if (index + 2 >= token.size()) throw std::runtime_error("invalid VR job escape");
            const int high = hex(token[index + 1]);
            const int low = hex(token[index + 2]);
            if (high < 0 || low < 0) throw std::runtime_error("invalid VR job escape");
            value = static_cast<unsigned char>((high << 4) | low);
            index += 2;
        }
        if (value < 0x20 || value > 0x7e) {
            throw std::runtime_error("invalid VR job text");
        }
        result.push_back(static_cast<char>(value));
        if (result.size() > maximumLength) throw std::runtime_error("VR job text too large");
    }
    return result;
}

inline bool validJobWord(const std::string& value, size_t maximumLength) {
    if (value.empty() || value.size() > maximumLength) return false;
    for (const unsigned char character : value) {
        if (!(std::islower(character) || std::isdigit(character) ||
              character == '_' || character == '-')) return false;
    }
    return true;
}

inline JobSnapshot loadJobSnapshot(const std::string& path) {
    if (path.empty()) return {};
    std::ifstream input(path);
    if (!input) throw std::runtime_error("could not open VR job snapshot");

    std::string header;
    if (!std::getline(input, header)) throw std::runtime_error("empty VR job snapshot");
    std::istringstream headerStream(header);
    std::string magic;
    std::string versionToken;
    std::string countToken;
    std::string availableToken;
    std::string totalToken;
    std::string sequenceToken;
    std::string updatedAtToken;
    std::string extra;
    if (!(headerStream >> magic >> versionToken) || magic != "NADOCVR_JOBS") {
        throw std::runtime_error("invalid VR job snapshot header");
    }
    const int version = strictJobInteger(versionToken, 1, 2);
    uint64_t sequence = 0;
    uint64_t updatedAtMs = 0;
    if (version == 1) {
        if (!(headerStream >> countToken >> availableToken >> totalToken) ||
            headerStream >> extra) {
            throw std::runtime_error("invalid VR job snapshot header");
        }
    } else {
        if (!(headerStream >> sequenceToken >> countToken >> availableToken >> totalToken >>
              updatedAtToken) || headerStream >> extra) {
            throw std::runtime_error("invalid VR job snapshot header");
        }
        sequence = strictJobUnsigned(sequenceToken, 1, 9'007'199'254'740'991ULL);
        updatedAtMs = strictJobUnsigned(updatedAtToken, 1, 999'999'999'999'999ULL);
    }
    const int count = strictJobInteger(countToken, 0, 64);
    const bool available = strictJobInteger(availableToken, 0, 1) != 0;
    const int total = strictJobInteger(totalToken, 0, 1'000'000);
    if (total < count || (!available && total != 0)) {
        throw std::runtime_error("invalid VR job snapshot total");
    }

    std::vector<JobSnapshotRow> rows;
    rows.reserve(static_cast<size_t>(count));
    std::unordered_set<std::string> identities;
    for (int rowIndex = 0; rowIndex < count; ++rowIndex) {
        std::string line;
        if (!std::getline(input, line) || line.size() > 2048) {
            throw std::runtime_error("truncated VR job snapshot");
        }
        std::istringstream rowStream(line);
        std::vector<std::string> fields;
        std::string field;
        while (rowStream >> field) fields.push_back(field);
        if (fields.size() != 12 || fields[0] != "J") {
            throw std::runtime_error("invalid VR job row");
        }
        JobSnapshotRow row;
        row.depth = strictJobInteger(fields[1], 0, 8);
        row.progressPermille = strictJobInteger(fields[2], 0, 1000);
        row.viewable = strictJobInteger(fields[3], 0, 1) != 0;
        row.stale = strictJobInteger(fields[4], 0, 1) != 0;
        row.archived = strictJobInteger(fields[5], 0, 1) != 0;
        row.engine = decodeJobField(fields[6], 24);
        row.status = decodeJobField(fields[7], 32);
        row.jobId = decodeJobField(fields[8], 128);
        const std::string parent = decodeJobField(fields[9], 128);
        row.parentJobId = parent == "-" ? "" : parent;
        row.label = decodeJobField(fields[10], 48);
        row.statusText = decodeJobField(fields[11], 96);
        if (!validJobWord(row.engine, 24) || !validJobWord(row.status, 32) ||
            row.jobId.empty() || row.label.empty() || row.statusText.empty() ||
            !identities.insert(row.engine + "\n" + row.jobId).second) {
            throw std::runtime_error("invalid VR job identity");
        }
        rows.push_back(std::move(row));
    }
    std::string trailing;
    while (std::getline(input, trailing)) {
        if (trailing.find_first_not_of(" \t\r") != std::string::npos) {
            throw std::runtime_error("unexpected VR job snapshot data");
        }
    }
    return {available, total, sequence, updatedAtMs, std::move(rows)};
}

}  // namespace nadoc_vr
