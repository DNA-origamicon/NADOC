#pragma once

#include "interaction.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <istream>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nadoc_vr::scrywrite {

inline constexpr size_t kMaximumWitnessLineBytes = 4096;
inline constexpr size_t kMaximumWitnessCommands = 10'000;
inline constexpr uint64_t kMaximumWitnessFrames = 1'000'000;

enum class WitnessButton { menu, trigger, grip };
enum class WitnessCommandKind {
    head, pose, button, step, aim_menu, touch_menu, snapshot,
    expect_menu, expect_hover, expect_tool, expect_status,
    expect_menu_placement, expect_menu_moved, expect_layout,
    expect_display, expect_tracking, expect_overlay,
    expect_framing, expect_representation,
};

struct WitnessHeadPose {
    glm::vec3 position{0.0F, 1.6F, 0.0F};
    glm::quat orientation{1.0F, 0.0F, 0.0F, 0.0F};
};

struct WitnessInput {
    WitnessHeadPose head;
    std::array<HandPose, 2> hands{};
    std::array<bool, 2> menuPressed{};
    std::array<bool, 2> triggerPressed{};
    std::array<bool, 2> gripPressed{};
};

struct WitnessObservation {
    WitnessObservation(
        std::string menuValue = "closed",
        std::string hoverValue = "none",
        std::string toolValue = "none",
        std::string statusValue = "none",
        std::string menuPlacementValue = "closed",
        glm::vec3 menuPositionValue = {},
        std::string layoutValue = "pending",
        std::string layoutDetailValue = {},
        std::string displayValue = "pending",
        std::string trackingValue = "pending",
        std::string overlayValue = "pending",
        std::string framingValue = "pending",
        std::string representationValue = "full")
        : menu(std::move(menuValue)), hover(std::move(hoverValue)),
          tool(std::move(toolValue)), status(std::move(statusValue)),
          menuPlacement(std::move(menuPlacementValue)),
          menuPosition(menuPositionValue), layout(std::move(layoutValue)),
          layoutDetail(std::move(layoutDetailValue)),
          display(std::move(displayValue)), tracking(std::move(trackingValue)),
          overlay(std::move(overlayValue)), framing(std::move(framingValue)),
          representation(std::move(representationValue)) {}

    std::string menu = "closed";
    std::string hover = "none";
    std::string tool = "none";
    std::string status = "none";
    std::string menuPlacement = "closed";
    glm::vec3 menuPosition{};
    std::string layout = "pending";
    std::string layoutDetail;
    std::string display = "pending";
    std::string tracking = "pending";
    std::string overlay = "pending";
    std::string framing = "pending";
    std::string representation = "full";
};

struct WitnessAim {
    size_t hand = 0;
    std::string label;
    size_t line = 0;
};

struct WitnessMenuTouch {
    size_t hand = 0;
    std::string edge;
    size_t line = 0;
};

struct WitnessSnapshot {
    std::string name;
    size_t line = 0;
};

struct WitnessMenuEntry {
    std::string label;
    int hit = -1;
    glm::vec3 worldPosition{};
};

struct WitnessGuideLine {
    glm::vec3 first{};
    glm::vec3 second{};
};

struct WitnessCommand {
    WitnessCommandKind kind = WitnessCommandKind::step;
    size_t line = 0;
    std::string source;
    size_t hand = 0;
    WitnessButton button = WitnessButton::trigger;
    bool pressed = false;
    uint64_t frames = 0;
    glm::vec3 position{};
    glm::quat orientation{1.0F, 0.0F, 0.0F, 0.0F};
    std::string value;
    float minimumDistance = 0.0F;
};

class WitnessReplay {
  public:
    static WitnessReplay load(std::istream& input) {
        WitnessReplay replay;
        replay.parse(input);
        return replay;
    }

    void advance(const WitnessObservation& observation) {
        if (failed_ || finished_) return;
        if (paused_ && !singleStepRequested_) return;
        if (pendingSnapshot_) return;
        singleStepRequested_ = false;
        ++frame_;
        if (waitingFrames_ > 0) {
            --waitingFrames_;
            return;
        }
        while (nextCommand_ < commands_.size()) {
            const WitnessCommand& command = commands_[nextCommand_++];
            currentLine_ = command.line;
            currentCommand_ = command.source;
            switch (command.kind) {
                case WitnessCommandKind::head:
                    input_.head = {command.position, command.orientation};
                    break;
                case WitnessCommandKind::pose:
                    input_.hands[command.hand].valid = true;
                    input_.hands[command.hand].position = command.position;
                    input_.hands[command.hand].orientation = command.orientation;
                    break;
                case WitnessCommandKind::button:
                    setButton(command.hand, command.button, command.pressed);
                    break;
                case WitnessCommandKind::step:
                    waitingFrames_ = command.frames > 0 ? command.frames - 1U : 0U;
                    return;
                case WitnessCommandKind::aim_menu:
                    pendingAim_ = WitnessAim{command.hand, command.value, command.line};
                    return;
                case WitnessCommandKind::touch_menu:
                    pendingMenuTouch_ = WitnessMenuTouch{
                        command.hand, command.value, command.line};
                    return;
                case WitnessCommandKind::snapshot:
                    pendingSnapshot_ = WitnessSnapshot{command.value, command.line};
                    return;
                case WitnessCommandKind::expect_menu:
                    if (canonical(observation.menu) != command.value) {
                        fail(command.line, "expected menu " + command.value +
                             ", got " + canonical(observation.menu));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_hover:
                    if (canonical(observation.hover) != command.value) {
                        fail(command.line, "expected hover " + command.value +
                             ", got " + canonical(observation.hover));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_tool:
                    if (canonical(observation.tool) != command.value) {
                        fail(command.line, "expected tool " + command.value +
                             ", got " + canonical(observation.tool));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_status:
                    if (canonical(observation.status) != command.value) {
                        fail(command.line, "expected status " + command.value +
                             ", got " + canonical(observation.status));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_menu_placement:
                    if (canonical(observation.menuPlacement) != command.value) {
                        fail(command.line, "expected menu placement " + command.value +
                             ", got " + canonical(observation.menuPlacement));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_menu_moved:
                    if (!menuPositionBaseline_) {
                        fail(command.line, "expect menu_moved requires touch_menu first");
                        return;
                    }
                    if (const float distance = glm::length(
                            observation.menuPosition - *menuPositionBaseline_);
                        !std::isfinite(distance) || distance < command.minimumDistance) {
                        fail(command.line, "expected menu to move at least " +
                             std::to_string(command.minimumDistance) + " m, got " +
                             std::to_string(distance) + " m");
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_layout:
                    if (canonical(observation.layout) != command.value) {
                        fail(command.line, "expected layout " + command.value +
                             ", got " + canonical(observation.layout) +
                             (observation.layoutDetail.empty()
                                  ? "" : " (" + observation.layoutDetail + ")"));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_display:
                    if (canonical(observation.display) != command.value) {
                        fail(command.line, "expected display " + command.value +
                             ", got " + canonical(observation.display));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_tracking:
                    if (canonical(observation.tracking) != command.value) {
                        fail(command.line, "expected tracking " + command.value +
                             ", got " + canonical(observation.tracking));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_overlay:
                    if (canonical(observation.overlay) != command.value) {
                        fail(command.line, "expected overlay " + command.value +
                             ", got " + canonical(observation.overlay));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_framing:
                    if (canonical(observation.framing) != command.value) {
                        fail(command.line, "expected framing " + command.value +
                             ", got " + canonical(observation.framing));
                        return;
                    }
                    break;
                case WitnessCommandKind::expect_representation:
                    if (canonical(observation.representation) != command.value) {
                        fail(command.line, "expected representation " + command.value +
                             ", got " + canonical(observation.representation));
                        return;
                    }
                    break;
            }
        }
        finished_ = true;
        neutralizeButtons();
        currentCommand_ = "complete";
    }

    [[nodiscard]] const WitnessInput& input() const { return input_; }
    [[nodiscard]] bool failed() const { return failed_; }
    [[nodiscard]] bool finished() const { return finished_; }
    [[nodiscard]] bool paused() const { return paused_; }
    [[nodiscard]] uint64_t frame() const { return frame_; }
    [[nodiscard]] size_t currentLine() const { return currentLine_; }
    [[nodiscard]] const std::string& currentCommand() const { return currentCommand_; }
    [[nodiscard]] const std::string& error() const { return error_; }
    [[nodiscard]] const std::optional<WitnessAim>& pendingAim() const { return pendingAim_; }
    [[nodiscard]] const std::optional<WitnessMenuTouch>& pendingMenuTouch() const {
        return pendingMenuTouch_;
    }
    [[nodiscard]] const std::optional<WitnessSnapshot>& pendingSnapshot() const {
        return pendingSnapshot_;
    }

    void resolveAim(const glm::quat& orientation) {
        if (!pendingAim_) return;
        input_.hands[pendingAim_->hand].orientation = glm::normalize(orientation);
        pendingAim_.reset();
    }

    void rejectAim(const std::string& reason) {
        if (!pendingAim_) return;
        fail(pendingAim_->line, reason);
        pendingAim_.reset();
    }

    void resolveMenuTouch(const glm::vec3& position, const glm::vec3& menuPosition) {
        if (!pendingMenuTouch_) return;
        input_.hands[pendingMenuTouch_->hand].position = position;
        menuPositionBaseline_ = menuPosition;
        pendingMenuTouch_.reset();
    }

    void rejectMenuTouch(const std::string& reason) {
        if (!pendingMenuTouch_) return;
        fail(pendingMenuTouch_->line, reason);
        pendingMenuTouch_.reset();
    }

    void resolveSnapshot() { pendingSnapshot_.reset(); }

    void rejectSnapshot(const std::string& reason) {
        if (!pendingSnapshot_) return;
        fail(pendingSnapshot_->line, reason);
        pendingSnapshot_.reset();
    }

    void togglePaused() { paused_ = !paused_; }
    void requestSingleStep() {
        paused_ = true;
        singleStepRequested_ = true;
    }

    [[nodiscard]] std::string status() const {
        if (failed_) return "FAILED L" + std::to_string(currentLine_) + " " + error_;
        if (finished_) return "PASSED";
        if (paused_) return "PAUSED L" + std::to_string(currentLine_) + " " + currentCommand_;
        return "RUNNING L" + std::to_string(currentLine_) + " " + currentCommand_;
    }

    static std::string canonical(std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
            if (character == ' ' || character == '/' || character == '+') return '_';
            return static_cast<char>(std::tolower(character));
        });
        value.erase(std::unique(value.begin(), value.end(), [](char first, char second) {
            return first == '_' && second == '_';
        }), value.end());
        return value;
    }

  private:
    [[noreturn]] static void parseFail(size_t line, const std::string& message) {
        throw std::runtime_error("line " + std::to_string(line) + ": " + message);
    }

    void fail(size_t line, const std::string& message) {
        failed_ = true;
        paused_ = true;
        currentLine_ = line;
        error_ = message;
        neutralizeButtons();
    }

    static float number(const std::string& token, size_t line) {
        size_t consumed = 0;
        double value = 0.0;
        try {
            value = std::stod(token, &consumed);
        } catch (const std::exception&) {
            parseFail(line, "invalid finite number: " + token);
        }
        if (consumed != token.size() || !std::isfinite(value) ||
            std::abs(value) > std::numeric_limits<float>::max()) {
            parseFail(line, "invalid finite number: " + token);
        }
        return static_cast<float>(value);
    }

    static uint64_t frames(const std::string& token, size_t line) {
        size_t consumed = 0;
        unsigned long long value = 0;
        try {
            value = std::stoull(token, &consumed);
        } catch (const std::exception&) {
            parseFail(line, "invalid frame count: " + token);
        }
        if (consumed != token.size() || value == 0 || value > kMaximumWitnessFrames) {
            parseFail(line, "frame count must be between 1 and 1000000");
        }
        return static_cast<uint64_t>(value);
    }

    static size_t hand(const std::string& token, size_t line) {
        if (token == "left") return 0;
        if (token == "right") return 1;
        parseFail(line, "unknown hand: " + token);
    }

    static WitnessButton button(const std::string& token, size_t line) {
        if (token == "menu") return WitnessButton::menu;
        if (token == "trigger") return WitnessButton::trigger;
        if (token == "grip") return WitnessButton::grip;
        parseFail(line, "unknown button: " + token);
    }

    static glm::quat orientation(
        const std::vector<std::string>& fields, size_t offset, size_t line) {
        glm::quat result(
            number(fields[offset], line), number(fields[offset + 1U], line),
            number(fields[offset + 2U], line), number(fields[offset + 3U], line));
        const float magnitude = glm::length(result);
        if (!std::isfinite(magnitude) || magnitude < 1.0e-6F) {
            parseFail(line, "pose quaternion must be non-zero");
        }
        return glm::normalize(result);
    }

    void parse(std::istream& input) {
        std::string lineText;
        size_t line = 0;
        bool header = false;
        while (std::getline(input, lineText)) {
            ++line;
            if (!lineText.empty() && lineText.back() == '\r') lineText.pop_back();
            if (lineText.size() > kMaximumWitnessLineBytes) {
                parseFail(line, "script line exceeds 4096 bytes");
            }
            if (!std::all_of(lineText.begin(), lineText.end(), [](unsigned char character) {
                    return character == '\t' ||
                           (character >= 0x20U && character <= 0x7eU);
                })) {
                parseFail(line, "script v1 accepts printable ASCII and tabs only");
            }
            std::istringstream parser(lineText);
            std::vector<std::string> fields;
            std::string field;
            while (parser >> field) fields.push_back(field);
            if (fields.empty() || fields.front().starts_with('#')) continue;
            if (!header) {
                if (fields.size() != 2 || fields[0] != "SCRYWRITE_WITNESS" || fields[1] != "1") {
                    parseFail(line, "expected SCRYWRITE_WITNESS 1 header");
                }
                header = true;
                continue;
            }
            if (commands_.size() >= kMaximumWitnessCommands) {
                parseFail(line, "script exceeds 10000 commands");
            }
            WitnessCommand command;
            command.line = line;
            command.source = lineText;
            if (fields[0] == "head" || fields[0] == "pose") {
                const size_t expected = fields[0] == "head" ? 8U : 9U;
                if (fields.size() != expected) {
                    parseFail(line, fields[0] + " requires x y z qw qx qy qz");
                }
                const size_t offset = fields[0] == "head" ? 1U : 2U;
                command.kind = fields[0] == "head"
                    ? WitnessCommandKind::head : WitnessCommandKind::pose;
                if (fields[0] == "pose") command.hand = hand(fields[1], line);
                command.position = {
                    number(fields[offset], line), number(fields[offset + 1U], line),
                    number(fields[offset + 2U], line),
                };
                command.orientation = orientation(fields, offset + 3U, line);
            } else if (fields[0] == "button") {
                if (fields.size() != 4) {
                    parseFail(line, "button requires <hand> <menu|trigger|grip> <down|up>");
                }
                command.kind = WitnessCommandKind::button;
                command.hand = hand(fields[1], line);
                command.button = button(fields[2], line);
                if (fields[3] != "down" && fields[3] != "up") {
                    parseFail(line, "button state must be down or up");
                }
                command.pressed = fields[3] == "down";
            } else if (fields[0] == "step") {
                if (fields.size() != 2) parseFail(line, "step requires a frame count");
                command.kind = WitnessCommandKind::step;
                command.frames = frames(fields[1], line);
            } else if (fields[0] == "aim_menu") {
                if (fields.size() != 3) parseFail(line, "aim_menu requires <hand> <label>");
                command.kind = WitnessCommandKind::aim_menu;
                command.hand = hand(fields[1], line);
                command.value = canonical(fields[2]);
            } else if (fields[0] == "touch_menu") {
                if (fields.size() != 3) {
                    parseFail(line, "touch_menu requires <hand> <left|right|top|bottom>");
                }
                command.kind = WitnessCommandKind::touch_menu;
                command.hand = hand(fields[1], line);
                command.value = canonical(fields[2]);
                if (command.value != "left" && command.value != "right" &&
                    command.value != "top" && command.value != "bottom") {
                    parseFail(line, "touch_menu edge must be left, right, top, or bottom");
                }
            } else if (fields[0] == "snapshot") {
                if (fields.size() != 2) parseFail(line, "snapshot requires a name");
                if (fields[1].empty() || fields[1].size() > 64U ||
                    !std::all_of(fields[1].begin(), fields[1].end(), [](unsigned char value) {
                        return std::islower(value) || std::isdigit(value) ||
                               value == '_' || value == '-';
                    })) {
                    parseFail(line,
                        "snapshot name must use 1-64 lowercase letters, digits, _ or -");
                }
                command.kind = WitnessCommandKind::snapshot;
                command.value = fields[1];
            } else if (fields[0] == "expect") {
                if (fields.size() != 3 ||
                    (fields[1] != "menu" && fields[1] != "hover" &&
                     fields[1] != "tool" && fields[1] != "status" &&
                     fields[1] != "placement" && fields[1] != "menu_moved" &&
                     fields[1] != "layout" && fields[1] != "display" &&
                     fields[1] != "tracking" && fields[1] != "overlay" &&
                     fields[1] != "framing" && fields[1] != "representation")) {
                    parseFail(line,
                        "expect requires <menu|hover|tool|status|placement|menu_moved|layout|display|tracking|overlay|framing|representation> <value>");
                }
                if (fields[1] == "menu") command.kind = WitnessCommandKind::expect_menu;
                else if (fields[1] == "hover") command.kind = WitnessCommandKind::expect_hover;
                else if (fields[1] == "tool") command.kind = WitnessCommandKind::expect_tool;
                else if (fields[1] == "status") command.kind = WitnessCommandKind::expect_status;
                else if (fields[1] == "placement") {
                    command.kind = WitnessCommandKind::expect_menu_placement;
                    command.value = canonical(fields[2]);
                    if (command.value != "following" && command.value != "docked") {
                        parseFail(line, "menu placement must be following or docked");
                    }
                } else if (fields[1] == "menu_moved") {
                    command.kind = WitnessCommandKind::expect_menu_moved;
                    command.minimumDistance = number(fields[2], line);
                    if (command.minimumDistance <= 0.0F || command.minimumDistance > 5.0F) {
                        parseFail(line, "menu_moved distance must be greater than 0 and at most 5 m");
                    }
                } else if (fields[1] == "layout") {
                    command.kind = WitnessCommandKind::expect_layout;
                    command.value = canonical(fields[2]);
                } else if (fields[1] == "display") {
                    command.kind = WitnessCommandKind::expect_display;
                } else if (fields[1] == "tracking") {
                    command.kind = WitnessCommandKind::expect_tracking;
                } else if (fields[1] == "overlay") {
                    command.kind = WitnessCommandKind::expect_overlay;
                } else if (fields[1] == "representation") {
                    command.kind = WitnessCommandKind::expect_representation;
                } else {
                    command.kind = WitnessCommandKind::expect_framing;
                }
                if (fields[1] != "placement" && fields[1] != "menu_moved" &&
                    fields[1] != "layout") {
                    command.value = canonical(fields[2]);
                }
            } else {
                parseFail(line, "unknown witness command: " + fields[0]);
            }
            commands_.push_back(std::move(command));
        }
        if (!header) parseFail(line == 0 ? 1 : line, "missing SCRYWRITE_WITNESS 1 header");
    }

    void setButton(size_t handIndex, WitnessButton kind, bool pressed) {
        if (kind == WitnessButton::menu) input_.menuPressed[handIndex] = pressed;
        else if (kind == WitnessButton::trigger) input_.triggerPressed[handIndex] = pressed;
        else {
            input_.gripPressed[handIndex] = pressed;
            input_.hands[handIndex].pressed = pressed;
        }
    }

    void neutralizeButtons() {
        input_.menuPressed.fill(false);
        input_.triggerPressed.fill(false);
        input_.gripPressed.fill(false);
        for (auto& handInput : input_.hands) handInput.pressed = false;
    }

    std::vector<WitnessCommand> commands_;
    WitnessInput input_;
    size_t nextCommand_ = 0;
    uint64_t waitingFrames_ = 0;
    uint64_t frame_ = 0;
    size_t currentLine_ = 0;
    std::string currentCommand_ = "starting";
    std::string error_;
    std::optional<WitnessAim> pendingAim_;
    std::optional<WitnessMenuTouch> pendingMenuTouch_;
    std::optional<WitnessSnapshot> pendingSnapshot_;
    std::optional<glm::vec3> menuPositionBaseline_;
    bool failed_ = false;
    bool finished_ = false;
    bool paused_ = false;
    bool singleStepRequested_ = false;
};

inline std::optional<WitnessMenuEntry> findWitnessMenuEntry(
    const std::vector<WitnessMenuEntry>& entries, const std::string& canonicalLabel) {
    const auto found = std::find_if(entries.begin(), entries.end(), [&](const auto& entry) {
        return WitnessReplay::canonical(entry.label) == canonicalLabel;
    });
    return found == entries.end() ? std::nullopt
                                  : std::optional<WitnessMenuEntry>(*found);
}

inline std::string witnessHoverLabel(
    const std::vector<WitnessMenuEntry>& entries, int hit) {
    const auto found = std::find_if(entries.begin(), entries.end(), [&](const auto& entry) {
        return entry.hit == hit;
    });
    return found == entries.end() ? "none" : WitnessReplay::canonical(found->label);
}

inline std::optional<glm::quat> witnessAimOrientation(
    const glm::vec3& origin, const glm::vec3& target) {
    const glm::vec3 offset = target - origin;
    if (glm::length(offset) < 1.0e-5F) return std::nullopt;
    const glm::vec3 direction = glm::normalize(offset);
    glm::vec3 up(0.0F, 1.0F, 0.0F);
    if (std::abs(glm::dot(direction, up)) > 0.98F) up = {1.0F, 0.0F, 0.0F};
    return glm::quatLookAt(direction, up);
}

inline std::optional<glm::vec3> witnessMenuTouchPosition(
    const MenuPlacement& placement, const glm::vec2& minimum,
    const glm::vec2& maximum, const std::string& edge) {
    const glm::vec2 midpoint = (minimum + maximum) * 0.5F;
    if (edge == "left") return placement.worldPoint({minimum.x, midpoint.y, 0.0F});
    if (edge == "right") return placement.worldPoint({maximum.x, midpoint.y, 0.0F});
    if (edge == "top") return placement.worldPoint({midpoint.x, maximum.y, 0.0F});
    if (edge == "bottom") return placement.worldPoint({midpoint.x, minimum.y, 0.0F});
    return std::nullopt;
}

inline void resolveWitnessMenuTouch(
    WitnessReplay& replay, const MenuPlacement& placement,
    const glm::vec2& minimum, const glm::vec2& maximum, bool menuOpen) {
    if (!replay.pendingMenuTouch()) return;
    const auto touch = *replay.pendingMenuTouch();
    if (!menuOpen) {
        replay.rejectMenuTouch("touch_menu requires an open menu");
        return;
    }
    if (!replay.input().hands[touch.hand].valid) {
        replay.rejectMenuTouch("touch_menu requires a valid scripted hand pose");
        return;
    }
    const auto position = witnessMenuTouchPosition(
        placement, minimum, maximum, touch.edge);
    if (!position) {
        replay.rejectMenuTouch("unknown menu edge: " + touch.edge);
        return;
    }
    replay.resolveMenuTouch(*position, placement.position());
}

inline std::vector<WitnessGuideLine> witnessHeadFrustum(const WitnessHeadPose& head) {
    const glm::vec3 forward = head.orientation * glm::vec3(0.0F, 0.0F, -1.0F);
    const glm::vec3 right = head.orientation * glm::vec3(1.0F, 0.0F, 0.0F);
    const glm::vec3 up = head.orientation * glm::vec3(0.0F, 1.0F, 0.0F);
    const glm::vec3 center = head.position + forward * 0.22F;
    const std::array<glm::vec3, 4> corners = {
        center - right * 0.284F - up * 0.160F,
        center + right * 0.284F - up * 0.160F,
        center + right * 0.284F + up * 0.160F,
        center - right * 0.284F + up * 0.160F,
    };
    std::vector<WitnessGuideLine> lines;
    lines.reserve(8);
    for (size_t index = 0; index < corners.size(); ++index) {
        lines.push_back({head.position, corners[index]});
        lines.push_back({corners[index], corners[(index + 1U) % corners.size()]});
    }
    return lines;
}

}  // namespace nadoc_vr::scrywrite
