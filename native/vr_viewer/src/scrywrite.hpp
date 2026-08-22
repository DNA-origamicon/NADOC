#pragma once

#include "interaction.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <istream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_vr::scrywrite {

inline constexpr size_t kMaximumScriptLineBytes = 4096;
inline constexpr size_t kMaximumCommands = 10'000;
inline constexpr uint64_t kMaximumStepFrames = 1'000'000;

struct TraceEvent {
    size_t sequence = 0;
    size_t line = 0;
    uint64_t frame = 0;
    std::string command;
    std::string outcome = "passed";
    std::string error;
    std::string selectionKind = "none";
    std::string selectionIdentity;
    std::string tool = "inspect";
    std::string status = "VIEW ONLY";
    bool preview = false;
    bool executionPending = false;
    bool undoAvailable = false;
    bool pendingIdentity = true;
    glm::vec3 pendingTranslation{};
    glm::vec3 effectiveTranslation{};
};

struct RunResult {
    bool ok = false;
    size_t commands = 0;
    size_t assertions = 0;
    uint64_t frames = 0;
    std::string error;
};

inline std::string jsonEscape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\b': output << "\\b"; break;
            case '\f': output << "\\f"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (character < 0x20U) {
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<unsigned int>(character) << std::dec;
                } else {
                    output << character;
                }
        }
    }
    return output.str();
}

inline glm::vec3 matrixTranslation(const glm::mat4& matrix) {
    return glm::vec3(matrix * glm::vec4(0.0F, 0.0F, 0.0F, 1.0F));
}

inline bool matrixIsIdentity(const glm::mat4& matrix, float epsilon = 1.0e-6F) {
    const glm::mat4 identity(1.0F);
    for (size_t column = 0; column < 4; ++column) {
        for (size_t row = 0; row < 4; ++row) {
            if (std::abs(matrix[column][row] - identity[column][row]) > epsilon) {
                return false;
            }
        }
    }
    return true;
}

class Session {
  public:
    RunResult run(std::istream& input) {
        reset();
        std::string line;
        size_t lineNumber = 0;
        bool headerSeen = false;
        try {
            while (std::getline(input, line)) {
                ++lineNumber;
                if (line.size() > kMaximumScriptLineBytes) {
                    fail(lineNumber, "script line exceeds 4096 bytes");
                }
                trimCarriageReturn(line);
                if (!isPortableScriptLine(line)) {
                    fail(lineNumber, "script v1 accepts printable ASCII and tabs only");
                }
                const std::vector<std::string> fields = split(line);
                if (fields.empty() || fields.front().starts_with('#')) continue;
                if (!headerSeen) {
                    if (fields.size() != 2 || fields[0] != "SCRYWRITE" || fields[1] != "1") {
                        fail(lineNumber, "expected SCRYWRITE 1 header");
                    }
                    headerSeen = true;
                    continue;
                }
                if (result_.commands >= kMaximumCommands) {
                    fail(lineNumber, "script exceeds 10000 commands");
                }
                ++result_.commands;
                try {
                    execute(fields, lineNumber);
                    record(fields[0], lineNumber, "passed", "");
                } catch (const std::exception& error) {
                    record(fields[0], lineNumber, "failed", error.what());
                    throw;
                }
            }
            if (!headerSeen) fail(lineNumber == 0 ? 1 : lineNumber, "missing SCRYWRITE 1 header");
            result_.ok = true;
            result_.frames = frame_;
        } catch (const std::exception& error) {
            result_.ok = false;
            result_.frames = frame_;
            result_.error = error.what();
        }
        return result_;
    }

    [[nodiscard]] const RunResult& result() const { return result_; }
    [[nodiscard]] const std::vector<TraceEvent>& events() const { return events_; }

    [[nodiscard]] std::string traceJson() const {
        std::ostringstream output;
        output << std::setprecision(9);
        output << "{\n  \"schema\": \"scrywrite.trace.v1\",\n"
               << "  \"result\": \"" << (result_.ok ? "passed" : "failed") << "\",\n"
               << "  \"commands\": " << result_.commands << ",\n"
               << "  \"assertions\": " << result_.assertions << ",\n"
               << "  \"virtual_frames\": " << result_.frames << ",\n"
               << "  \"error\": \"" << jsonEscape(result_.error) << "\",\n"
               << "  \"coverage\": {\n";
        writeStringSet(output, "commands", commandsSeen_);
        output << ",\n";
        writeStringSet(output, "states", statesSeen_);
        output << ",\n";
        writeStringSet(output, "selection_kinds", selectionKindsSeen_);
        output << "\n  },\n  \"events\": [";
        for (size_t index = 0; index < events_.size(); ++index) {
            const TraceEvent& event = events_[index];
            output << (index == 0 ? "\n" : ",\n")
                   << "    {\"sequence\":" << event.sequence
                   << ",\"line\":" << event.line
                   << ",\"frame\":" << event.frame
                   << ",\"command\":\"" << jsonEscape(event.command)
                   << "\",\"outcome\":\"" << event.outcome
                   << "\",\"error\":\"" << jsonEscape(event.error)
                   << "\",\"selection_kind\":\"" << jsonEscape(event.selectionKind)
                   << "\",\"selection_identity\":\""
                   << jsonEscape(event.selectionIdentity)
                   << "\",\"tool\":\"" << jsonEscape(event.tool)
                   << "\",\"status\":\"" << jsonEscape(event.status)
                   << "\",\"preview\":" << boolean(event.preview)
                   << ",\"execution_pending\":" << boolean(event.executionPending)
                   << ",\"undo_available\":" << boolean(event.undoAvailable)
                   << ",\"pending_identity\":" << boolean(event.pendingIdentity)
                   << ",\"pending_translation\":";
            writeVector(output, event.pendingTranslation);
            output << ",\"effective_translation\":";
            writeVector(output, event.effectiveTranslation);
            output << '}';
        }
        if (!events_.empty()) output << '\n';
        output << "  ]\n}\n";
        return output.str();
    }

  private:
    [[noreturn]] static void fail(size_t line, const std::string& message) {
        throw std::runtime_error("line " + std::to_string(line) + ": " + message);
    }

    static void trimCarriageReturn(std::string& line) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
    }

    static bool isPortableScriptLine(const std::string& line) {
        return std::all_of(line.begin(), line.end(), [](unsigned char character) {
            return character == '\t' || (character >= 0x20U && character <= 0x7eU);
        });
    }

    static std::vector<std::string> split(const std::string& line) {
        std::istringstream input(line);
        std::vector<std::string> fields;
        std::string field;
        while (input >> field) fields.push_back(field);
        return fields;
    }

    static float parseFloat(const std::string& token, size_t line) {
        size_t consumed = 0;
        double value = 0.0;
        try {
            value = std::stod(token, &consumed);
        } catch (const std::exception&) {
            fail(line, "invalid finite number: " + token);
        }
        if (consumed != token.size() || !std::isfinite(value) ||
            value < -static_cast<double>(std::numeric_limits<float>::max()) ||
            value > static_cast<double>(std::numeric_limits<float>::max())) {
            fail(line, "invalid finite number: " + token);
        }
        return static_cast<float>(value);
    }

    static uint64_t parseFrames(const std::string& token, size_t line) {
        size_t consumed = 0;
        unsigned long long value = 0;
        try {
            value = std::stoull(token, &consumed);
        } catch (const std::exception&) {
            fail(line, "invalid frame count: " + token);
        }
        if (consumed != token.size() || value == 0 || value > kMaximumStepFrames) {
            fail(line, "frame count must be between 1 and 1000000");
        }
        return static_cast<uint64_t>(value);
    }

    static bool parseBoolean(const std::string& token, size_t line) {
        if (token == "true") return true;
        if (token == "false") return false;
        fail(line, "expected true or false, got: " + token);
    }

    static ToolMode parseTool(const std::string& token, size_t line) {
        if (token == "inspect") return ToolMode::inspect;
        if (token == "move_rotate") return ToolMode::move_rotate;
        if (token == "extrude") return ToolMode::extrude;
        if (token == "twist") return ToolMode::twist;
        if (token == "bend") return ToolMode::bend;
        fail(line, "unknown tool: " + token);
    }

    static size_t parseHand(const std::string& token, size_t line) {
        if (token == "left") return 0;
        if (token == "right") return 1;
        fail(line, "unknown hand: " + token);
    }

    static bool validSelectionKind(const std::string& kind) {
        static const std::array<std::string, 12> kinds = {
            "none", "cluster", "strand", "domain", "end", "crossover",
            "base", "atom", "bond", "overhang", "extension", "protein",
        };
        return std::find(kinds.begin(), kinds.end(), kind) != kinds.end();
    }

    static std::string statusFromToken(std::string token) {
        std::replace(token.begin(), token.end(), '_', ' ');
        return token;
    }

    static std::string boolean(bool value) { return value ? "true" : "false"; }

    static void writeVector(std::ostringstream& output, const glm::vec3& value) {
        output << '[' << value.x << ',' << value.y << ',' << value.z << ']';
    }

    static void writeStringSet(
        std::ostringstream& output, const char* name,
        const std::set<std::string>& values) {
        output << "    \"" << name << "\": [";
        size_t index = 0;
        for (const std::string& value : values) {
            if (index++ > 0) output << ',';
            output << "\"" << jsonEscape(value) << "\"";
        }
        output << ']';
    }

    void reset() {
        result_ = {};
        events_.clear();
        commandsSeen_.clear();
        statesSeen_.clear();
        selectionKindsSeen_.clear();
        shell_ = ToolShell{};
        pending_ = PendingRigidTransform{};
        hands_ = {};
        selectionKind_ = "none";
        selectionIdentity_.clear();
        committedTransform_ = glm::mat4(1.0F);
        commitHistory_.clear();
        confirmCandidate_.reset();
        frame_ = 0;
        feedbackSequence_ = 0;
    }

    [[nodiscard]] bool previewEnabled() const {
        return shell_.mode() == ToolMode::move_rotate && shell_.previewRequested() &&
               !shell_.executionPending();
    }

    [[nodiscard]] glm::mat4 effectiveTransform() const {
        return committedTransform_ * pending_.transform();
    }

    void step(uint64_t count) {
        if (count > kMaximumStepFrames || frame_ > kMaximumStepFrames - count) {
            throw std::runtime_error("virtual frame budget exceeds 1000000");
        }
        for (uint64_t index = 0; index < count; ++index) {
            ++frame_;
            pending_.update(hands_[1], glm::mat4(1.0F), previewEnabled());
        }
    }

    void execute(const std::vector<std::string>& fields, size_t line) {
        const std::string& command = fields[0];
        if (command == "select") executeSelect(fields, line);
        else if (command == "tool") executeTool(fields, line);
        else if (command == "preview") executePreview(fields, line);
        else if (command == "pose") executePose(fields, line);
        else if (command == "grip") executeGrip(fields, line);
        else if (command == "step") executeStep(fields, line);
        else if (command == "cancel") executeCancel(fields, line);
        else if (command == "confirm") executeConfirm(fields, line);
        else if (command == "undo") executeUndo(fields, line);
        else if (command == "feedback") executeFeedback(fields, line);
        else if (command == "expect") executeExpect(fields, line);
        else fail(line, "unknown command: " + command);
    }

    void executeSelect(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 3) fail(line, "select requires <kind> <identity>");
        if (!validSelectionKind(fields[1]) || fields[1] == "none") {
            fail(line, "invalid selection kind: " + fields[1]);
        }
        if (fields[2].empty() || fields[2].size() > 2048) {
            fail(line, "invalid selection identity");
        }
        const bool changed = selectionKind_ != fields[1] || selectionIdentity_ != fields[2];
        selectionKind_ = fields[1];
        selectionIdentity_ = fields[2];
        shell_.syncSelection(selectionKind_, changed);
        if (changed && !shell_.previewRequested()) pending_.cancel();
    }

    void executeTool(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 2) fail(line, "tool requires <mode>");
        const ToolMode mode = parseTool(fields[1], line);
        shell_.activate(mode, selectionKind_);
        pending_.cancel();
        confirmCandidate_.reset();
    }

    void executePreview(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 1) fail(line, "preview takes no arguments");
        shell_.apply(ToolAction::preview, selectionKind_);
        if (shell_.previewRequested()) pending_.activate();
    }

    void executePose(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 9) {
            fail(line, "pose requires <hand> x y z qw qx qy qz");
        }
        HandPose& hand = hands_[parseHand(fields[1], line)];
        hand.valid = true;
        hand.position = {
            parseFloat(fields[2], line), parseFloat(fields[3], line),
            parseFloat(fields[4], line),
        };
        glm::quat orientation(
            parseFloat(fields[5], line), parseFloat(fields[6], line),
            parseFloat(fields[7], line), parseFloat(fields[8], line));
        const float magnitude = glm::length(orientation);
        if (!std::isfinite(magnitude) || magnitude < 1.0e-6F) {
            fail(line, "pose quaternion must be non-zero");
        }
        hand.orientation = glm::normalize(orientation);
    }

    void executeGrip(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 3) fail(line, "grip requires <hand> <down|up>");
        HandPose& hand = hands_[parseHand(fields[1], line)];
        if (!hand.valid) fail(line, "grip requires a valid pose first");
        if (fields[2] == "down") hand.pressed = true;
        else if (fields[2] == "up") hand.pressed = false;
        else fail(line, "grip state must be down or up");
    }

    void executeStep(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() > 2) fail(line, "step accepts at most one frame count");
        step(fields.size() == 2 ? parseFrames(fields[1], line) : 1U);
    }

    void executeCancel(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 1) fail(line, "cancel takes no arguments");
        shell_.apply(ToolAction::cancel, selectionKind_);
        if (!shell_.executionPending()) {
            pending_.cancel();
            confirmCandidate_.reset();
        }
    }

    void executeConfirm(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 1) fail(line, "confirm takes no arguments");
        const bool wasPending = shell_.executionPending();
        shell_.apply(ToolAction::confirm, selectionKind_);
        if (!wasPending && shell_.executionPending()) {
            confirmCandidate_ = pending_.transform();
        }
    }

    void executeUndo(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 1) fail(line, "undo takes no arguments");
        shell_.apply(ToolAction::undo, selectionKind_);
    }

    void executeFeedback(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() != 5) {
            fail(line, "feedback requires <confirm|undo> <status> <reason> <feature|->");
        }
        if (fields[1] != "confirm" && fields[1] != "undo") {
            fail(line, "feedback action must be confirm or undo");
        }
        static const std::array<std::string, 4> statuses = {
            "pending", "succeeded", "failed", "refused",
        };
        if (std::find(statuses.begin(), statuses.end(), fields[2]) == statuses.end()) {
            fail(line, "invalid feedback status: " + fields[2]);
        }
        shell_.applyExecutionFeedback(ToolExecutionFeedback{
            ++feedbackSequence_, result_.commands, toolModeName(shell_.mode()), fields[1],
            selectionKind_, selectionIdentity_, fields[2],
            fields[3] == "-" ? "" : fields[3], fields[4] == "-" ? "" : fields[4],
        });
        if (fields[2] != "succeeded") return;
        if (fields[1] == "confirm") {
            if (!confirmCandidate_) fail(line, "confirm success has no pending candidate");
            commitHistory_.push_back(committedTransform_);
            committedTransform_ = committedTransform_ * *confirmCandidate_;
            pending_.cancel();
            confirmCandidate_.reset();
        } else {
            if (commitHistory_.empty()) fail(line, "undo success has no committed transform");
            committedTransform_ = commitHistory_.back();
            commitHistory_.pop_back();
        }
    }

    void executeExpect(const std::vector<std::string>& fields, size_t line) {
        if (fields.size() < 3) fail(line, "expect requires an assertion and value");
        ++result_.assertions;
        const std::string& assertion = fields[1];
        if (assertion == "status") {
            if (fields.size() != 3) fail(line, "expect status requires one token");
            const std::string expected = statusFromToken(fields[2]);
            if (shell_.status() != expected) {
                fail(line, "expected status " + expected + ", got " + shell_.status());
            }
        } else if (assertion == "selected") {
            if (fields.size() != 4) fail(line, "expect selected requires <kind> <identity>");
            if (selectionKind_ != fields[2] || selectionIdentity_ != fields[3]) {
                fail(line, "semantic selection mismatch");
            }
        } else if (assertion == "preview") {
            expectBoolean(fields, line, shell_.previewRequested(), "preview");
        } else if (assertion == "execution_pending") {
            expectBoolean(fields, line, shell_.executionPending(), "execution_pending");
        } else if (assertion == "undo_available") {
            expectBoolean(fields, line, shell_.undoAvailable(), "undo_available");
        } else if (assertion == "pending_identity") {
            expectBoolean(fields, line, pending_.isIdentity(0.0F), "pending_identity");
        } else if (assertion == "effective_identity") {
            expectBoolean(fields, line, matrixIsIdentity(effectiveTransform(), 0.0F),
                          "effective_identity");
        } else if (assertion == "pending_translation") {
            expectTranslation(fields, line, matrixTranslation(pending_.transform()), assertion);
        } else if (assertion == "effective_translation") {
            expectTranslation(fields, line, matrixTranslation(effectiveTransform()), assertion);
        } else {
            fail(line, "unknown assertion: " + assertion);
        }
    }

    static void expectBoolean(
        const std::vector<std::string>& fields, size_t line, bool actual,
        const std::string& name) {
        if (fields.size() != 3) fail(line, "expect " + name + " requires true or false");
        const bool expected = parseBoolean(fields[2], line);
        if (actual != expected) {
            fail(line, "expected " + name + " " + boolean(expected) + ", got " +
                           boolean(actual));
        }
    }

    static void expectTranslation(
        const std::vector<std::string>& fields, size_t line, const glm::vec3& actual,
        const std::string& name) {
        if (fields.size() != 6) {
            fail(line, "expect " + name + " requires x y z tolerance");
        }
        const glm::vec3 expected{
            parseFloat(fields[2], line), parseFloat(fields[3], line),
            parseFloat(fields[4], line),
        };
        const float tolerance = parseFloat(fields[5], line);
        if (tolerance < 0.0F) fail(line, "translation tolerance cannot be negative");
        if (glm::length(actual - expected) > tolerance) {
            std::ostringstream message;
            message << std::setprecision(9) << "expected " << name << " ["
                    << expected.x << ',' << expected.y << ',' << expected.z << "] +/- "
                    << tolerance << ", got [" << actual.x << ',' << actual.y << ','
                    << actual.z << ']';
            fail(line, message.str());
        }
    }

    void record(
        const std::string& command, size_t line, const std::string& outcome,
        const std::string& error) {
        const glm::mat4 effective = effectiveTransform();
        events_.push_back(TraceEvent{
            events_.size() + 1U,
            line,
            frame_,
            command,
            outcome,
            error,
            selectionKind_,
            selectionIdentity_,
            toolModeName(shell_.mode()),
            shell_.status(),
            shell_.previewRequested(),
            shell_.executionPending(),
            shell_.undoAvailable(),
            pending_.isIdentity(),
            matrixTranslation(pending_.transform()),
            matrixTranslation(effective),
        });
        commandsSeen_.insert(command);
        statesSeen_.insert(shell_.status());
        selectionKindsSeen_.insert(selectionKind_);
    }

    RunResult result_{};
    std::vector<TraceEvent> events_;
    std::set<std::string> commandsSeen_;
    std::set<std::string> statesSeen_;
    std::set<std::string> selectionKindsSeen_;
    ToolShell shell_;
    PendingRigidTransform pending_;
    std::array<HandPose, 2> hands_{};
    std::string selectionKind_ = "none";
    std::string selectionIdentity_;
    glm::mat4 committedTransform_{1.0F};
    std::vector<glm::mat4> commitHistory_;
    std::optional<glm::mat4> confirmCandidate_;
    uint64_t frame_ = 0;
    uint64_t feedbackSequence_ = 0;
};

}  // namespace nadoc_vr::scrywrite
