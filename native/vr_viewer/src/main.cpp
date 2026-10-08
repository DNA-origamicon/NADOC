#include "placement_integrity.hpp"
#include <atomic>
#include <future>
#include <deque>
#include <condition_variable>
#include <mutex>
#include "lattice_grip.hpp"
#include "thumbwheel_mesh.hpp"
#define XR_USE_PLATFORM_XLIB
#define XR_USE_GRAPHICS_API_OPENGL
#define GL_GLEXT_PROTOTYPES
#define GLFW_EXPOSE_NATIVE_X11
#define GLFW_EXPOSE_NATIVE_GLX

#include <GL/gl.h>
#include <GL/glx.h>
#include <GLFW/glfw3.h>
#include <GLFW/glfw3native.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <zlib.h>

#include "interaction.hpp"
#include "selection_wheel.hpp"
#include "selection_owner_index.hpp"
#include "shadow_light.hpp"
#include "desktop_panel.hpp"
#include "remote_panel.hpp"
#include "representation_buffers.hpp"
#include "async_trace.hpp"
#include "loading_frame_trace.hpp"
#include "frame_audit.hpp"
#include "motion_detail.hpp"
#include "latest_atomic_file.hpp"
#include "ordered_atomic_file.hpp"
#include "representation_meshes.hpp"
#include "painted_commit_gate.hpp"
#include "selection_level_guard.hpp"
#include "freeform_draft.hpp"
#include "scene_refresh.hpp"
#include "lattice_view.hpp"
#include "lattice_context.hpp"
#include "lattice_painter.hpp"
#include "extrude_plane.hpp"
#include "stroke_font.hpp"
#include "controller_diagnostics.hpp"
#include "controller_paths.hpp"
#include "jobs.hpp"
#include "menu_layout.hpp"
#include "sidebar_menu.hpp"
#include "simulation_panel.hpp"
#include "routing_panel.hpp"
#include "trajectory_panel.hpp"
#include "dimension_panel.hpp"
#include "view_volume_panel.hpp"
#include "extrude_panel.hpp"
#include "sweep_panel.hpp"
#include "bend_panel.hpp"
#include "move_panel.hpp"
#include "end_resize.hpp"
#include "ligation.hpp"
#include "quiver_gesture.hpp"
#include "view_volume_shader.hpp"
#include "dimension_sync.hpp"
#include "sidebar_grips.hpp"
#include "picking.hpp"
#include "representation_picking.hpp"
#include "reference_grid.hpp"
#include "scrywrite_witness.hpp"
#include "scrywrite_live.hpp"
#include "scrywrite_witness_surface.hpp"
#include "scrywrite_visual.hpp"
#include "spectator_mirror.hpp"
#include "live_mirror_capture.hpp"
#include "live_visual_measure.hpp"
#include "live_presentation.hpp"
#include "presenter_ui.hpp"
#include "trajectory.hpp"
#include "coordinate_playback.hpp"
#include "visualization.hpp"

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <charconv>
#include <cmath>
#include <cctype>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <tuple>
#include <unordered_set>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

constexpr float kViewSizeMeters = 0.60F;
constexpr float kViewDistanceMeters = 1.30F;
constexpr float kNearMeters = 0.02F;
constexpr float kFarMeters = 100.0F;
constexpr int32_t kMirrorDiagnosticSize = 64;
constexpr uint64_t kMirrorDiagnosticIntervalFrames = 30U;

std::atomic_bool gStopRequested{false};

double currentResidentMiB() {
    std::ifstream status("/proc/self/status");
    std::string line;
    while (std::getline(status, line)) {
        if (!line.starts_with("VmRSS:")) continue;
        std::istringstream fields(line.substr(6));
        double kibibytes = 0.0;
        fields >> kibibytes;
        return kibibytes / 1024.0;
    }
    return -1.0;
}

std::optional<float> parseFiniteFloat(const std::string& value) {
    float parsed = 0.0F;
    const auto result = std::from_chars(
        value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() ||
        !std::isfinite(parsed)) {
        return std::nullopt;
    }
    return parsed;
}

struct Vertex {
    glm::vec3 position{};
    glm::vec3 color{};
    float size = 1.0F;
    uint32_t objectId = 0;
};

struct Cylinder {
    glm::vec3 start{};
    glm::vec3 end{};
    float radius = 0.01F;
    glm::vec3 color{};
    uint32_t objectId = 0;
    float endRadius = -1.0F;
};


struct Box {
    glm::vec3 center{};
    glm::vec3 axisX{};
    glm::vec3 axisY{};
    glm::vec3 axisZ{};
    glm::vec3 color{};
    uint32_t objectId = 0;
    std::array<glm::vec3,3> normals{};
};

struct CylinderMeshVertex {
    glm::vec3 position{};
    glm::vec3 normal{};
};

#include "representations.hpp"
enum class Coloring : size_t { strand = 0, base = 1, cluster = 2, cpk = 3 };

struct ColorSet {
    std::array<glm::vec3, 4> values{};
    [[nodiscard]] glm::vec3 get(Coloring coloring) const {
        return values[static_cast<size_t>(coloring)];
    }
};

struct StyledPoint {
    std::string identity;
    glm::vec3 position{};
    ColorSet colors{};
    float size = 1.0F;
    float vdwSize = 0.0F;
};

struct StyledCylinder {
    std::string identity;
    glm::vec3 start{};
    glm::vec3 end{};
    float radius = 0.01F;
    ColorSet colors{};
    float endRadius = -1.0F;
};

struct StyledBox {
    std::string identity;
    glm::vec3 center{};
    glm::vec3 axisX{};
    glm::vec3 axisY{};
    glm::vec3 axisZ{};
    ColorSet colors{};
    std::array<glm::vec3,3> normals{};
};

struct OwnerHandle {
    std::string token;
    glm::vec3 center{};
};

struct ToolHandle {
    std::string id;
    std::string token;
    std::string kind;
    glm::vec3 center{};
};

struct TransformOwner {
    std::string token;
    float startWeight = 0.0F;
    float endWeight = 0.0F;

    bool operator==(const TransformOwner&) const = default;
};

struct TransformOwnership {
    std::string identity;
    std::vector<TransformOwner> owners;

    bool operator==(const TransformOwnership&) const = default;
};

struct RepresentationData {
    std::vector<StyledPoint> points;
    std::vector<StyledCylinder> cylinders;
    std::vector<StyledCylinder> halfCylinders;
    std::vector<StyledBox> boxes;
    std::vector<nadoc_vr::OwnerAliasEntry> ownerAliases;
    std::vector<OwnerHandle> ownerHandles;
    std::vector<TransformOwnership> transformOwnership;
    std::vector<ToolHandle> toolHandles;
    std::vector<TransformOwnership> toolScopeOwnership;
};

#include "prepared_representation.hpp"
#include "rigid_preview.hpp"

struct SceneData {
    std::array<std::shared_ptr<PreparedRepresentation>,kRepresentationCount> prepared{};
    std::array<size_t,kRepresentationCount> cpuBytes{};
    nadoc_vr::ExtrudePlane extrudePlane;
    nadoc_vr::LatticeContext latticeContext;
    std::array<RepresentationData, kRepresentationCount> representations;
    std::array<bool,kRepresentationCount> available{};
    bool emptyAuthoring = false;
    std::optional<bool> preparedAtomisticSharedGeometry;
    Representation initialRepresentation = Representation::full;
    Coloring initialColoring = Coloring::strand;
    glm::mat3 sourceAxes{1.0F};
    glm::vec3 normalizationCenter{};
    float normalizationScale = 1.0F;
    SceneData()=default;
    SceneData(SceneData&&)=default;
    SceneData& operator=(SceneData&&)=default;
    // Prepared records/indexes borrow primitive addresses. A deep scene copy
    // must not retain pointers into the original; ordinary moves keep them valid.
    SceneData(const SceneData& other):cpuBytes(other.cpuBytes),extrudePlane(other.extrudePlane),latticeContext(other.latticeContext),
        representations(other.representations),
        available(other.available),emptyAuthoring(other.emptyAuthoring),
        initialRepresentation(other.initialRepresentation),initialColoring(other.initialColoring),
        sourceAxes(other.sourceAxes),normalizationCenter(other.normalizationCenter),normalizationScale(other.normalizationScale){}
    SceneData& operator=(const SceneData& other){if(this!=&other)*this=SceneData(other);return *this;}
};

[[nodiscard]] inline bool atomisticCylindersEquivalent(const SceneData& scene) {
        const auto& ballstick = scene.representations[
            static_cast<size_t>(Representation::ballstick)];
        const auto& stick = scene.representations[
            static_cast<size_t>(Representation::stick)];
        if (ballstick.cylinders.size() != stick.cylinders.size() ||
            !ballstick.halfCylinders.empty() || !stick.halfCylinders.empty() ||
            !ballstick.boxes.empty() || !stick.boxes.empty()) {
            return false;
        }
        for (size_t index = 0; index < ballstick.cylinders.size(); ++index) {
            const StyledCylinder& first = ballstick.cylinders[index];
            const StyledCylinder& second = stick.cylinders[index];
            if (first.identity != second.identity || first.start != second.start ||
                first.end != second.end || first.radius != second.radius) {
                return false;
            }
            for (size_t color = 0; color < first.colors.values.size(); ++color) {
                if (first.colors.values[color] != second.colors.values[color]) return false;
            }
        }
        return true;
    }


struct SelectionVolumeHits {
    std::vector<nadoc_vr::PickHit> representatives;
    std::vector<std::string> ownerTokens;
    std::vector<std::string> directIdentities;
};

Representation representationFromName(const std::string& name) {
    for (size_t i = 0; i < kRepresentationCount; ++i)
        if (name == kRepresentationNames[i]) return static_cast<Representation>(i);
    throw std::runtime_error("Unknown VR representation: " + name);
}

Coloring coloringFromName(const std::string& name) {
    if (name == "strand") return Coloring::strand;
    if (name == "base") return Coloring::base;
    if (name == "cluster") return Coloring::cluster;
    if (name == "cpk") return Coloring::cpk;
    throw std::runtime_error("Unknown VR coloring: " + name);
}

const char* representationName(Representation representation) {
    return kRepresentationNames.at(static_cast<size_t>(representation)).data();
}

const char* coloringName(Coloring coloring) {
    switch (coloring) {
        case Coloring::strand: return "strand";
        case Coloring::base: return "base";
        case Coloring::cluster: return "cluster";
        case Coloring::cpk: return "cpk";
    }
    return "strand";
}

struct Swapchain {
    XrSwapchain handle = XR_NULL_HANDLE;
    int32_t width = 0;
    int32_t height = 0;
    std::vector<XrSwapchainImageOpenGLKHR> images;
    GLuint depth = 0;
};

void signalHandler(int) { gStopRequested = true; }

void checkXr(XrInstance instance, XrResult result, const char* operation) {
    if (XR_SUCCEEDED(result)) return;
    char buffer[XR_MAX_RESULT_STRING_SIZE] = {};
    if (instance != XR_NULL_HANDLE) xrResultToString(instance, result, buffer);
    throw std::runtime_error(std::string(operation) + " failed: " + buffer +
                             " (" + std::to_string(result) + ")");
}

GLuint compileShader(GLenum kind, const char* source) {
    const GLuint shader = glCreateShader(kind);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok == GL_TRUE) return shader;
    GLint length = 0;
    glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetShaderInfoLog(shader, length, nullptr, log.data());
    glDeleteShader(shader);
    throw std::runtime_error("OpenGL shader compilation failed: " + log);
}

GLuint makeProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aPosition;
        layout(location = 1) in vec3 aColor;
        uniform mat4 uViewProjection;
        uniform mat4 uVolumeModel;
        out vec3 vColor;
        out vec3 vWorldPosition;
        void main() {
            gl_Position = uViewProjection * vec4(aPosition, 1.0);
            vColor = aColor;
            vWorldPosition=(uVolumeModel*vec4(aPosition,1)).xyz;
        }
    )GLSL";
    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec3 vColor;
        in vec3 vWorldPosition;
        out vec4 outColor;
        void main() {
            outColor = vec4(vColor, 1.0);
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER,nadoc_vr::volumeFragment(fragmentSource,"void main() {","vWorldPosition").c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL program link failed: " + log);
}

GLuint makeDesktopProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aPosition;
        layout(location = 1) in vec2 aUv;
        uniform mat4 uViewProjection;
        out vec2 vUv;
        void main() {
            gl_Position = uViewProjection * vec4(aPosition, 1.0);
            vUv = aUv;
        }
    )GLSL";
    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uDesktop;
        uniform vec2 uPointer;
        uniform int uPointerVisible;
        uniform int uMagnifying;
        out vec4 outColor;
        void main() {
            vec2 sampleUv = vUv;
            float aspect = float(textureSize(uDesktop, 0).x) / float(textureSize(uDesktop, 0).y);
            float radius = length((vUv-uPointer)*vec2(aspect,1.0));
            bool lens = uMagnifying != 0 && uPointerVisible != 0 && radius < 0.16;
            if (lens) sampleUv = uPointer + (vUv-uPointer)/3.0;
            vec3 color = texture(uDesktop, clamp(sampleUv,vec2(0),vec2(1))).rgb;
            if (lens && radius > 0.155) color = vec3(0.35,0.65,1.0);
            if (uPointerVisible != 0) {
                vec2 delta = abs(vUv-uPointer)*vec2(textureSize(uDesktop,0));
                bool stem = delta.x < 1.5 && delta.y > 3.0 && delta.y < 12.0;
                bool bar = delta.y < 1.5 && delta.x > 3.0 && delta.x < 12.0;
                if (stem || bar) color = vec3(1.0, 0.72, 0.10);
            }
            outColor = vec4(color, 1.0);
        }
    )GLSL";
    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, fragmentSource);
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL desktop shader link failed: " + log);
}

#include "frosted_glass.hpp"
#include "room_floor.hpp"
#include "qr_calibration.hpp"

GLuint makeMenuPanelProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aPosition;
        layout(location = 1) in vec2 aUv;
        uniform mat4 uViewProjection;
        out vec2 vUv;
        void main() {
            gl_Position = uViewProjection * vec4(aPosition, 1.0);
            vUv = aUv;
        }
    )GLSL";
    const std::string fragmentSource = std::string(R"GLSL(
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uPanel;
        uniform bool uTransparentPanel;
        out vec4 outColor;
    )GLSL") + frostedGlassShader + R"GLSL(
        void main() {
            vec4 color = texture(uPanel, vUv);
            if (color.a < 0.004) discard;
            // Transparent MSAA/mip texels contain coverage-weighted RGB.
            // Recover ink before frost and ordinary source-alpha blending.
            if (uTransparentPanel) color.rgb /= color.a;
            outColor = frostedMenu(color);
        }
    )GLSL";
    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, fragmentSource.c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL menu panel program link failed: " + log);
}

constexpr const char* kLitFragmentSource = R"GLSL(
    #version 330 core
    in vec3 vColor;
    in vec3 vNormal;
    flat in int vTwoSided;
    in vec3 vWorldPosition;
    uniform sampler2DShadow uShadowMap;
    uniform mat4 uLightViewProjection;
    uniform vec3 uLightDirection;
    uniform int uShadowsEnabled;
    uniform float uAlpha;
    uniform float uEmissive;
    flat in uint vSelection;
    layout(location = 0) out vec4 outColor;
    layout(location = 1) out uint outObjectId;
    flat in uint vObjectId;

    float shadowVisibility(vec3 normal) {
        if (uShadowsEnabled == 0) return 1.0;
        vec4 lightClip = uLightViewProjection * vec4(vWorldPosition, 1.0);
        vec3 projected = lightClip.xyz / lightClip.w;
        projected = projected * 0.5 + 0.5;
        if (projected.x <= 0.0 || projected.x >= 1.0 ||
            projected.y <= 0.0 || projected.y >= 1.0 ||
            projected.z <= 0.0 || projected.z >= 1.0) return 1.0;
        float facing = max(dot(normal, uLightDirection), 0.0);
        float bias = mix(0.0012, 0.00018, facing);
        float visibility = 0.0;
        const float texel = 1.0 / 2048.0;
        for (int y = -1; y <= 1; ++y) {
            for (int x = -1; x <= 1; ++x) {
                visibility += texture(
                    uShadowMap,
                    vec3(projected.xy + vec2(x, y) * texel, projected.z - bias));
            }
        }
        return visibility / 9.0;
    }

    void main() {
        vec3 normal = normalize(vNormal) * (vTwoSided != 0 && !gl_FrontFacing ? -1.0 : 1.0);
        float diffuse = max(dot(normal, uLightDirection), 0.0);
        float lighting = 0.20 + 0.90 * diffuse * shadowVisibility(normal);
        lighting = mix(lighting, 1.0, uEmissive);
        outObjectId = vObjectId;
        vec3 shaded = vColor * lighting;
        vec3 selectionColor = vSelection == 2u ? vec3(0.22, 1.0, 0.42) : vec3(1.0, 0.68, 0.12);
        outColor = vec4(mix(shaded, selectionColor, vSelection == 0u ? 0.0 : 0.48), uAlpha);
    }
)GLSL";

GLuint makeSphereProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aUnitPosition;
        layout(location = 1) in vec3 aCenter;
        layout(location = 2) in float aRadius;
        layout(location = 3) in vec3 aColor;
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        layout(location = 7) in uint aObjectId;
        flat out uint vObjectId;
        uniform usamplerBuffer uSelectionState;
        uniform int uSelectionCount;
        flat out uint vSelection;
        out vec3 vColor;
        out vec2 vCorner;
        flat out vec3 vWorldCenter;
        flat out float vWorldRadius;
        flat out vec4 vCenterClip;
        void main() {
            vec4 worldCenter = uModel * vec4(aCenter, 1.0);
            float modelScale = max(length(uModel[0].xyz),
                               max(length(uModel[1].xyz), length(uModel[2].xyz)));
            vec3 projectionRowX = vec3(
                uViewProjection[0][0], uViewProjection[1][0],
                uViewProjection[2][0]);
            vec3 projectionRowY = vec3(
                uViewProjection[0][1], uViewProjection[1][1],
                uViewProjection[2][1]);
            vec3 cameraBack = -normalize(vec3(
                uViewProjection[0][2], uViewProjection[1][2],
                uViewProjection[2][2]));
            // Asymmetric eye projections add a forward component to X/Y.
            // Remove it before using these rows as billboard axes/scales.
            projectionRowX -= cameraBack * dot(projectionRowX, cameraBack);
            projectionRowY -= cameraBack * dot(projectionRowY, cameraBack);
            vWorldRadius = aRadius * modelScale;
            vWorldCenter = worldCenter.xyz;
            vCenterClip = uViewProjection * worldCenter;
            gl_Position = vCenterClip;
            gl_Position.xy += aUnitPosition.xy * vWorldRadius *
                vec2(length(projectionRowX), length(projectionRowY));
            vCorner = aUnitPosition.xy;
            vColor = aColor;
            vObjectId = aObjectId;
            vSelection = gl_InstanceID < uSelectionCount
                ? texelFetch(uSelectionState, gl_InstanceID).r : 0u;
        }
    )GLSL";

    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec3 vColor;
        in vec2 vCorner;
        flat in vec3 vWorldCenter;
        flat in float vWorldRadius;
        flat in vec4 vCenterClip;
        uniform mat4 uViewProjection;
        uniform sampler2DShadow uShadowMap;
        uniform mat4 uLightViewProjection;
        uniform vec3 uLightDirection;
        uniform int uShadowsEnabled;
        uniform float uAlpha;
        uniform float uEmissive;
    flat in uint vSelection;
        layout(location = 0) out vec4 outColor;
        layout(location = 1) out uint outObjectId;
        flat in uint vObjectId;

        float shadowVisibility(vec3 worldPosition, vec3 normal) {
            if (uShadowsEnabled == 0) return 1.0;
            vec4 lightClip = uLightViewProjection * vec4(worldPosition, 1.0);
            vec3 projected = lightClip.xyz / lightClip.w;
            projected = projected * 0.5 + 0.5;
            if (projected.x <= 0.0 || projected.x >= 1.0 ||
                projected.y <= 0.0 || projected.y >= 1.0 ||
                projected.z <= 0.0 || projected.z >= 1.0) return 1.0;
            float facing = max(dot(normal, uLightDirection), 0.0);
            float bias = mix(0.0012, 0.00018, facing);
            float visibility = 0.0;
            const float texel = 1.0 / 2048.0;
            for (int y = -1; y <= 1; ++y) {
                for (int x = -1; x <= 1; ++x) {
                    visibility += texture(
                        uShadowMap,
                        vec3(projected.xy + vec2(x, y) * texel,
                             projected.z - bias));
                }
            }
            return visibility / 9.0;
        }

        void main() {
            float radiusSquared = dot(vCorner, vCorner);
            if (radiusSquared > 1.0) discard;
            vec3 projectionRowX = vec3(
                uViewProjection[0][0], uViewProjection[1][0],
                uViewProjection[2][0]);
            vec3 projectionRowY = vec3(
                uViewProjection[0][1], uViewProjection[1][1],
                uViewProjection[2][1]);
            vec3 projectionRowZ = vec3(
                uViewProjection[0][2], uViewProjection[1][2],
                uViewProjection[2][2]);
            vec3 cameraBack = -normalize(projectionRowZ);
            projectionRowX -= cameraBack * dot(projectionRowX, cameraBack);
            projectionRowY -= cameraBack * dot(projectionRowY, cameraBack);
            vec3 normal = normalize(
                normalize(projectionRowX) * vCorner.x +
                normalize(projectionRowY) * vCorner.y -
                normalize(projectionRowZ) * sqrt(1.0 - radiusSquared));
            vec3 worldPosition = vWorldCenter + normal * vWorldRadius;
            vec4 surfaceClip = uViewProjection * vec4(worldPosition, 1.0);
            gl_FragDepth = surfaceClip.z / surfaceClip.w * 0.5 + 0.5;
            float diffuse = max(dot(normal, uLightDirection), 0.0);
            float lighting = 0.20 + 0.90 * diffuse *
                shadowVisibility(worldPosition, normal);
            lighting = mix(lighting, 1.0, uEmissive);
            outObjectId = vObjectId;
            vec3 shaded = vColor * lighting;
        vec3 selectionColor = vSelection == 2u ? vec3(0.22, 1.0, 0.42) : vec3(1.0, 0.68, 0.12);
        outColor = vec4(mix(shaded, selectionColor, vSelection == 0u ? 0.0 : 0.48), uAlpha);
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, nadoc_vr::volumeFragment(fragmentSource, "vec3 worldPosition = vWorldCenter + normal * vWorldRadius;", "worldPosition").c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL sphere shader link failed: " + log);
}

GLuint makeCylinderProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aUnitPosition;
        layout(location = 5) in vec3 aUnitNormal;
        layout(location = 1) in vec3 aStart;
        layout(location = 2) in vec3 aEnd;
        layout(location = 3) in float aRadius;
        layout(location = 6) in float aEndRadius;
        layout(location = 4) in vec3 aColor;
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        layout(location = 7) in uint aObjectId;
        flat out uint vObjectId;
        uniform usamplerBuffer uSelectionState;
        uniform int uSelectionCount;
        flat out uint vSelection;
        out vec3 vColor;
        out vec3 vNormal;
        flat out int vTwoSided;
        out vec3 vWorldPosition;
        void main() {
            vec3 delta = aEnd - aStart;
            float lengthAlongAxis = length(delta);
            vec3 axis = lengthAlongAxis > 0.000001
                ? delta / lengthAlongAxis : vec3(0.0, 0.0, 1.0);
            vec3 helper = abs(axis.z) < 0.95 ? vec3(0.0, 0.0, 1.0)
                                             : vec3(0.0, 1.0, 0.0);
            vec3 basisX = normalize(cross(helper, axis));
            vec3 basisY = cross(axis, basisX);
            vec3 radial = basisX * aUnitPosition.x + basisY * aUnitPosition.y;
            vec3 localPosition = mix(aStart, aEnd, aUnitPosition.z)
                               + radial * mix(aRadius, aEndRadius < 0.0 ? aRadius : aEndRadius, aUnitPosition.z);
            vec3 localNormal = basisX * aUnitNormal.x
                             + basisY * aUnitNormal.y
                             + axis * aUnitNormal.z;
            if (aEndRadius >= 0.0 && abs(aUnitNormal.z) < 0.5)
                localNormal -= axis * ((aEndRadius-aRadius)/max(lengthAlongAxis, 0.000001));
            vec4 worldPosition = uModel * vec4(localPosition, 1.0);
            gl_Position = uViewProjection * worldPosition;
            vNormal = normalize(mat3(uModel) * localNormal);
            vTwoSided = 0;
            vWorldPosition = worldPosition.xyz;
            vColor = aColor;
            vObjectId = aObjectId;
            vSelection = gl_InstanceID < uSelectionCount
                ? texelFetch(uSelectionState, gl_InstanceID).r : 0u;
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, nadoc_vr::volumeFragment(kLitFragmentSource, "void main() {", "vWorldPosition").c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL cylinder shader link failed: " + log);
}

GLuint makeAtomisticBondProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 1) in vec3 aStart;
        layout(location = 2) in vec3 aEnd;
        layout(location = 4) in vec3 aColor;
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        layout(location = 7) in uint aObjectId;
        flat out uint vObjectId;
        uniform usamplerBuffer uSelectionState;
        uniform int uSelectionCount;
        flat out uint vSelection;
        out vec3 vColor;
        out vec3 vWorldPosition;
        void main() {
            vec3 position = gl_VertexID == 0 ? aStart : aEnd;
            gl_Position = uViewProjection * uModel * vec4(position, 1.0);
            vWorldPosition = (uModel * vec4(position,1)).xyz;
            vColor = aColor;
            vObjectId = aObjectId;
            vSelection = gl_InstanceID < uSelectionCount
                ? texelFetch(uSelectionState, gl_InstanceID).r : 0u;
        }
    )GLSL";
    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec3 vColor;
        in vec3 vWorldPosition;
        layout(location = 0) out vec4 outColor;
        layout(location = 1) out uint outObjectId;
        flat in uint vObjectId;
        void main() {
            outObjectId = vObjectId;
            outColor = vec4(vColor, 1.0);
        }
    )GLSL";
    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, nadoc_vr::volumeFragment(fragmentSource, "void main() {", "vWorldPosition").c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL atomistic bond program link failed: " + log);
}

GLuint makeBoxProgram() {
    static constexpr const char* vertexSource = R"GLSL(
        #version 330 core
        layout(location = 0) in vec3 aUnitPosition;
        layout(location = 5) in vec3 aUnitNormal;
        layout(location = 1) in vec3 aCenter;
        layout(location = 2) in vec3 aAxisX;
        layout(location = 3) in vec3 aAxisY;
        layout(location = 4) in vec3 aAxisZ;
        layout(location = 6) in vec3 aColor;
        layout(location = 8) in vec3 aNormal0;
        layout(location = 9) in vec3 aNormal1;
        layout(location = 10) in vec3 aNormal2;
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        layout(location = 7) in uint aObjectId;
        flat out uint vObjectId;
        uniform usamplerBuffer uSelectionState;
        uniform int uSelectionCount;
        flat out uint vSelection;
        out vec3 vColor;
        out vec3 vNormal;
        flat out int vTwoSided;
        out vec3 vWorldPosition;
        void main() {
            vec3 localPosition = aCenter
                + aAxisX * aUnitPosition.x
                + aAxisY * aUnitPosition.y
                + aAxisZ * aUnitPosition.z;
            vec3 localNormal = length(aNormal0) > 0.0
                ? normalize(aNormal0 * (-aUnitPosition.x-aUnitPosition.y)
                    + aNormal1 * (aUnitPosition.x+0.5) + aNormal2 * (aUnitPosition.y+0.5))
                : normalize(transpose(inverse(mat3(aAxisX,aAxisY,aAxisZ))) * aUnitNormal);
            vec4 worldPosition = uModel * vec4(localPosition, 1.0);
            gl_Position = uViewProjection * worldPosition;
            vNormal = normalize(mat3(uModel) * localNormal);
            vTwoSided = length(aNormal0) > 0.0 ? 1 : 0;
            vWorldPosition = worldPosition.xyz;
            vColor = aColor;
            vObjectId = aObjectId;
            vSelection = gl_InstanceID < uSelectionCount
                ? texelFetch(uSelectionState, gl_InstanceID).r : 0u;
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, nadoc_vr::volumeFragment(kLitFragmentSource,"void main() {","vWorldPosition").c_str());
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint ok = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (ok == GL_TRUE) return program;
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    std::string log(static_cast<size_t>(std::max(length, 1)), '\0');
    glGetProgramInfoLog(program, length, nullptr, log.data());
    glDeleteProgram(program);
    throw std::runtime_error("OpenGL box shader link failed: " + log);
}

class GzipStreamBuffer : public std::streambuf {
  public:
    explicit GzipStreamBuffer(const std::string& path)
        : file_(gzopen(path.c_str(), "rb")) {
        setg(buffer_.data(), buffer_.data(), buffer_.data());
    }

    ~GzipStreamBuffer() override {
        if (file_) gzclose(file_);
    }

    [[nodiscard]] bool isOpen() const { return file_ != nullptr; }
    [[nodiscard]] bool failed() const { return failed_; }

  protected:
    int_type underflow() override {
        if (gptr() < egptr()) return traits_type::to_int_type(*gptr());
        if (!file_) return traits_type::eof();
        const int count = gzread(
            file_, buffer_.data(), static_cast<unsigned int>(buffer_.size()));
        if (count <= 0) {
            int error = Z_OK;
            gzerror(file_, &error);
            failed_ = error != Z_OK && error != Z_STREAM_END;
            return traits_type::eof();
        }
        setg(buffer_.data(), buffer_.data(), buffer_.data() + count);
        return traits_type::to_int_type(*gptr());
    }

  private:
    gzFile file_ = nullptr;
    bool failed_ = false;
    std::array<char, 64 * 1024> buffer_{};
};

class GzipInputStream : public std::istream {
  public:
    explicit GzipInputStream(const std::string& path)
        : std::istream(nullptr), buffer_(path) {
        rdbuf(&buffer_);
        if (!buffer_.isOpen()) setstate(std::ios::badbit);
    }

    [[nodiscard]] bool compressionError() const { return buffer_.failed(); }

  private:
    GzipStreamBuffer buffer_;
};

SceneData loadScene(const std::string& path, std::optional<std::pair<glm::vec3, float>> fixedNormalization = std::nullopt,
                    const std::function<void(size_t)>& readProgress = {}) {
    const auto started = std::chrono::steady_clock::now();
    std::cout << "VR_METRIC event=process_progress phase=scene_load_start rss_mib="
              << currentResidentMiB() << std::endl;
    // zlib's transparent read mode accepts both gzip and ordinary scene files,
    // retaining legacy fixtures while production snapshots stay compact.
    GzipInputStream input(path);
    if (!input) throw std::runtime_error("Could not open scene snapshot: " + path);

    std::string magic;
    int version = 0;
    std::string initialRepresentation;
    std::string initialColoring;
    input >> magic >> version >> initialRepresentation >> initialColoring;
    if (magic != "NADOCVR" || (version < 4 || version > 16)) {
        throw std::runtime_error("Unsupported NADOC VR scene format");
    }

    SceneData scene;
    scene.initialRepresentation = representationFromName(initialRepresentation);
    scene.initialColoring = coloringFromName(initialColoring);
    RepresentationData* active = nullptr;
    size_t activeIndex = 0;
    size_t legacyIdentityIndex = 0;
    std::array<std::unordered_set<std::string>, kRepresentationCount> identities;
    std::array<std::unordered_set<std::string>, kRepresentationCount> aliasIdentities;
    std::array<std::unordered_set<std::string>, kRepresentationCount> handleTokens;
    std::array<std::unordered_set<std::string>, kRepresentationCount> transformIdentities;
    std::array<std::unordered_set<std::string>, kRepresentationCount> scopeHandleTokens;
    std::array<std::unordered_map<std::string, std::string>, kRepresentationCount>
        scopeHandleIds;
    std::array<std::unordered_set<std::string>, kRepresentationCount>
        declaredOwnerTokens;
    std::array<std::unordered_set<std::string>, kRepresentationCount> scopeIdentities;
    std::array<
        std::vector<std::tuple<std::string, std::string, std::string>>, kRepresentationCount>
        toolHandleKeys;
    size_t recordsRead = 0;
    auto readIdentity = [&](char recordType) {
        std::string identity;
        if (version >= 6) {
            input >> identity;
            if (identity.empty()) {
                throw std::runtime_error("VR primitive has an empty identity");
            }
            if (!identities[activeIndex].insert(identity).second) {
                throw std::runtime_error(
                    "Duplicate VR primitive identity: " + identity);
            }
        } else {
            identity = "legacy:" + std::string(1, recordType) + ":"
                     + std::to_string(legacyIdentityIndex++);
        }
        return identity;
    };
    char type = '\0';
    while (input >> type) {
        ++recordsRead;
        if(readProgress && recordsRead%2048==0)readProgress(recordsRead);
        if (recordsRead % 250000U == 0U) {
            const double milliseconds = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - started).count();
            std::cout << "VR_METRIC event=process_progress phase=scene_load"
                      << " records=" << recordsRead
                      << " elapsed_ms=" << milliseconds
                      << " rss_mib=" << currentResidentMiB() << std::endl;
        }
        if (type == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (type == 'O' && version >= 16) {
            if(active)throw std::runtime_error("Source frame must precede representations");
            for(int col=0;col<3;++col)for(int row=0;row<3;++row)input >> scene.sourceAxes[col][row];
            const auto gram=glm::transpose(scene.sourceAxes)*scene.sourceAxes;
            for(int col=0;col<3;++col)for(int row=0;row<3;++row)
                if(!std::isfinite(gram[col][row]) || std::abs(gram[col][row]-(col==row?1.F:0.F))>1e-5F)
                    throw std::runtime_error("Invalid source coordinate frame");
            if(std::abs(glm::determinant(scene.sourceAxes)-1.F)>1e-5F)
                throw std::runtime_error("Invalid source frame handedness");
        } else if (type == 'F' && version >= 13) {
            if (active) throw std::runtime_error("Extrude metadata must precede geometry");
            scene.extrudePlane.read(input);
        } else if (type == 'L' && version >= 16) {
            if (active) throw std::runtime_error("Lattice context must precede geometry");
            scene.latticeContext.read(input);
        } else if (type == 'G' && version >= 16) {
            if(active)throw std::runtime_error("Lattice occupancy must precede geometry");
            scene.latticeContext.readOccupancy(input);
        } else if (type == 'Q' && version >= 14) {
            std::string purpose;
            input >> purpose;
            if (active || scene.emptyAuthoring || purpose != "empty_authoring")
                throw std::runtime_error("Invalid empty authoring declaration");
            scene.emptyAuthoring = true;
        } else if (type == 'R') {
            std::string name;
            input >> name;
            activeIndex = static_cast<size_t>(representationFromName(name));
            active = &scene.representations[activeIndex];
        } else if (type == 'A' && version >= 8) {
            if (!active) {
                throw std::runtime_error(
                    "Owner aliases appear before representation block");
            }
            nadoc_vr::OwnerAliasEntry aliases;
            size_t count = 0;
            input >> aliases.identity >> count;
            if (aliases.identity.empty() || count == 0 || count > 8 ||
                !identities[activeIndex].contains(aliases.identity) ||
                !aliasIdentities[activeIndex]
                     .insert(aliases.identity).second) {
                throw std::runtime_error("Invalid VR primitive owner aliases");
            }
            aliases.tokens.resize(count);
            std::unordered_set<std::string> uniqueTokens;
            for (std::string& token : aliases.tokens) {
                std::string wireToken;
                input >> wireToken;
                if (version >= 12) {
                    const auto mapped = scopeHandleIds[activeIndex].find(
                        wireToken);
                    token = mapped == scopeHandleIds[activeIndex].end()
                        ? "" : mapped->second;
                } else {
                    token = std::move(wireToken);
                }
                if (token.empty() || token.size() > 2048 ||
                    !uniqueTokens.insert(token).second) {
                    throw std::runtime_error("Invalid VR primitive owner alias token");
                }
            }
            active->ownerAliases.push_back(std::move(aliases));
        } else if (type == 'K' && version >= 9) {
            if (!active) {
                throw std::runtime_error(
                    "Cluster handle appears before representation block");
            }
            OwnerHandle handle;
            input >> handle.token >> handle.center.x >> handle.center.y >> handle.center.z;
            if (handle.token.empty() || handle.token.size() > 2048 ||
                !handleTokens[activeIndex].insert(handle.token).second ||
                !scopeHandleTokens[activeIndex]
                     .insert(handle.token).second ||
                !std::isfinite(handle.center.x) || !std::isfinite(handle.center.y) ||
                !std::isfinite(handle.center.z)) {
                throw std::runtime_error("Invalid VR cluster handle");
            }
            active->ownerHandles.push_back(std::move(handle));
        } else if (type == 'J' && version >= 12) {
            if (!active) {
                throw std::runtime_error(
                    "Tool handle appears before representation block");
            }
            ToolHandle handle;
            input >> handle.id >> handle.token >> handle.kind
                  >> handle.center.x >> handle.center.y >> handle.center.z;
            const bool validKind = handle.kind == "base" || handle.kind == "end"
                || handle.kind == "domain" || handle.kind == "strand"
                || handle.kind == "crossover" || handle.kind == "atom" || handle.kind == "overhang";
            if (handle.id.empty() || handle.id.size() > 64 ||
                handle.token.empty() || handle.token.size() > 2048 || !validKind ||
                !scopeHandleIds[activeIndex]
                     .emplace(handle.id, handle.token).second ||
                !declaredOwnerTokens[activeIndex]
                     .insert(handle.token).second ||
                !scopeHandleTokens[activeIndex]
                     .insert(handle.token).second ||
                !std::isfinite(handle.center.x) || !std::isfinite(handle.center.y) ||
                !std::isfinite(handle.center.z)) {
                throw std::runtime_error("Invalid VR tool handle");
            }
            toolHandleKeys[activeIndex].emplace_back(
                handle.id, handle.token, handle.kind);
            active->toolHandles.push_back(std::move(handle));
        } else if (type == 'D' && version >= 12) {
            if (!active) {
                throw std::runtime_error(
                    "Owner dictionary appears before representation block");
            }
            std::string ownerId;
            std::string token;
            input >> ownerId >> token;
            if (ownerId.empty() || ownerId.size() > 64 || token.empty() ||
                token.size() > 2048 ||
                !scopeHandleIds[activeIndex]
                     .emplace(ownerId, token).second ||
                !declaredOwnerTokens[activeIndex]
                     .insert(token).second) {
                throw std::runtime_error("Invalid VR owner dictionary");
            }
        } else if (type == 'T' && version >= 10) {
            if (!active) {
                throw std::runtime_error(
                    "Transform ownership appears before representation block");
            }
            TransformOwnership ownership;
            size_t count = 0;
            input >> ownership.identity >> count;
            if (ownership.identity.empty() || count == 0 || count > 8 ||
                !identities[activeIndex].contains(ownership.identity) ||
                !transformIdentities[activeIndex]
                     .insert(ownership.identity).second) {
                throw std::runtime_error("Invalid VR transform ownership");
            }
            ownership.owners.resize(count);
            std::unordered_set<std::string> uniqueTokens;
            for (TransformOwner& owner : ownership.owners) {
                std::string wireOwner;
                input >> wireOwner >> owner.startWeight >> owner.endWeight;
                if (version >= 12) {
                    const auto mapped = scopeHandleIds[activeIndex].find(
                        wireOwner);
                    owner.token = mapped == scopeHandleIds[activeIndex].end()
                        ? "" : mapped->second;
                } else {
                    owner.token = std::move(wireOwner);
                }
                if (owner.token.empty() || owner.token.size() > 2048 ||
                    !handleTokens[activeIndex].contains(owner.token) ||
                    !uniqueTokens.insert(owner.token).second ||
                    !std::isfinite(owner.startWeight) ||
                    !std::isfinite(owner.endWeight) ||
                    owner.startWeight < 0.0F || owner.startWeight > 1.0F ||
                    owner.endWeight < 0.0F || owner.endWeight > 1.0F) {
                    throw std::runtime_error("Invalid VR transform owner");
                }
            }
            active->transformOwnership.push_back(std::move(ownership));
        } else if (type == 'W' && version >= 12) {
            if (!active) {
                throw std::runtime_error(
                    "Tool-scope ownership appears before representation block");
            }
            TransformOwnership ownership;
            size_t count = 0;
            input >> ownership.identity >> count;
            if (ownership.identity.empty() || count == 0 || count > 32 ||
                !identities[activeIndex].contains(ownership.identity) ||
                !scopeIdentities[activeIndex]
                     .insert(ownership.identity).second) {
                throw std::runtime_error("Invalid VR tool-scope ownership");
            }
            ownership.owners.resize(count);
            std::unordered_set<std::string> uniqueTokens;
            for (TransformOwner& owner : ownership.owners) {
                std::string wireOwner;
                input >> wireOwner >> owner.startWeight >> owner.endWeight;
                const auto mapped = scopeHandleIds[activeIndex].find(
                    wireOwner);
                owner.token = mapped == scopeHandleIds[activeIndex].end()
                    ? wireOwner : mapped->second;
                if (owner.token.empty() || owner.token.size() > 2048 ||
                    !scopeHandleTokens[activeIndex]
                         .contains(owner.token) ||
                    !uniqueTokens.insert(owner.token).second ||
                    !std::isfinite(owner.startWeight) ||
                    !std::isfinite(owner.endWeight) ||
                    owner.startWeight < 0.0F || owner.startWeight > 1.0F ||
                    owner.endWeight < 0.0F || owner.endWeight > 1.0F) {
                    throw std::runtime_error("Invalid VR tool-scope owner");
                }
            }
            active->toolScopeOwnership.push_back(std::move(ownership));
        } else if (type == 'P') {
            if (!active) throw std::runtime_error("Point appears before representation block");
            StyledPoint point;
            point.identity = readIdentity(type);
            input >> point.position.x >> point.position.y >> point.position.z >> point.size;
            for (glm::vec3& color : point.colors.values) {
                input >> color.r >> color.g >> color.b;
            }
            active->points.push_back(point);
        } else if (type == 'C' || type == 'H') {
            if (!active) throw std::runtime_error("Cylinder appears before representation block");
            StyledCylinder cylinder;
            cylinder.identity = readIdentity(type);
            input >> cylinder.start.x >> cylinder.start.y >> cylinder.start.z
                  >> cylinder.end.x >> cylinder.end.y >> cylinder.end.z
                  >> cylinder.radius;
            for (glm::vec3& color : cylinder.colors.values) {
                input >> color.r >> color.g >> color.b;
            }
            if (type == 'H') active->halfCylinders.push_back(cylinder);
            else active->cylinders.push_back(cylinder);
        } else if (type == 'N' && version >= 15) {
            std::string identity; input >> identity;
            if (!active || active->boxes.empty() || active->boxes.back().identity != identity)
                throw std::runtime_error("Invalid triangle normal annotation");
            for (auto& n : active->boxes.back().normals) input >> n.x >> n.y >> n.z;
        } else if (type == 'U' && version >= 15) {
            std::string identity; float radius; input >> identity >> radius;
            if (!active || active->cylinders.empty() || active->cylinders.back().identity != identity || !(radius > 0))
                throw std::runtime_error("Invalid tapered cylinder annotation");
            active->cylinders.back().endRadius = radius;
        } else if (type == 'V' && version >= 15) {
            std::string identity; float radius;
            input >> identity >> radius;
            if (!active || active->points.empty() || active->points.back().identity != identity || !(radius > 0))
                throw std::runtime_error("Invalid VDW radius annotation");
            active->points.back().vdwSize = radius;
        } else if (type == 'B') {
            if (!active) throw std::runtime_error("Box appears before representation block");
            StyledBox box;
            box.identity = readIdentity(type);
            input >> box.center.x >> box.center.y >> box.center.z
                  >> box.axisX.x >> box.axisX.y >> box.axisX.z
                  >> box.axisY.x >> box.axisY.y >> box.axisY.z
                  >> box.axisZ.x >> box.axisZ.y >> box.axisZ.z;
            for (glm::vec3& color : box.colors.values) {
                input >> color.r >> color.g >> color.b;
            }
            active->boxes.push_back(box);
        } else {
            throw std::runtime_error(std::string("Unknown scene record: ") + type);
        }
        if (!input) throw std::runtime_error("Malformed NADOC VR scene snapshot");
    }
    if (input.compressionError()) {
        throw std::runtime_error("Corrupt compressed NADOC VR scene snapshot");
    }
    const auto noPrimitives = [](const RepresentationData& rep) {
        return rep.points.empty() && rep.cylinders.empty()
            && rep.halfCylinders.empty() && rep.boxes.empty();
    };
    const bool empty = std::all_of(scene.representations.begin(), scene.representations.end(), noPrimitives);
    if (scene.emptyAuthoring) {
        scene.available.fill(true);
        if (!empty) throw std::runtime_error("Empty authoring scene contains geometry");
        scene.normalizationCenter = fixedNormalization ? fixedNormalization->first : glm::vec3(0.0F);
        scene.normalizationScale = fixedNormalization ? fixedNormalization->second : kViewSizeMeters / 100.0F; // 100 nm initial working extent.
        std::cout << "VR_METRIC event=process_progress phase=scene_load_end"
                  << " records=" << recordsRead << " empty_authoring=true"
                  << " elapsed_ms=" << std::chrono::duration<double, std::milli>(
                      std::chrono::steady_clock::now() - started).count()
                  << " rss_mib=" << currentResidentMiB() << std::endl;
        return scene; // No synthetic axes/part primitives in an empty document.
    }
    if (empty) throw std::runtime_error("The scene snapshot contains no visible geometry");
    for (size_t i=0; i<kRepresentationCount; ++i) {
        const auto rep=static_cast<Representation>(i);
        const auto& source=scene.representations[representationSourceIndex(rep)];
        scene.available[i]=!noPrimitives(source);
        if (rep==Representation::vdw) scene.available[i]=!source.points.empty() && std::all_of(
            source.points.begin(),source.points.end(),[](const auto& point){return point.vdwSize>0;});
    }



    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    auto include = [&](const glm::vec3& position) {
        lo = glm::min(lo, position);
        hi = glm::max(hi, position);
    };
    for (const RepresentationData& rep : scene.representations) {
        for (const StyledPoint& point : rep.points) include(point.position);
        for (const StyledCylinder& cylinder : rep.cylinders) {
            include(cylinder.start);
            include(cylinder.end);
        }
        for (const StyledCylinder& cylinder : rep.halfCylinders) {
            include(cylinder.start);
            include(cylinder.end);
        }
        for (const StyledBox& box : rep.boxes) {
            nadoc_vr::includeMeshBounds(box, include);
        }
    }
    const glm::vec3 center = fixedNormalization ? fixedNormalization->first : (lo + hi) * 0.5F;
    const glm::vec3 extent = hi - lo;
    const float maxExtent = std::max({extent.x, extent.y, extent.z, 1.0e-6F});
    const float scale = fixedNormalization ? fixedNormalization->second : kViewSizeMeters / maxExtent;
    scene.normalizationCenter = center;
    scene.normalizationScale = scale;
    auto normalize = [&](RepresentationData& rep, bool appendViewerAxes) {
        for (StyledPoint& point : rep.points) {
            point.position = (point.position - center) * scale;
            point.position.z -= kViewDistanceMeters;
            point.size *= scale;
            point.vdwSize *= scale;
        }
        for (StyledCylinder& cylinder : rep.cylinders) {
            cylinder.start = (cylinder.start - center) * scale;
            cylinder.end = (cylinder.end - center) * scale;
            cylinder.start.z -= kViewDistanceMeters;
            cylinder.end.z -= kViewDistanceMeters;
            cylinder.radius *= scale;
            if (cylinder.endRadius >= 0) cylinder.endRadius *= scale;
        }
        for (StyledCylinder& cylinder : rep.halfCylinders) {
            cylinder.start = (cylinder.start - center) * scale;
            cylinder.end = (cylinder.end - center) * scale;
            cylinder.start.z -= kViewDistanceMeters;
            cylinder.end.z -= kViewDistanceMeters;
            cylinder.radius *= scale;
            if (cylinder.endRadius >= 0) cylinder.endRadius *= scale;
        }
        for (StyledBox& box : rep.boxes) {
            box.center = (box.center - center) * scale;
            box.center.z -= kViewDistanceMeters;
            box.axisX *= scale;
            box.axisY *= scale;
            box.axisZ *= scale;
        }
        for (OwnerHandle& handle : rep.ownerHandles) {
            handle.center = (handle.center - center) * scale;
            handle.center.z -= kViewDistanceMeters;
        }
        for (ToolHandle& handle : rep.toolHandles) {
            handle.center = (handle.center - center) * scale;
            handle.center.z -= kViewDistanceMeters;
        }

        if (!appendViewerAxes) return;
        // Desktop AxesHelper(4): model origin and four-nanometre source axes,
        // carried through exactly the same rotation/normalization as the part.
        const glm::vec3 origin = -center * scale + glm::vec3(0,0,-kViewDistanceMeters);
        auto addAxis = [&](const char* name, glm::vec3 delta, glm::vec3 color) {
            ColorSet colors;
            colors.values.fill(color);
            rep.cylinders.push_back(
                StyledCylinder{name, origin, origin + scene.sourceAxes * delta * (4.F * scale), 0.04F * scale, colors});
        };
        addAxis("viewer:axis:x", {1, 0, 0}, {1.0F, 0.25F, 0.25F});
        addAxis("viewer:axis:y", {0, 1, 0}, {0.25F, 1.0F, 0.35F});
        addAxis("viewer:axis:z", {0, 0, 1}, {0.3F, 0.55F, 1.0F});
    };
    for (size_t index = 0; index < scene.representations.size(); ++index) {
        normalize(scene.representations[index], true);

    }
    for(size_t i=0;i<kRepresentationCount;++i)if(representationSourceIndex(static_cast<Representation>(i))==i)
        scene.cpuBytes[i]=representationCpuBytes(scene.representations[i]);
    std::array<std::shared_ptr<SourceIndex>,kRepresentationCount> indices{};
    for(size_t i=0;i<kRepresentationCount;++i)if(scene.available[i]) {
        const auto source=representationSourceIndex(static_cast<Representation>(i));
        if(!indices[source]){indices[source]=std::make_shared<SourceIndex>();indices[source]->rebuild(scene.representations[source]);}
        scene.prepared[i]=prepareStaticRepresentation(scene.representations[source],static_cast<Representation>(i),indices[source]);
        scene.cpuBytes[source]+=scene.prepared[i]->bytes()+scene.prepared[i]->highlightIndexBytes()+16*(scene.prepared[i]->records[0].size()+scene.prepared[i]->records[1].size()+scene.prepared[i]->records[2].size()+scene.prepared[i]->records[3].size());
    }
    scene.preparedAtomisticSharedGeometry = atomisticCylindersEquivalent(scene);
    const double milliseconds = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    std::cout << "VR_METRIC event=process_progress phase=scene_load_end"
              << " records=" << recordsRead
              << " elapsed_ms=" << milliseconds
              << " rss_mib=" << currentResidentMiB() << std::endl;
    return scene;
}

glm::mat4 projectionFromFov(const XrFovf& fov, float nearPlane, float farPlane) {
    const float left = std::tan(fov.angleLeft);
    const float right = std::tan(fov.angleRight);
    const float down = std::tan(fov.angleDown);
    const float up = std::tan(fov.angleUp);
    const float width = right - left;
    const float height = up - down;

    glm::mat4 projection(0.0F);
    projection[0][0] = 2.0F / width;
    projection[1][1] = 2.0F / height;
    projection[2][0] = (right + left) / width;
    projection[2][1] = (up + down) / height;
    projection[2][2] = -(farPlane + nearPlane) / (farPlane - nearPlane);
    projection[2][3] = -1.0F;
    projection[3][2] = -(2.0F * farPlane * nearPlane) / (farPlane - nearPlane);
    return projection;
}

glm::mat4 viewFromPose(const XrPosef& pose) {
    const glm::quat orientation(
        pose.orientation.w,
        pose.orientation.x,
        pose.orientation.y,
        pose.orientation.z);
    const glm::vec3 position(pose.position.x, pose.position.y, pose.position.z);
    return glm::inverse(glm::translate(glm::mat4(1.0F), position) * glm::toMat4(orientation));
}

nadoc_vr::HandPose handPoseFromXr(const XrPosef& pose) {
    nadoc_vr::HandPose result;
    result.valid = true;
    result.position = {pose.position.x, pose.position.y, pose.position.z};
    result.orientation = {
        pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z};
    return result;
}


#include "scene_retirement.hpp"
#include "staged_representation.hpp"
#include "loading_points.hpp"
#include "bend_points.hpp"

class GlScene {
    LoadingPoints loadingPoints_;
    mutable BendPoints bendPoints_;
    std::optional<nadoc_vr::BendArc> bendPointArc_;
    bool twistPointMode_=false;
    std::vector<std::string> movePointOwners_;
    glm::mat4 movePointTransform_{1};
  public:
#include "prepared_style_controller.inc"
#include "staged_scene_refresh.inc"
    explicit GlScene(SceneData scene, bool objectIds = false, const std::deque<std::string>& priorIdentities = {},
                     const std::function<void(size_t)>& preparing = {}, bool prewarm = true, bool initializeStyle = true)
        : scene_(std::move(scene)), objectIdsEnabled_(objectIds) {
        if (!priorIdentities.empty()) {
            objectIdentities_ = priorIdentities;
            for (size_t i = 1; i < objectIdentities_.size(); ++i) objectIdBucket(objectIdentities_[i]).emplace(objectIdentities_[i], static_cast<uint32_t>(i));
        }
        atomisticSharedGeometry_ = scene_.preparedAtomisticSharedGeometry
            ? *scene_.preparedAtomisticSharedGeometry : atomisticCylindersEquivalent(scene_);
        program_ = makeProgram();
        viewProjection_ = glGetUniformLocation(program_, "uViewProjection");
        upload({}, lineVao_, lineVbo_);
        upload({}, guideVao_, guideVbo_, GL_DYNAMIC_DRAW);
        uploadSpheres();
        uploadCylinders();
        uploadHalfCylinders();
        uploadBoxes();
        auto bindIds = [](GLuint vao, GLuint buffer, GLsizei stride, size_t offset) {
            glBindVertexArray(vao);
            glBindBuffer(GL_ARRAY_BUFFER, buffer);
            glEnableVertexAttribArray(7);
            glVertexAttribIPointer(7, 1, GL_UNSIGNED_INT, stride,
                                   reinterpret_cast<void*>(offset));
            glVertexAttribDivisor(7, 1);
        };
        bindIds(sphereVao_, sphereInstanceVbo_, sizeof(Vertex), offsetof(Vertex, objectId));
        bindIds(cylinderVao_, cylinderInstanceVbo_, sizeof(Cylinder), offsetof(Cylinder, objectId));
        bindIds(atomisticBondVao_, cylinderInstanceVbo_, sizeof(Cylinder), offsetof(Cylinder, objectId));
        bindIds(halfCylinderVao_, halfCylinderInstanceVbo_, sizeof(Cylinder), offsetof(Cylinder, objectId));
        bindIds(boxVao_, boxInstanceVbo_, sizeof(Box), offsetof(Box, objectId));
        glBindVertexArray(0);
        initializeShadowMap();
        // Prepare each static style before the first interactive frame.
        for (auto [vao, buffer] : {std::pair{cylinderVao_,cylinderInstanceVbo_},
             std::pair{cylinderGlowVao_,cylinderGlowInstanceVbo_},
             std::pair{halfCylinderVao_,halfCylinderInstanceVbo_},
             std::pair{halfCylinderGlowVao_,halfCylinderGlowInstanceVbo_}})
            nadoc_vr::bindInstanceAttribute(vao, buffer, 6, 1, sizeof(Cylinder), offsetof(Cylinder,endRadius));
        for (auto [vao, buffer] : {std::pair{boxVao_,boxInstanceVbo_}, std::pair{boxGlowVao_,boxGlowInstanceVbo_}})
            for (int i=0; i<3; ++i)
                nadoc_vr::bindInstanceAttribute(vao, buffer, 8+i, 3, sizeof(Box), offsetof(Box,normals)+i*sizeof(glm::vec3));
        for (size_t i = 0; prewarm && i < kRepresentationCount; ++i) {
            if (preparing) preparing(i);
            if (scene_.available[i]) setStyle(static_cast<Representation>(i), scene_.initialColoring);
        }
        if (initializeStyle) setStyle(scene_.initialRepresentation, scene_.initialColoring);
        else { representation_=scene_.initialRepresentation; coloring_=scene_.initialColoring; }
    }

    void retireSource(SceneRetirement& retired) { retired.retire(std::move(scene_)); }

    const std::deque<std::string>& objectIdentities() const { return objectIdentities_; }

    void setVisualization(const nadoc_vr::VisualizationSnapshot& snapshot) {
        nadoc_vr::CalculationScope auditScope("setVisualization");
        bool samePositions = visualizationPositions_.size() == snapshot.points.size();
        bool snapshotHasColors = false;
        bool snapshotHasSlabs = false;
        if (samePositions) {
            for (const auto& point : snapshot.points) {
                const auto previous = visualizationPositions_.find(point.ownerToken);
                if (previous == visualizationPositions_.end() ||
                    previous->second != point.position) {
                    samePositions = false;
                    break;
                }
                snapshotHasColors = snapshotHasColors || point.hasColor;
                snapshotHasSlabs = snapshotHasSlabs || point.hasSlabFrame;
            }
        } else {
            for (const auto& point : snapshot.points) {
                snapshotHasColors = snapshotHasColors || point.hasColor;
                snapshotHasSlabs = snapshotHasSlabs || point.hasSlabFrame;
            }
        }
        if (!samePositions || snapshotHasColors || snapshotHasSlabs ||
            !visualizationColors_.empty() || !visualizationSlabFrames_.empty()) {
            ++visualizationRevision_;
        }
        visualizationMode_ = snapshot.mode;
        visualizationPositions_.clear();
        visualizationColors_.clear();
        visualizationSlabFrames_.clear();
        visualizationAtomTokens_.clear();
        visualizationCoordinateIndex_.clear();
        visualizationCoordinateTokens_.clear();
        visualizationCoordinatePositions_.clear();
        visualizationDeltasValid_ = false;
        visualizationPositions_.reserve(snapshot.points.size());
        visualizationColors_.reserve(snapshot.points.size());
        visualizationCoordinateTokens_.reserve(snapshot.points.size());
        for (size_t pointIndex = 0; pointIndex < snapshot.points.size(); ++pointIndex) {
            const auto& point = snapshot.points[pointIndex];
            visualizationPositions_.emplace(point.ownerToken, point.position);
            visualizationCoordinateIndex_.emplace(point.ownerToken, pointIndex);
            visualizationCoordinateTokens_.push_back(point.ownerToken);
            if (point.hasColor) {
                visualizationColors_.emplace(point.ownerToken, point.color);
            }
            if (point.hasSlabFrame) {
                visualizationSlabFrames_.emplace(point.ownerToken, point);
            }
            if (point.ownerToken.starts_with("%5B%22atom%22")) {
                visualizationAtomTokens_.insert(point.ownerToken);
            }
        }
        visualizationCoordinatePositions_.reserve(visualizationCoordinateTokens_.size());
        for (const std::string& token : visualizationCoordinateTokens_) {
            visualizationCoordinatePositions_.push_back(
                &visualizationPositions_.find(token)->second);
        }
        // Legacy fixtures can use unencoded semantic tokens. Production v12 atom
        // tokens have the prefix above, avoiding a scan through every natural
        // representation (hundreds of thousands of handles for a full origami).
        if (!visualizationPositions_.empty() && visualizationAtomTokens_.empty()) {
            for (const RepresentationData& source : scene_.representations) {
                for (const ToolHandle& handle : source.toolHandles) {
                    if (handle.kind == "atom" &&
                        visualizationPositions_.contains(handle.token)) {
                        visualizationAtomTokens_.insert(handle.token);
                    }
                }
            }
        }
        if (!snapshot.representation.empty() && !snapshot.coloring.empty()) {
            setStyle(
                representationFromName(snapshot.representation),
                coloringFromName(snapshot.coloring));
        } else {
            // Backward compatibility for an already-running v1/v2 publisher.
            setStyle(representation_, coloring_);
        }
    }

    /** Update resident atom instances from a stable-order coordinate-only frame.
     * This deliberately avoids semantic-map reconstruction and style/color work. */
    bool updateAtomCoordinates(
        const std::vector<std::array<float, 3>>& coordinates,
        double* cpuMilliseconds = nullptr, double* uploadMilliseconds = nullptr) {
        nadoc_vr::CalculationScope auditScope("updateAtomCoordinates");
        const auto started = std::chrono::steady_clock::now();
        if ((representation_ != Representation::ballstick &&
             representation_ != Representation::stick && representation_ != Representation::vdw) ||
            coordinates.size() != visualizationCoordinateTokens_.size() ||
            coordinates.empty() || (atomisticCylinderInstances_.empty() && atomisticSphereInstances_.empty()) ||
            atomisticSphereCoordinateIndices_.size() != atomisticSphereInstances_.size() ||
            atomisticCylinderCoordinateIndices_.size() !=
                atomisticCylinderInstances_.size() ||
            !toolCommittedToken_.empty() || !toolPreviewToken_.empty() || previewGeometry_.active()) {
            return false;
        }
        normalizedCoordinateScratch_.resize(coordinates.size());
        for (size_t index = 0; index < coordinates.size(); ++index) {
            const auto& source = coordinates[index];
            glm::vec3 position(source[0], source[1], source[2]);
            position = (position - scene_.normalizationCenter) * scene_.normalizationScale;
            position.z -= kViewDistanceMeters;
            normalizedCoordinateScratch_[index] = position;
            *visualizationCoordinatePositions_[index] =
                glm::vec3(source[0], source[1], source[2]);
        }
        for (size_t index = 0; index < atomisticSphereInstances_.size(); ++index) {
            const int32_t coordinate = atomisticSphereCoordinateIndices_[index];
            if (coordinate >= 0) {
                atomisticSphereInstances_[index].position =
                    normalizedCoordinateScratch_[static_cast<size_t>(coordinate)];
            }
        }
        for (size_t index = 0; index < atomisticCylinderInstances_.size(); ++index) {
            const auto coordinate = atomisticCylinderCoordinateIndices_[index];
            if (coordinate[0] >= 0) {
                atomisticCylinderInstances_[index].start =
                    normalizedCoordinateScratch_[static_cast<size_t>(coordinate[0])];
            }
            if (coordinate[1] >= 0) {
                atomisticCylinderInstances_[index].end =
                    normalizedCoordinateScratch_[static_cast<size_t>(coordinate[1])];
            }
        }
        visualizationDeltasValid_ = false;
        const auto prepared = std::chrono::steady_clock::now();
        glBindBuffer(GL_ARRAY_BUFFER, sphereInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
            static_cast<GLsizeiptr>(atomisticSphereInstances_.size() * sizeof(Vertex)),
            nullptr, GL_STREAM_DRAW);
        glBufferSubData(GL_ARRAY_BUFFER, 0,
            static_cast<GLsizeiptr>(atomisticSphereInstances_.size() * sizeof(Vertex)),
            atomisticSphereInstances_.data());
        glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
            static_cast<GLsizeiptr>(atomisticCylinderInstances_.size() * sizeof(Cylinder)),
            nullptr, GL_STREAM_DRAW);
        glBufferSubData(GL_ARRAY_BUFFER, 0,
            static_cast<GLsizeiptr>(atomisticCylinderInstances_.size() * sizeof(Cylinder)),
            atomisticCylinderInstances_.data());
        sphereCount_ = representation_ != Representation::stick
            ? static_cast<GLsizei>(atomisticSphereInstances_.size()) : 0;
        cylinderCount_ = static_cast<GLsizei>(atomisticCylinderInstances_.size());
        const auto uploaded = std::chrono::steady_clock::now();
        if (cpuMilliseconds) {
            *cpuMilliseconds = std::chrono::duration<double, std::milli>(
                prepared - started).count();
        }
        if (uploadMilliseconds) {
            *uploadMilliseconds = std::chrono::duration<double, std::milli>(
                uploaded - prepared).count();
        }
        return true;
    }

    [[nodiscard]] const std::string& visualizationMode() const {
        return visualizationMode_;
    }

    void setToolPreview(
        const std::vector<std::string>& ownerTokens, const glm::mat4& transform) {
        nadoc_vr::CalculationScope auditScope("setToolPreview");
        std::string token;
        const RepresentationData& source = currentSource();
        for (const std::string& candidate : ownerTokens) {
            if (previewGeometry_.active() && candidate == previewGeometry_.token) {
                token = candidate;
                break;
            }
            const auto& ownershipRecords = source.toolScopeOwnership.empty()
                ? source.transformOwnership : source.toolScopeOwnership;
            const bool explicitOwner = std::any_of(
                ownershipRecords.begin(), ownershipRecords.end(),
                [&](const TransformOwnership& ownership) {
                    return std::any_of(
                        ownership.owners.begin(), ownership.owners.end(),
                        [&](const TransformOwner& owner) { return owner.token == candidate; });
                });
            const bool implicitOwner = std::any_of(
                source.ownerAliases.begin(), source.ownerAliases.end(),
                [&](const nadoc_vr::OwnerAliasEntry& entry) {
                    return std::find(entry.tokens.begin(), entry.tokens.end(), candidate)
                        != entry.tokens.end();
                });
            if (explicitOwner || implicitOwner) {
                token = candidate;
                break;
            }
        }
        bool sameTransform = true;
        for (size_t column = 0; column < 4 && sameTransform; ++column) {
            for (size_t row = 0; row < 4; ++row) {
                if (std::abs(toolPreviewTransform_[column][row] - transform[column][row])
                    > 1.0e-6F) {
                    sameTransform = false;
                    break;
                }
            }
        }
        if (token == toolPreviewToken_ && sameTransform) return;
        if (!token.empty()) motionDetail_.changed();
        toolPreviewToken_ = std::move(token);
        toolPreviewTransform_ = transform;
        const auto started = std::chrono::steady_clock::now();
        if (!previewGeometry_.active()) prepareResidentPreview();
        if (previewGeometry_.active() &&
            (toolPreviewToken_.empty() || toolPreviewToken_ == previewGeometry_.token)) {
            applyPackedPreview(toolPreviewToken_.empty() ? glm::mat4(1) : transform);
        } else {
            setStyle(representation_, coloring_);
        }
        const double milliseconds = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - started).count();
        if (!toolPreviewToken_.empty() && previewTiming_.add(milliseconds)) {
            const auto summary = previewTiming_.takeSummary();
            if (summary) {
                std::cout << "VR preview upload ms (" << summary->samples
                          << " samples): p50=" << summary->p50Milliseconds
                          << " p95=" << summary->p95Milliseconds
                          << " p99=" << summary->p99Milliseconds
                          << " max=" << summary->maxMilliseconds << std::endl;
            }
        }
    }

    [[nodiscard]] bool acceptToolCommit() {
        // Materialize detailed geometry once, only after a successful commit.
        if (!movePointOwners_.empty()) {
            setToolPreview(movePointOwners_,movePointTransform_);
            movePointOwners_.clear();
        }
        if (toolPreviewToken_.empty()) return false;
        const bool retainPacked = toolCommittedToken_.empty() && previewGeometry_.active() &&
            previewGeometry_.token == toolPreviewToken_;
        if (!toolCommittedToken_.empty()) bakeCommittedLayer();
        toolCommittedToken_ = std::move(toolPreviewToken_);
        toolCommittedTransform_ = toolPreviewTransform_;
        updateCommittedHandleOffsets();
        toolPreviewToken_.clear();
        toolPreviewTransform_ = glm::mat4(1.0F);
        // The displayed packed instances already are the accepted pose. Retain
        // their identity, colors and GPU buffers, plus exact pre-commit values
        // for Undo (fractional endpoint weights are not generally invertible).
        if (retainPacked) previewGeometry_.commit();
        else setStyle(representation_, coloring_);
        return true;
    }

    [[nodiscard]] bool acceptToolUndo() {
        if (toolCommittedToken_.empty()) return false;
        const bool retainPacked = previewGeometry_.hasCommittedBaseline &&
            previewGeometry_.token == toolCommittedToken_;
        toolCommittedToken_.clear();
        toolCommittedTransform_ = glm::mat4(1.0F);
        committedHandleOffsets_.clear();
        if (retainPacked) {
            previewGeometry_.undoCommit();
            applyPackedPreview(toolPreviewToken_.empty() ? glm::mat4(1.0F) : toolPreviewTransform_);
        } else setStyle(representation_, coloring_);
        return true;
    }

    [[nodiscard]] glm::mat4 viewSpaceToolTransform(
        const glm::mat4& normalizedTransform) const {
        return nadoc_vr::normalizedToSourceTransform(
            normalizedTransform, scene_.normalizationCenter,
            scene_.normalizationScale, {0.0F, 0.0F, -kViewDistanceMeters});
    }

#include "static_snap_highlights.inc"
#include "selection_tint.inc"
#include "prepared_preview.inc"

    void setSelectionHighlights(
        const std::vector<std::string>& snapOwnerTokens,
        const std::vector<std::string>& snapDirectIdentities,
        const std::vector<std::string>& selectedOwnerTokens,
        const std::vector<std::string>& selectedDirectIdentities, bool applyStyle = true) {
        nadoc_vr::CalculationScope auditScope("setSelectionHighlights");
        const std::unordered_set<std::string> nextSnapTokens(
            snapOwnerTokens.begin(), snapOwnerTokens.end());
        const std::unordered_set<std::string> nextSnapIdentities(
            snapDirectIdentities.begin(), snapDirectIdentities.end());
        const std::unordered_set<std::string> nextSelectedTokens(
            selectedOwnerTokens.begin(), selectedOwnerTokens.end());
        const std::unordered_set<std::string> nextSelectedIdentities(
            selectedDirectIdentities.begin(), selectedDirectIdentities.end());
        if (nextSnapTokens == snapHighlightOwnerTokens_ &&
            nextSnapIdentities == snapHighlightIdentities_ &&
            nextSelectedTokens == selectedHighlightOwnerTokens_ &&
            nextSelectedIdentities == selectedHighlightIdentities_) {
            return;
        }
        const bool selectionUnchanged = nextSelectedTokens == selectedHighlightOwnerTokens_ &&
            nextSelectedIdentities == selectedHighlightIdentities_;
        const auto priorSnapTokens=std::move(snapHighlightOwnerTokens_);
        const auto priorSnapIdentities=std::move(snapHighlightIdentities_);
        snapHighlightOwnerTokens_ = nextSnapTokens;
        snapHighlightIdentities_ = nextSnapIdentities;
        selectedHighlightOwnerTokens_ = nextSelectedTokens;
        selectedHighlightIdentities_ = nextSelectedIdentities;
        selectionTintDirty_ = true;
        if (selectionTintEnabled()) {
            if (!selectionUnchanged && toolPreviewToken_.empty() && toolCommittedToken_.empty())
                previewGeometry_.clear();
            return;
        }
        if (applyStyle && !updateStaticSnapHighlights(selectionUnchanged, priorSnapTokens, priorSnapIdentities)) setStyle(representation_, coloring_);
    }

    void installRepresentation(SceneData incoming) {
        previewGeometry_.clear();
        // Full remains the normalization/presentation anchor. Replace only blocks
        // delivered in this request; retain previously loaded representations.
        for(size_t i=0;i<kRepresentationCount;++i) {
            // loadScene adds reference axes to Full even in a selective export.
            // Availability is derived before those axes: only real source blocks
            // may replace resident geometry. Otherwise Beads/Full become blank.
            if(!incoming.available[i])continue;
            auto& source=incoming.representations[i];
            if(source.points.empty() && source.cylinders.empty() && source.halfCylinders.empty() && source.boxes.empty())continue;
            scene_.cpuBytes[i]=incoming.cpuBytes[i];
            scene_.representations[i]=std::move(source);
        }
        for(size_t i=0;i<kRepresentationCount;++i)scene_.available[i]=scene_.available[i]||incoming.available[i];
        for(size_t i=0;i<kRepresentationCount;++i)if(incoming.available[i]) {
            representationBuffers_.invalidate(i);
            residentStyles_[i].reset();
            scene_.prepared[i]=std::move(incoming.prepared[i]);
            staticSourceIndices_.erase(&scene_.representations[i]);
        }
        displayedSourceValid_=sourceIndexValid_=false;visualizationDeltasValid_=false;
        atomisticBuffersResident_=false;
        atomisticSharedGeometry_=false; // Independent static buffers; no full-scene comparison on the XR thread.
    }

    bool supportsRepresentation(Representation representation) const {
        return scene_.available.at(static_cast<size_t>(representation));
    }
    void applyPackedPreview(const glm::mat4& transform) {
        nadoc_vr::CalculationScope auditScope("applyPackedPreview");
        { nadoc_vr::CalculationScope scope("previewTransform");
          previewGeometry_.apply(transform); }
        { nadoc_vr::CalculationScope scope("previewUpload");
        previewGeometry_.points.upload(sphereInstanceVbo_);
        previewGeometry_.glowPoints.upload(sphereGlowInstanceVbo_);
        previewGeometry_.cylinders.upload(cylinderInstanceVbo_);
        previewGeometry_.glowCylinders.upload(cylinderGlowInstanceVbo_);
        previewGeometry_.halves.upload(halfCylinderInstanceVbo_);
        previewGeometry_.glowHalves.upload(halfCylinderGlowInstanceVbo_);
        previewGeometry_.boxes.upload(boxInstanceVbo_);
        previewGeometry_.glowBoxes.upload(boxGlowInstanceVbo_); }
        { nadoc_vr::CalculationScope scope("previewBounds");
          previewGeometry_.bounds(localCenter_, localRadius_); }
    }
#ifdef NADOC_SCRYWRITE_TESTING
    bool residentPreviewForTest = true;
    void disablePackedPreviewForTest() { packedPreviewEnabled_ = false; previewGeometry_.clear(); }
    bool hasPackedPreviewForTest() const { return previewGeometry_.active(); }
    bool volumeGuardsEnabledForTest = true;
    size_t styleApplicationsForTest=0,volumeUploadsForTest=0;
#endif
    void setStyle(Representation representation, Coloring coloring) {
        nadoc_vr::CalculationScope auditScope("setStyle");
#ifdef NADOC_SCRYWRITE_TESTING
        ++styleApplicationsForTest;
#endif
        previewGeometry_.clear();
        selectionTintDirty_ = true;
        dynamicSelectionRows_ = false;
        for (auto& rows : selectionRows_) rows.clear();
        if (!supportsRepresentation(representation)) throw std::runtime_error("Representation missing from scene snapshot: " + std::string(representationName(representation)));
        const auto styleStarted = std::chrono::steady_clock::now();
        // Coarse helix cylinders have domain-level ownership and cannot represent
        // independent per-base MD motion. Keep an active desktop visualization in
        // one of the base-resolved representations instead of showing a stale pose.
        if (!visualizationPositions_.empty() &&
            representation == Representation::cylinders) {
            representation = Representation::full;
        }
        const bool cacheable = visualizationPositions_.empty() && visualizationColors_.empty() &&
            visualizationSlabFrames_.empty() &&
            toolPreviewToken_.empty() && toolCommittedToken_.empty() &&
            (selectionTintEnabled() || (snapHighlightOwnerTokens_.empty() && snapHighlightIdentities_.empty() &&
            selectedHighlightOwnerTokens_.empty() && selectedHighlightIdentities_.empty()));
        if(deferStyles_ && cacheable && !renderingVolumes_ && scene_.prepared[static_cast<size_t>(representation)]) {
            requestPreparedStyle(representation,coloring);return;
        }
        cancelPreparedStyle();detachResidentStyle();
        const std::array<GLuint,4> buffers{sphereInstanceVbo_,cylinderInstanceVbo_,halfCylinderInstanceVbo_,boxInstanceVbo_};
        std::array<GLsizei,4> counts{};
        if (cacheable && representationBuffers_.restore(static_cast<size_t>(representation),
                static_cast<int>(coloring),buffers,counts,localCenter_,localRadius_)) {
            representation_=representation; coloring_=coloring; prepareDisplayedSource(); ensureSourceIndex(currentSource());
            sphereCount_=counts[0]; cylinderCount_=counts[1]; halfCylinderCount_=counts[2]; boxCount_=counts[3];
            sphereGlowCount_=cylinderGlowCount_=halfCylinderGlowCount_=boxGlowCount_=0;
            atomisticBuffersResident_=false; // Static cache does not carry trajectory indices.
            uploadedVisualizationRevision_=visualizationRevision_;
            const double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-styleStarted).count();
            if(!renderingVolumes_) std::cout << "VR_METRIC event=process_progress phase=style_apply representation="
                << representationName(representation_) << " coloring=" << coloringName(coloring_)
                << " total_ms=" << elapsed << " fast_path=static_gpu_buffers" << std::endl;
            return;
        }
        const bool atomisticPair =
            (representation_ == Representation::ballstick &&
             representation == Representation::stick) ||
            (representation_ == Representation::stick &&
             representation == Representation::ballstick);
        if (!cacheable && toolPreviewToken_.empty() && toolCommittedToken_.empty() &&
            atomisticPair && coloring == coloring_ && atomisticSharedGeometry_ &&
            atomisticBuffersResident_ &&
            uploadedVisualizationRevision_ == visualizationRevision_) {
            representation_ = representation;
            prepareDisplayedSource();
            ensureSourceIndex(currentSource());
            sphereCount_ = representation_ == Representation::ballstick
                ? ballstickSphereCount_ : 0;
            const double milliseconds = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - styleStarted).count();
            if(!renderingVolumes_) std::cout << "VR_METRIC event=process_progress phase=style_apply"
                      << " representation=" << representationName(representation_)
                      << " coloring=" << coloringName(coloring_)
                      << " points=" << sphereCount_
                      << " cylinders=" << cylinderCount_
                      << " half_cylinders=" << halfCylinderCount_
                      << " boxes=" << boxCount_
                      << " prepare_ms=" << milliseconds
                      << " upload_ms=0 total_ms=" << milliseconds
                      << " fast_path=shared_atomistic_buffers"
                      << " rss_mib=" << currentResidentMiB() << std::endl;
            return;
        }
        const bool restoringAtomistic = toolPreviewToken_.empty() && toolCommittedToken_.empty() &&
            (representation == Representation::ballstick || representation == Representation::stick) &&
            representation_ != Representation::ballstick &&
            representation_ != Representation::stick &&
            cachedAtomisticVisualizationRevision_ == visualizationRevision_ &&
            cachedAtomisticColoring_ == coloring &&
            !atomisticCylinderInstances_.empty() &&
            (selectionTintEnabled() || (snapHighlightOwnerTokens_.empty() && snapHighlightIdentities_.empty() &&
            selectedHighlightOwnerTokens_.empty() && selectedHighlightIdentities_.empty()));
        if (restoringAtomistic) {
            representation_ = representation;
            coloring_ = coloring;
            prepareDisplayedSource();
            ensureSourceIndex(currentSource());
            const auto preparedAt = std::chrono::steady_clock::now();
            glBindBuffer(GL_ARRAY_BUFFER, sphereInstanceVbo_);
            glBufferData(GL_ARRAY_BUFFER,
                static_cast<GLsizeiptr>(atomisticSphereInstances_.size() * sizeof(Vertex)),
                atomisticSphereInstances_.data(), GL_DYNAMIC_DRAW);
            glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
            glBufferData(GL_ARRAY_BUFFER,
                static_cast<GLsizeiptr>(atomisticCylinderInstances_.size() * sizeof(Cylinder)),
                atomisticCylinderInstances_.data(), GL_DYNAMIC_DRAW);
            sphereCount_ = representation_ == Representation::ballstick
                ? static_cast<GLsizei>(atomisticSphereInstances_.size()) : 0;
            cylinderCount_ = static_cast<GLsizei>(atomisticCylinderInstances_.size());
            halfCylinderCount_ = 0;
            boxCount_ = 0;
            sphereGlowCount_ = cylinderGlowCount_ = halfCylinderGlowCount_ = boxGlowCount_ = 0;
            atomisticBuffersResident_ = true;
            uploadedVisualizationRevision_ = visualizationRevision_;
            const auto uploadedAt = std::chrono::steady_clock::now();
            const double prepareMilliseconds = std::chrono::duration<double, std::milli>(
                preparedAt - styleStarted).count();
            const double uploadMilliseconds = std::chrono::duration<double, std::milli>(
                uploadedAt - preparedAt).count();
            const double milliseconds = std::chrono::duration<double, std::milli>(
                uploadedAt - styleStarted).count();
            if(!renderingVolumes_) std::cout << "VR_METRIC event=process_progress phase=style_apply"
                      << " representation=" << representationName(representation_)
                      << " coloring=" << coloringName(coloring_)
                      << " points=" << sphereCount_
                      << " cylinders=" << cylinderCount_
                      << " prepare_ms=" << prepareMilliseconds
                      << " upload_ms=" << uploadMilliseconds
                      << " total_ms=" << milliseconds
                      << " fast_path=restored_atomistic_buffers"
                      << " rss_mib=" << currentResidentMiB() << std::endl;
            return;
        }
        representation_ = representation;
        coloring_ = coloring;
        prepareDisplayedSource();
        const RepresentationData& source = currentSource();
        ensureSourceIndex(source);
        const auto preparedAt = std::chrono::steady_clock::now();
        auto coordinateIndexFor = [&](const std::string& identity, bool end) -> int32_t {
            const auto ownership = sourceIndex_->ownership.find(identity);
            if (ownership != sourceIndex_->ownership.end()) {
                for (const TransformOwner& owner : ownership->second->owners) {
                    const float weight = end ? owner.endWeight : owner.startWeight;
                    const auto coordinate = visualizationCoordinateIndex_.find(owner.token);
                    if (weight > 0.0F && coordinate != visualizationCoordinateIndex_.end()) {
                        return static_cast<int32_t>(coordinate->second);
                    }
                }
            }
            const auto aliases = sourceIndex_->aliases.find(identity);
            if (aliases != sourceIndex_->aliases.end()) {
                for (const std::string& token : aliases->second->tokens) {
                    const auto coordinate = visualizationCoordinateIndex_.find(token);
                    if (coordinate != visualizationCoordinateIndex_.end()) {
                        return static_cast<int32_t>(coordinate->second);
                    }
                }
            }
            return -1;
        };
        auto collectWeights = [&](const std::string& token) {
            std::unordered_map<std::string, std::pair<float, float>> result;
            if (token.empty()) return result;
            const auto& ownershipRecords = source.toolScopeOwnership.empty()
                ? source.transformOwnership : source.toolScopeOwnership;
            for (const TransformOwnership& ownership : ownershipRecords) {
                const auto owner = std::find_if(
                    ownership.owners.begin(), ownership.owners.end(),
                    [&](const TransformOwner& candidate) {
                        return candidate.token == token;
                    });
                if (owner != ownership.owners.end()) {
                    result.emplace(
                        ownership.identity,
                        std::pair(owner->startWeight, owner->endWeight));
                }
            }
            for (const nadoc_vr::OwnerAliasEntry& aliases : source.ownerAliases) {
                if (std::find(
                        aliases.tokens.begin(), aliases.tokens.end(), token)
                    != aliases.tokens.end()) {
                    result.emplace(
                        aliases.identity, std::pair(1.0F, 1.0F));
                }
            }
            return result;
        };
        const auto committedWeights = collectWeights(toolCommittedToken_);
        // Prepare on selection, before the first drag. Visualized slab frames
        // have a separate deformation path and retain the general rebuild path.
        const bool packedRepresentation = representation_ == Representation::full ||
            representation_ == Representation::stick || representation_ == Representation::ballstick ||
            representation_ == Representation::vdw;
        if (packedPreviewEnabled_ && packedRepresentation && visualizationSlabFrames_.empty()) {
            if (!toolPreviewToken_.empty()) previewGeometry_.token = toolPreviewToken_;
            else if (selectedHighlightOwnerTokens_.size() == 1)
                previewGeometry_.token = *selectedHighlightOwnerTokens_.begin();
        }
        const auto pendingWeights = collectWeights(toolPreviewToken_);
        const auto packedWeights = collectWeights(previewGeometry_.token);
        // A selected token can become stale after a scene replacement. Do not
        // let a cache entry make an otherwise invalid preview owner valid.
        if (packedWeights.empty()) previewGeometry_.clear();
        auto weights = [](const auto& values, const std::string& identity) {
            const auto found = values.find(identity);
            return found == values.end()
                ? std::pair(0.0F, 0.0F) : found->second;
        };
        auto transformPoint = [&](const glm::vec3& point, const std::string& identity,
                                  bool end,
                                  const std::pair<glm::vec3, glm::vec3>& visualization) {
            const auto committed = weights(committedWeights, identity);
            const auto pending = weights(pendingWeights, identity);
            glm::vec3 result = nadoc_vr::weightedTransformPoint(
                point + (end ? visualization.second : visualization.first),
                toolCommittedTransform_, end ? committed.second : committed.first);
            if (previewGeometry_.active()) return result;
            return nadoc_vr::weightedTransformPoint(
                result, toolPreviewTransform_, end ? pending.second : pending.first);
        };
        auto transformVector = [&](const glm::vec3& vector, const std::string& identity) {
            const float committed = weights(committedWeights, identity).first;
            const float pending = weights(pendingWeights, identity).first;
            glm::vec3 result = nadoc_vr::weightedTransformVector(
                vector, toolCommittedTransform_, committed);
            if (previewGeometry_.active()) return result;
            return nadoc_vr::weightedTransformVector(
                result, toolPreviewTransform_, pending);
        };
        auto matchesOwner = [&](const std::string& identity,
                                const std::unordered_set<std::string>& tokens) {
            if (tokens.empty()) return false;
            const auto aliases = sourceIndex_->aliases.find(identity);
            if (aliases != sourceIndex_->aliases.end() && std::any_of(
                aliases->second->tokens.begin(), aliases->second->tokens.end(),
                [&](const std::string& token) { return tokens.contains(token); })) {
                return true;
            }
            const auto ownership = sourceIndex_->ownership.find(identity);
            return ownership != sourceIndex_->ownership.end() && std::any_of(
                ownership->second->owners.begin(), ownership->second->owners.end(),
                [&](const TransformOwner& owner) {
                    return (owner.startWeight > 0.0F || owner.endWeight > 0.0F) &&
                        tokens.contains(owner.token);
                });
        };
        dynamicSelectionRows_ = true;
        auto glowColor = [&](const std::string& identity) -> std::optional<glm::vec3> {
            if (selectionTintEnabled()) return std::nullopt;
            if (selectedHighlightIdentities_.contains(identity) ||
                matchesOwner(identity, selectedHighlightOwnerTokens_)) {
                return glm::vec3(0.22F, 1.0F, 0.42F);
            }
            if (snapHighlightIdentities_.contains(identity) ||
                matchesOwner(identity, snapHighlightOwnerTokens_)) {
                return glm::vec3(1.0F, 0.68F, 0.12F);
            }
            return std::nullopt;
        };

        std::vector<Vertex> points;
        std::vector<int32_t> sphereCoordinateIndices;
        std::vector<Vertex> glowPoints;
        points.reserve(source.points.size());
        sphereCoordinateIndices.reserve(source.points.size());
        for (const StyledPoint& point : source.points) {
            if (point.identity.starts_with("atom-ref:") &&
                !hasCompleteVisualizationAtomEndpoints(source, point.identity)) {
                continue;
            }
            const auto visualization = visualizationOffsets(source, point.identity);
            const glm::vec3 position = transformPoint(
                point.position, point.identity, false, visualization);
            selectionRows_[0].push_back(&point.identity);
            points.push_back(Vertex{
                position,
                visualizationColor(source, point.identity)
                    .value_or(point.colors.get(coloring)),
                representationPointRadius(representation_, point), objectId(point.identity)});
            if (previewGeometry_.active()) previewGeometry_.points.add(points.back(), weights(packedWeights, point.identity));
            sphereCoordinateIndices.push_back(coordinateIndexFor(point.identity, false));
            if (const auto color = glowColor(point.identity)) {
                glowPoints.push_back(Vertex{position, *color, representationPointRadius(representation_, point) * 1.55F});
                if (previewGeometry_.active()) previewGeometry_.glowPoints.add(glowPoints.back(), weights(packedWeights, point.identity));
            }
        }
        glBindBuffer(GL_ARRAY_BUFFER, sphereInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(points.size() * sizeof(Vertex)),
                     points.data(), GL_DYNAMIC_DRAW);
        sphereCount_ = static_cast<GLsizei>(points.size());
        glBindBuffer(GL_ARRAY_BUFFER, sphereGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(glowPoints.size() * sizeof(Vertex)),
                     glowPoints.data(), GL_DYNAMIC_DRAW);
        sphereGlowCount_ = static_cast<GLsizei>(glowPoints.size());

        std::vector<Cylinder> cylinders;
        std::vector<std::array<int32_t, 2>> cylinderCoordinateIndices;
        std::vector<Cylinder> glowCylinders;
        cylinders.reserve(source.cylinders.size());
        cylinderCoordinateIndices.reserve(source.cylinders.size());
        for (const StyledCylinder& cylinder : source.cylinders) {
            if (!representationCylinderVisible(representation_, cylinder.identity)) continue;
            if (cylinder.identity.starts_with("atom-bond-ref:") &&
                !hasCompleteVisualizationAtomEndpoints(source, cylinder.identity)) {
                continue;
            }
            const auto visualization = visualizationOffsets(source, cylinder.identity);
            const glm::vec3 start = transformPoint(
                cylinder.start, cylinder.identity, false, visualization);
            glm::vec3 end = transformPoint(
                cylinder.end, cylinder.identity, true, visualization);
            if (cylinder.identity.ends_with(":slab-connector")) {
                if (const auto frame = displayedVisualizationSlabFrame(
                        source, cylinder.identity)) {
                    end = nadoc_vr::visualizationSlabConnectionCorner(
                        frame->center, frame->axisX, frame->axisZ, start);
                }
            }
            selectionRows_[1].push_back(&cylinder.identity);
            cylinders.push_back(Cylinder{
                start, end, cylinder.radius,
                visualizationColor(source, cylinder.identity)
                    .value_or(cylinder.colors.get(coloring)), objectId(cylinder.identity), cylinder.endRadius});
            if (previewGeometry_.active()) previewGeometry_.cylinders.add(cylinders.back(), weights(packedWeights, cylinder.identity));
            cylinderCoordinateIndices.push_back({
                coordinateIndexFor(cylinder.identity, false),
                coordinateIndexFor(cylinder.identity, true),
            });
            if (const auto color = glowColor(cylinder.identity)) {
                glowCylinders.push_back(Cylinder{
                    start, end, cylinder.radius * 1.55F, *color, 0,
                    cylinder.endRadius < 0 ? -1.0F : cylinder.endRadius * 1.55F});
                if (previewGeometry_.active()) previewGeometry_.glowCylinders.add(glowCylinders.back(), weights(packedWeights, cylinder.identity));
            }
        }
        glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(cylinders.size() * sizeof(Cylinder)),
                     cylinders.data(), GL_DYNAMIC_DRAW);
        cylinderCount_ = static_cast<GLsizei>(cylinders.size());
        glBindBuffer(GL_ARRAY_BUFFER, cylinderGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(glowCylinders.size() * sizeof(Cylinder)),
                     glowCylinders.data(), GL_DYNAMIC_DRAW);
        cylinderGlowCount_ = static_cast<GLsizei>(glowCylinders.size());

        if ((representation_ == Representation::ballstick ||
             representation_ == Representation::stick || representation_ == Representation::vdw) &&
            !visualizationAtomTokens_.empty()) {
            atomisticSphereInstances_ = points;
            atomisticSphereCoordinateIndices_ = std::move(sphereCoordinateIndices);
            atomisticCylinderInstances_ = cylinders;
            atomisticCylinderCoordinateIndices_ =
                std::move(cylinderCoordinateIndices);
            // VDW radii differ from ball-and-stick; do not restore these buffers
            // through the ball-and-stick/stick style-switch shortcut.
            cachedAtomisticVisualizationRevision_ = representation_ == Representation::vdw ? 0 : visualizationRevision_;
            cachedAtomisticColoring_ = coloring_;
        }

        std::vector<Cylinder> halfCylinders;
        std::vector<Cylinder> glowHalfCylinders;
        halfCylinders.reserve(source.halfCylinders.size());
        for (const StyledCylinder& cylinder : source.halfCylinders) {
            const auto visualization = visualizationOffsets(source, cylinder.identity);
            const glm::vec3 start = transformPoint(
                cylinder.start, cylinder.identity, false, visualization);
            const glm::vec3 end = transformPoint(
                cylinder.end, cylinder.identity, true, visualization);
            selectionRows_[2].push_back(&cylinder.identity);
            halfCylinders.push_back(Cylinder{
                start, end, cylinder.radius,
                visualizationColor(source, cylinder.identity)
                    .value_or(cylinder.colors.get(coloring)), objectId(cylinder.identity), cylinder.endRadius});
            if (previewGeometry_.active()) previewGeometry_.halves.add(halfCylinders.back(), weights(packedWeights, cylinder.identity));
            if (const auto color = glowColor(cylinder.identity)) {
                glowHalfCylinders.push_back(Cylinder{
                    start, end, cylinder.radius * 1.55F, *color, 0,
                    cylinder.endRadius < 0 ? -1.0F : cylinder.endRadius * 1.55F});
                if (previewGeometry_.active()) previewGeometry_.glowHalves.add(glowHalfCylinders.back(), weights(packedWeights, cylinder.identity));
            }
        }
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(halfCylinders.size() * sizeof(Cylinder)),
                     halfCylinders.data(), GL_DYNAMIC_DRAW);
        halfCylinderCount_ = static_cast<GLsizei>(halfCylinders.size());
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(
                         glowHalfCylinders.size() * sizeof(Cylinder)),
                     glowHalfCylinders.data(), GL_DYNAMIC_DRAW);
        halfCylinderGlowCount_ = static_cast<GLsizei>(glowHalfCylinders.size());

        std::vector<Box> boxes;
        std::vector<Box> glowBoxes;
        boxes.reserve(source.boxes.size());
        for (const StyledBox& box : source.boxes) {
            if (!representationBoxVisible(representation_, box.identity)) continue;
            glm::vec3 center;
            glm::vec3 axisX;
            glm::vec3 axisY;
            glm::vec3 axisZ;
            if (const auto frame = displayedVisualizationSlabFrame(
                    source, box.identity)) {
                center = frame->center;
                axisX = frame->axisX;
                axisY = frame->axisY;
                axisZ = frame->axisZ;
            } else {
                const auto visualization = visualizationOffsets(source, box.identity);
                center = transformPoint(
                    box.center, box.identity, false, visualization);
                axisX = transformVector(box.axisX, box.identity);
                axisY = transformVector(box.axisY, box.identity);
                axisZ = transformVector(box.axisZ, box.identity);
            }
            selectionRows_[3].push_back(&box.identity);
            boxes.push_back(Box{
                center, axisX, axisY, axisZ,
                visualizationColor(source, box.identity)
                    .value_or(box.colors.get(coloring)), objectId(box.identity),
                {transformVector(box.normals[0], box.identity), transformVector(box.normals[1], box.identity), transformVector(box.normals[2], box.identity)}});
            if (previewGeometry_.active()) previewGeometry_.boxes.add(boxes.back(), weights(packedWeights, box.identity));
            if (const auto color = glowColor(box.identity)) {
                glowBoxes.push_back(Box{
                    center, axisX * 1.18F, axisY * 1.18F, axisZ * 1.18F, *color});
                if (previewGeometry_.active()) previewGeometry_.glowBoxes.add(glowBoxes.back(), weights(packedWeights, box.identity));
            }
        }
        glBindBuffer(GL_ARRAY_BUFFER, boxInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(boxes.size() * sizeof(Box)),
                     boxes.data(), GL_DYNAMIC_DRAW);
        boxCount_ = static_cast<GLsizei>(boxes.size());
        glBindBuffer(GL_ARRAY_BUFFER, boxGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(glowBoxes.size() * sizeof(Box)),
                     glowBoxes.data(), GL_DYNAMIC_DRAW);
        boxGlowCount_ = static_cast<GLsizei>(glowBoxes.size());

        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        auto include = [&](const glm::vec3& point, float radius = 0.0F) {
            lo = glm::min(lo, point - glm::vec3(radius));
            hi = glm::max(hi, point + glm::vec3(radius));
        };
        for (const Vertex& point : points) include(point.position, point.size);
        for (const Cylinder& cylinder : cylinders) {
            include(cylinder.start, cylinder.radius);
            include(cylinder.end, cylinder.radius);
        }
        for (const Cylinder& cylinder : halfCylinders) {
            include(cylinder.start, cylinder.radius);
            include(cylinder.end, cylinder.radius);
        }
        for (const Box& box : boxes) {
            nadoc_vr::includeMeshBounds(box, include);
        }
        if (source.points.empty() && source.cylinders.empty()
            && source.halfCylinders.empty() && source.boxes.empty()) {
            localCenter_ = {0.0F, 0.0F, -kViewDistanceMeters};
            localRadius_ = 0.5F;
        } else {
            localCenter_ = (lo + hi) * 0.5F;
            localRadius_ = std::max(glm::length(hi - lo) * 0.5F, 0.01F);
        }
        if (previewGeometry_.active()) {
            previewGeometry_.finish();
            if (!toolPreviewToken_.empty()) applyPackedPreview(toolPreviewTransform_);
        }
        const auto completedAt = std::chrono::steady_clock::now();
        const double prepareMilliseconds = std::chrono::duration<double, std::milli>(
            preparedAt - styleStarted).count();
        const double uploadMilliseconds = std::chrono::duration<double, std::milli>(
            completedAt - preparedAt).count();
        if(!renderingVolumes_) std::cout << "VR_METRIC event=process_progress phase=style_apply"
                  << " representation=" << representationName(representation_)
                  << " coloring=" << coloringName(coloring_)
                  << " points=" << sphereCount_
                  << " cylinders=" << cylinderCount_
                  << " half_cylinders=" << halfCylinderCount_
                  << " boxes=" << boxCount_
                  << " prepare_ms=" << prepareMilliseconds
                  << " upload_ms=" << uploadMilliseconds
                  << " total_ms=" << (prepareMilliseconds + uploadMilliseconds)
                  << " rss_mib=" << currentResidentMiB() << std::endl;
        if (cacheable) representationBuffers_.capture(static_cast<size_t>(representation_),
            static_cast<int>(coloring_),buffers,{sphereCount_,cylinderCount_,halfCylinderCount_,boxCount_},localCenter_,localRadius_);
        uploadedVisualizationRevision_ = visualizationRevision_;
        atomisticBuffersResident_ = representation_ == Representation::ballstick;
        if (atomisticBuffersResident_) ballstickSphereCount_ = sphereCount_;
    }

    [[nodiscard]] Representation representation() const { return representation_; }
    [[nodiscard]] Coloring coloring() const { return coloring_; }
    [[nodiscard]] std::optional<nadoc_vr::PickHit> pick(
        const nadoc_vr::Ray& worldRay, const glm::mat4& modelTransform) const {
        nadoc_vr::CalculationScope auditScope("pick");
        const glm::mat4 worldToModel = glm::inverse(modelTransform);
        nadoc_vr::Ray ray;
        ray.origin = glm::vec3(worldToModel * glm::vec4(worldRay.origin, 1.0F));
        ray.direction = glm::normalize(
            glm::vec3(worldToModel * glm::vec4(worldRay.direction, 0.0F)));
        const RepresentationData& source = currentSource();
        std::optional<nadoc_vr::PickHit> nearest;
        auto consider = [&](const std::string& identity, std::optional<float> distance) {
            if (!distance || identity.starts_with("viewer:") || *distance > 10.0F) return;
            const glm::vec3 localPosition = ray.origin + ray.direction * *distance;
            const glm::vec3 worldPosition = glm::vec3(
                modelTransform * glm::vec4(localPosition, 1.0F));
            const float worldDistance = glm::length(worldPosition - worldRay.origin);
            if (!nearest || worldDistance < nearest->distance) {
                nearest = nadoc_vr::PickHit{identity, worldDistance, worldPosition};
            }
        };
        for (const StyledPoint& point : source.points) {
            consider(point.identity, nadoc_vr::raySphere(
                ray, displayedPoint(source, point.position, point.identity), representationPointRadius(representation_, point)));
        }
        for (const StyledCylinder& cylinder : source.cylinders) {
            if (!representationCylinderVisible(representation_, cylinder.identity)) continue;
            consider(cylinder.identity, nadoc_vr::rayCapsule(
                ray, displayedPoint(source, cylinder.start, cylinder.identity),
                displayedPoint(source, cylinder.end, cylinder.identity, true),
                cylinder.radius));
        }
        for (const StyledCylinder& cylinder : source.halfCylinders) {
            consider(cylinder.identity, nadoc_vr::rayHalfCylinder(
                ray, displayedPoint(source, cylinder.start, cylinder.identity),
                displayedPoint(source, cylinder.end, cylinder.identity, true),
                cylinder.radius));
        }
        for (const StyledBox& box : source.boxes) {
            if (!representationBoxVisible(representation_, box.identity)) continue;
            const float committed = committedWeights(source, box.identity).first;
            const float pending = previewWeights(source, box.identity).first;
            consider(box.identity, nadoc_vr::rayRepresentationMesh(
                representation_, ray, displayedPoint(source, box.center, box.identity),
                previewVector(box.axisX, committed, pending),
                previewVector(box.axisY, committed, pending),
                previewVector(box.axisZ, committed, pending)));
        }
        return nearest;
    }

    // Use the selected packed instances; a base grab never scans the full
    // atomistic scene or rebuilds semantic ownership on each controller frame.
    [[nodiscard]] std::optional<glm::vec3> pickSelected(
            const nadoc_vr::Ray& worldRay,const glm::mat4& model,const std::vector<std::string>& owners) const {
        nadoc_vr::CalculationScope auditScope("pickSelected");
        // Remaining tokens are parent-domain/strand aliases, not extra selections.
        if(owners.empty())return std::nullopt;
        if(!previewGeometry_.active() || previewGeometry_.token!=owners.front()) {
            const auto hit=pick(worldRay,model);
            if(!hit)return std::nullopt;
            const auto weights=layerWeights(currentSource(),hit->identity,owners.front(),*sourceIndex_);
            return weights.first!=0 || weights.second!=0?std::optional(hit->position):std::nullopt;
        }
        const auto inverse=glm::inverse(model);
        const nadoc_vr::Ray ray{glm::vec3(inverse*glm::vec4(worldRay.origin,1)),
            glm::normalize(glm::vec3(inverse*glm::vec4(worldRay.direction,0)))};
        const float modelScale=std::max(glm::length(glm::vec3(model[0])),1e-6F);
        // One degree of pointing tolerance, bounded to 2–12 mm in tracking
        // space. Tiny selected bases remain acquirable with controller jitter.
        auto padding=[&](glm::vec3 p){return glm::clamp(glm::distance(p,ray.origin)*modelScale*.017455F,.002F,.012F)/modelScale;};
        std::optional<float> nearest;
        auto include=[&](std::optional<float> t){if(t && *t>=0 && (!nearest || *t<*nearest))nearest=t;};
        for(const auto& e:previewGeometry_.points.edits) {
            const auto& p=previewGeometry_.points.current[e.index];include(nadoc_vr::raySphere(ray,p.position,p.size+padding(p.position)));
        }
        for(const auto* channel:{&previewGeometry_.cylinders,&previewGeometry_.halves})for(const auto& e:channel->edits) {
            const auto& c=channel->current[e.index];
            const float radius=c.radius+padding((c.start+c.end)*.5F);
            if(!nadoc_vr::raySphere(ray,(c.start+c.end)*.5F,glm::distance(c.start,c.end)*.5F+radius))continue;
            include(channel==&previewGeometry_.halves?nadoc_vr::rayHalfCylinder(ray,c.start,c.end,radius):nadoc_vr::rayCapsule(ray,c.start,c.end,radius));
        }
        for(const auto& e:previewGeometry_.boxes.edits) {
            const auto& b=previewGeometry_.boxes.current[e.index];
            const float extra=padding(b.center);
            auto expand=[&](glm::vec3 v){return v*(1+extra/std::max(glm::length(v),1e-6F));};
            include(nadoc_vr::rayRepresentationMesh(representation_,ray,b.center,expand(b.axisX),expand(b.axisY),expand(b.axisZ)));
        }
        if(!nearest)return std::nullopt;
        const auto point=glm::vec3(model*glm::vec4(ray.origin+ray.direction* *nearest,1));
        return glm::distance(point,worldRay.origin)<=10.F?std::optional(point):std::nullopt;
    }

    [[nodiscard]] std::vector<nadoc_vr::PickHit> selectVolume(
        const glm::vec3& worldCenter, float worldRadius,
        const glm::mat4& modelTransform) const {
        nadoc_vr::CalculationScope auditScope("selectVolume");
        const glm::mat4 worldToModel = glm::inverse(modelTransform);
        const glm::vec3 center = glm::vec3(
            worldToModel * glm::vec4(worldCenter, 1.0F));
        const float modelScale = std::max({
            glm::length(glm::vec3(modelTransform[0])),
            glm::length(glm::vec3(modelTransform[1])),
            glm::length(glm::vec3(modelTransform[2])),
            1.0e-6F,
        });
        const float radius = worldRadius / modelScale;
        const RepresentationData& source = currentSource();
        std::vector<nadoc_vr::PickHit> hits;
        auto include = [&](const std::string& identity, bool overlaps,
                           const glm::vec3& localPosition) {
            if (!overlaps || identity.starts_with("viewer:")) return;
            const glm::vec3 position = glm::vec3(
                modelTransform * glm::vec4(localPosition, 1.0F));
            hits.push_back({identity, glm::length(position - worldCenter), position});
        };
        for (const StyledPoint& point : source.points) {
            const glm::vec3 position = displayedPoint(
                source, point.position, point.identity);
            include(point.identity, nadoc_vr::sphereOverlapsSphere(
                center, radius, position, representationPointRadius(representation_, point)), position);
        }
        auto includeCylinders = [&](const std::vector<StyledCylinder>& cylinders,
                                    bool half) {
            for (const StyledCylinder& cylinder : cylinders) {
            if (!representationCylinderVisible(representation_, cylinder.identity)) continue;
                const glm::vec3 start = displayedPoint(
                    source, cylinder.start, cylinder.identity);
                const glm::vec3 end = displayedPoint(
                    source, cylinder.end, cylinder.identity, true);
                const bool overlaps = half
                    ? nadoc_vr::sphereOverlapsHalfCylinder(
                        center, radius, start, end, cylinder.radius)
                    : nadoc_vr::sphereOverlapsCapsule(
                        center, radius, start, end, cylinder.radius);
                include(cylinder.identity, overlaps,
                        nadoc_vr::closestPointOnSegment(center, start, end));
            }
        };
        includeCylinders(source.cylinders, false);
        includeCylinders(source.halfCylinders, true);
        for (const StyledBox& box : source.boxes) {
            if (!representationBoxVisible(representation_, box.identity)) continue;
            const float committed = committedWeights(source, box.identity).first;
            const float pending = previewWeights(source, box.identity).first;
            const glm::vec3 boxCenter = displayedPoint(
                source, box.center, box.identity);
            const glm::vec3 axisX = previewVector(box.axisX, committed, pending);
            const glm::vec3 axisY = previewVector(box.axisY, committed, pending);
            const glm::vec3 axisZ = previewVector(box.axisZ, committed, pending);
            include(box.identity, nadoc_vr::sphereOverlapsBox(
                center, radius, boxCenter, axisX, axisY, axisZ), boxCenter);
        }
        std::sort(hits.begin(), hits.end(), [](const auto& a, const auto& b) {
            return a.distance < b.distance;
        });
        return hits;
    }

    [[nodiscard]] bool belongsToSelection(const std::string& identity,const std::vector<std::string>& tokens) const {
        const auto aliases=sourceIndex_->aliases.find(identity);
        if(aliases==sourceIndex_->aliases.end())return false;
        return std::any_of(aliases->second->tokens.begin(),aliases->second->tokens.end(),[&](const auto& token){
            return std::find(tokens.begin(),tokens.end(),token)!=tokens.end();
        });
    }

    /** Collapse primitive overlaps through the same canonical filter as desktop.
     * One representative identity is retained per canonical object for the browser
     * event, while owner tokens drive whole-object native highlighting. */
    [[nodiscard]] SelectionVolumeHits resolveSelectionVolumeHits(
        const std::vector<nadoc_vr::PickHit>& hits,
        const std::string& selectionLevel,
        const std::string& selectedSelectionKind,
        const std::vector<std::string>& selectedOwnerTokens) const {
        nadoc_vr::CalculationScope auditScope("resolveSelectionVolumeHits");
        const auto& owners = sourceIndex_->selectionOwners;

        SelectionVolumeHits result;
        result.representatives.reserve(std::min<size_t>(hits.size(), 16U));
        std::unordered_set<std::string> seen;
        size_t identityBytes = 0;
        for (const nadoc_vr::PickHit& hit : hits) {
            if (result.representatives.size() == 16U) break;
            // These levels select residues/domains, not the connecting bond.
            // A bond's center can be closer than its endpoint and otherwise
            // suppress the valid bead through canonical-token deduplication.
            if((selectionLevel=="base" || selectionLevel=="end" || selectionLevel=="domain") &&
               (hit.identity.starts_with("backbone:") || hit.identity.starts_with("atom-bond-ref:")))continue;
            auto token = owners.resolve(hit.identity, selectionLevel);
            if (selectionLevel == "default") {
                const auto strandToken = owners.resolve(hit.identity, "strand");
                const bool drillingSameStrand = strandToken &&
                    (selectedSelectionKind == "strand" ||
                     selectedSelectionKind == "base") &&
                    std::find(
                        selectedOwnerTokens.begin(), selectedOwnerTokens.end(),
                        *strandToken) != selectedOwnerTokens.end();
                if (drillingSameStrand) {
                    token = owners.resolve(hit.identity, "base");
                    if (!token) {
                        token = owners.resolve(hit.identity, "domain");
                    }
                } else {
                    token = strandToken;
                }
            }
            if (selectionLevel == "end" && !token) continue;
            const std::string& key = token ? *token : hit.identity;
            if (!seen.insert(key).second ||
                identityBytes + hit.identity.size() > 2048U) {
                continue;
            }
            identityBytes += hit.identity.size();
            result.representatives.push_back(hit);
            if (token) result.ownerTokens.push_back(*token);
            else result.directIdentities.push_back(hit.identity);
        }
        return result;
    }

    [[nodiscard]] std::optional<nadoc_vr::PickHit> anchor(
        const std::string& identity,
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform) const {
        nadoc_vr::CalculationScope auditScope("anchor");
        if (identity.empty()) return std::nullopt;
        const RepresentationData& source = currentSource();
        auto containsIdentity = [&](const std::string& candidate) {
            return std::any_of(source.points.begin(), source.points.end(),
                               [&](const StyledPoint& value) {
                                   return value.identity == candidate;
                               }) ||
                   std::any_of(source.cylinders.begin(), source.cylinders.end(),
                               [&](const StyledCylinder& value) {
                                   return value.identity == candidate;
                               }) ||
                   std::any_of(source.halfCylinders.begin(), source.halfCylinders.end(),
                               [&](const StyledCylinder& value) {
                                   return value.identity == candidate;
                               }) ||
                   std::any_of(source.boxes.begin(), source.boxes.end(),
                               [&](const StyledBox& value) {
                                   return value.identity == candidate;
                               });
        };
        std::string resolvedIdentity = identity;
        if (!containsIdentity(resolvedIdentity)) {
            const auto fallback = nadoc_vr::resolveOwnerIdentity(
                source.ownerAliases, ownerTokens);
            if (!fallback) return std::nullopt;
            resolvedIdentity = *fallback;
        }
        const float worldScale = std::max({
            glm::length(glm::vec3(modelTransform[0])),
            glm::length(glm::vec3(modelTransform[1])),
            glm::length(glm::vec3(modelTransform[2])),
        });
        auto result = [&](const glm::vec3& center, float radius) {
            return nadoc_vr::PickHit{
                resolvedIdentity,
                std::max(radius * worldScale, 0.009F),
                glm::vec3(modelTransform * glm::vec4(center, 1.0F)),
            };
        };
        for (const StyledPoint& point : source.points) {
            if (point.identity == resolvedIdentity) {
                return result(
                    displayedPoint(source, point.position, point.identity),
                    representationPointRadius(representation_, point));
            }
        }
        auto cylinderAnchor = [&](const std::vector<StyledCylinder>& cylinders)
            -> std::optional<nadoc_vr::PickHit> {
            for (const StyledCylinder& cylinder : cylinders) {
            if (!representationCylinderVisible(representation_, cylinder.identity)) continue;
                if (cylinder.identity == resolvedIdentity) {
                    return result(
                        (displayedPoint(source, cylinder.start, cylinder.identity)
                         + displayedPoint(
                             source, cylinder.end, cylinder.identity, true)) * 0.5F,
                        cylinder.radius);
                }
            }
            return std::nullopt;
        };
        if (auto found = cylinderAnchor(source.cylinders)) return found;
        if (auto found = cylinderAnchor(source.halfCylinders)) return found;
        for (const StyledBox& box : source.boxes) {
            if (!representationBoxVisible(representation_, box.identity)) continue;
            if (box.identity == resolvedIdentity) {
                const float committed = committedWeights(source, box.identity).first;
                const float pending = previewWeights(source, box.identity).first;
                const float radius = 0.5F * std::min({
                    glm::length(previewVector(box.axisX, committed, pending)),
                    glm::length(previewVector(box.axisY, committed, pending)),
                    glm::length(previewVector(box.axisZ, committed, pending)),
                });
                return result(displayedPoint(source, box.center, box.identity), radius);
            }
        }
        return std::nullopt;
    }

    /** Bounds of every primitive carrying the most-specific available owner token.
     * Unlike anchor(), this describes the selected owner rather than one fallback
     * primitive, so tool affordances remain stable across representation changes. */
    [[nodiscard]] std::optional<nadoc_vr::BoundsSummary> ownerBounds(
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform, bool allAuthored = false) const {
        nadoc_vr::CalculationScope auditScope("ownerBounds");
        const RepresentationData& source = currentSource();
        std::unordered_set<std::string> identities;
        for (const std::string& token : ownerTokens) {
            for (const nadoc_vr::OwnerAliasEntry& entry : source.ownerAliases) {
                if (std::find(entry.tokens.begin(), entry.tokens.end(), token)
                    != entry.tokens.end()) {
                    identities.insert(entry.identity);
                }
            }
            if (!identities.empty()) break;
        }
        if (allAuthored) {
            for (const auto& entry : source.ownerAliases) identities.insert(entry.identity);
        }
        if (identities.empty()) return std::nullopt;

        nadoc_vr::BoundsAccumulator bounds;
        for (const StyledPoint& point : source.points) {
            if (identities.contains(point.identity)) {
                bounds.includePoint(displayedPoint(
                    source, point.position, point.identity), representationPointRadius(representation_, point));
            }
        }
        auto includeCylinders = [&](const std::vector<StyledCylinder>& cylinders) {
            for (const StyledCylinder& cylinder : cylinders) {
            if (!representationCylinderVisible(representation_, cylinder.identity)) continue;
                if (identities.contains(cylinder.identity)) {
                    bounds.includeSegment(
                        displayedPoint(source, cylinder.start, cylinder.identity),
                        displayedPoint(
                            source, cylinder.end, cylinder.identity, true),
                        cylinder.radius);
                }
            }
        };
        includeCylinders(source.cylinders);
        includeCylinders(source.halfCylinders);
        for (const StyledBox& box : source.boxes) {
            if (!representationBoxVisible(representation_, box.identity)) continue;
            if (identities.contains(box.identity)) {
                const float committed = committedWeights(source, box.identity).first;
                const float pending = previewWeights(source, box.identity).first;
                bounds.includeBox(
                    displayedPoint(source, box.center, box.identity),
                    previewVector(box.axisX, committed, pending),
                    previewVector(box.axisY, committed, pending),
                    previewVector(box.axisZ, committed, pending));
            }
        }
        return bounds.summary(modelTransform);
    }

    // Bounded read-only physical picking observations for ScryWrite. These are
    // rendered backbone points, never a semantic selection/mutation command.
    std::string movePickPoints(const glm::mat4& model) const {
        const auto& source=currentSource();std::ostringstream out;out << '[';size_t count=0;
        for(const auto& point:source.points) {
            if(!point.identity.starts_with("nuc:") || !point.identity.ends_with(":backbone"))continue;
            if(count++>=1024)break;
            if(count>1)out << ',';
            const auto world=glm::vec3(model*glm::vec4(displayedPoint(source,point.position,point.identity),1));
            out << "{\"identity\":\"" << nadoc_vr::scrywrite::visualJson(point.identity)
                << "\",\"world\":[" << world.x << ',' << world.y << ',' << world.z << "]}";
        }
        out << ']';return out.str();
    }

    struct BendCluster {
        std::string token, identity;
        std::vector<std::pair<glm::vec3,glm::vec3>> segments;
    };
    std::vector<BendCluster> bendClusters() const {
        const auto& source=currentSource();
        std::vector<BendCluster> result;
        std::unordered_map<std::string,size_t> owners;
        for(const auto& handle:source.ownerHandles) {
            owners.emplace(handle.token,result.size());result.push_back({handle.token,{},{}});
        }
        std::unordered_map<std::string,std::vector<size_t>> aliases;
        for(const auto& alias:source.ownerAliases)for(const auto& token:alias.tokens)
            if(const auto owner=owners.find(token);owner!=owners.end())aliases[alias.identity].push_back(owner->second);
        auto add=[&](const auto& id,glm::vec3 a,glm::vec3 b) {
            const auto it=aliases.find(id);if(it==aliases.end())return;
            for(auto index:it->second) {
                auto& cluster=result[index];if(cluster.identity.empty())cluster.identity=id;
                cluster.segments.emplace_back(displayedPoint(source,a,id),displayedPoint(source,b,id,true));
            }
        };
        for(const auto& point:source.points)add(point.identity,point.position,point.position);
        for(const auto& c:source.cylinders)add(c.identity,c.start,c.end);
        for(const auto& c:source.halfCylinders)add(c.identity,c.start,c.end);
        for(const auto& b:source.boxes)add(b.identity,b.center-b.axisZ,b.center+b.axisZ);
        std::erase_if(result,[](const auto& c){return c.identity.empty();});return result;
    }

    /** Desktop-equivalent current gizmo center projected by scene v9. */
    [[nodiscard]] std::optional<glm::vec3> ownerHandle(
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform) const {
        nadoc_vr::CalculationScope auditScope("ownerHandle");
        const RepresentationData& source = currentSource();
        for (const std::string& token : ownerTokens) {
            const auto toolHandle = std::find_if(
                source.toolHandles.begin(), source.toolHandles.end(),
                [&](const ToolHandle& candidate) { return candidate.token == token; });
            if (toolHandle != source.toolHandles.end()) {
                glm::vec3 center = committedHandleCenter(toolHandle->token,toolHandle->center);
                if (toolHandle->token == toolPreviewToken_) {
                    center = glm::vec3(toolPreviewTransform_ * glm::vec4(center, 1.0F));
                }
                return glm::vec3(
                    modelTransform * glm::vec4(center, 1.0F));
            }
            const auto handle = std::find_if(
                source.ownerHandles.begin(), source.ownerHandles.end(),
                [&](const OwnerHandle& candidate) { return candidate.token == token; });
            if (handle != source.ownerHandles.end()) {
                glm::vec3 center = committedHandleCenter(handle->token,handle->center);
                if (handle->token == toolPreviewToken_) {
                    center = glm::vec3(toolPreviewTransform_ * glm::vec4(center, 1.0F));
                }
                return glm::vec3(modelTransform * glm::vec4(center, 1.0F));
            }
        }
        return std::nullopt;
    }

    GLsizei motionCylinderCount() const { return motionDetail_.coarse()?48:cylinderIndexCount_; }
    const void* motionCylinderOffset() const { return reinterpret_cast<const void*>(motionDetail_.coarse()?cylinderIndexCount_*sizeof(GLushort):0); }
    bool motionDetailReduced() const { return motionDetail_.reduced; }

    void renderShadowMap(const glm::mat4& modelTransform, const nadoc_vr::ShadowLightFrame& light,
                         const nadoc_vr::ShadowLightFrame* stabilized = nullptr) {
        nadoc_vr::CalculationScope auditScope("renderShadowMap");
        lightDirection_ = glm::normalize(light.direction);
        motionDetail_.beginFrame(!toolPreviewToken_.empty());
        if (motionDetail_.reduced) { nadoc_vr::CalculationScope reduced("motionDetail"); return; }
        const glm::vec3 worldCenter = glm::vec3(
            modelTransform * glm::vec4(localCenter_, 1.0F));
        const float modelScale = std::max({
            glm::length(glm::vec3(modelTransform[0])),
            glm::length(glm::vec3(modelTransform[1])),
            glm::length(glm::vec3(modelTransform[2])),
        });
        const float radius = std::max(localRadius_ * modelScale * 1.08F, 0.02F);
        const auto& projectionLight = stabilized ? *stabilized : light;
        const glm::vec3 eye = worldCenter + glm::normalize(projectionLight.direction) * (2.0F * radius);
        lightViewProjection_ = glm::ortho(
            -radius, radius, -radius, radius, radius * 0.05F, radius * 4.0F)
            * glm::lookAt(eye, worldCenter, projectionLight.up);

        // Every representation, including atomistic views, casts into the same
        // soft self-shadow map shared by both eyes.

        glBindFramebuffer(GL_FRAMEBUFFER, shadowFramebuffer_);
        glViewport(0, 0, kShadowMapSize, kShadowMapSize);
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
        glClear(GL_DEPTH_BUFFER_BIT);
        glEnable(GL_POLYGON_OFFSET_FILL);
        glPolygonOffset(1.5F, 2.0F);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, 0);

        auto shadowUniforms = [&](GLuint program, GLint projection, GLint model,
                                  GLint lightProjection, GLint lightDirectionUniform) {
            glUseProgram(program);
            glUniform1i(glGetUniformLocation(program,"uSelectionState"),6);
            glUniform1i(glGetUniformLocation(program,"uSelectionCount"),0);
            glUniformMatrix4fv(projection, 1, GL_FALSE, &lightViewProjection_[0][0]);
            glUniformMatrix4fv(model, 1, GL_FALSE, &modelTransform[0][0]);
            glUniformMatrix4fv(
                lightProjection, 1, GL_FALSE, &lightViewProjection_[0][0]);
            glUniform3fv(lightDirectionUniform, 1, &lightDirection_[0]);
        };
        if (sphereCount_ > 0) {
            shadowUniforms(sphereProgram_, sphereViewProjection_, sphereModel_,
                           sphereLightViewProjection_, sphereLightDirection_);
            glBindVertexArray(sphereVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, sphereIndexCount_, GL_UNSIGNED_SHORT, nullptr, sphereCount_);
        }
        if (cylinderCount_ > 0) {
            shadowUniforms(cylinderProgram_, cylinderViewProjection_, cylinderModel_,
                           cylinderLightViewProjection_, cylinderLightDirection_);
            glBindVertexArray(cylinderVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, motionCylinderCount(), GL_UNSIGNED_SHORT, motionCylinderOffset(), cylinderCount_);
        }
        if (halfCylinderCount_ > 0) {
            shadowUniforms(cylinderProgram_, cylinderViewProjection_, cylinderModel_,
                           cylinderLightViewProjection_, cylinderLightDirection_);
            glBindVertexArray(halfCylinderVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, halfCylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr,
                halfCylinderCount_);
        }
        if (boxCount_ > 0) {
            shadowUniforms(boxProgram_, boxViewProjection_, boxModel_,
                           boxLightViewProjection_, boxLightDirection_);
            glBindVertexArray(boxVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, boxDrawCount(), GL_UNSIGNED_SHORT, boxDrawOffset(), boxCount_);
        }
        glDisable(GL_POLYGON_OFFSET_FILL);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glBindVertexArray(0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    ~GlScene() {
        glDeleteBuffers(4, selectionBuffers_.data());
        glDeleteTextures(4, selectionTextures_.data());
        if(activeResident_)sphereInstanceVbo_=cylinderInstanceVbo_=halfCylinderInstanceVbo_=boxInstanceVbo_=0;
        glDeleteBuffers(1,&volumeBuffer_);glDeleteTextures(1,&volumeTexture_);
        if (lineVbo_) glDeleteBuffers(1, &lineVbo_);
        if (guideVbo_) glDeleteBuffers(1, &guideVbo_);
        if (sphereMeshVbo_) glDeleteBuffers(1, &sphereMeshVbo_);
        if (sphereIndexVbo_) glDeleteBuffers(1, &sphereIndexVbo_);
        if (sphereInstanceVbo_) glDeleteBuffers(1, &sphereInstanceVbo_);
        if (sphereGlowInstanceVbo_) glDeleteBuffers(1, &sphereGlowInstanceVbo_);
        if (cylinderInstanceVbo_) glDeleteBuffers(1, &cylinderInstanceVbo_);
        if (cylinderGlowInstanceVbo_) glDeleteBuffers(1, &cylinderGlowInstanceVbo_);
        if (cylinderMeshVbo_) glDeleteBuffers(1, &cylinderMeshVbo_);
        if (cylinderIndexVbo_) glDeleteBuffers(1, &cylinderIndexVbo_);
        if (halfCylinderInstanceVbo_) glDeleteBuffers(1, &halfCylinderInstanceVbo_);
        if (halfCylinderGlowInstanceVbo_) {
            glDeleteBuffers(1, &halfCylinderGlowInstanceVbo_);
        }
        if (halfCylinderMeshVbo_) glDeleteBuffers(1, &halfCylinderMeshVbo_);
        if (halfCylinderIndexVbo_) glDeleteBuffers(1, &halfCylinderIndexVbo_);
        if (boxInstanceVbo_) glDeleteBuffers(1, &boxInstanceVbo_);
        if (boxGlowInstanceVbo_) glDeleteBuffers(1, &boxGlowInstanceVbo_);
        if (boxMeshVbo_) glDeleteBuffers(1, &boxMeshVbo_);
        if (boxIndexVbo_) glDeleteBuffers(1, &boxIndexVbo_);
        if (lineVao_) glDeleteVertexArrays(1, &lineVao_);
        if (guideVao_) glDeleteVertexArrays(1, &guideVao_);
        if (sphereVao_) glDeleteVertexArrays(1, &sphereVao_);
        if (sphereGlowVao_) glDeleteVertexArrays(1, &sphereGlowVao_);
        if (cylinderVao_) glDeleteVertexArrays(1, &cylinderVao_);
        if (atomisticBondVao_) glDeleteVertexArrays(1, &atomisticBondVao_);
        if (cylinderGlowVao_) glDeleteVertexArrays(1, &cylinderGlowVao_);
        if (halfCylinderVao_) glDeleteVertexArrays(1, &halfCylinderVao_);
        if (halfCylinderGlowVao_) glDeleteVertexArrays(1, &halfCylinderGlowVao_);
        if (boxVao_) glDeleteVertexArrays(1, &boxVao_);
        if (boxGlowVao_) glDeleteVertexArrays(1, &boxGlowVao_);
        if (program_) glDeleteProgram(program_);
        if (sphereProgram_) glDeleteProgram(sphereProgram_);
        if (cylinderProgram_) glDeleteProgram(cylinderProgram_);
        if (atomisticBondProgram_) glDeleteProgram(atomisticBondProgram_);
        if (boxProgram_) glDeleteProgram(boxProgram_);
        if (shadowTexture_) glDeleteTextures(1, &shadowTexture_);
        if (shadowFramebuffer_) glDeleteFramebuffers(1, &shadowFramebuffer_);
    }

    std::string objectTable(const std::vector<uint32_t>& visibleIds) const {
        std::ostringstream out;
        out << '[';
        bool first = true;
        for (uint32_t id : visibleIds) {
            if (id == 0) continue;
            if (id >= objectIdentities_.size()) throw std::runtime_error("Unknown rendered object ID");
            const auto& identity = objectIdentities_[id];
            if (!first) out << ',';
            first = false;
            out << "{\"id\":" << id << ",\"identity\":\""
                << nadoc_vr::scrywrite::visualJson(identity) << "\",\"owner_tokens\":[";
            std::vector<std::string> owners;
            const auto aliases = sourceIndex_->aliases.find(identity);
            if (aliases != sourceIndex_->aliases.end()) owners = aliases->second->tokens;
            const auto ownership = sourceIndex_->ownership.find(identity);
            if (ownership != sourceIndex_->ownership.end()) {
                for (const auto& owner : ownership->second->owners) {
                    if ((owner.startWeight > 0 || owner.endWeight > 0) &&
                        std::find(owners.begin(), owners.end(), owner.token) == owners.end()) {
                        owners.push_back(owner.token);
                    }
                }
            }
            for (size_t i = 0; i < owners.size(); ++i) {
                if (i) out << ',';
                out << '"' << nadoc_vr::scrywrite::visualJson(owners[i]) << '"';
            }
            out << "]}";
        }
        out << ']';
        return out.str();
    }

    size_t bendPointCount() const {return bendPointArc_ && bendPointArc_->angle!=0?bendPoints_.pointCount():0;}
    size_t movePointCount() const {return movePointOwners_.empty()?0:bendPoints_.pointCount();}
    void setMovePointPreview(const std::vector<std::string>& owners,const glm::mat4& transform) {
        movePointOwners_=owners;movePointTransform_=transform;
    }
    void setBendPointArc(std::optional<nadoc_vr::BendArc> arc,bool twist=false) {
        bendPointArc_=std::move(arc);twistPointMode_=twist;
    }
    void renderBendPoints(const glm::mat4& vp,const glm::mat4& model,bool ids=false) const {
        const bool move=!movePointOwners_.empty();
        if(!move && (!bendPointArc_ || bendPointArc_->length<=0 || bendPointArc_->angle==0))return;
        nadoc_vr::CalculationScope auditScope("renderBendPoints");
        updateSelectionTint();bendPoints_.update(selectionMasks_);
        if(ids){const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,buffers);}
        nadoc_vr::BendArc arc=move?nadoc_vr::BendArc{}:*bendPointArc_;
        if(move)arc.length=1;
        bendPoints_.begin(vp,model,arc,move?2:twistPointMode_?1:0,movePointTransform_);
        bendPoints_.draw<Vertex>(0,sphereInstanceVbo_,offsetof(Vertex,position));
        bendPoints_.draw<Cylinder>(1,cylinderInstanceVbo_,offsetof(Cylinder,start));
        bendPoints_.draw<Cylinder>(1,cylinderInstanceVbo_,offsetof(Cylinder,end));
        bendPoints_.draw<Cylinder>(2,halfCylinderInstanceVbo_,offsetof(Cylinder,start));
        bendPoints_.draw<Cylinder>(2,halfCylinderInstanceVbo_,offsetof(Cylinder,end));
        bendPoints_.draw<Box>(3,boxInstanceVbo_,offsetof(Box,center));
        bendPoints_.end();
        if(ids)glDrawBuffer(GL_COLOR_ATTACHMENT0);
    }

    void renderVolumes(const glm::mat4& vp,const glm::mat4& model,const std::vector<Vertex>& guides,
            bool ids,const std::vector<nadoc_vr::ViewVolumeRecord>& entries,bool lightweight=false) {
        nadoc_vr::CalculationScope auditScope("renderVolumes");
#ifdef NADOC_SCRYWRITE_TESTING
        const bool guard=volumeGuardsEnabledForTest;
#else
        constexpr bool guard=true;
#endif
        pinnedSources_.fill(false);
        for(const auto& entry:entries)if(entry.enabled && entry.opacity>0)
            pinnedSources_[representationSourceIndex(representationFromName(entry.representation))]=true;
        std::vector<const nadoc_vr::ViewVolumeRecord*> active;
        std::vector<glm::vec4> data;
        const auto frame=nadoc_vr::ViewVolumeInteraction::frame(model,scene_.normalizationCenter,scene_.normalizationScale,{0,0,-kViewDistanceMeters});
        for(const auto& e:entries) if(e.enabled && e.opacity>0 && supportsRepresentation(representationFromName(e.representation))) {
            active.push_back(&e);
            glm::vec3 half=e.half;if(e.sides==6)half.x=half.y=std::min(half.x,half.y);
            const auto inverse=glm::inverse(frame*glm::translate(glm::mat4(1),e.center)*glm::mat4_cast(e.rotation)*glm::scale(glm::mat4(1),half));
            for(int i=0;i<4;++i)data.push_back(inverse[i]);
            data.push_back({float(e.sides),0,0,0});
        }
        // Clip uniforms are reset after each volume pass. With no active
        // volumes there is no texture upload or shader state to change.
        if(guard && active.empty()) {render(vp,model,guides,ids,lightweight);return;}
        if(!volumeBuffer_) {glGenBuffers(1,&volumeBuffer_);glGenTextures(1,&volumeTexture_);}
        glBindBuffer(GL_TEXTURE_BUFFER,volumeBuffer_);
        // Both eyes use the same clipping geometry, independent of view.
        if(!guard || data!=uploadedVolumeData_) {
#ifdef NADOC_SCRYWRITE_TESTING
            ++volumeUploadsForTest;
#endif
            glBufferData(GL_TEXTURE_BUFFER,std::max(size_t(1),data.size())*sizeof(glm::vec4),data.empty()?nullptr:data.data(),GL_STREAM_DRAW);
            uploadedVolumeData_=std::move(data);
        }
        glActiveTexture(GL_TEXTURE7);glBindTexture(GL_TEXTURE_BUFFER,volumeTexture_);
        glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,volumeBuffer_);glActiveTexture(GL_TEXTURE0);
        auto clip=[&](int layer,float opacity) {
            for(GLuint program:{program_,sphereProgram_,cylinderProgram_,boxProgram_,atomisticBondProgram_,loadingPoints_.program(),bendPoints_.program()}) {
                glUseProgram(program);
                glUniform1i(glGetUniformLocation(program,"uVolumes"),7);
                glUniform1i(glGetUniformLocation(program,"uVolumeCount"),int(active.size()));
                glUniform1i(glGetUniformLocation(program,"uVolumeLayer"),layer);
                glUniform1f(glGetUniformLocation(program,"uVolumeOpacity"),opacity);
            }
        };
        const auto original=representation_;const auto color=coloring_;
        renderingVolumes_=!active.empty();
        clip(-1,1);render(vp,model,{},ids,lightweight);
        for(size_t i=0;i<active.size();++i) {
            const auto& e=*active[i];
            const auto rep=representationFromName(e.representation);
            const auto volumeColor=coloringFromName(e.coloring=="overhang-only"?"strand":e.coloring);
            // setStyle also rebuilds selection/preview geometry. Calling it for
            // the style already on screen discards the drag cache every eye.
            if(!guard || rep!=representation_ || volumeColor!=coloring_)setStyle(rep,volumeColor);
            clip(int(i),e.opacity);
            glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
            render(vp,model,{},ids,lightweight);glDisable(GL_BLEND);
        }
        if((!guard && !active.empty()) || representation_!=original || coloring_!=color)setStyle(original,color);
        renderingVolumes_=false;active.clear();clip(-1,1);
        renderGuides(vp,guides);
    }

    void render(const glm::mat4& viewProjection, const glm::mat4& modelTransform,
                const std::vector<Vertex>& guides, bool captureIds = false, bool lightweight = false) const {
        nadoc_vr::CalculationScope auditScope("render");
        updateSelectionTint();
        if(lightweight){
            loadingPoints_.begin(viewProjection,modelTransform,captureIds);
            loadingPoints_.draw<Vertex>(sphereInstanceVbo_,sphereCount_,offsetof(Vertex,position));
            for(auto [buffer,count]:{std::pair{cylinderInstanceVbo_,cylinderCount_},std::pair{halfCylinderInstanceVbo_,halfCylinderCount_}}){
                loadingPoints_.draw<Cylinder>(buffer,count,offsetof(Cylinder,start));
                loadingPoints_.draw<Cylinder>(buffer,count,offsetof(Cylinder,end));
            }
            loadingPoints_.draw<Box>(boxInstanceVbo_,boxCount_,offsetof(Box,center));
            loadingPoints_.end(captureIds);
            renderBendPoints(viewProjection,modelTransform,captureIds);
            renderGuides(viewProjection,guides);
            return;
        }
        glUseProgram(program_);
        const glm::mat4 modelViewProjection = viewProjection * modelTransform;
        glUniformMatrix4fv(glGetUniformLocation(program_,"uVolumeModel"),1,GL_FALSE,&modelTransform[0][0]);
        glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &modelViewProjection[0][0]);
        glBindVertexArray(lineVao_);
        glLineWidth(1.5F);
        glDrawArrays(GL_LINES, 0, lineCount_);

        if (captureIds) {
            const GLenum buffers[] = {GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1};
            glDrawBuffers(2, buffers);
        }
        if (sphereCount_ > 0) {
            glUseProgram(sphereProgram_);
            glUniformMatrix4fv(sphereViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(sphereModel_, 1, GL_FALSE, &modelTransform[0][0]);
            glUniform1f(sphereAlpha_, 1.0F);
            glUniform1f(sphereEmissive_, 0.0F);
            applyLightingUniforms(
                sphereLightViewProjection_, sphereLightDirection_, sphereShadowMap_,
                sphereShadowsEnabled_);
            bindSelectionTint(sphereProgram_, 0);
            glBindVertexArray(sphereVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, sphereIndexCount_, GL_UNSIGNED_SHORT, nullptr, sphereCount_);
        }

        if (cylinderCount_ > 0) {
            // Bonds use the same lit geometry in the color and shadow passes.
            glUseProgram(cylinderProgram_);
            glUniformMatrix4fv(cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
            glUniform1f(cylinderAlpha_, 1.0F);
            glUniform1f(cylinderEmissive_, 0.0F);
            applyLightingUniforms(cylinderLightViewProjection_, cylinderLightDirection_,
                                  cylinderShadowMap_, cylinderShadowsEnabled_);
            bindSelectionTint(cylinderProgram_, 1);
            glBindVertexArray(cylinderVao_);
            glDrawElementsInstanced(GL_TRIANGLES, motionCylinderCount(), GL_UNSIGNED_SHORT,
                                    motionCylinderOffset(), cylinderCount_);
        }

        if (halfCylinderCount_ > 0) {
            glUseProgram(cylinderProgram_);
            glUniformMatrix4fv(cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
            glUniform1f(cylinderAlpha_, 1.0F);
            glUniform1f(cylinderEmissive_, 0.0F);
            applyLightingUniforms(
                cylinderLightViewProjection_, cylinderLightDirection_, cylinderShadowMap_,
                cylinderShadowsEnabled_);
            bindSelectionTint(cylinderProgram_, 2);
            glBindVertexArray(halfCylinderVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, halfCylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr,
                halfCylinderCount_);
        }

        if (boxCount_ > 0) {
            glUseProgram(boxProgram_);
            glUniformMatrix4fv(boxViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(boxModel_, 1, GL_FALSE, &modelTransform[0][0]);
            glUniform1f(boxAlpha_, 1.0F);
            glUniform1f(boxEmissive_, 0.0F);
            applyLightingUniforms(
                boxLightViewProjection_, boxLightDirection_, boxShadowMap_,
                boxShadowsEnabled_);
            bindSelectionTint(boxProgram_, 3);
            glBindVertexArray(boxVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, boxDrawCount(), GL_UNSIGNED_SHORT, boxDrawOffset(), boxCount_);
        }

        // Glow and UI do not own design pixels. Keep their color rendering unchanged.
        if (captureIds) glDrawBuffer(GL_COLOR_ATTACHMENT0);

        if (sphereGlowCount_ > 0 || cylinderGlowCount_ > 0 ||
            halfCylinderGlowCount_ > 0 || boxGlowCount_ > 0) {
            glDepthMask(GL_FALSE);
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            if (sphereGlowCount_ > 0) {
                glUseProgram(sphereProgram_);
                glUniformMatrix4fv(
                    sphereViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
                glUniformMatrix4fv(sphereModel_, 1, GL_FALSE, &modelTransform[0][0]);
                glUniform1f(sphereAlpha_, 0.34F);
                glUniform1f(sphereEmissive_, 1.0F);
                applyLightingUniforms(
                    sphereLightViewProjection_, sphereLightDirection_, sphereShadowMap_,
                    sphereShadowsEnabled_);
                glBindVertexArray(sphereGlowVao_);
                glDrawElementsInstanced(
                    GL_TRIANGLES, sphereIndexCount_, GL_UNSIGNED_SHORT, nullptr,
                    sphereGlowCount_);
            }
            if (cylinderGlowCount_ > 0) {
                glUseProgram(cylinderProgram_);
                glUniformMatrix4fv(
                    cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
                glUniformMatrix4fv(
                    cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
                glUniform1f(cylinderAlpha_, 0.34F);
                glUniform1f(cylinderEmissive_, 1.0F);
                applyLightingUniforms(
                    cylinderLightViewProjection_, cylinderLightDirection_,
                    cylinderShadowMap_, cylinderShadowsEnabled_);
                glBindVertexArray(cylinderGlowVao_);
                glDrawElementsInstanced(
                    GL_TRIANGLES, motionCylinderCount(), GL_UNSIGNED_SHORT, motionCylinderOffset(),
                    cylinderGlowCount_);
            }
            if (halfCylinderGlowCount_ > 0) {
                glUseProgram(cylinderProgram_);
                glUniformMatrix4fv(
                    cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
                glUniformMatrix4fv(
                    cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
                glUniform1f(cylinderAlpha_, 0.34F);
                glUniform1f(cylinderEmissive_, 1.0F);
                applyLightingUniforms(
                    cylinderLightViewProjection_, cylinderLightDirection_,
                    cylinderShadowMap_, cylinderShadowsEnabled_);
                glBindVertexArray(halfCylinderGlowVao_);
                glDrawElementsInstanced(
                    GL_TRIANGLES, halfCylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr,
                    halfCylinderGlowCount_);
            }
            if (boxGlowCount_ > 0) {
                glUseProgram(boxProgram_);
                glUniformMatrix4fv(
                    boxViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
                glUniformMatrix4fv(boxModel_, 1, GL_FALSE, &modelTransform[0][0]);
                glUniform1f(boxAlpha_, 0.34F);
                glUniform1f(boxEmissive_, 1.0F);
                applyLightingUniforms(
                    boxLightViewProjection_, boxLightDirection_, boxShadowMap_,
                    boxShadowsEnabled_);
                glBindVertexArray(boxGlowVao_);
                glDrawElementsInstanced(
                    GL_TRIANGLES, boxDrawCount(), GL_UNSIGNED_SHORT, boxDrawOffset(),
                    boxGlowCount_);
            }
            glDisable(GL_BLEND);
            glDepthMask(GL_TRUE);
        }

        renderBendPoints(viewProjection,modelTransform,captureIds);
        renderGuides(viewProjection, guides);
        glBindVertexArray(0);
        glUseProgram(0);
    }

    void renderGuides(
        const glm::mat4& viewProjection, const std::vector<Vertex>& guides,
        const std::array<size_t, 2>* handEnds = nullptr, float lineWidth = 3.0F,
        bool writeDepth = true, bool depthTest = true) const {
        nadoc_vr::CalculationScope auditScope("renderGuides");
        if (!guides.empty()) {
            if (depthTest) glEnable(GL_DEPTH_TEST);
            else glDisable(GL_DEPTH_TEST);
            glDepthMask(writeDepth ? GL_TRUE : GL_FALSE);
            glUseProgram(program_);
            glUniform1i(glGetUniformLocation(program_,"uVolumeCount"),0);
            glUniform1f(glGetUniformLocation(program_,"uVolumeOpacity"),1);
            glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glBindBuffer(GL_ARRAY_BUFFER, guideVbo_);
            glBufferData(GL_ARRAY_BUFFER,
                         static_cast<GLsizeiptr>(guides.size() * sizeof(Vertex)),
                         guides.data(), GL_DYNAMIC_DRAW);
            glBindVertexArray(guideVao_);
            glLineWidth(lineWidth);
            if (handEnds) {
                nadoc_vr::drawClassifiedControllerGuides(guides.size(), *handEnds);
            } else {
                glDrawArrays(GL_LINES, 0, static_cast<GLsizei>(guides.size()));
            }
            glEnable(GL_DEPTH_TEST);
        }
        glDepthMask(GL_TRUE);
        glBindVertexArray(0);
        glUseProgram(0);
    }

  private:

    void prepareDisplayedSource() {
        nadoc_vr::CalculationScope auditScope("prepareDisplayedSource");
        if (displayedSourceValid_ && displayedRepresentation_ == representation_) return;
        displayedRepresentation_ = representation_;
        displayedSource_ = nullptr;
        sourceIndexValid_ = false;
        displayedSourceValid_ = true;
        updateDisplayedGeometry();
    }

    void ensureSourceIndex(const RepresentationData& source) {
        nadoc_vr::CalculationScope auditScope("ensureSourceIndex");
        if (!sourceIndexValid_) {
                const auto prepared=scene_.prepared[static_cast<size_t>(representation_)];
                if(prepared && &source==&scene_.representations[representationSourceIndex(representation_)]) sourceIndex_=prepared->index.get();
                else {
                    auto [index, inserted] = staticSourceIndices_.try_emplace(&source);
                    if (inserted) index->second.rebuild(source);
                    sourceIndex_ = &index->second;
                }
            sourceIndexValid_ = true;
            visualizationDeltasValid_ = false;
        }
        if (visualizationDeltasValid_) return;
        visualizationDeltas_.clear();
        visualizationDeltas_.reserve(visualizationPositions_.size());
        for (const auto& [token, target] : visualizationPositions_) {
            const auto handle = sourceIndex_->toolHandles.find(token);
            if (handle == sourceIndex_->toolHandles.end()) continue;
            glm::vec3 normalized =
                (target - scene_.normalizationCenter) * scene_.normalizationScale;
            normalized.z -= kViewDistanceMeters;
            visualizationDeltas_.emplace(token, normalized - handle->second->center);
        }
        visualizationDeltasValid_ = true;
    }

    void updateDisplayedGeometry() {
        if (!displayedSourceValid_) return;
        const size_t index = representationSourceIndex(representation_);
        const RepresentationData& natural = scene_.representations[index];
        if (displayedSource_ != &natural) sourceIndexValid_ = false;
        displayedSource_ = &natural;
    }

    [[nodiscard]] const RepresentationData& currentSource() const {
        if (!displayedSource_) {
            throw std::runtime_error("VR displayed source is not prepared");
        }
        return *displayedSource_;
    }

    [[nodiscard]] static std::pair<float, float> layerWeights(
        const RepresentationData&, const std::string& identity,
        const std::string& token, const SourceIndex& index) {
        if (token.empty()) return {0.0F, 0.0F};
        const auto ownership = index.ownership.find(identity);
        if (ownership != index.ownership.end()) {
            const auto owner = std::find_if(
                ownership->second->owners.begin(), ownership->second->owners.end(),
                [&](const TransformOwner& candidate) {
                    return candidate.token == token;
                });
            if (owner != ownership->second->owners.end()) {
                return {owner->startWeight, owner->endWeight};
            }
        }
        const auto aliases = index.aliases.find(identity);
        if (aliases == index.aliases.end()) return {0.0F, 0.0F};
        return std::find(
            aliases->second->tokens.begin(), aliases->second->tokens.end(), token)
            == aliases->second->tokens.end()
            ? std::pair(0.0F, 0.0F) : std::pair(1.0F, 1.0F);
    }

    // Rigid edits already have exact endpoint ownership in every cached
    // representation. Keep related pivots current too, without rebuilding a
    // complete scene: moving a cluster moves its Base/Overhang handles; moving
    // one base shifts its parent's centroid by that base's contribution.
    void updateCommittedHandleOffsets() {
        {
            auto& offsets=committedHandleOffsets_;offsets.clear();
            const auto& full=scene_.representations
                [static_cast<size_t>(Representation::full)];
            SourceIndex index;index.rebuild(full);
            std::unordered_map<std::string,size_t> counts;
            for(const auto& point:full.points) {
                if(!point.identity.ends_with(":backbone"))continue;
                const auto aliases=index.aliases.find(point.identity);
                if(aliases==index.aliases.end())continue;
                const float weight=layerWeights(full,point.identity,toolCommittedToken_,index).first;
                const auto delta=nadoc_vr::weightedTransformPoint(point.position,toolCommittedTransform_,weight)-point.position;
                for(const auto& token:aliases->second->tokens) {
                    auto [value,inserted]=offsets.try_emplace(token,glm::vec3(0));
                    value->second+=delta;++counts[token];
                }
            }
            for(auto& [token,delta]:offsets)delta/=float(counts.at(token));
        }
    }

    glm::vec3 committedHandleCenter(const std::string& token,const glm::vec3& center) const {
        if(token==toolCommittedToken_)
            return glm::vec3(toolCommittedTransform_*glm::vec4(center,1));
        const auto found=committedHandleOffsets_.find(token);
        return center+(found==committedHandleOffsets_.end()?glm::vec3(0):found->second);
    }

    void bakeCommittedLayer(RepresentationData& source) {
        if (toolCommittedToken_.empty()) return;
        SourceIndex index;
        index.rebuild(source);
        for (StyledPoint& point : source.points) {
            const float weight = layerWeights(
                source, point.identity, toolCommittedToken_, index).first;
            point.position = nadoc_vr::weightedTransformPoint(
                point.position, toolCommittedTransform_, weight);
        }
        auto bakeCylinders = [&](std::vector<StyledCylinder>& cylinders) {
            for (StyledCylinder& cylinder : cylinders) {
                const auto [startWeight, endWeight] = layerWeights(
                    source, cylinder.identity, toolCommittedToken_, index);
                cylinder.start = nadoc_vr::weightedTransformPoint(
                    cylinder.start, toolCommittedTransform_, startWeight);
                cylinder.end = nadoc_vr::weightedTransformPoint(
                    cylinder.end, toolCommittedTransform_, endWeight);
            }
        };
        bakeCylinders(source.cylinders);
        bakeCylinders(source.halfCylinders);
        for (StyledBox& box : source.boxes) {
            const float weight = layerWeights(
                source, box.identity, toolCommittedToken_, index).first;
            box.center = nadoc_vr::weightedTransformPoint(
                box.center, toolCommittedTransform_, weight);
            box.axisX = nadoc_vr::weightedTransformVector(
                box.axisX, toolCommittedTransform_, weight);
            box.axisY = nadoc_vr::weightedTransformVector(
                box.axisY, toolCommittedTransform_, weight);
            box.axisZ = nadoc_vr::weightedTransformVector(
                box.axisZ, toolCommittedTransform_, weight);
            for (auto& normal : box.normals)
                normal = nadoc_vr::weightedTransformVector(normal, toolCommittedTransform_, weight);
        }
        for (OwnerHandle& handle : source.ownerHandles) {
            handle.center=committedHandleCenter(handle.token,handle.center);
        }
        for (ToolHandle& handle : source.toolHandles) {
            handle.center=committedHandleCenter(handle.token,handle.center);
        }
    }

    void bakeCommittedLayer() {
        cancelPreparedStyle();
        for(auto& prepared:scene_.prepared)prepared.reset();
        for(auto& resident:residentStyles_)resident.reset();
        representationBuffers_.clear();
        staticSourceIndices_.clear();
        for (RepresentationData& source : scene_.representations) {
            bakeCommittedLayer(source);
        }

        committedHandleOffsets_.clear();
        toolCommittedToken_.clear();
        toolCommittedTransform_ = glm::mat4(1.0F);
        displayedSourceValid_ = false;
        sourceIndexValid_ = false;
    }

    [[nodiscard]] std::optional<glm::vec3> visualizationDelta(
        const RepresentationData&, const std::string& token) const {
        const auto delta = visualizationDeltas_.find(token);
        return delta == visualizationDeltas_.end()
            ? std::nullopt : std::optional<glm::vec3>(delta->second);
    }

    [[nodiscard]] std::pair<glm::vec3, glm::vec3> visualizationOffsets(
        const RepresentationData& source, const std::string& identity) const {
        if (visualizationPositions_.empty()) return {};
        const auto ownership = sourceIndex_->ownership.find(identity);
        if (ownership != sourceIndex_->ownership.end()) {
            std::array<nadoc_vr::VisualizationOffsetContribution, 32>
                contributions{};
            size_t contributionCount = 0;
            for (const TransformOwner& owner : ownership->second->owners) {
                if (const auto delta = visualizationDelta(source, owner.token)) {
                    if (contributionCount >= contributions.size()) break;
                    contributions[contributionCount++] = {
                        *delta,
                        owner.startWeight,
                        owner.endWeight,
                        visualizationAtomTokens_.contains(owner.token),
                    };
                }
            }
            if (contributionCount > 0) {
                return nadoc_vr::aggregateVisualizationOffsets(
                    contributions.data(), contributionCount);
            }
        }
        const auto aliases = sourceIndex_->aliases.find(identity);
        if (aliases != sourceIndex_->aliases.end()) {
            for (const std::string& token : aliases->second->tokens) {
                if (const auto delta = visualizationDelta(source, token)) {
                    return {*delta, *delta};
                }
            }
        }
        return {};
    }

    /** Whether every endpoint of an atom primitive has a measured trajectory atom.
     * The native scene starts from NADOC's design topology; NAMD can legitimately
     * omit terminal phosphate atoms. Once an atom feed is active, leaving those
     * unmatched primitives visible would mix reconstructed and measured positions. */
    [[nodiscard]] bool hasCompleteVisualizationAtomEndpoints(
        const RepresentationData&, const std::string& identity) const {
        if (visualizationAtomTokens_.empty()) return true;
        const auto ownership = sourceIndex_->ownership.find(identity);
        if (ownership == sourceIndex_->ownership.end()) return false;
        bool start = false;
        bool end = false;
        for (const TransformOwner& owner : ownership->second->owners) {
            if (!visualizationAtomTokens_.contains(owner.token)) continue;
            start = start || owner.startWeight > 0.0F;
            end = end || owner.endWeight > 0.0F;
        }
        return start && end;
    }

    [[nodiscard]] std::optional<glm::vec3> visualizationColor(
        const RepresentationData&, const std::string& identity) const {
        if (visualizationColors_.empty()) return std::nullopt;
        const auto aliases = sourceIndex_->aliases.find(identity);
        if (aliases != sourceIndex_->aliases.end()) {
            for (const std::string& token : aliases->second->tokens) {
                const auto color = visualizationColors_.find(token);
                if (color != visualizationColors_.end()) return color->second;
            }
        }
        const auto ownership = sourceIndex_->ownership.find(identity);
        if (ownership == sourceIndex_->ownership.end()) return std::nullopt;
        glm::vec3 total{};
        float weight = 0.0F;
        for (const TransformOwner& owner : ownership->second->owners) {
            const auto color = visualizationColors_.find(owner.token);
            if (color == visualizationColors_.end()) continue;
            const float ownerWeight = (owner.startWeight + owner.endWeight) * 0.5F;
            total += color->second * ownerWeight;
            weight += ownerWeight;
        }
        return weight > 0.0F ? std::optional<glm::vec3>(total / weight) : std::nullopt;
    }

    [[nodiscard]] const nadoc_vr::VisualizationPoint* visualizationSlabFrame(
        const RepresentationData&, const std::string& identity) const {
        if (visualizationSlabFrames_.empty()) return nullptr;
        const auto aliases = sourceIndex_->aliases.find(identity);
        if (aliases != sourceIndex_->aliases.end()) {
            for (const std::string& token : aliases->second->tokens) {
                const auto frame = visualizationSlabFrames_.find(token);
                if (frame != visualizationSlabFrames_.end()) return &frame->second;
            }
        }
        const auto ownership = sourceIndex_->ownership.find(identity);
        if (ownership != sourceIndex_->ownership.end()) {
            for (const TransformOwner& owner : ownership->second->owners) {
                const auto frame = visualizationSlabFrames_.find(owner.token);
                if (frame != visualizationSlabFrames_.end()) return &frame->second;
            }
        }
        return nullptr;
    }

    struct DisplayedVisualizationSlabFrame {
        glm::vec3 center{};
        glm::vec3 axisX{};
        glm::vec3 axisY{};
        glm::vec3 axisZ{};
    };

    [[nodiscard]] std::optional<DisplayedVisualizationSlabFrame>
    displayedVisualizationSlabFrame(
        const RepresentationData& source, const std::string& identity) const {
        const auto* frame = visualizationSlabFrame(source, identity);
        if (!frame) return std::nullopt;
        DisplayedVisualizationSlabFrame displayed{
            (frame->slabCenter - scene_.normalizationCenter) *
                scene_.normalizationScale,
            frame->slabAxisX * scene_.normalizationScale,
            frame->slabAxisY * scene_.normalizationScale,
            frame->slabAxisZ * scene_.normalizationScale,
        };
        displayed.center.z -= kViewDistanceMeters;
        const float committed = layerWeights(
            source, identity, toolCommittedToken_, *sourceIndex_).first;
        const float pending = layerWeights(
            source, identity, toolPreviewToken_, *sourceIndex_).first;
        displayed.center = nadoc_vr::weightedTransformPoint(
            displayed.center, toolCommittedTransform_, committed);
        displayed.center = nadoc_vr::weightedTransformPoint(
            displayed.center, toolPreviewTransform_, pending);
        for (glm::vec3* axis : {
                 &displayed.axisX, &displayed.axisY, &displayed.axisZ}) {
            *axis = nadoc_vr::weightedTransformVector(
                *axis, toolCommittedTransform_, committed);
            *axis = nadoc_vr::weightedTransformVector(
                *axis, toolPreviewTransform_, pending);
        }
        return displayed;
    }

    [[nodiscard]] std::pair<float, float> previewWeights(
        const RepresentationData& source, const std::string& identity) const {
        return layerWeights(source, identity, toolPreviewToken_, *sourceIndex_);
    }

    [[nodiscard]] std::pair<float, float> committedWeights(
        const RepresentationData& source, const std::string& identity) const {
        return layerWeights(source, identity, toolCommittedToken_, *sourceIndex_);
    }

    [[nodiscard]] glm::vec3 previewPoint(
        const glm::vec3& point, float committedWeight, float pendingWeight) const {
        const glm::vec3 committed = nadoc_vr::weightedTransformPoint(
            point, toolCommittedTransform_, committedWeight);
        return nadoc_vr::weightedTransformPoint(
            committed, toolPreviewTransform_, pendingWeight);
    }

    [[nodiscard]] glm::vec3 displayedPoint(
        const RepresentationData& source, const glm::vec3& point,
        const std::string& identity, bool end = false) const {
        const auto offsets = visualizationOffsets(source, identity);
        const auto committed = committedWeights(source, identity);
        const auto pending = previewWeights(source, identity);
        return previewPoint(
            point + (end ? offsets.second : offsets.first),
            end ? committed.second : committed.first,
            end ? pending.second : pending.first);
    }

    [[nodiscard]] glm::vec3 previewVector(
        const glm::vec3& vector, float committedWeight, float pendingWeight) const {
        const glm::vec3 committed = nadoc_vr::weightedTransformVector(
            vector, toolCommittedTransform_, committedWeight);
        return nadoc_vr::weightedTransformVector(
            committed, toolPreviewTransform_, pendingWeight);
    }

    void applyLightingUniforms(
        GLint lightProjection, GLint lightDirection, GLint shadowMap,
        GLint shadowsEnabled) const {
        glUniformMatrix4fv(
            lightProjection, 1, GL_FALSE, &lightViewProjection_[0][0]);
        glUniform3fv(lightDirection, 1, &lightDirection_[0]);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, shadowTexture_);
        glUniform1i(shadowMap, 0);
        glUniform1i(shadowsEnabled, motionDetail_.reduced ? 0 : 1);
    }

    void initializeShadowMap() {
        glGenTextures(1, &shadowTexture_);
        glBindTexture(GL_TEXTURE_2D, shadowTexture_);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24,
                     kShadowMapSize, kShadowMapSize, 0,
                     GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
        const GLfloat border[] = {1.0F, 1.0F, 1.0F, 1.0F};
        glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, border);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL);

        glGenFramebuffers(1, &shadowFramebuffer_);
        glBindFramebuffer(GL_FRAMEBUFFER, shadowFramebuffer_);
        glFramebufferTexture2D(
            GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, shadowTexture_, 0);
        glDrawBuffer(GL_NONE);
        glReadBuffer(GL_NONE);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("Could not create VR shadow framebuffer");
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glBindTexture(GL_TEXTURE_2D, 0);
    }

    void uploadSpheres() {
        sphereProgram_ = makeSphereProgram();
        sphereViewProjection_ = glGetUniformLocation(sphereProgram_, "uViewProjection");
        sphereModel_ = glGetUniformLocation(sphereProgram_, "uModel");
        sphereLightViewProjection_ =
            glGetUniformLocation(sphereProgram_, "uLightViewProjection");
        sphereLightDirection_ = glGetUniformLocation(sphereProgram_, "uLightDirection");
        sphereShadowMap_ = glGetUniformLocation(sphereProgram_, "uShadowMap");
        sphereShadowsEnabled_ = glGetUniformLocation(sphereProgram_, "uShadowsEnabled");
        sphereAlpha_ = glGetUniformLocation(sphereProgram_, "uAlpha");
        sphereEmissive_ = glGetUniformLocation(sphereProgram_, "uEmissive");

        std::vector<glm::vec3> mesh = {
            {-1, -1, 0}, {1, -1, 0}, {1, 1, 0}, {-1, 1, 0},
        };
        static constexpr std::array<GLushort, 6> indices = {0, 1, 2, 0, 2, 3};
        sphereIndexCount_ = static_cast<GLsizei>(indices.size());

        glGenVertexArrays(1, &sphereVao_);
        glBindVertexArray(sphereVao_);
        glGenBuffers(1, &sphereMeshVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, sphereMeshVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(mesh.size() * sizeof(glm::vec3)),
                     mesh.data(), GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(glm::vec3), nullptr);
        glGenBuffers(1, &sphereIndexVbo_);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, sphereIndexVbo_);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(indices), indices.data(), GL_STATIC_DRAW);

        glGenBuffers(1, &sphereInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, sphereInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, position)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, size)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, color)));
        for (GLuint attribute = 1; attribute <= 3; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);

        glGenVertexArrays(1, &sphereGlowVao_);
        glBindVertexArray(sphereGlowVao_);
        glBindBuffer(GL_ARRAY_BUFFER, sphereMeshVbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(glm::vec3), nullptr);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, sphereIndexVbo_);
        glGenBuffers(1, &sphereGlowInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, sphereGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, position)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, size)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, color)));
        for (GLuint attribute = 1; attribute <= 3; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);
    }

    void uploadCylinders() {
        cylinderProgram_ = makeCylinderProgram();
        atomisticBondProgram_ = makeAtomisticBondProgram();
        atomisticBondViewProjection_ =
            glGetUniformLocation(atomisticBondProgram_, "uViewProjection");
        atomisticBondModel_ = glGetUniformLocation(atomisticBondProgram_, "uModel");
        cylinderViewProjection_ = glGetUniformLocation(cylinderProgram_, "uViewProjection");
        cylinderModel_ = glGetUniformLocation(cylinderProgram_, "uModel");
        cylinderLightViewProjection_ =
            glGetUniformLocation(cylinderProgram_, "uLightViewProjection");
        cylinderLightDirection_ = glGetUniformLocation(cylinderProgram_, "uLightDirection");
        cylinderShadowMap_ = glGetUniformLocation(cylinderProgram_, "uShadowMap");
        cylinderShadowsEnabled_ =
            glGetUniformLocation(cylinderProgram_, "uShadowsEnabled");
        cylinderAlpha_ = glGetUniformLocation(cylinderProgram_, "uAlpha");
        cylinderEmissive_ = glGetUniformLocation(cylinderProgram_, "uEmissive");

        constexpr size_t sides = 8;
        constexpr float pi = 3.14159265358979323846F;
        std::vector<CylinderMeshVertex> mesh;
        std::vector<GLushort> indices;
        mesh.reserve(sides * 4U + 2U);
        indices.reserve(sides * 12U);
        for (size_t side = 0; side < sides; ++side) {
            const float angle = 2.0F * pi * static_cast<float>(side)
                              / static_cast<float>(sides);
            const glm::vec3 radial(std::cos(angle), std::sin(angle), 0.0F);
            mesh.push_back({{radial.x, radial.y, 0.0F}, radial});
            mesh.push_back({{radial.x, radial.y, 1.0F}, radial});
        }
        for (size_t side = 0; side < sides; ++side) {
            const GLushort bottom = static_cast<GLushort>(side * 2U);
            const GLushort top = static_cast<GLushort>(bottom + 1U);
            const GLushort nextBottom = static_cast<GLushort>(((side + 1U) % sides) * 2U);
            const GLushort nextTop = static_cast<GLushort>(nextBottom + 1U);
            indices.insert(indices.end(), {bottom, top, nextBottom, top, nextTop, nextBottom});
        }

        const GLushort bottomCenter = static_cast<GLushort>(mesh.size());
        mesh.push_back({{0, 0, 0}, {0, 0, -1}});
        const GLushort bottomRing = static_cast<GLushort>(mesh.size());
        for (size_t side = 0; side < sides; ++side) {
            const float angle = 2.0F * pi * static_cast<float>(side)
                              / static_cast<float>(sides);
            mesh.push_back({{std::cos(angle), std::sin(angle), 0}, {0, 0, -1}});
        }
        const GLushort topCenter = static_cast<GLushort>(mesh.size());
        mesh.push_back({{0, 0, 1}, {0, 0, 1}});
        const GLushort topRing = static_cast<GLushort>(mesh.size());
        for (size_t side = 0; side < sides; ++side) {
            const float angle = 2.0F * pi * static_cast<float>(side)
                              / static_cast<float>(sides);
            mesh.push_back({{std::cos(angle), std::sin(angle), 1}, {0, 0, 1}});
        }
        for (size_t side = 0; side < sides; ++side) {
            const GLushort current = static_cast<GLushort>(side);
            const GLushort next = static_cast<GLushort>((side + 1U) % sides);
            indices.insert(indices.end(), {
                bottomCenter,
                static_cast<GLushort>(bottomRing + next),
                static_cast<GLushort>(bottomRing + current),
                topCenter,
                static_cast<GLushort>(topRing + current),
                static_cast<GLushort>(topRing + next),
            });
        }
        cylinderIndexCount_ = static_cast<GLsizei>(indices.size());
        nadoc_vr::MotionDetail::appendCoarseCylinder(indices);

        glGenVertexArrays(1, &cylinderVao_);
        glBindVertexArray(cylinderVao_);
        glGenBuffers(1, &cylinderMeshVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, cylinderMeshVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(mesh.size() * sizeof(CylinderMeshVertex)),
                     mesh.data(), GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glGenBuffers(1, &cylinderIndexVbo_);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cylinderIndexVbo_);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(indices.size() * sizeof(GLushort)),
                     indices.data(), GL_STATIC_DRAW);

        glGenBuffers(1, &cylinderInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, start)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, end)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, radius)));
        glEnableVertexAttribArray(4);
        glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, color)));
        for (GLuint attribute = 1; attribute <= 4; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);

        glGenVertexArrays(1, &atomisticBondVao_);
        glBindVertexArray(atomisticBondVao_);
        glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(
            1, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
            reinterpret_cast<void*>(offsetof(Cylinder, start)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(
            2, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
            reinterpret_cast<void*>(offsetof(Cylinder, end)));
        glEnableVertexAttribArray(4);
        glVertexAttribPointer(
            4, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
            reinterpret_cast<void*>(offsetof(Cylinder, color)));
        for (GLuint attribute : {1U, 2U, 4U}) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);

        glGenVertexArrays(1, &cylinderGlowVao_);
        glBindVertexArray(cylinderGlowVao_);
        glBindBuffer(GL_ARRAY_BUFFER, cylinderMeshVbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cylinderIndexVbo_);
        glGenBuffers(1, &cylinderGlowInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, cylinderGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, start)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, end)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, radius)));
        glEnableVertexAttribArray(4);
        glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, color)));
        for (GLuint attribute = 1; attribute <= 4; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);

    }

    void uploadHalfCylinders() {
        constexpr size_t sides = 8;
        constexpr float pi = 3.14159265358979323846F;
        std::vector<CylinderMeshVertex> mesh;
        std::vector<GLushort> indices;

        // Curved wall on the +X half, matching helix_renderer's GEO_HALF_CYL.
        for (size_t side = 0; side <= sides; ++side) {
            const float angle = -0.5F * pi + pi * static_cast<float>(side)
                              / static_cast<float>(sides);
            const glm::vec3 radial(std::cos(angle), std::sin(angle), 0.0F);
            mesh.push_back({{radial.x, radial.y, 0.0F}, radial});
            mesh.push_back({{radial.x, radial.y, 1.0F}, radial});
        }
        for (size_t side = 0; side < sides; ++side) {
            const GLushort bottom = static_cast<GLushort>(side * 2U);
            const GLushort top = static_cast<GLushort>(bottom + 1U);
            const GLushort nextBottom = static_cast<GLushort>((side + 1U) * 2U);
            const GLushort nextTop = static_cast<GLushort>(nextBottom + 1U);
            indices.insert(indices.end(), {bottom, top, nextBottom, top, nextTop, nextBottom});
        }

        // Flat diametral face closes the trough.
        const GLushort flat = static_cast<GLushort>(mesh.size());
        mesh.insert(mesh.end(), {
            {{0, -1, 0}, {-1, 0, 0}}, {{0, -1, 1}, {-1, 0, 0}},
            {{0, 1, 1}, {-1, 0, 0}}, {{0, 1, 0}, {-1, 0, 0}},
        });
        indices.insert(indices.end(), {
            flat, static_cast<GLushort>(flat + 1), static_cast<GLushort>(flat + 2),
            flat, static_cast<GLushort>(flat + 2), static_cast<GLushort>(flat + 3),
        });

        auto addCap = [&](float z, glm::vec3 normal, bool reverse) {
            const GLushort center = static_cast<GLushort>(mesh.size());
            mesh.push_back({{0, 0, z}, normal});
            const GLushort ring = static_cast<GLushort>(mesh.size());
            for (size_t side = 0; side <= sides; ++side) {
                const float angle = -0.5F * pi + pi * static_cast<float>(side)
                                  / static_cast<float>(sides);
                mesh.push_back({{std::cos(angle), std::sin(angle), z}, normal});
            }
            for (size_t side = 0; side < sides; ++side) {
                const GLushort current = static_cast<GLushort>(ring + side);
                const GLushort next = static_cast<GLushort>(current + 1U);
                if (reverse) indices.insert(indices.end(), {center, next, current});
                else indices.insert(indices.end(), {center, current, next});
            }
        };
        addCap(0.0F, {0, 0, -1}, true);
        addCap(1.0F, {0, 0, 1}, false);
        halfCylinderIndexCount_ = static_cast<GLsizei>(indices.size());

        glGenVertexArrays(1, &halfCylinderVao_);
        glBindVertexArray(halfCylinderVao_);
        glGenBuffers(1, &halfCylinderMeshVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderMeshVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(mesh.size() * sizeof(CylinderMeshVertex)),
                     mesh.data(), GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glGenBuffers(1, &halfCylinderIndexVbo_);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, halfCylinderIndexVbo_);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(indices.size() * sizeof(GLushort)),
                     indices.data(), GL_STATIC_DRAW);

        glGenBuffers(1, &halfCylinderInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, start)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, end)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, radius)));
        glEnableVertexAttribArray(4);
        glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, color)));
        for (GLuint attribute = 1; attribute <= 4; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);

        glGenVertexArrays(1, &halfCylinderGlowVao_);
        glBindVertexArray(halfCylinderGlowVao_);
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderMeshVbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, halfCylinderIndexVbo_);
        glGenBuffers(1, &halfCylinderGlowInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, start)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, end)));
        glEnableVertexAttribArray(3);
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, radius)));
        glEnableVertexAttribArray(4);
        glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, sizeof(Cylinder),
                              reinterpret_cast<void*>(offsetof(Cylinder, color)));
        for (GLuint attribute = 1; attribute <= 4; ++attribute) {
            glVertexAttribDivisor(attribute, 1);
        }
        glBindVertexArray(0);
    }

    GLsizei boxDrawCount() const {
        if (representation_ == Representation::surface || representation_ == Representation::surfaceDetail || representation_ == Representation::hull || representation_ == Representation::cylinders) return 3;
        if (representation_ == Representation::oxdna) return nadoc_vr::ellipsoidIndexCount;
        return boxIndexCount_;
    }
    const void* boxDrawOffset() const {
        const size_t offset = representation_ == Representation::surface || representation_ == Representation::surfaceDetail || representation_ == Representation::hull || representation_ == Representation::cylinders
            ? nadoc_vr::triangleIndexOffset : representation_ == Representation::oxdna ? nadoc_vr::ellipsoidIndexOffset : 0;
        return reinterpret_cast<void*>(offset*sizeof(GLushort));
    }
    void uploadBoxes() {
        boxProgram_ = makeBoxProgram();
        boxViewProjection_ = glGetUniformLocation(boxProgram_, "uViewProjection");
        boxModel_ = glGetUniformLocation(boxProgram_, "uModel");
        boxLightViewProjection_ = glGetUniformLocation(boxProgram_, "uLightViewProjection");
        boxLightDirection_ = glGetUniformLocation(boxProgram_, "uLightDirection");
        boxShadowMap_ = glGetUniformLocation(boxProgram_, "uShadowMap");
        boxShadowsEnabled_ = glGetUniformLocation(boxProgram_, "uShadowsEnabled");
        boxAlpha_ = glGetUniformLocation(boxProgram_, "uAlpha");
        boxEmissive_ = glGetUniformLocation(boxProgram_, "uEmissive");

        std::vector<CylinderMeshVertex> vertices;
        std::vector<GLushort> indices;
        vertices.reserve(24);
        indices.reserve(36);
        auto face = [&](glm::vec3 a, glm::vec3 b, glm::vec3 c, glm::vec3 d,
                        glm::vec3 normal) {
            const GLushort first = static_cast<GLushort>(vertices.size());
            vertices.insert(vertices.end(), {{a, normal}, {b, normal}, {c, normal}, {d, normal}});
            indices.insert(indices.end(), {
                first, static_cast<GLushort>(first + 1), static_cast<GLushort>(first + 2),
                first, static_cast<GLushort>(first + 2), static_cast<GLushort>(first + 3),
            });
        };
        constexpr float n = -0.5F;
        constexpr float p = 0.5F;
        face({p,n,n}, {p,p,n}, {p,p,p}, {p,n,p}, {1,0,0});
        face({n,n,p}, {n,p,p}, {n,p,n}, {n,n,n}, {-1,0,0});
        face({n,p,n}, {n,p,p}, {p,p,p}, {p,p,n}, {0,1,0});
        face({n,n,p}, {n,n,n}, {p,n,n}, {p,n,p}, {0,-1,0});
        face({n,n,p}, {p,n,p}, {p,p,p}, {n,p,p}, {0,0,1});
        face({p,n,n}, {n,n,n}, {n,p,n}, {p,p,n}, {0,0,-1});
        boxIndexCount_ = static_cast<GLsizei>(indices.size());
        nadoc_vr::appendRepresentationMeshes(vertices, indices);

        glGenVertexArrays(1, &boxVao_);
        glBindVertexArray(boxVao_);
        glGenBuffers(1, &boxMeshVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, boxMeshVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(vertices.size() * sizeof(CylinderMeshVertex)),
                     vertices.data(), GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glGenBuffers(1, &boxIndexVbo_);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, boxIndexVbo_);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(indices.size() * sizeof(GLushort)),
                     indices.data(), GL_STATIC_DRAW);

        glGenBuffers(1, &boxInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, boxInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        const std::array<std::pair<GLuint, size_t>, 5> attributes = {{
            {1, offsetof(Box, center)},
            {2, offsetof(Box, axisX)},
            {3, offsetof(Box, axisY)},
            {4, offsetof(Box, axisZ)},
            {6, offsetof(Box, color)},
        }};
        for (const auto& [location, offset] : attributes) {
            glEnableVertexAttribArray(location);
            glVertexAttribPointer(location, 3, GL_FLOAT, GL_FALSE, sizeof(Box),
                                  reinterpret_cast<void*>(offset));
            glVertexAttribDivisor(location, 1);
        }
        glBindVertexArray(0);

        glGenVertexArrays(1, &boxGlowVao_);
        glBindVertexArray(boxGlowVao_);
        glBindBuffer(GL_ARRAY_BUFFER, boxMeshVbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, position)));
        glEnableVertexAttribArray(5);
        glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, sizeof(CylinderMeshVertex),
                              reinterpret_cast<void*>(offsetof(CylinderMeshVertex, normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, boxIndexVbo_);
        glGenBuffers(1, &boxGlowInstanceVbo_);
        glBindBuffer(GL_ARRAY_BUFFER, boxGlowInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER, 0, nullptr, GL_DYNAMIC_DRAW);
        for (const auto& [location, offset] : attributes) {
            glEnableVertexAttribArray(location);
            glVertexAttribPointer(location, 3, GL_FLOAT, GL_FALSE, sizeof(Box),
                                  reinterpret_cast<void*>(offset));
            glVertexAttribDivisor(location, 1);
        }
        glBindVertexArray(0);
    }

    static void upload(const std::vector<Vertex>& vertices, GLuint& vao, GLuint& vbo,
                       GLenum usage = GL_STATIC_DRAW) {
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(
            GL_ARRAY_BUFFER,
            static_cast<GLsizeiptr>(vertices.size() * sizeof(Vertex)),
            vertices.data(),
            usage);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, color)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, size)));
        glBindVertexArray(0);
    }

    GLuint program_ = 0;
    bool renderingVolumes_=false;
    GLuint volumeBuffer_=0,volumeTexture_=0;
    std::vector<glm::vec4> uploadedVolumeData_;
    SceneData scene_;
    bool objectIdsEnabled_ = false;
    std::array<std::unordered_map<std::string,uint32_t>,256> objectIds_;
    std::unordered_map<std::string,uint32_t>& objectIdBucket(const std::string& id){return objectIds_[std::hash<std::string>{}(id)%objectIds_.size()];}
    std::deque<std::string> objectIdentities_{""};

    uint32_t objectId(const std::string& identity) {
        if (!objectIdsEnabled_ || identity.empty() || identity.starts_with("viewer:")) return 0;
        auto& bucket=objectIdBucket(identity);
        const auto found = bucket.find(identity);
        if (found != bucket.end()) return found->second;
        if (objectIdentities_.size() >= std::numeric_limits<uint32_t>::max()) {
            throw std::runtime_error("Object ID capacity exceeded");
        }
        const auto id = static_cast<uint32_t>(objectIdentities_.size());
        bucket.emplace(identity, id);
        objectIdentities_.push_back(identity);
        return id;
    }

    const RepresentationData* displayedSource_ = nullptr;
    std::unordered_map<const RepresentationData*, SourceIndex> staticSourceIndices_;
    SourceIndex* sourceIndex_ = nullptr;
    bool sourceIndexValid_ = false;
    Representation displayedRepresentation_ = Representation::full;
    bool displayedSourceValid_ = false;
    Representation representation_ = Representation::full;
    Coloring coloring_ = Coloring::strand;
    std::string toolCommittedToken_;
    std::unordered_map<std::string,glm::vec3> committedHandleOffsets_;
    glm::mat4 toolCommittedTransform_{1.0F};
    RigidPreviewGeometry previewGeometry_;
    bool packedPreviewEnabled_ = true;
    std::string toolPreviewToken_;
    glm::mat4 toolPreviewTransform_{1.0F};
    std::string visualizationMode_ = "none";
    std::unordered_map<std::string, glm::vec3> visualizationPositions_;
    std::unordered_map<std::string, glm::vec3> visualizationColors_;
    std::unordered_map<std::string, nadoc_vr::VisualizationPoint>
        visualizationSlabFrames_;
    std::unordered_set<std::string> visualizationAtomTokens_;
    std::unordered_map<std::string, size_t> visualizationCoordinateIndex_;
    std::vector<std::string> visualizationCoordinateTokens_;
    std::vector<glm::vec3*> visualizationCoordinatePositions_;
    std::vector<glm::vec3> normalizedCoordinateScratch_;
    std::unordered_map<std::string, glm::vec3> visualizationDeltas_;
    bool visualizationDeltasValid_ = false;
    uint64_t visualizationRevision_ = 0;
    uint64_t uploadedVisualizationRevision_ = std::numeric_limits<uint64_t>::max();
    nadoc_vr::RepresentationBuffers representationBuffers_;
    bool atomisticSharedGeometry_ = false;
    bool atomisticBuffersResident_ = false;
    GLsizei ballstickSphereCount_ = 0;
    std::vector<Vertex> atomisticSphereInstances_;
    std::vector<int32_t> atomisticSphereCoordinateIndices_;
    std::vector<Cylinder> atomisticCylinderInstances_;
    std::vector<std::array<int32_t, 2>> atomisticCylinderCoordinateIndices_;
    uint64_t cachedAtomisticVisualizationRevision_ =
        std::numeric_limits<uint64_t>::max();
    Coloring cachedAtomisticColoring_ = Coloring::strand;
    std::unordered_set<std::string> snapHighlightOwnerTokens_;
    std::unordered_set<std::string> snapHighlightIdentities_;
    std::unordered_set<std::string> selectedHighlightOwnerTokens_;
    std::unordered_set<std::string> selectedHighlightIdentities_;
    nadoc_vr::TimingWindow previewTiming_{240};
    GLuint lineVao_ = 0;
    GLuint lineVbo_ = 0;
    GLuint guideVao_ = 0;
    GLuint guideVbo_ = 0;
    GLuint sphereProgram_ = 0;
    GLuint sphereVao_ = 0;
    GLuint sphereMeshVbo_ = 0;
    GLuint sphereIndexVbo_ = 0;
    GLuint sphereInstanceVbo_ = 0;
    GLuint sphereGlowVao_ = 0;
    GLuint sphereGlowInstanceVbo_ = 0;
    GLuint cylinderProgram_ = 0;
    GLuint atomisticBondProgram_ = 0;
    GLuint atomisticBondVao_ = 0;
    GLuint cylinderVao_ = 0;
    GLuint cylinderMeshVbo_ = 0;
    GLuint cylinderIndexVbo_ = 0;
    GLuint cylinderInstanceVbo_ = 0;
    GLuint cylinderGlowVao_ = 0;
    GLuint cylinderGlowInstanceVbo_ = 0;
    GLuint halfCylinderVao_ = 0;
    GLuint halfCylinderMeshVbo_ = 0;
    GLuint halfCylinderIndexVbo_ = 0;
    GLuint halfCylinderInstanceVbo_ = 0;
    GLuint halfCylinderGlowVao_ = 0;
    GLuint halfCylinderGlowInstanceVbo_ = 0;
    GLuint boxProgram_ = 0;
    GLuint boxVao_ = 0;
    GLuint boxMeshVbo_ = 0;
    GLuint boxIndexVbo_ = 0;
    GLuint boxInstanceVbo_ = 0;
    GLuint boxGlowVao_ = 0;
    GLuint boxGlowInstanceVbo_ = 0;
    GLuint shadowFramebuffer_ = 0;
    GLuint shadowTexture_ = 0;
    GLint viewProjection_ = -1;
    GLint sphereViewProjection_ = -1;
    GLint sphereModel_ = -1;
    GLint sphereLightViewProjection_ = -1;
    GLint sphereLightDirection_ = -1;
    GLint sphereShadowMap_ = -1;
    GLint sphereShadowsEnabled_ = -1;
    GLint sphereAlpha_ = -1;
    GLint sphereEmissive_ = -1;
    GLint cylinderViewProjection_ = -1;
    GLint atomisticBondViewProjection_ = -1;
    GLint atomisticBondModel_ = -1;
    GLint cylinderModel_ = -1;
    GLint cylinderLightViewProjection_ = -1;
    GLint cylinderLightDirection_ = -1;
    GLint cylinderShadowMap_ = -1;
    GLint cylinderShadowsEnabled_ = -1;
    GLint cylinderAlpha_ = -1;
    GLint cylinderEmissive_ = -1;
    GLint boxViewProjection_ = -1;
    GLint boxModel_ = -1;
    GLint boxLightViewProjection_ = -1;
    GLint boxLightDirection_ = -1;
    GLint boxShadowMap_ = -1;
    GLint boxShadowsEnabled_ = -1;
    GLint boxAlpha_ = -1;
    GLint boxEmissive_ = -1;
    GLsizei lineCount_ = 0;
    nadoc_vr::MotionDetail motionDetail_;
    GLsizei sphereIndexCount_ = 0;
    GLsizei sphereCount_ = 0;
    GLsizei sphereGlowCount_ = 0;
    GLsizei cylinderIndexCount_ = 0;
    GLsizei cylinderCount_ = 0;
    GLsizei cylinderGlowCount_ = 0;
    GLsizei halfCylinderIndexCount_ = 0;
    GLsizei halfCylinderCount_ = 0;
    GLsizei halfCylinderGlowCount_ = 0;
    GLsizei boxIndexCount_ = 0;
    GLsizei boxCount_ = 0;
    GLsizei boxGlowCount_ = 0;
    glm::vec3 localCenter_{0.0F, 0.0F, -kViewDistanceMeters};
    float localRadius_ = 0.5F;
    glm::mat4 lightViewProjection_{1.0F};
    glm::vec3 lightDirection_{-0.577F, 0.577F, 0.577F};
    static constexpr GLsizei kShadowMapSize = nadoc_vr::kShadowMapResolution;
};

struct DeformationPlanePose {
    glm::vec3 center{};
    glm::vec3 normal{};
    float halfExtent = 0.0F;
};

struct DeformationPlaneGuide {
    DeformationPlanePose natural;
};

struct DesktopVertex {
    glm::vec3 position{};
    glm::vec2 uv{};
};

/** X11 desktop capture and input owned by NADOC rather than Steam's browser bridge.
 *
 * SteamVR's native Dashboard remains available, but its Linux Desktop surface can
 * exist as a blank overlay when Steam's XComposite browser window loses its XID.
 * This small fallback captures the real X11 root and injects ordinary pointer input,
 * keeping the desktop usable inside the same controller-mounted tablet.
 */
int benchmarkAtomisticStyles(
    const std::string& scenePath, const std::string& visualizationPath) {
    const auto started = std::chrono::steady_clock::now();
    std::cout << "VR_METRIC event=process_start mode=benchmark_atomistic_styles"
              << " rss_mib=" << currentResidentMiB() << std::endl;
    SceneData scene = loadScene(scenePath);
    nadoc_vr::VisualizationSnapshot visualization;
    if (!visualizationPath.empty()) {
        visualization = nadoc_vr::loadVisualizationSnapshot(visualizationPath);
    } else {
        visualization.sequence = 1;
        visualization.mode = "namd_display";
        visualization.representation = "ballstick";
        visualization.coloring = "cpk";
        const RepresentationData& atomistic = scene.representations[
            static_cast<size_t>(Representation::ballstick)];
        std::unordered_set<std::string> tokens;
        tokens.reserve(atomistic.toolHandles.size());
        visualization.points.reserve(atomistic.toolHandles.size());
        for (const ToolHandle& handle : atomistic.toolHandles) {
            if (handle.kind != "atom" || !tokens.insert(handle.token).second) continue;
            glm::vec3 sourcePosition = handle.center;
            sourcePosition.z += kViewDistanceMeters;
            sourcePosition = sourcePosition / scene.normalizationScale
                           + scene.normalizationCenter;
            visualization.points.push_back(nadoc_vr::VisualizationPoint{
                handle.token, sourcePosition});
        }
    }
    std::cout << "VR_METRIC event=process_progress phase=visualization_ready"
              << " points=" << visualization.points.size()
              << " rss_mib=" << currentResidentMiB() << std::endl;

    if (!glfwInit()) throw std::runtime_error("GLFW initialization failed");
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    GLFWwindow* window = glfwCreateWindow(64, 64, "NADOC VR benchmark", nullptr, nullptr);
    if (!window) {
        glfwTerminate();
        throw std::runtime_error("Could not create the benchmark OpenGL context");
    }
    glfwMakeContextCurrent(window);
    try {
        {
            GlScene glScene(std::move(scene));
            glScene.setVisualization(visualization);
            glScene.setStyle(Representation::stick, Coloring::cpk);
            glScene.setStyle(Representation::ballstick, Coloring::cpk);
            glFinish();
            std::vector<std::array<float, 3>> coordinates;
            coordinates.reserve(visualization.points.size());
            for (const auto& point : visualization.points) {
                coordinates.push_back({point.position.x, point.position.y, point.position.z});
            }
            std::vector<double> frameMilliseconds;
            std::vector<double> cpuMilliseconds;
            std::vector<double> uploadMilliseconds;
            constexpr size_t benchmarkFrames = 40;
            for (size_t frame = 0; frame < benchmarkFrames; ++frame) {
                const float offset = (frame & 1U) == 0U ? 0.0001F : -0.0001F;
                for (auto& position : coordinates) position[0] += offset;
                double cpu = 0.0;
                double upload = 0.0;
                const auto frameStarted = std::chrono::steady_clock::now();
                if (!glScene.updateAtomCoordinates(coordinates, &cpu, &upload)) {
                    throw std::runtime_error("coordinate fast path rejected benchmark frame");
                }
                glFinish();
                const double total = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - frameStarted).count();
                if (frame >= 5U) {
                    frameMilliseconds.push_back(total);
                    cpuMilliseconds.push_back(cpu);
                    uploadMilliseconds.push_back(upload);
                }
            }
            auto percentile = [](std::vector<double> values, double quantile) {
                std::sort(values.begin(), values.end());
                const size_t index = static_cast<size_t>(std::floor(
                    quantile * static_cast<double>(values.size() - 1U)));
                return values[index];
            };
            std::cout << "VR_METRIC event=process_end phase=coordinate_benchmark"
                      << " frames=" << frameMilliseconds.size()
                      << " atoms=" << coordinates.size()
                      << " payload_bytes=" << coordinates.size() * 12U
                      << " cpu_p50_ms=" << percentile(cpuMilliseconds, 0.50)
                      << " cpu_p95_ms=" << percentile(cpuMilliseconds, 0.95)
                      << " upload_submit_p50_ms=" << percentile(uploadMilliseconds, 0.50)
                      << " upload_submit_p95_ms=" << percentile(uploadMilliseconds, 0.95)
                      << " gpu_complete_p50_ms=" << percentile(frameMilliseconds, 0.50)
                      << " gpu_complete_p95_ms=" << percentile(frameMilliseconds, 0.95)
                      << " gpu_complete_max_ms="
                      << *std::max_element(frameMilliseconds.begin(), frameMilliseconds.end())
                      << " rss_mib=" << currentResidentMiB() << std::endl;
            glScene.setStyle(Representation::full, Coloring::cpk);
            if (glScene.updateAtomCoordinates(coordinates)) {
                throw std::runtime_error(
                    "atom-only coordinate frame was accepted in Full representation");
            }
            glScene.setStyle(Representation::ballstick, Coloring::cpk);
            glFinish();
        }
        glfwDestroyWindow(window);
        glfwTerminate();
    } catch (...) {
        glfwDestroyWindow(window);
        glfwTerminate();
        throw;
    }
    const double milliseconds = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    std::cout << "VR_METRIC event=process_end mode=benchmark_atomistic_styles"
              << " status=ok elapsed_ms=" << milliseconds
              << " rss_mib=" << currentResidentMiB() << std::endl;
    return 0;
}

class DesktopSurface {
  public:
    GLuint presenterTexture() const {return textureReady_?texture_:0;}
    uint64_t presenterVersion() const {return presenterVersion_;}
    void initialize(Display* display) {
        display_ = display;
        root_ = DefaultRootWindow(display_);
        XWindowAttributes attributes{};
        if (XGetWindowAttributes(display_, root_, &attributes) &&
            attributes.width > 0 && attributes.height > 0) {
            width_ = attributes.width;
            height_ = attributes.height;
        }
        program_ = makeDesktopProgram();
        viewProjection_ = glGetUniformLocation(program_, "uViewProjection");
        textureUniform_ = glGetUniformLocation(program_, "uDesktop");
        pointerUniform_ = glGetUniformLocation(program_, "uPointer");
        pointerVisibleUniform_ = glGetUniformLocation(program_, "uPointerVisible");
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(DesktopVertex) * 4, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(
            0, 3, GL_FLOAT, GL_FALSE, sizeof(DesktopVertex),
            reinterpret_cast<void*>(offsetof(DesktopVertex, position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(
            1, 2, GL_FLOAT, GL_FALSE, sizeof(DesktopVertex),
            reinterpret_cast<void*>(offsetof(DesktopVertex, uv)));
        glBindVertexArray(0);
        glGenTextures(1, &texture_);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);

        xtestLibrary_ = dlopen("libXtst.so.6", RTLD_LAZY | RTLD_LOCAL);
        if (xtestLibrary_) {
            fakeMotion_ = reinterpret_cast<FakeMotion>(
                dlsym(xtestLibrary_, "XTestFakeMotionEvent"));
            fakeButton_ = reinterpret_cast<FakeButton>(
                dlsym(xtestLibrary_, "XTestFakeButtonEvent"));
        }
    }

    void shutdown() {
        if (texture_) glDeleteTextures(1, &texture_);
        if (vbo_) glDeleteBuffers(1, &vbo_);
        if (vao_) glDeleteVertexArrays(1, &vao_);
        if (program_) glDeleteProgram(program_);
        texture_ = vbo_ = vao_ = program_ = 0;
        if (xtestLibrary_) dlclose(xtestLibrary_);
        xtestLibrary_ = nullptr;
        fakeMotion_ = nullptr;
        fakeButton_ = nullptr;
        display_ = nullptr;
    }

    void setPointer(const glm::vec2& uv, bool inject = true) {
        pointer_ = glm::clamp(uv, glm::vec2(0.0F), glm::vec2(1.0F));
        pointerVisible_ = true;
        if (!inject || !display_ || width_ <= 0 || height_ <= 0) return;
        const int x = static_cast<int>(std::round(pointer_.x * (width_ - 1)));
        const int y = static_cast<int>(std::round(pointer_.y * (height_ - 1)));
        if (x == pointerX_ && y == pointerY_) return;
        pointerX_ = x;
        pointerY_ = y;
        if (fakeMotion_) fakeMotion_(display_, -1, x, y, CurrentTime);
        else XWarpPointer(display_, None, root_, 0, 0, 0, 0, x, y);
        XFlush(display_);
    }

    void hidePointer() { pointerVisible_ = false; }

    [[nodiscard]] float aspectRatio() const {
        return width_ > 0 && height_ > 0
            ? static_cast<float>(width_) / static_cast<float>(height_)
            : 16.0F / 9.0F;
    }

    void click() { button(1); }
    void scroll(bool upward) { button(upward ? 4U : 5U); }

    void update(bool visible) {
        if (!visible || !display_) return;
        const auto now = std::chrono::steady_clock::now();
        if (textureReady_ && now - lastCapture_ < std::chrono::milliseconds(80)) return;
        lastCapture_ = now;
        XWindowAttributes attributes{};
        if (!XGetWindowAttributes(display_, root_, &attributes) ||
            attributes.width <= 0 || attributes.height <= 0) {
            return;
        }
        XImage* image = XGetImage(
            display_, root_, 0, 0,
            static_cast<unsigned int>(attributes.width),
            static_cast<unsigned int>(attributes.height), AllPlanes, ZPixmap);
        if (!image) return;
        if (image->bits_per_pixel == 32) {
            const bool resized = width_ != image->width || height_ != image->height;
            width_ = image->width;
            height_ = image->height;
            glBindTexture(GL_TEXTURE_2D, texture_);
            glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
            glPixelStorei(GL_UNPACK_ROW_LENGTH, image->bytes_per_line / 4);
            if (resized || !textureReady_) {
                glTexImage2D(
                    GL_TEXTURE_2D, 0, GL_RGBA8, width_, height_, 0,
                    GL_BGRA, GL_UNSIGNED_BYTE, image->data);
            } else {
                glTexSubImage2D(
                    GL_TEXTURE_2D, 0, 0, 0, width_, height_,
                    GL_BGRA, GL_UNSIGNED_BYTE, image->data);
            }
            glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
            glBindTexture(GL_TEXTURE_2D, 0);
            textureReady_ = true; ++presenterVersion_;
        }
        XDestroyImage(image);
    }

    void render(const glm::mat4& viewProjection,
                const std::array<glm::vec3, 4>& corners, bool magnifying = false) const {
        if (!textureReady_) return;
        const std::array<DesktopVertex, 4> vertices = {{
            {corners[0], {0.0F, 0.0F}},
            {corners[1], {0.0F, 1.0F}},
            {corners[2], {1.0F, 0.0F}},
            {corners[3], {1.0F, 1.0F}},
        }};
        // The desktop is a world-space tablet, not a compositor overlay.  Keep
        // depth testing/writes enabled so nearby scene geometry and the panel
        // obey the same occlusion cues in both eyes.
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glUseProgram(program_);
        glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
        glUniform2fv(pointerUniform_, 1, &pointer_[0]);
        glUniform1i(pointerVisibleUniform_, pointerVisible_ ? 1 : 0);
        glUniform1i(glGetUniformLocation(program_, "uMagnifying"), magnifying ? 1 : 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glUniform1i(textureUniform_, 0);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferSubData(GL_ARRAY_BUFFER, 0, sizeof(vertices), vertices.data());
        glBindVertexArray(vao_);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        glBindVertexArray(0);
        glBindTexture(GL_TEXTURE_2D, 0);
        glUseProgram(0);
    }

  private:
    using FakeMotion = int (*)(Display*, int, int, int, unsigned long);
    using FakeButton = int (*)(Display*, unsigned int, Bool, unsigned long);

    void button(unsigned int number) {
        if (!display_ || !fakeButton_) return;
        fakeButton_(display_, number, True, CurrentTime);
        fakeButton_(display_, number, False, CurrentTime);
        XFlush(display_);
    }

    Display* display_ = nullptr;
    Window root_ = None;
    void* xtestLibrary_ = nullptr;
    FakeMotion fakeMotion_ = nullptr;
    FakeButton fakeButton_ = nullptr;
    GLuint program_ = 0;
    GLuint vao_ = 0;
    GLuint vbo_ = 0;
    GLuint texture_ = 0;
    GLint viewProjection_ = -1;
    GLint textureUniform_ = -1;
    GLint pointerUniform_ = -1;
    GLint pointerVisibleUniform_ = -1;
    int width_ = 0;
    int height_ = 0;
    int pointerX_ = -1;
    int pointerY_ = -1;
    uint64_t presenterVersion_=0;
    bool textureReady_ = false;
    bool pointerVisible_ = false;
    glm::vec2 pointer_{0.5F, 0.5F};
    std::chrono::steady_clock::time_point lastCapture_{};
};

/** Cached, multisampled tablet UI rendered as one depth-tested world quad. */
class MenuPanelSurface {
  public:
    GLuint presenterTexture() const {return ready_?texture_:0;}
    struct CacheStats {
        uint64_t updates = 0;
        uint64_t hits = 0;
        double lastUpdateMilliseconds = 0.0;
        size_t guideVertices = 0;
        int width = 0;
        int height = 0;
        int samples = 1;
    };

    void initialize() {
        lineProgram_ = makeProgram();
        lineProjection_ = glGetUniformLocation(lineProgram_, "uViewProjection");
        panelProgram_ = makeMenuPanelProgram();
        panelProjection_ = glGetUniformLocation(panelProgram_, "uViewProjection");
        panelTextureUniform_ = glGetUniformLocation(panelProgram_, "uPanel");

        glGenVertexArrays(1, &lineVao_);
        glGenBuffers(1, &lineVbo_);
        glBindVertexArray(lineVao_);
        glBindBuffer(GL_ARRAY_BUFFER, lineVbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(
            0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
            reinterpret_cast<void*>(offsetof(Vertex, position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(
            1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
            reinterpret_cast<void*>(offsetof(Vertex, color)));

        glGenVertexArrays(1, &panelVao_);
        glGenBuffers(1, &panelVbo_);
        glBindVertexArray(panelVao_);
        glBindBuffer(GL_ARRAY_BUFFER, panelVbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(DesktopVertex) * 4, nullptr, GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(
            0, 3, GL_FLOAT, GL_FALSE, sizeof(DesktopVertex),
            reinterpret_cast<void*>(offsetof(DesktopVertex, position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(
            1, 2, GL_FLOAT, GL_FALSE, sizeof(DesktopVertex),
            reinterpret_cast<void*>(offsetof(DesktopVertex, uv)));
        glBindVertexArray(0);

        glGenFramebuffers(1, &multisampleFramebuffer_);
        glGenFramebuffers(1, &resolveFramebuffer_);
        glGenRenderbuffers(1, &multisampleColor_);
        glGenTextures(1, &texture_);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);

        GLint maximumSamples = 1;
        glGetIntegerv(GL_MAX_SAMPLES, &maximumSamples);
        samples_ = std::max(1, std::min(4, maximumSamples));
        stats_.samples = samples_;
    }

    void shutdown() {
        if (texture_) glDeleteTextures(1, &texture_);
        if (multisampleColor_) glDeleteRenderbuffers(1, &multisampleColor_);
        if (resolveFramebuffer_) glDeleteFramebuffers(1, &resolveFramebuffer_);
        if (multisampleFramebuffer_) glDeleteFramebuffers(1, &multisampleFramebuffer_);
        if (panelVbo_) glDeleteBuffers(1, &panelVbo_);
        if (panelVao_) glDeleteVertexArrays(1, &panelVao_);
        if (lineVbo_) glDeleteBuffers(1, &lineVbo_);
        if (lineVao_) glDeleteVertexArrays(1, &lineVao_);
        if (panelProgram_) glDeleteProgram(panelProgram_);
        if (lineProgram_) glDeleteProgram(lineProgram_);
        texture_ = multisampleColor_ = resolveFramebuffer_ = multisampleFramebuffer_ = 0;
        panelVbo_ = panelVao_ = lineVbo_ = lineVao_ = 0;
        panelProgram_ = lineProgram_ = 0;
        ready_ = false;
    }

    bool update(
        const std::vector<Vertex>& localGuides,
        const nadoc_vr::MenuPanelBounds& bounds, bool transparentBackground,
        const std::vector<Vertex>& fills = {}) {
        const uint64_t contentHash = hash(localGuides, bounds, transparentBackground)
            ^ (hash(fills, bounds, false) << 1);
        if (ready_ && contentHash == contentHash_) {
            ++stats_.hits;
            return false;
        }
        const auto started = std::chrono::steady_clock::now();
        const float aspect = std::max(
            (bounds.maximum.x - bounds.minimum.x) /
                std::max(bounds.maximum.y - bounds.minimum.y, 1.0e-4F),
            0.25F);
        constexpr int kTextureHeight = 1536;
        const int width = std::clamp(
            static_cast<int>(std::lround(kTextureHeight * aspect)), 512, 2048);
        // Keep equal texel density on both axes after the width cap. Stretching
        // a 2048x1536 cache across a wide desktop overfilters thin text in mipmaps.
        const int height = std::max(1, static_cast<int>(std::lround(width / aspect)));
        GLint previousDrawFramebuffer = 0;
        GLint previousReadFramebuffer = 0;
        std::array<GLint, 4> previousViewport{};
        std::array<GLfloat, 4> previousClearColor{};
        GLfloat previousLineWidth = 1.0F;
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previousDrawFramebuffer);
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previousReadFramebuffer);
        glGetIntegerv(GL_VIEWPORT, previousViewport.data());
        glGetFloatv(GL_COLOR_CLEAR_VALUE, previousClearColor.data());
        glGetFloatv(GL_LINE_WIDTH, &previousLineWidth);
        const GLboolean depthEnabled = glIsEnabled(GL_DEPTH_TEST);
        const GLboolean blendEnabled = glIsEnabled(GL_BLEND);
        const GLboolean multisampleEnabled = glIsEnabled(GL_MULTISAMPLE);

        allocate(width, height);
        glBindFramebuffer(GL_FRAMEBUFFER, multisampleFramebuffer_);
        glViewport(0, 0, width_, height_);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
        if (samples_ > 1) glEnable(GL_MULTISAMPLE);
        if (transparentBackground) glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
        else glClearColor(0.026F, 0.046F, 0.078F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT);
        if (!fills.empty()) {
            const glm::mat4 projection = glm::ortho(bounds.minimum.x, bounds.maximum.x,
                bounds.minimum.y, bounds.maximum.y, -1.0F, 1.0F);
            glUseProgram(lineProgram_);
            glUniformMatrix4fv(lineProjection_, 1, GL_FALSE, &projection[0][0]);
            glBindBuffer(GL_ARRAY_BUFFER, lineVbo_);
            glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(fills.size()*sizeof(Vertex)), fills.data(), GL_DYNAMIC_DRAW);
            glBindVertexArray(lineVao_);
            glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(fills.size()));
        }
        if (!localGuides.empty()) {
            const glm::mat4 projection = glm::ortho(
                bounds.minimum.x, bounds.maximum.x,
                bounds.minimum.y, bounds.maximum.y, -1.0F, 1.0F);
            glUseProgram(lineProgram_);
            glUniformMatrix4fv(lineProjection_, 1, GL_FALSE, &projection[0][0]);
            glBindBuffer(GL_ARRAY_BUFFER, lineVbo_);
            glBufferData(
                GL_ARRAY_BUFFER,
                static_cast<GLsizeiptr>(localGuides.size() * sizeof(Vertex)),
                localGuides.data(), GL_DYNAMIC_DRAW);
            glBindVertexArray(lineVao_);
            glLineWidth(4.0F);
            glDrawArrays(GL_LINES, 0, static_cast<GLsizei>(localGuides.size()));
        }

        glBindFramebuffer(GL_READ_FRAMEBUFFER, multisampleFramebuffer_);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, resolveFramebuffer_);
        glBlitFramebuffer(
            0, 0, width_, height_, 0, 0, width_, height_,
            GL_COLOR_BUFFER_BIT, GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glGenerateMipmap(GL_TEXTURE_2D);
        glBindTexture(GL_TEXTURE_2D, 0);

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previousDrawFramebuffer);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, previousReadFramebuffer);
        glViewport(previousViewport[0], previousViewport[1],
                   previousViewport[2], previousViewport[3]);
        glClearColor(previousClearColor[0], previousClearColor[1],
                     previousClearColor[2], previousClearColor[3]);
        glLineWidth(previousLineWidth);
        if (depthEnabled) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
        if (blendEnabled) glEnable(GL_BLEND); else glDisable(GL_BLEND);
        if (multisampleEnabled) glEnable(GL_MULTISAMPLE); else glDisable(GL_MULTISAMPLE);
        glBindVertexArray(0);
        glUseProgram(0);

        contentHash_ = contentHash;
        transparent_ = transparentBackground;
        ready_ = true;
        ++stats_.updates;
        stats_.guideVertices = localGuides.size();
        stats_.lastUpdateMilliseconds = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - started).count();
        return true;
    }

    void render(
        const glm::mat4& viewProjection,
        const nadoc_vr::MenuPlacement& placement,
        const nadoc_vr::MenuPanelBounds& bounds, float localDepth = 0.002F, bool frosted = true) const {
        if (!ready_) return;
        const std::array<DesktopVertex, 4> vertices = {{
            {placement.worldPoint({bounds.minimum.x, bounds.maximum.y, localDepth}),
             {0.0F, 1.0F}},
            {placement.worldPoint({bounds.minimum.x, bounds.minimum.y, localDepth}),
             {0.0F, 0.0F}},
            {placement.worldPoint({bounds.maximum.x, bounds.maximum.y, localDepth}),
             {1.0F, 1.0F}},
            {placement.worldPoint({bounds.maximum.x, bounds.minimum.y, localDepth}),
             {1.0F, 0.0F}},
        }};
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        if (transparent_) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        } else {
            glDisable(GL_BLEND);
        }
        glUseProgram(panelProgram_);
        FrostedGlass::bind(panelProgram_, frosted);
        glUniformMatrix4fv(panelProjection_, 1, GL_FALSE, &viewProjection[0][0]);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glUniform1i(panelTextureUniform_, 0);
        glUniform1i(glGetUniformLocation(panelProgram_, "uTransparentPanel"), transparent_);
        glBindBuffer(GL_ARRAY_BUFFER, panelVbo_);
        glBufferSubData(GL_ARRAY_BUFFER, 0, sizeof(vertices), vertices.data());
        glBindVertexArray(panelVao_);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        glBindVertexArray(0);
        glBindTexture(GL_TEXTURE_2D, 0);
        glUseProgram(0);
        glDisable(GL_BLEND);
    }

    [[nodiscard]] const CacheStats& stats() const { return stats_; }

  private:
    static uint64_t mixHash(uint64_t value, int64_t component) {
        value ^= static_cast<uint64_t>(component);
        value *= 1099511628211ULL;
        return value;
    }

    static int64_t quantized(float value) {
        return static_cast<int64_t>(std::llround(static_cast<double>(value) * 100000.0));
    }

    static uint64_t hash(
        const std::vector<Vertex>& guides,
        const nadoc_vr::MenuPanelBounds& bounds, bool transparent) {
        uint64_t value = 1469598103934665603ULL;
        value = mixHash(value, transparent ? 1 : 0);
        value = mixHash(value, quantized(bounds.minimum.x));
        value = mixHash(value, quantized(bounds.minimum.y));
        value = mixHash(value, quantized(bounds.maximum.x));
        value = mixHash(value, quantized(bounds.maximum.y));
        value = mixHash(value, static_cast<int64_t>(guides.size()));
        for (const Vertex& guide : guides) {
            value = mixHash(value, quantized(guide.position.x));
            value = mixHash(value, quantized(guide.position.y));
            value = mixHash(value, quantized(guide.position.z));
            value = mixHash(value, quantized(guide.color.r));
            value = mixHash(value, quantized(guide.color.g));
            value = mixHash(value, quantized(guide.color.b));
        }
        return value;
    }

    void allocate(int width, int height) {
        if (width_ == width && height_ == height) return;
        width_ = width;
        height_ = height;
        glBindRenderbuffer(GL_RENDERBUFFER, multisampleColor_);
        if (samples_ > 1) {
            glRenderbufferStorageMultisample(
                GL_RENDERBUFFER, samples_, GL_RGBA8, width_, height_);
        } else {
            glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, width_, height_);
        }
        glBindFramebuffer(GL_FRAMEBUFFER, multisampleFramebuffer_);
        glFramebufferRenderbuffer(
            GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, multisampleColor_);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("OpenGL multisampled menu framebuffer is incomplete");
        }

        glBindTexture(GL_TEXTURE_2D, texture_);
        glTexImage2D(
            GL_TEXTURE_2D, 0, GL_RGBA8, width_, height_, 0,
            GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glBindFramebuffer(GL_FRAMEBUFFER, resolveFramebuffer_);
        glFramebufferTexture2D(
            GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture_, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("OpenGL resolved menu framebuffer is incomplete");
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glBindRenderbuffer(GL_RENDERBUFFER, 0);
        glBindTexture(GL_TEXTURE_2D, 0);
        stats_.width = width_;
        stats_.height = height_;
    }

    GLuint lineProgram_ = 0;
    GLuint lineVao_ = 0;
    GLuint lineVbo_ = 0;
    GLuint panelProgram_ = 0;
    GLuint panelVao_ = 0;
    GLuint panelVbo_ = 0;
    GLuint multisampleFramebuffer_ = 0;
    GLuint resolveFramebuffer_ = 0;
    GLuint multisampleColor_ = 0;
    GLuint texture_ = 0;
    GLint lineProjection_ = -1;
    GLint panelProjection_ = -1;
    GLint panelTextureUniform_ = -1;
    int width_ = 0;
    int height_ = 0;
    int samples_ = 1;
    bool ready_ = false;
    bool transparent_ = false;
    uint64_t contentHash_ = 0;
    CacheStats stats_{};
};

class GpuFrameTimer {
  public:
    struct Report {
        bool menuOpen = false;
        nadoc_vr::TimingSummary summary;
    };

    void initialize() {
        glGenQueries(static_cast<GLsizei>(slots_.size()), queries_.data());
    }

    void shutdown() {
        if (queries_[0]) {
            glDeleteQueries(static_cast<GLsizei>(queries_.size()), queries_.data());
        }
        queries_.fill(0);
        active_.reset();
    }

    void begin(bool menuOpen) {
        if (active_) return;
        collect();
        for (size_t offset = 0; offset < slots_.size(); ++offset) {
            const size_t index = (next_ + offset) % slots_.size();
            if (slots_[index].pending) continue;
            glBeginQuery(GL_TIME_ELAPSED, queries_[index]);
            slots_[index] = {true, menuOpen, std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count()};
            active_ = index;
            next_ = (index + 1U) % slots_.size();
            return;
        }
        ++skipped_;
    }

    void end() {
        if (!active_) return;
        glEndQuery(GL_TIME_ELAPSED);
        active_.reset();
    }

    void collect() {
        for (size_t index = 0; index < slots_.size(); ++index) {
            if (!slots_[index].pending || active_ == index) continue;
            GLint available = GL_FALSE;
            glGetQueryObjectiv(queries_[index], GL_QUERY_RESULT_AVAILABLE, &available);
            if (available != GL_TRUE) continue;
            GLuint64 nanoseconds = 0;
            glGetQueryObjectui64v(queries_[index], GL_QUERY_RESULT, &nanoseconds);
            if(nanoseconds>8000000)nadoc_vr::TraceRecord{}<<"VR_GPU_TRACE epoch_ms="<<std::fixed<<slots_[index].epochMs<<" gpu_ms="<<double(nanoseconds)/1e6<<'\n';
            auto& window = slots_[index].menuOpen ? menuOpenTiming_ : menuClosedTiming_;
            if (window.add(static_cast<double>(nanoseconds) / 1.0e6)) {
                if (const auto summary = window.takeSummary()) {
                    reports_.push_back({slots_[index].menuOpen, *summary});
                }
            }
            slots_[index].pending = false;
        }
    }

    [[nodiscard]] std::vector<Report> takeReports() {
        collect();
        std::vector<Report> result;
        result.swap(reports_);
        return result;
    }

    [[nodiscard]] uint64_t skipped() const { return skipped_; }

  private:
    struct Slot {
        bool pending = false;
        bool menuOpen = false;
        double epochMs=0;
    };
    std::array<GLuint, 16> queries_{};
    std::array<Slot, 16> slots_{};
    std::optional<size_t> active_;
    size_t next_ = 0;
    uint64_t skipped_ = 0;
    nadoc_vr::TimingWindow menuOpenTiming_{120};
    nadoc_vr::TimingWindow menuClosedTiming_{120};
    std::vector<Report> reports_;
};

#include "sidebar_runtime.hpp"

#include "view_tools.hpp"

#include "component_gallery_desktop.hpp"
#include "startup_loading.hpp"
#include "scene_retirement.hpp"
#include "representation_loading.hpp"

class Viewer {
#ifdef NADOC_SCRYWRITE_TESTING
    friend struct LiveViewerTest;
#endif
  public:
    void enableComponentGallery(bool buttons=false,bool cards=false) { componentGallery_.active=true;componentGallery_.buttonMode=buttons;componentGallery_.cardMode=cards; }
    void loadControllerPath(const std::string& path) { controllerPaths_.load(path); }

    explicit Viewer(SceneData scene, std::string eventPath = {},
                    std::string feedbackPath = {},
                    std::string toolFeedbackPath = {},
                    std::string planeFeedbackPath = {},
                    std::string preflightFeedbackPath = {},
                    std::string toolExecutionFeedbackPath = {},
                    std::string jobPath = {},
                    nadoc_vr::JobSnapshot jobSnapshot = {},
                    std::string visualizationPath = {},
                    nadoc_vr::VisualizationSnapshot visualizationSnapshot = {},
                    std::string trajectoryPath = {},
                    std::string coordinatePath = {},
                    std::string selectionLevel = "default",
                    std::vector<std::string> selectedOwnerTokens = {},
                    std::string selectedSelectionKind = "none",
                    std::string witnessPath = {},
                    nadoc_vr::SpectatorMirrorEye mirrorEye =
                        nadoc_vr::SpectatorMirrorEye::off,
                    bool referenceGrid = false,
                    bool placeSceneInView = false,
                    nadoc_vr::SceneViewPlacement sceneViewPlacement = {},
                    std::string mirrorDiagnosticsPath = {},
                    std::string witnessCaptureDirectory = {},
                    std::string witnessVisualExpectationDirectory = {},
                    bool exitOnWitnessComplete = false,
                    std::string liveSocketPath = {}, std::string liveMode = "inspect")
        : sceneData_(std::move(scene)), eventPath_(std::move(eventPath)),
          feedbackPath_(std::move(feedbackPath)),
          toolFeedbackPath_(std::move(toolFeedbackPath)),
          planeFeedbackPath_(std::move(planeFeedbackPath)),
          preflightFeedbackPath_(std::move(preflightFeedbackPath)),
          toolExecutionFeedbackPath_(std::move(toolExecutionFeedbackPath)),
          jobPath_(std::move(jobPath)),
          visualizationPath_(std::move(visualizationPath)),
          trajectoryPath_(std::move(trajectoryPath)),
          coordinatePath_(std::move(coordinatePath)),
          jobSnapshotSequence_(jobSnapshot.sequence),
          visualizationSnapshot_(std::move(visualizationSnapshot)),
          visualizationSequence_(visualizationSnapshot_.sequence),
          desktopRepresentation_(jobSnapshot.representation),
          desktopColoring_(jobSnapshot.coloring),
          mirrorEye_(mirrorEye), referenceGrid_(referenceGrid),
          initialScenePlacementEnabled_(placeSceneInView),
          initialScenePlacementRequested_(placeSceneInView),
          sceneViewPlacement_(sceneViewPlacement),
          mirrorDiagnosticsPath_(std::move(mirrorDiagnosticsPath)),
          witnessCaptureDirectory_(std::move(witnessCaptureDirectory)),
          witnessVisualExpectationDirectory_(
              std::move(witnessVisualExpectationDirectory)),
          exitOnWitnessComplete_(exitOnWitnessComplete),
          selectionLevel_(std::move(selectionLevel)) {
        if (!visualizationPath_.empty()) {
            std::error_code error;
            const auto modified = std::filesystem::last_write_time(
                visualizationPath_, error);
            if (!error) visualizationModified_ = modified;
        }
        if (!trajectoryPath_.empty()) {
            std::ifstream input(trajectoryPath_);
            trajectoryState_ = nadoc_vr::loadTrajectoryState(input);
            std::error_code error;
            trajectoryModified_ = std::filesystem::last_write_time(
                trajectoryPath_, error);
        }
        if (!coordinatePath_.empty()) {
            std::error_code error;
            coordinateModified_ = std::filesystem::last_write_time(
                coordinatePath_, error);
        }
        if (initialScenePlacementRequested_ &&
            sceneViewPlacement_.view == nadoc_vr::ScenePlacementView::mirror &&
            mirrorEye_ == nadoc_vr::SpectatorMirrorEye::off) {
            throw std::invalid_argument(
                "mirror-targeted scene placement requires a mirrored eye");
        }
        if (!mirrorDiagnosticsPath_.empty()) {
            mirrorDiagnosticsOutput_.open(
                mirrorDiagnosticsPath_, std::ios::out | std::ios::trunc);
            if (!mirrorDiagnosticsOutput_) {
                throw std::runtime_error(
                    "Could not open mirror diagnostics " + mirrorDiagnosticsPath_);
            }
        }
        if (!liveSocketPath.empty()) {
            if (!witnessPath.empty()) throw std::runtime_error("live and Witness modes are exclusive");
            if (!eventPath_.empty() && liveMode == "control")
                throw std::runtime_error("live browser events require explicit transactions mode");
            liveMode_ = std::move(liveMode);
            liveDirectory_ = std::filesystem::path(liveSocketPath).parent_path();
            liveSession_ = std::to_string(::getpid()) + "-" + std::to_string(
                std::chrono::steady_clock::now().time_since_epoch().count());
            liveSocket_.open(liveSocketPath);
        }
        if (!witnessPath.empty()) {
            std::ifstream input(witnessPath);
            if (!input) {
                throw std::runtime_error("Could not open ScryWrite witness script " +
                                         witnessPath);
            }
            witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(input));
            std::cout << "ScryWrite Witness Mode: " << witnessPath << '\n';
        }
        extrudePlane_ = sceneData_.extrudePlane;
        latticeContext_ = sceneData_.latticeContext;
        normalizationCenter_ = sceneData_.normalizationCenter;
        normalizationScale_ = sceneData_.normalizationScale;
        sourceAxes_ = sceneData_.sourceAxes;
        volumePanel_.initialize(eventPath_);
        volumePanel_.update(sidebarMenus_.menus);
        dimensionSync_.initialize(eventPath_,dimensionPanel_.tool,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters});
        const RepresentationData& initial = sceneData_.representations[
            representationSourceIndex(sceneData_.initialRepresentation)];
        const auto identity = nadoc_vr::resolveOwnerIdentity(
            initial.ownerAliases, selectedOwnerTokens);
        if(selectedSelectionKind=="selection" && selectedOwnerTokens.size()>2) {
            selectedIdentity_=selectedOwnerTokens.front();selectedOwnerTokens_={selectedIdentity_};selectedSelectionKind_="selection";
            committedSelectionOwnerTokens_={selectedOwnerTokens.begin()+1,selectedOwnerTokens.end()};
        } else if (identity && selectedSelectionKind != "none") {
            selectedIdentity_ = *identity;
            selectedOwnerTokens_ = std::move(selectedOwnerTokens);
            selectedSelectionKind_ = std::move(selectedSelectionKind);
            committedSelectionIdentities_ = {selectedIdentity_};
            if (!selectedOwnerTokens_.empty()) {
                committedSelectionOwnerTokens_ = {selectedOwnerTokens_.front()};
            }
        }
    }

    void beginStartup(const std::string& scene,const std::string& status,
                      std::vector<std::string> owners,const std::string& kind) {
        representationLoading_.enabled=true;representationLoading_.eventPath=eventPath_;
        startup_.begin(scene,status);startupOwners_=std::move(owners);startupKind_=kind;
    }

    void pollStartup() {
        if(!startup_.active)return;
        // Submit the upload stage before doing GPU work on this context.
        if(startup_.candidate && startup_.uploadPending) {
            startup_.uploadPending=false;
            try {
                auto scene=std::move(*startup_.candidate);startup_.candidate.reset();
                normalizationCenter_=scene.normalizationCenter;normalizationScale_=scene.normalizationScale;
                sourceAxes_=scene.sourceAxes;
                extrudePlane_=scene.extrudePlane;
                latticeContext_=scene.latticeContext;
                const auto identity=nadoc_vr::resolveOwnerIdentity(
                    scene.representations[representationSourceIndex(scene.initialRepresentation)].ownerAliases,startupOwners_);
                if(startupKind_=="selection" && startupOwners_.size()>2) {
                    selectedIdentity_=startupOwners_.front();selectedOwnerTokens_={selectedIdentity_};selectedSelectionKind_="selection";
                    committedSelectionOwnerTokens_={startupOwners_.begin()+1,startupOwners_.end()};
                } else if(identity && startupKind_!="none") {
                    selectedIdentity_=*identity;selectedOwnerTokens_=startupOwners_;selectedSelectionKind_=startupKind_;
                    committedSelectionIdentities_={selectedIdentity_};
                    committedSelectionOwnerTokens_=startupOwners_;
                }
                glScene_->installInitialScene(std::move(scene));
                glScene_->enablePreparedStyles();
                glScene_->setVisualization(visualizationSnapshot_);
                glScene_->setSelectionHighlights({}, {}, committedSelectionOwnerTokens_, committedSelectionIdentities_);
                dimensionSync_.initialize(eventPath_,dimensionPanel_.tool,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters});
                startup_.phase="upload";startup_.percent=96;startup_.detail="Uploading display in frame budget";
            } catch(const std::exception& e){startup_.phase="error";startup_.detail=e.what();}
        } else if(startup_.phase=="upload") {
            try {
                glScene_->pollPreparedStyle();startup_.percent=96+int(3*glScene_->styleProgress());
                if(!glScene_->stylePending()) {
                    startup_.percent=99;startup_.detail="Submitting first part frame";
                    startup_.phase="submitting";startup_.completedAt=glfwGetTime();
                }
            }catch(const std::exception& e){glScene_->cancelPreparedStyle();startup_.phase="error";startup_.detail=e.what();}
        } else startup_.poll();
        if(startup_.completedAt>=0 && glfwGetTime()-startup_.completedAt>.75) {
            startup_.active=false;startup_.surface.shutdown();
            requestedRepresentation_="full";requestedColoring_=coloringName(glScene_->coloring());
            ++styleSequence_;publishEventState();
        }
    }

    void pollRepresentationLoading() {
        auto& loading=representationLoading_;
        if(startup_.active)return;
        // Standalone snapshots also queue prepared styles, without lazy loading.
        if(!loading.enabled){glScene_->pollPreparedStyle();return;}
        if(loading.pending && loading.generation!=sceneRefresh_.revision()){loading.cancel();glScene_->cancelPreparedStyle();}
        if(loading.candidate) {
            try {
                glScene_->installRepresentation(std::move(*loading.candidate));loading.candidate.reset();
                visualizationModified_.reset();
                if(!glScene_->supportsRepresentation(loading.target))throw std::runtime_error("Representation has no display geometry");
                loading.percent=96;loading.phase="waiting";loading.detail="Applying desktop style";
                publishStyleRequest(loading.target,loading.color);
            } catch(const std::exception& e){loading.fail(e.what());}
        } else loading.poll(normalizationCenter_,normalizationScale_);
        try{glScene_->pollPreparedStyle();if(!loading.pending)glScene_->trimPreparedCache(loading.retired);}catch(const std::exception& e){glScene_->cancelPreparedStyle();loading.fail(e.what());}
        if(loading.pending && glScene_->stylePending()){loading.percent=96+3*glScene_->styleProgress();loading.detail="Uploading display in frame budget";}
        if(loading.pending && loading.phase=="waiting" && !glScene_->stylePending() && glScene_->representation()==loading.target && glScene_->coloring()==loading.color) {
            loading.percent=100;loading.phase="ready";loading.detail="Representation ready";loading.pending=false;loading.lightweight=false;loading.visibleUntil=glfwGetTime()+1;
        }
    }

    int run() {
        initializeWindow();
        initializeOpenXr();
        initializeGraphics();
        eventLoop();
        return 0;
    }

    ~Viewer() {
        gpuFrameTimer_.shutdown();
        qrCalibration_.shutdown();
        roomFloor_.shutdown();
        menuGlass_.shutdown();
        startup_.surface.shutdown();
        representationLoading_.popup.surface.shutdown();
        placementFailurePopup_.surface.shutdown();
        latticePanelSurface_.shutdown();
        routingPopup_.shutdown();
        sidebarMenus_.shutdown();
        witnessSurface_.shutdown();
        viewTools_.shutdown();
        presenterUI_.shutdown();
        desktopSurface_.shutdown();
        desktopFrameSurface_.shutdown();
        componentGallery_.ui.shutdown();
        solidWheels_.shutdown();
        glScene_.reset();
        for (Swapchain& swapchain : swapchains_) {
            if (swapchain.depth) glDeleteRenderbuffers(1, &swapchain.depth);
            if (swapchain.handle != XR_NULL_HANDLE) xrDestroySwapchain(swapchain.handle);
        }
        if (liveObjectIdTexture_) glDeleteTextures(1, &liveObjectIdTexture_);
        if (framebuffer_) glDeleteFramebuffers(1, &framebuffer_);
        if (mirrorDiagnosticsTexture_) glDeleteTextures(1, &mirrorDiagnosticsTexture_);
        if (mirrorDiagnosticsDepthStencil_) {
            glDeleteRenderbuffers(1, &mirrorDiagnosticsDepthStencil_);
        }
        if (mirrorDiagnosticsFramebuffer_) {
            glDeleteFramebuffers(1, &mirrorDiagnosticsFramebuffer_);
        }
        for (XrSpace handSpace : handSpaces_) {
            if (handSpace != XR_NULL_HANDLE) xrDestroySpace(handSpace);
        }
        if (space_ != XR_NULL_HANDLE) xrDestroySpace(space_);
        if (session_ != XR_NULL_HANDLE) xrDestroySession(session_);
        if (actionSet_ != XR_NULL_HANDLE) xrDestroyActionSet(actionSet_);
        if (instance_ != XR_NULL_HANDLE) xrDestroyInstance(instance_);
        if (window_) glfwDestroyWindow(window_);
        if (glfwInitialized_) glfwTerminate();
    }

  private:
    void initializeWindow() {
        if (!glfwInit()) throw std::runtime_error("GLFW initialization failed");
        glfwInitialized_ = true;
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
        glfwWindowHint(GLFW_STENCIL_BITS, 8);
        const bool mirrorEnabled = mirrorEye_ != nadoc_vr::SpectatorMirrorEye::off;
        std::string title = nadoc_vr::spectatorMirrorWindowTitle(mirrorEye_);
        if (referenceGrid_) title += " — ROOM GRID ACTIVE";
        window_ = glfwCreateWindow(
            mirrorEnabled ? 960 : 720, mirrorEnabled ? 540 : 180,
            title.c_str(), nullptr, nullptr);
        if (!window_) throw std::runtime_error("Could not create the OpenGL companion window");
        glfwMakeContextCurrent(window_);
        glfwSwapInterval(0);
    }

    XrPath path(const char* value) const {
        XrPath result = XR_NULL_PATH;
        checkXr(instance_, xrStringToPath(instance_, value, &result), "xrStringToPath");
        return result;
    }

    XrAction createAction(XrActionType type, const char* name, const char* localizedName) {
        XrActionCreateInfo info{XR_TYPE_ACTION_CREATE_INFO};
        info.actionType = type;
        std::snprintf(info.actionName, XR_MAX_ACTION_NAME_SIZE, "%s", name);
        std::snprintf(info.localizedActionName, XR_MAX_LOCALIZED_ACTION_NAME_SIZE,
                      "%s", localizedName);
        info.countSubactionPaths = static_cast<uint32_t>(handPaths_.size());
        info.subactionPaths = handPaths_.data();
        XrAction action = XR_NULL_HANDLE;
        checkXr(instance_, xrCreateAction(actionSet_, &info, &action), "xrCreateAction");
        return action;
    }

    void suggestBindings(const char* profile,
                         const std::array<const char*, 16>& componentPaths) {
        std::vector<XrActionSuggestedBinding> bindings;
        bindings.reserve(componentPaths.size());
        for (size_t hand = 0; hand < handPaths_.size(); ++hand) {
            const size_t offset = hand * 8U;
            const std::array<XrAction, 8> actions = {
                poseAction_, triggerAction_, menuAction_, gripAction_,
                trackpadAction_, trackpadTouchAction_, trackpadAxisAction_, hapticAction_};
            for (size_t component = 0; component < actions.size(); ++component) {
                if (componentPaths[offset + component]) {
                    bindings.push_back(
                        {actions[component], path(componentPaths[offset + component])});
                }
            }
        }
        XrInteractionProfileSuggestedBinding suggested{
            XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING};
        suggested.interactionProfile = path(profile);
        suggested.countSuggestedBindings = static_cast<uint32_t>(bindings.size());
        suggested.suggestedBindings = bindings.data();
        checkXr(instance_, xrSuggestInteractionProfileBindings(instance_, &suggested),
                "xrSuggestInteractionProfileBindings");
    }

    void initializeActions() {
        handPaths_ = {path("/user/hand/left"), path("/user/hand/right")};

        XrActionSetCreateInfo setInfo{XR_TYPE_ACTION_SET_CREATE_INFO};
        std::snprintf(setInfo.actionSetName, XR_MAX_ACTION_SET_NAME_SIZE, "%s", "navigation");
        std::snprintf(setInfo.localizedActionSetName,
                      XR_MAX_LOCALIZED_ACTION_SET_NAME_SIZE, "%s", "NADOC navigation");
        setInfo.priority = 0;
        checkXr(instance_, xrCreateActionSet(instance_, &setInfo, &actionSet_),
                "xrCreateActionSet");

        poseAction_ = createAction(XR_ACTION_TYPE_POSE_INPUT, "hand_pose", "Hand pose");
        triggerAction_ = createAction(XR_ACTION_TYPE_FLOAT_INPUT, "select", "Select");
        menuAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "vr_menu", "VR menu");
        gripAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "scene_grab", "Move or resize scene");
        trackpadAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "trackpad_click", "Radial tool menu");
        trackpadTouchAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "trackpad_touch", "Resize Selection Volume");
        trackpadAxisAction_ = createAction(
            XR_ACTION_TYPE_VECTOR2F_INPUT, "trackpad_axis", "Selection Volume size");
        hapticAction_ = createAction(
            XR_ACTION_TYPE_VIBRATION_OUTPUT, "haptic", "Navigation haptic");

        suggestBindings(
            "/interaction_profiles/htc/vive_controller",
            {"/user/hand/left/input/grip/pose",
             "/user/hand/left/input/trigger/value",
             "/user/hand/left/input/menu/click",
             "/user/hand/left/input/squeeze/click",
             "/user/hand/left/input/trackpad/click",
             "/user/hand/left/input/trackpad/touch",
             "/user/hand/left/input/trackpad",
             "/user/hand/left/output/haptic",
             "/user/hand/right/input/grip/pose",
             "/user/hand/right/input/trigger/value",
             "/user/hand/right/input/menu/click",
             "/user/hand/right/input/squeeze/click",
             "/user/hand/right/input/trackpad/click",
             "/user/hand/right/input/trackpad/touch",
             "/user/hand/right/input/trackpad",
             "/user/hand/right/output/haptic"});
        suggestBindings(
            "/interaction_profiles/khr/simple_controller",
            {"/user/hand/left/input/grip/pose",
             "/user/hand/left/input/select/click",
             "/user/hand/left/input/menu/click",
             nullptr,
             nullptr,
             nullptr,
             nullptr,
             "/user/hand/left/output/haptic",
             "/user/hand/right/input/grip/pose",
             "/user/hand/right/input/select/click",
             nullptr,
             nullptr,
             nullptr,
             nullptr,
             nullptr,
             "/user/hand/right/output/haptic"});
    }

    void attachActions() {
        for (size_t hand = 0; hand < handSpaces_.size(); ++hand) {
            XrActionSpaceCreateInfo info{XR_TYPE_ACTION_SPACE_CREATE_INFO};
            info.action = poseAction_;
            info.subactionPath = handPaths_[hand];
            info.poseInActionSpace.orientation.w = 1.0F;
            checkXr(instance_, xrCreateActionSpace(session_, &info, &handSpaces_[hand]),
                    "xrCreateActionSpace");
        }
        XrSessionActionSetsAttachInfo attachInfo{XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO};
        attachInfo.countActionSets = 1;
        attachInfo.actionSets = &actionSet_;
        checkXr(instance_, xrAttachSessionActionSets(session_, &attachInfo),
                "xrAttachSessionActionSets");
    }

    void initializeOpenXr() {
        uint32_t extensionCount = 0;
        checkXr(XR_NULL_HANDLE, xrEnumerateInstanceExtensionProperties(
            nullptr, 0, &extensionCount, nullptr), "xrEnumerateInstanceExtensionProperties");
        std::vector<XrExtensionProperties> extensions(
            extensionCount, {XR_TYPE_EXTENSION_PROPERTIES});
        checkXr(XR_NULL_HANDLE, xrEnumerateInstanceExtensionProperties(
            nullptr, extensionCount, &extensionCount, extensions.data()),
            "xrEnumerateInstanceExtensionProperties");
        const bool hasOpenGl = std::any_of(extensions.begin(), extensions.end(), [](const auto& ext) {
            return std::string(ext.extensionName) == XR_KHR_OPENGL_ENABLE_EXTENSION_NAME;
        });
        if (!hasOpenGl) throw std::runtime_error("The active OpenXR runtime does not support OpenGL");

        const char* enabledExtensions[] = {XR_KHR_OPENGL_ENABLE_EXTENSION_NAME};
        XrInstanceCreateInfo createInfo{XR_TYPE_INSTANCE_CREATE_INFO};
        std::snprintf(createInfo.applicationInfo.applicationName,
                      XR_MAX_APPLICATION_NAME_SIZE, "%s", "NADOC VR Viewer");
        createInfo.applicationInfo.applicationVersion = 1;
        std::snprintf(createInfo.applicationInfo.engineName,
                      XR_MAX_ENGINE_NAME_SIZE, "%s", "NADOC Native");
        createInfo.applicationInfo.engineVersion = 1;
        createInfo.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
        createInfo.enabledExtensionCount = 1;
        createInfo.enabledExtensionNames = enabledExtensions;
        checkXr(XR_NULL_HANDLE, xrCreateInstance(&createInfo, &instance_), "xrCreateInstance");
        initializeActions();

        XrSystemGetInfo systemInfo{XR_TYPE_SYSTEM_GET_INFO};
        systemInfo.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
        checkXr(instance_, xrGetSystem(instance_, &systemInfo, &systemId_), "xrGetSystem");

        PFN_xrGetOpenGLGraphicsRequirementsKHR getRequirements = nullptr;
        checkXr(instance_, xrGetInstanceProcAddr(
            instance_, "xrGetOpenGLGraphicsRequirementsKHR",
            reinterpret_cast<PFN_xrVoidFunction*>(&getRequirements)),
            "xrGetInstanceProcAddr(xrGetOpenGLGraphicsRequirementsKHR)");
        XrGraphicsRequirementsOpenGLKHR requirements{XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_KHR};
        checkXr(instance_, getRequirements(instance_, systemId_, &requirements),
                "xrGetOpenGLGraphicsRequirementsKHR");

        Display* display = glfwGetX11Display();
        const GLXContext context = glfwGetGLXContext(window_);
        const GLXDrawable drawable = glfwGetGLXWindow(window_);
        int fbConfigId = 0;
        if (glXQueryContext(display, context, GLX_FBCONFIG_ID, &fbConfigId) != Success) {
            throw std::runtime_error("Could not query the GLFW GLX framebuffer configuration");
        }
        const int attributes[] = {GLX_FBCONFIG_ID, fbConfigId, None};
        int configCount = 0;
        GLXFBConfig* configs = glXChooseFBConfig(
            display, DefaultScreen(display), attributes, &configCount);
        if (!configs || configCount == 0) {
            if (configs) XFree(configs);
            throw std::runtime_error("Could not resolve the GLFW GLX framebuffer configuration");
        }
        const GLXFBConfig config = configs[0];
        XWindowAttributes windowAttributes{};
        XGetWindowAttributes(display, glfwGetX11Window(window_), &windowAttributes);

        XrGraphicsBindingOpenGLXlibKHR binding{XR_TYPE_GRAPHICS_BINDING_OPENGL_XLIB_KHR};
        binding.xDisplay = display;
        binding.visualid = static_cast<uint32_t>(XVisualIDFromVisual(windowAttributes.visual));
        binding.glxFBConfig = config;
        binding.glxDrawable = drawable;
        binding.glxContext = context;

        XrSessionCreateInfo sessionInfo{XR_TYPE_SESSION_CREATE_INFO};
        sessionInfo.next = &binding;
        sessionInfo.systemId = systemId_;
        const XrResult sessionResult = xrCreateSession(instance_, &sessionInfo, &session_);
        XFree(configs);
        checkXr(instance_, sessionResult, "xrCreateSession");

        XrReferenceSpaceCreateInfo spaceInfo{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
        spaceInfo.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
        spaceInfo.poseInReferenceSpace.orientation.w = 1.0F;
        checkXr(instance_, xrCreateReferenceSpace(session_, &spaceInfo, &space_),
                "xrCreateReferenceSpace");
        attachActions();
    }

    void initializeGraphics() {
        uint32_t viewCount = 0;
        checkXr(instance_, xrEnumerateViewConfigurationViews(
            instance_, systemId_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
            0, &viewCount, nullptr), "xrEnumerateViewConfigurationViews");
        viewConfigs_.assign(viewCount, {XR_TYPE_VIEW_CONFIGURATION_VIEW});
        checkXr(instance_, xrEnumerateViewConfigurationViews(
            instance_, systemId_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
            viewCount, &viewCount, viewConfigs_.data()), "xrEnumerateViewConfigurationViews");
        views_.assign(viewCount, {XR_TYPE_VIEW});

        uint32_t formatCount = 0;
        checkXr(instance_, xrEnumerateSwapchainFormats(
            session_, 0, &formatCount, nullptr), "xrEnumerateSwapchainFormats");
        std::vector<int64_t> formats(formatCount);
        checkXr(instance_, xrEnumerateSwapchainFormats(
            session_, formatCount, &formatCount, formats.data()), "xrEnumerateSwapchainFormats");
        const std::array<int64_t, 2> preferred = {GL_SRGB8_ALPHA8, GL_RGBA8};
        int64_t selectedFormat = formats.front();
        for (const int64_t candidate : preferred) {
            if (std::find(formats.begin(), formats.end(), candidate) != formats.end()) {
                selectedFormat = candidate;
                break;
            }
        }

        swapchains_.resize(viewCount);
        for (uint32_t i = 0; i < viewCount; ++i) {
            Swapchain& swapchain = swapchains_[i];
            swapchain.width = static_cast<int32_t>(viewConfigs_[i].recommendedImageRectWidth);
            swapchain.height = static_cast<int32_t>(viewConfigs_[i].recommendedImageRectHeight);
            XrSwapchainCreateInfo info{XR_TYPE_SWAPCHAIN_CREATE_INFO};
            info.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT;
            info.format = selectedFormat;
            info.sampleCount = 1;
            info.width = static_cast<uint32_t>(swapchain.width);
            info.height = static_cast<uint32_t>(swapchain.height);
            info.faceCount = 1;
            info.arraySize = 1;
            info.mipCount = 1;
            checkXr(instance_, xrCreateSwapchain(session_, &info, &swapchain.handle),
                    "xrCreateSwapchain");
            uint32_t imageCount = 0;
            checkXr(instance_, xrEnumerateSwapchainImages(
                swapchain.handle, 0, &imageCount, nullptr), "xrEnumerateSwapchainImages");
            swapchain.images.assign(imageCount, {XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_KHR});
            checkXr(instance_, xrEnumerateSwapchainImages(
                swapchain.handle, imageCount, &imageCount,
                reinterpret_cast<XrSwapchainImageBaseHeader*>(swapchain.images.data())),
                "xrEnumerateSwapchainImages");
            glGenRenderbuffers(1, &swapchain.depth);
            glBindRenderbuffer(GL_RENDERBUFFER, swapchain.depth);
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8,
                                  swapchain.width, swapchain.height);
        }

        glGenFramebuffers(1, &framebuffer_);
        if (mirrorEye_ != nadoc_vr::SpectatorMirrorEye::off) {
            glGenTextures(1, &mirrorDiagnosticsTexture_);
            glBindTexture(GL_TEXTURE_2D, mirrorDiagnosticsTexture_);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                kMirrorDiagnosticSize, kMirrorDiagnosticSize,
                0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
            glGenFramebuffers(1, &mirrorDiagnosticsFramebuffer_);
            glBindFramebuffer(GL_FRAMEBUFFER, mirrorDiagnosticsFramebuffer_);
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                mirrorDiagnosticsTexture_, 0);
            glGenRenderbuffers(1, &mirrorDiagnosticsDepthStencil_);
            glBindRenderbuffer(GL_RENDERBUFFER, mirrorDiagnosticsDepthStencil_);
            glRenderbufferStorage(
                GL_RENDERBUFFER, GL_DEPTH24_STENCIL8,
                kMirrorDiagnosticSize, kMirrorDiagnosticSize);
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER,
                mirrorDiagnosticsDepthStencil_);
            if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
                throw std::runtime_error("Mirror diagnostic framebuffer is incomplete");
            }
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
        }
        glScene_ = std::make_unique<GlScene>(std::move(sceneData_), liveSocket_.enabled());
        glScene_->setVisualization(visualizationSnapshot_);
        glScene_->enablePreparedStyles();
        glScene_->setSelectionHighlights(
            {}, {}, committedSelectionOwnerTokens_, committedSelectionIdentities_);
        if (referenceGrid_) {
            const auto grid = nadoc_vr::buildRoomReferenceGrid();
            referenceGridGuides_.reserve(grid.size() * 2U);
            for (const auto& segment : grid) {
                referenceGridGuides_.push_back(Vertex{segment.first, segment.color, 1.0F});
                referenceGridGuides_.push_back(Vertex{segment.second, segment.color, 1.0F});
            }
        }
        desktopSurface_.initialize(glfwGetX11Display());
        desktopFrameSurface_.initialize();
        viewTools_.initialize();
        roomFloor_.initialize(session_);
        latticePanelSurface_.initialize();
        sidebarMenus_.initialize();
        routingPopup_.initialize();
        routingPopup_.menus[1].available=[this](const std::string& action){return routingPanel_.available(action);};
        routingPopup_.menus[1].isActive=[this](const std::string& action){return routingPanel_.active(action);};
        simulationPanel_.bind(sidebarMenus_.menus[0], &sidebarMenus_.menus[1]);
        for(auto& sidebar:sidebarMenus_.menus) {
            sidebar.label=[this](const std::string& action,const std::string& fallback) {
                if(action=="vr:head-light")return std::string(shadowLight_.headFollowing()?"Head-following lighting: On":"Head-following lighting: Off");
                if(action=="qr:calibrate")return std::string(qrCalibration_.running()?"Cancel QR calibration":"Calibrate QR code");
                if(action=="qr:cube")return std::string(qrCalibration_.running()&&qrCalibration_.cubeMode()?"Cancel cube calibration":"Calibrate cube");
                if(action=="qr:status" || action=="qr:cube-status")return qrCalibration_.status;
                if(action!="share:status")return fallback;
                return std::string(shareFailed_?"Action failed - check desktop":!shareActive_?"Start presentation on desktop":shareBusy_ || shareAck_<shareSequence_?"Updating presentation...":sharePerspective_?"Sharing desktop perspective":"Perspective paused");
            };
            sidebar.available=[this](const std::string& action) {
                if(action.starts_with("routing:"))return routingPanel_.available(action);
                if(action=="qr:status" || action=="qr:cube-status")return false;
                if(action=="qr:cube")return !qrCalibration_.running() || qrCalibration_.cubeMode();
                if(action=="qr:calibrate")return !qrCalibration_.running() || !qrCalibration_.cubeMode();
                if(action.starts_with("share:")) return shareAvailable(action);
                if(action=="tool:bend" || action=="tool:twist" || action=="tool:sweep")return !toolShell_.executionPending();
                if(action.starts_with("sweep:"))return sweepActionAvailable(action);
                if(action.starts_with("twist:")) {
                    if(toolShell_.executionPending())return false;
                    if(action=="twist:confirm")return bendReady();
                    if(action=="twist:undo")return toolShell_.undoAvailable() && !bendPanel_.hand;
                    if(bendPanel_.hand || bendPanel_.wheelHand || bendPanel_.planeHand)return action=="twist:cancel";
                    if(action=="twist:units")return bendReady();
                    return true;
                }
                if(action.starts_with("bend:")) {
                    if(toolShell_.executionPending())return false;
                    if(bendPanel_.planeHand || bendPanel_.defaultPlanes || !bendPanel_.pendingSelection.empty())return action=="bend:cancel" || action=="bend:back";
                    if(action=="bend:radius-less" || action=="bend:radius-more")return toolConfig_.bendAngleDegrees()>0 && planeGuides_[0] && planeGuides_[1];
                    if(bendPanel_.hand)return action=="bend:cancel" || action=="bend:angle" || action=="bend:direction" || action=="bend:radius" || action.ends_with("-wheel") || action.starts_with("bend:direction-") || action.starts_with("bend:radius-");
                    if(action=="bend:confirm")return bendReady();
                    if(action=="bend:undo")return toolShell_.undoAvailable();
                    return true;
                }
                if(action=="tool:move_rotate")return !toolShell_.executionPending();
                if(action.starts_with("move:")) {
                    if(toolShell_.executionPending() || moveAwaitRefresh_)return false;
                    if(action=="move:apply")return toolShell_.previewRequested()&&!pendingToolTransform_.isIdentity();
                    if(action=="move:undo")return toolShell_.undoAvailable();
                    return true;
                }
                if(action.starts_with("extrude:")) {
                    if(toolShell_.executionPending()) return action=="extrude:back";
                    if(action=="extrude:confirm") return paintedExtrusionReady();
                    if(action=="extrude:freeform") return freeformAvailable();
                    if(action=="extrude:undo") return toolShell_.undoAvailable();
                    if(action=="extrude:lattice") return false;
                    if(action=="extrude:plane") return toolConfig_.targetSelectionKind()=="none";
                    return true;
                }
                if(action.starts_with("repr:") && representationLoading_.enabled)return true;
                if(action.starts_with("repr:")) return glScene_->supportsRepresentation(static_cast<Representation>(std::stoi(action.substr(5))));
                if(action.starts_with("color:")) return (nadoc_vr::kSidebarColoringMasks.at(static_cast<size_t>(glScene_->representation())) & (1U << std::stoi(action.substr(6)))) != 0;
                if(!action.starts_with("tool:")) return true;
                const auto mode=action=="tool:extrude"?nadoc_vr::ToolMode::extrude
                    :action=="tool:twist"?nadoc_vr::ToolMode::twist
                    :action=="tool:bend"?nadoc_vr::ToolMode::bend
                    :action=="tool:move_rotate"?nadoc_vr::ToolMode::move_rotate:nadoc_vr::ToolMode::inspect;
                return nadoc_vr::ToolShell::selectionCapability(mode,selectedSelectionKind_)!=nadoc_vr::ToolCapability::unsupported;
            };
            sidebar.loadingProgress=[this](const std::string& action){return representationLoading_.button(action);};
            sidebar.isActive=[this](const std::string& action) {
                if(action.starts_with("routing:"))return routingPanel_.active(action);
                if(action=="vr:head-light")return shadowLight_.headFollowing();
                if(action=="share:avatar")return showVRAvatar_;
                if(action=="share:status")return shareActive_;
                return (action.starts_with("repr:") && std::stoi(action.substr(5))==static_cast<int>(glScene_->representation()))
                    || (action.starts_with("color:") && std::stoi(action.substr(6))==static_cast<int>(glScene_->coloring()));
            };
        }
        if(startup_.active)startup_.surface.initialize();
        representationLoading_.popup.surface.initialize();
        placementFailurePopup_.surface.initialize();
        gpuFrameTimer_.initialize();
        if (witness_) witnessSurface_.initialize(makeDesktopProgram());
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_PROGRAM_POINT_SIZE);
        glDisable(GL_CULL_FACE);
    }

    void pollXrEvents() {
        XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
        while (xrPollEvent(instance_, &event) == XR_SUCCESS) {
            if (event.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) {
                const auto* changed = reinterpret_cast<XrEventDataSessionStateChanged*>(&event);
                sessionState_ = changed->state;
                if (sessionState_ == XR_SESSION_STATE_READY) {
                    XrSessionBeginInfo beginInfo{XR_TYPE_SESSION_BEGIN_INFO};
                    beginInfo.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
                    checkXr(instance_, xrBeginSession(session_, &beginInfo), "xrBeginSession");
                    sessionRunning_ = true;
                } else if (sessionState_ == XR_SESSION_STATE_STOPPING) {
                    sessionRunning_ = false;
                    checkXr(instance_, xrEndSession(session_), "xrEndSession");
                } else if (sessionState_ == XR_SESSION_STATE_EXITING ||
                           sessionState_ == XR_SESSION_STATE_LOSS_PENDING) {
                    exitLoop_ = true;
                }
            } else if (event.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING) {
                exitLoop_ = true;
            }
            event = {XR_TYPE_EVENT_DATA_BUFFER};
        }
    }

    void pulse(size_t hand, float amplitude = 0.35F) {
        ++hapticRequests_[hand];
        hapticAmplitude_[hand]=amplitude;
        if (witness_ || liveSocket_.enabled()) return;
        XrHapticActionInfo info{XR_TYPE_HAPTIC_ACTION_INFO};
        info.action = hapticAction_;
        info.subactionPath = handPaths_[hand];
        XrHapticVibration vibration{XR_TYPE_HAPTIC_VIBRATION};
        vibration.duration = 30'000'000;
        vibration.frequency = XR_FREQUENCY_UNSPECIFIED;
        vibration.amplitude = amplitude;
        const XrResult result = xrApplyHapticFeedback(
            session_, &info, reinterpret_cast<const XrHapticBaseHeader*>(&vibration));
        if (XR_FAILED(result) && result != XR_SESSION_NOT_FOCUSED) {
            checkXr(instance_, result, "xrApplyHapticFeedback");
        }
    }

    void appendPlacedText(
        const nadoc_vr::MenuPlacement& placement, const std::string& text,
        float x, float y, float scale, const glm::vec3& color,
        float z = 0.002F) {
        for (size_t character = 0; character < text.size(); ++character) {
            const auto rows = nadoc_vr::glyph(static_cast<char>(
                std::toupper(static_cast<unsigned char>(text[character]))));
            for (size_t row = 0; row < rows.size(); ++row) {
                for (int column = 0; column < 5; ++column) {
                    if ((rows[row] & (1U << (4 - column))) == 0) continue;
                    const float px = x + static_cast<float>(character * 6U + column) * scale;
                    const float py = y - static_cast<float>(row) * scale;
                    controllerGuides_.push_back(
                        Vertex{placement.worldPoint({px, py, z}), color, 1.0F});
                    controllerGuides_.push_back(
                        Vertex{placement.worldPoint({px + scale * 0.82F, py, z}),
                               color, 1.0F});
                }
            }
        }
    }

    void appendPlacedTextFitted(
        const nadoc_vr::MenuPlacement& placement,
        const nadoc_vr::MenuPanelBounds& bounds, const std::string& text,
        float x, float y, float maximumScale, const glm::vec3& color,
        float z = 0.002F) {
        constexpr float margin = 0.012F;
        const float left = glm::clamp(
            x, bounds.minimum.x + margin, bounds.maximum.x - margin);
        const float available = std::max(0.0F, bounds.maximum.x - margin - left);
        const float scale = nadoc_vr::fittedStrokeTextScale(
            text.size(), maximumScale, available);
        if (scale <= 0.0F) return;
        appendPlacedText(placement, text, left, y, scale, color, z);
    }

    void appendPlacedTextCentered(
        const nadoc_vr::MenuPlacement& placement,
        const nadoc_vr::MenuPanelBounds& bounds, const std::string& text,
        float y, float maximumScale, const glm::vec3& color,
        float z = 0.002F) {
        constexpr float margin = 0.012F;
        const float available = bounds.maximum.x - bounds.minimum.x - 2.0F * margin;
        const float scale = nadoc_vr::fittedStrokeTextScale(
            text.size(), maximumScale, available);
        if (scale <= 0.0F) return;
        const float width = nadoc_vr::strokeTextWidth(text.size(), scale);
        const float x = (bounds.minimum.x + bounds.maximum.x - width) * 0.5F;
        appendPlacedText(placement, text, x, y, scale, color, z);
    }

    static constexpr auto kLatticePanelBounds = nadoc_vr::kLatticePainterBounds;
    static constexpr int kMaximumLatticeAxisRadius = 64;
    static constexpr auto kLatticeExitBounds = nadoc_vr::kLatticePainterExit;
    static constexpr auto kLatticeGridBounds = nadoc_vr::kLatticePainterGrid;

    [[nodiscard]] const nadoc_vr::SidebarMenu& observedSidebar() const {
        if(routingPopup_.anyOpen())return routingPopup_.menus[1];
        return sidebarMenus_.menus[sidebarMenus_.menus[1].open ? 1 : 0];
    }

    [[nodiscard]] const char* menuPageName() const {
        return sidebarMenus_.anyOpen() ? "sidebars" : "closed";
    }

    [[nodiscard]] std::vector<nadoc_vr::scrywrite::WitnessMenuEntry>
    witnessMenuEntries() const {
        if(routingPopup_.anyOpen())return routingPopup_.entries();
        return sidebarMenus_.entries();
    }

    [[nodiscard]] std::string combinedMenuLayoutStatus() const {
        if(latticeOpen_ && !latticeLayoutAudit_.valid()) return latticeLayoutAudit_.status();
        for(const auto& menu:sidebarMenus_.menus)
            if(menu.open && !menu.audit.valid()) return menu.audit.status();
        return sidebarMenus_.anyOpen()?"valid":"closed";
    }

    [[nodiscard]] std::string witnessHoverName() const {
        return routingPopup_.anyOpen()?routingPopup_.hoverLabel():sidebarMenus_.hoverLabel();
    }

    [[nodiscard]] std::string witnessMenuFramingStatus() const {
        if (!witness_ || !sidebarMenus_.anyOpen()) return "closed";
        const auto& menu=observedSidebar();
        const auto bounds=menu.bounds();
        const auto& placement=menu.placement;
        const std::array<glm::vec3, 4> corners{{
            placement.worldPoint({bounds.minimum.x, bounds.minimum.y, 0.0F}),
            placement.worldPoint({bounds.minimum.x, bounds.maximum.y, 0.0F}),
            placement.worldPoint({bounds.maximum.x, bounds.minimum.y, 0.0F}),
            placement.worldPoint({bounds.maximum.x, bounds.maximum.y, 0.0F}),
        }};
        const auto& head = witness_->input().head;
        return nadoc_vr::assessActorEyePanelFraming(
            corners, head.position, head.orientation).status();
    }

    void toggleSidebar(size_t hand) {
        if(routingPopup_.anyOpen()) {
            for(const auto& row:routingPanel_.controls)if(row.label=="Cancel"||row.label=="Done"||row.id=="dismiss") {
                if(routingPanel_.activate("routing:"+row.id))publishEventState();
                break;
            }
            return;
        }
        sidebarMenus_.toggle(hand,hands_[hand].position,hands_[hand].orientation);
    }

    void openSidebarTab(size_t hand, const std::string& tab) {
        if(hand==0 && trajectoryPanel_.active) {
            trajectoryPanel_.exit(sidebarMenus_.menus);trajectoryScrubHand_.reset();
        }
        auto& menu=sidebarMenus_.menus[hand];
        if(!menu.open) toggleSidebar(hand);
        menu.customTab.reset();
        for(size_t index=0;index<menu.tabs.size();++index)
            if(nadoc_vr::kSidebarTabs[menu.tabs[index]].key==tab) menu.selected=index;
        menu.focus.reset();menu.hovered.clear();
        suppressManipulationUntilRelease_=true;
    }

    void resolveWitnessAim() {
        if (!witness_ || !witness_->pendingAim()) return;
        const auto aim = *witness_->pendingAim();
        const auto item = nadoc_vr::scrywrite::findWitnessMenuEntry(
            liveTargets(), aim.label);
        if (!item) {
            witness_->rejectAim("menu control not present: " + aim.label);
            return;
        }
        const auto& hand = witness_->input().hands[aim.hand];
        if (!hand.valid) {
            witness_->rejectAim("aim_menu requires a valid scripted hand pose");
            return;
        }
        const auto orientation = nadoc_vr::scrywrite::witnessAimOrientation(
            hand.position, item->worldPosition);
        if (!orientation) {
            witness_->rejectAim("scripted hand is coincident with menu control");
            return;
        }
        witness_->resolveAim(*orientation);
    }

#include "sweep_runtime.inc"

    void toggleMenu(size_t hand) {
        ligation_.cancel();
        if(sweepPanel_.active) {sidebarMenus_.menus[1].open=!sidebarMenus_.menus[1].open;return;}
        if(bendPanel_.active) {sidebarMenus_.menus[1].open=true;return;}
        if(movePanel_.active) {
            sidebarMenus_.menus[1].open=!sidebarMenus_.menus[1].open;
            sidebarMenus_.menus[1].focus.reset();return;
        }
        if(extrudePanel_.active) {extrudePanel_.exit(sidebarMenus_.menus);latticeOpen_=false;return;}
        if(volumePanel_.active) {volumePanel_.exit(sidebarMenus_.menus);return;}
        if(dimensionPanel_.tool.active) {dimensionPanel_.exit(sidebarMenus_.menus);return;}
        radialToolMenu_.close();
        toggleSidebar(hand);
        suppressManipulationUntilRelease_ = true;
        pulse(hand, 0.45F);
    }

    bool bendReady() const {
        return bendPanel_.active && planeGuides_[0] && planeGuides_[1] &&
            toolConfig_.planeABp() && toolConfig_.planeBBp() &&
            *toolConfig_.planeABp()<*toolConfig_.planeBBp() &&
            nadoc_vr::BendPanel::supports(toolConfig_.targetSelectionKind()) && !bendPanel_.selecting &&
            !bendPanel_.hand && !bendPanel_.planeHand && !bendPanel_.wheelHand && !activePlanePickSequence_ && !bendPanel_.defaultPlanes &&
            bendPanel_.pendingSelection.empty() && std::none_of(bendPanel_.wheels.begin(),bendPanel_.wheels.end(),[](const auto& w){return w.moving();});
    }
    std::string extrudeStatus() const {
        if(toolShell_.executionPending())return "EXTRUDING";
        if(toolShell_.status()=="COMMIT FAILED")return "EXTRUDE FAILED - ADJUST OR RETRY";
        if(toolShell_.status()=="COMMIT REFUSED")return "EXTRUDE REFUSED - ADJUST OR RETRY";
        if(paintedExtrusionReady())return "READY TO EXTRUDE";
        if(extrudeLatticeDraft_.cells().empty() && toolConfig_.targetSelectionKind()=="none")return "PAINT CELLS TO EXTRUDE";
        if(toolConfig_.lengthBp()==0)return "SET EXTRUDE LENGTH";
        if(freeformDraft_.armed())return "PLACE EXTRUSION PLANE";
        if(eventPath_.empty())return "OPEN VR FROM YOUR DESIGN";
        const auto* feedback=currentToolPreflightFeedback();
        if(!feedback || feedback->status=="waiting")return "VALIDATING EXTRUSION";
        if(feedback->reason=="painted_cell_occupied")return "PAINT UNOCCUPIED CELLS";
        if(feedback->reason=="source_frame_required" || feedback->reason=="source_frame_ambiguous")return "SELECT AN END OR PLACE FREEFORM";
        if(feedback->reason=="strand_filter_unsupported")return "SELECT BOTH STRANDS";
        if(feedback->reason=="source_plane_mismatch")return "SELECT THE SOURCE PLANE";
        if(feedback->status=="error")return "VALIDATION FAILED - ADJUST TO RETRY";
        return "EXTRUSION BLOCKED - CHECK DESIGN";
    }
    void refreshExtrudePanel() {
        radialToolMenu_.setWorkflow(bendPanel_.active,bendHasAngle());
        radialToolMenu_.setSweep(sweepPanel_.active && sweepDraft_.step==2);
        sweepPanel_.refresh(sidebarMenus_.menus,sweepDraft_,extrudeLatticeDraft_.cells().size(),latticeSquare_,
            nadoc_vr::toolStrandFilterName(toolConfig_.strandFilter()),toolConfig_.ligateAdjacent(),sweepStatus(),extrudePlane_.plane);
        const std::string bendStatus=toolShell_.executionPending()?toolShell_.status()
            :bendPanel_.hand?"PLANE "+std::to_string(2-bendPanel_.grabbed)+" FIXED / RELEASE TO FINISH"
            :bendPanel_.pickSlot?"HOLD TRIGGER CLOSE TO ELEMENT"
            :bendReady()?(bendPanel_.twist?"TURN PLANE 2 / CONFIRM":(bendPanel_.manual?"GRAB PLANE / FIXED BP":"AIM AT PLANE / SLIDE BP")):toolShell_.status();
        bendPanel_.refresh(sidebarMenus_.menus,toolConfig_,bendStatus);
        extrudePanel_.refresh(sidebarMenus_.menus,toolConfig_.lengthBp(),toolConfig_.directionSign(),
            extrudePlane_.label(),nadoc_vr::toolStrandFilterName(toolConfig_.strandFilter()),
            toolConfig_.ligateAdjacent(),extrudeLatticeDraft_.cells().size(),latticeSquare_,
            freeformDraft_.placed(),extrudeStatus());
    }

    void cancelMove() {
        if(toolShell_.executionPending())return;
        movePanel_.hand.reset();pendingToolTransform_.cancel();publishToolTransform();
        glScene_->setMovePointPreview({},glm::mat4(1));
        toolShell_.apply(nadoc_vr::ToolAction::cancel,selectedSelectionKind_);
        publishToolIntent(nadoc_vr::ToolAction::cancel);
    }

    bool undoAuthoringTool(size_t hand) {
        if(toolShell_.executionPending() || !toolShell_.undoAvailable())return false;
        toolShell_.apply(nadoc_vr::ToolAction::undo,selectedSelectionKind_);
        publishToolIntent(nadoc_vr::ToolAction::undo);
        pulse(hand,.62F);
        return true;
    }

    void confirmMove() {
        if(toolShell_.executionPending() || !toolShell_.previewRequested() || pendingToolTransform_.isIdentity())return;
        movePanel_.hand.reset();publishToolTransform();
        toolShell_.apply(nadoc_vr::ToolAction::confirm,selectedSelectionKind_);
        publishToolIntent(nadoc_vr::ToolAction::confirm);
        moveAwaitRefresh_=true;
    }

    bool shareAvailable(const std::string& action) const {
        if(action=="share:avatar")return true;
        if(action=="share:status")return false;
        if(!shareActive_ || shareBusy_ || shareAck_<shareSequence_)return false;
        return action=="share:end" || (action=="share:pause" && sharePerspective_) || (action=="share:resume" && !sharePerspective_);
    }
    void activateSidebarAction(const std::string& requestedAction, size_t hand) {
        if(requestedAction=="trajectory") {
            openSidebarTab(0,"dynamics");
            trajectoryPanel_.enter(sidebarMenus_.menus,trajectoryState_);
            return;
        }
        if(requestedAction.starts_with("trajectory:")) {
            if(!trajectoryPanel_.active)return;
            if(requestedAction=="trajectory:back") {
                trajectoryPanel_.exit(sidebarMenus_.menus);trajectoryScrubHand_.reset();return;
            }
            if(!trajectoryState_.active || trajectoryState_.frameCount==0)return;
            if(requestedAction=="trajectory:play")
                publishTrajectoryRequest(trajectoryState_.playing?"pause":"play",trajectoryState_.frameIndex);
            else if(requestedAction=="trajectory:previous")
                publishTrajectoryRequest("seek",trajectoryState_.frameIndex>0?trajectoryState_.frameIndex-1:0);
            else if(requestedAction=="trajectory:next")
                publishTrajectoryRequest("seek",std::min(trajectoryState_.frameIndex+1,trajectoryState_.frameCount-1));
            else if(requestedAction=="trajectory:seek")
                publishTrajectoryRequest("seek",trajectoryState_.frameIndex);
            return;
        }
        const bool known=requestedAction=="options" || requestedAction=="tools" || requestedAction=="settings" ||
            requestedAction=="jobs" || requestedAction=="trajectory" || requestedAction=="desktop" || requestedAction=="recenter" ||
            requestedAction=="feedback:activate" || requestedAction=="vr:head-light" || requestedAction=="vr:exit" ||
            requestedAction=="qr:calibrate" || requestedAction=="qr:cube" || requestedAction.starts_with("tool:") ||
            requestedAction.starts_with("twist:") || requestedAction.starts_with("bend:") || requestedAction.starts_with("move:") ||
            requestedAction.starts_with("extrude:") || requestedAction.starts_with("sweep:") || requestedAction.starts_with("routing:") || requestedAction.starts_with("simulation:") || requestedAction.starts_with("share:") ||
            requestedAction.starts_with("volume:") || requestedAction.starts_with("dimension:") || requestedAction.starts_with("repr:") ||
            requestedAction.starts_with("color:") || requestedAction.starts_with("trajectory:");
        if(!known)return;
        if(requestedAction.starts_with("tool:") && requestedAction!="tool:extrude" && requestedAction!="tool:sweep" && requestedAction!="tool:twist" &&
           requestedAction!="tool:bend" && requestedAction!="tool:move_rotate" && requestedAction!="tool:inspect")return;
        if(requestedAction.starts_with("sweep:")) {activateSweepAction(requestedAction,hand);return;}
        if(sweepPanel_.active && (requestedAction.starts_with("tool:") || requestedAction.starts_with("volume:") || requestedAction.starts_with("dimension:"))) {
            if(toolShell_.executionPending())return;
            cancelSweep();
        }
        if(requestedAction=="tool:sweep") {activateSweep();return;}
        if(requestedAction=="vr:head-light") {
            const bool enabled = !shadowLight_.headFollowing();
            shadowLight_.setHeadFollowing(enabled);
            witnessShadowLight_.setHeadFollowing(enabled);
            return;
        }
        if(requestedAction=="vr:exit") {
            exitRequested_=true;
            return;
        }
        // Plane selection, cancellation and transaction ownership are shared with Bend.
        std::string action=requestedAction;
        if(action.starts_with("twist:")) {
            if(!bendPanel_.active || !bendPanel_.twist || toolShell_.executionPending())return;
            if((bendPanel_.hand || bendPanel_.wheelHand || bendPanel_.planeHand) && action!="twist:cancel")return;
            if(action=="twist:zero" && bendPanel_.selecting) {publishSelect({});return;}
            if(action=="twist:amount") {
                clearPlanePick();bendPanel_.pickSlot.reset();bendPanel_.lastPick.clear();
                bendPanel_.wheelHand=hand;
                bendPanel_.wheel.begin(sidebarMenus_.menus[1].placement.localPoint(hands_[hand].position).y);return;
            }
            if(action=="twist:units" || action=="twist:reverse" || action=="twist:zero" || action=="twist:less" || action=="twist:more") {
                if(action=="twist:units") {if(!toolConfig_.toggleTwistUnits())return;}
                else {
                    const double step=toolConfig_.twistAmountMode()==nadoc_vr::TwistAmountMode::total_degrees?5:.5;
                    const double amount=action=="twist:zero"?0:action=="twist:reverse"?-toolConfig_.twistAmount():
                        toolConfig_.twistAmount()+(action=="twist:more"?step:-step);
                    (void)toolConfig_.setTwist(amount);
                }
                refreshExtrudePanel();publishToolConfiguration();return;
            }
            action="bend:"+action.substr(6);
        }
        if(action.starts_with("bend:")) {
            if(toolShell_.executionPending())return;
            if(bendPanel_.hand && action!="bend:cancel" && action!="bend:angle" && action!="bend:direction" && action!="bend:radius" && !action.ends_with("-wheel") && !action.starts_with("bend:direction-") && !action.starts_with("bend:radius-"))return;
            if(action=="bend:back") {
                bendPanel_.exit(sidebarMenus_.menus);clearPlanePick();clearPlaneGuides();
                if(toolConfig_.clear())publishToolConfiguration();
                toolShell_.activate(nadoc_vr::ToolMode::inspect,selectedSelectionKind_);
                publishToolIntent(nadoc_vr::ToolAction::activate);return;
            }
            if(action=="bend:cancel") {
                bendPanel_.reset();bendPanel_.pickSlot.reset();clearPlanePick();clearPlaneGuides();
                (void)toolConfig_.clear();(void)toolConfig_.bind(bendPanel_.twist?nadoc_vr::ToolMode::twist:nadoc_vr::ToolMode::bend,selectedIdentity_,selectedSelectionKind_,selectedOwnerTokens_);
                publishToolConfiguration();
                toolShell_.apply(nadoc_vr::ToolAction::cancel,selectedSelectionKind_);
                publishToolIntent(nadoc_vr::ToolAction::cancel);
                if(!bendPanel_.selecting && nadoc_vr::BendPanel::supports(selectedSelectionKind_)) {
                    bendPanel_.defaultPlanes=true;requestBendDefaultPlane("a");
                }
                return;
            }
            if(action=="bend:cluster" || action=="bend:target") {
                bendPanel_.selecting=!bendPanel_.selecting;
                if(bendPanel_.twist)(void)toolConfig_.setTwist(0);
                else (void)toolConfig_.setBend(0,toolConfig_.bendDirectionDegrees());
                publishToolConfiguration();
                bendPanel_.reset();bendPanel_.pickSlot.reset();clearPlanePick();clearPlaneGuides();
                if(!bendPanel_.selecting && nadoc_vr::BendPanel::supports(selectedSelectionKind_)) {
                    bendPanel_.defaultPlanes=true;requestBendDefaultPlane("a");
                } else bendPanel_.selecting=true;
                refreshExtrudePanel();return;
            }
            if(action=="bend:clusters-prev" || action=="bend:clusters-next") {
                if(action=="bend:clusters-prev")bendPanel_.clusterPage=bendPanel_.clusterPage>=4?bendPanel_.clusterPage-4:0;
                else if(bendPanel_.clusterPage+4<bendClusters_.size())bendPanel_.clusterPage+=4;
                refreshExtrudePanel();return;
            }
            if(action.starts_with("bend:cluster-")) {
                const auto index=std::stoul(action.substr(13));if(index<bendClusters_.size())selectBendCluster(index);return;
            }
            if(action=="bend:manual") {
                if(bendPanel_.selecting) {publishSelect({});return;}
                if(!bendReady())return;
                bendPanel_.manual=!bendPanel_.manual;bendPanel_.pickSlot.reset();refreshExtrudePanel();return;
            }
            if(action=="bend:plane1" || action=="bend:plane2") {
                if(!bendPanel_.twist)return;
                bendPanel_.defaultPlanes=false;
                clearPlanePick(); // Discard feedback bound to the previous draft sequence.
                bendPanel_.pickSlot=action=="bend:plane1"?"a":"b";
                bendPanel_.lastPick.clear();bendPanel_.posed=false;bendPanel_.grabbed=1;
                (void)toolConfig_.setBend(0,0);publishToolConfiguration();
                planePickStatus_="HOLD TRIGGER CLOSE TO ELEMENT";return;
            }
            if(action=="bend:direction-less" || action=="bend:direction-more" || action=="bend:radius-less" || action=="bend:radius-more") {
                double angle=toolConfig_.bendAngleDegrees(),direction=toolConfig_.bendDirectionDegrees();
                const double sign=action.ends_with("more")?1:-1;
                if(action.starts_with("bend:direction-"))direction=std::fmod(direction+sign*5+360,360);
                else {
                    if(angle<=0 || !toolConfig_.planeABp() || !toolConfig_.planeBBp())return;
                    const double contour=(*toolConfig_.planeBBp()-*toolConfig_.planeABp())*.334;
                    const double radius=std::max(contour/glm::radians(359.0),contour/glm::radians(angle)+sign*10);
                    angle=glm::degrees(contour/radius);
                }
                applyBendAdjustment(angle,direction);pulse(hand,.16F);return;
            }
            if(action=="bend:angle" || action=="bend:direction" || action=="bend:radius")return;
            if(action=="bend:angle-wheel" || action=="bend:direction-wheel" || action=="bend:radius-wheel") {
                if(bendPanel_.wheelHand || bendPanel_.planeHand || bendPanel_.defaultPlanes)return;
                const auto local=bendWheelPoint(hand);if(!local)return;
                clearPlanePick();bendPanel_.pickSlot.reset();bendPanel_.lastPick.clear();
                bendPanel_.wheelIndex=action=="bend:direction-wheel"?1:action=="bend:radius-wheel"?2:0;
                bendPanel_.wheelHand=hand;bendPanel_.wheels[bendPanel_.wheelIndex].begin(local->y);return;
            }
            if(action=="bend:recenter") {recenterRequested_=true;recenterHand_=hand;return;}
            if(action!="bend:confirm" && action!="bend:undo")return;
            const auto intent=action=="bend:confirm"?nadoc_vr::ToolAction::confirm:nadoc_vr::ToolAction::undo;
            if(intent==nadoc_vr::ToolAction::confirm && !bendReady())return;
            if(intent==nadoc_vr::ToolAction::undo) {undoAuthoringTool(hand);return;}
            toolShell_.apply(intent,selectedSelectionKind_,bendReady());publishToolIntent(intent);return;
        }
        if(bendPanel_.active && action.starts_with("tool:")) {bendPanel_.exit(sidebarMenus_.menus);clearPlanePick();}
        if(action=="tool:bend" || action=="tool:twist") {
            if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
            if(movePanel_.active){cancelMove();movePanel_.exit(sidebarMenus_.menus);}
            if(volumePanel_.active)volumePanel_.exit(sidebarMenus_.menus);
            if(dimensionPanel_.tool.active)dimensionPanel_.exit(sidebarMenus_.menus);
            activateAuthoringTool(action=="tool:twist"?1:2);return;
        }
        if(action.starts_with("routing:")) {if(routingPanel_.activate(action))publishEventState();return;}
        if(action.starts_with("simulation:")) {if(simulationPanel_.activate(action))publishEventState();return;}
        if(action=="qr:calibrate") {qrCalibration_.start();return;}
        if(action=="qr:cube") {qrCalibration_.start(true);return;}
        if(action=="share:avatar") {showVRAvatar_=!showVRAvatar_;return;}
        if(action.starts_with("share:")) {
            if(shareAvailable(action)) {shareAction_=action.substr(6);++shareSequence_;publishEventState();}
            return;
        }
        if(action=="feedback:activate") {pulse(hand,.22F);return;}
        if(action.starts_with("move:")) {
            if(toolShell_.executionPending() || moveAwaitRefresh_)return;
            if(action=="move:apply")confirmMove();
            else if(action=="move:undo") {
                if(!toolShell_.undoAvailable())return;
                cancelMove();
                undoAuthoringTool(hand);
            } else if(action=="move:recenter") {recenterRequested_=true;recenterHand_=hand;}
            else if(action=="move:back" || action=="move:cancel") {
                cancelMove();
                if(action=="move:back")movePanel_.exit(sidebarMenus_.menus);
            }
            return;
        }
        if(movePanel_.active) {if(toolShell_.executionPending())return;cancelMove();movePanel_.exit(sidebarMenus_.menus);}
        if(action=="tool:move_rotate") {
            if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
            if(volumePanel_.active)volumePanel_.exit(sidebarMenus_.menus);
            if(dimensionPanel_.tool.active)dimensionPanel_.exit(sidebarMenus_.menus);
            activateAuthoringTool(3);radialToolMenu_.close();
            movePanel_.enter(sidebarMenus_.menus);
            movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());return;
        }
        if(action.starts_with("extrude:")) {
            if(action=="extrude:length" || nadoc_vr::extrudeWheelIndex(action))return;
            if(action=="extrude:back") {extrudePanel_.exit(sidebarMenus_.menus);latticeOpen_=false;return;}
            if(toolShell_.executionPending())return;
            if(action=="extrude:cancel") {cancelExtrudeInterface();return;}
            bool changed=false;
            if(action=="extrude:less" || action=="extrude:more" ||
               action=="extrude:less-period" || action=="extrude:more-period") {
                resetThumbwheels();
                const bool coarse=action.ends_with("-period");
                const int direction=action.starts_with("extrude:more")?1:-1;
                changed=toolConfig_.adjustExtrudeLengthBp(
                    direction*nadoc_vr::extrudeLengthStep(latticeSquare_,coarse));
            }
            else if(action=="extrude:direction") changed=toolConfig_.adjustSecondary(toolConfig_.directionSign()>0?-1:1);
            else if(action=="extrude:strands") changed=toolConfig_.cycleOption();
            else if(action=="extrude:ligate") changed=toolConfig_.toggleFlag();
            else if(action=="extrude:plane") {freeformDraft_.clear();extrudePlane_.cycle();centerLatticePainting(true);changed=true;}

            else if(action=="extrude:paint") latticeOpen_=true;
            else if(action=="extrude:recenter") {recenterRequested_=true;recenterHand_=hand;}
            else if(action=="extrude:freeform" && freeformAvailable()) {
                if(freeformDraft_.placed()) {freeformDraft_.clear();centerLatticePainting(true);}
                else {freeformDraft_.arm();latticeOpen_=false;sidebarMenus_.menus[1].open=false;}
                changed=true;
            } else {
                const auto intent=action=="extrude:confirm"?nadoc_vr::ToolAction::confirm
                    :action=="extrude:preview"?nadoc_vr::ToolAction::preview
                    :action=="extrude:undo"?nadoc_vr::ToolAction::undo:nadoc_vr::ToolAction::cancel;
                if(intent==nadoc_vr::ToolAction::confirm&&!paintedExtrusionReady())return;
                if(intent==nadoc_vr::ToolAction::undo) {undoAuthoringTool(hand);return;}
                toolShell_.apply(intent,toolConfig_.targetSelectionKind(),paintedExtrusionReady());
                if(intent==nadoc_vr::ToolAction::cancel) {freeformDraft_.clear();pendingToolTransform_.cancel();publishToolTransform();}
                publishToolIntent(intent);
            }
            if(changed)publishToolConfiguration();
            refreshExtrudePanel();return;
        }
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        if(action=="tool:extrude") {
            activateAuthoringTool(0);
            refreshExtrudePanel();return;
        }
        if(volumePanel_.action(action,sidebarMenus_.menus,normalizationCenter_,normalizationScale_)) {
            radialToolMenu_.close();latticeOpen_=false;return;
        }
        if(dimensionPanel_.action(action,sidebarMenus_.menus,normalizationScale_)) {
            radialToolMenu_.close();latticeOpen_=false;
            dimensionPanel_.tool.update(hands_,manipulator_.transform(),false);
            return;
        }
        if (action.starts_with("repr:")) {
            publishStyleRequest(static_cast<Representation>(std::stoi(action.substr(5))), glScene_->coloring());
        } else if (action.starts_with("color:")) {
            publishStyleRequest(glScene_->representation(), static_cast<Coloring>(std::stoi(action.substr(6))));
        } else if (action == "desktop") {
            desktopPanel_.show(hands_[hand].position,hands_[hand].orientation);
        } else if (action == "recenter") {
            recenterRequested_ = true; recenterHand_ = hand;
        } else if (action.starts_with("tool:")) {
            const std::array<std::string,5> names{"extrude","twist","bend","move_rotate","inspect"};
            const auto item=std::find(names.begin(),names.end(),action.substr(5));
            if(item!=names.end()) activateAuthoringTool(static_cast<size_t>(item-names.begin()));
        } else if (action=="options") {
            openSidebarTab(0,"vr");
        } else if (action=="jobs") {
            openSidebarTab(0,"dynamics");
        } else if (action=="tools" || action=="settings") {
            activateAuthoringTool(4);
            openSidebarTab(1,"tools");
        }
    }

    [[nodiscard]] bool latticeCellOccupied(const nadoc_vr::LatticeCell& cell) const {
        if(freeformDraft_.placed() || freeformDraft_.armed())return false;
        const auto* context=paintOccupancy();
        return context && context->occupied(cell);
    }

    [[nodiscard]] const std::vector<nadoc_vr::LatticeCell>& existingLatticeCells() const {
        static const std::vector<nadoc_vr::LatticeCell> empty;
        if(freeformDraft_.placed() || freeformDraft_.armed())return empty;
        const auto* context=paintOccupancy();
        return context?context->cells:empty;
    }

    [[nodiscard]] const nadoc_vr::LatticePlaneContext* paintOccupancy() const {
        if(!sweepPanel_.active)if(const auto* source=latticeContext_.find(extrudePlane_.plane))return source;
        return latticeContext_.occupancy(extrudePlane_.plane);
    }

    void centerLatticePainting(bool discardOccupied=false) {
        if(discardOccupied && !freeformDraft_.placed() && !freeformDraft_.armed()) {
            if(const auto* context=paintOccupancy())
                context->discardOccupied(extrudeLatticeDraft_);
            latticePaintStroke_.reset();latticeHover_.reset();
        }
        auto cells=existingLatticeCells();
        cells.insert(cells.end(),extrudeLatticeDraft_.cells().begin(),extrudeLatticeDraft_.cells().end());
        latticeOrigin_=nadoc_vr::centeredPaintOrigin(cells,latticeOrigin_);
        latticeGrip_.zoom=nadoc_vr::fittedPaintZoom(cells,latticeOrigin_,latticeSquare_,
            nadoc_vr::latticePanelUnitsPerNanometer(normalizationScale_,manipulator_.scale(),latticePlacement_.scale()));
    }

    [[nodiscard]] glm::vec2 latticeCellPosition(
        const nadoc_vr::LatticeCell& cell) const {
        const float unitsPerNanometer = nadoc_vr::latticePanelUnitsPerNanometer(
            normalizationScale_, manipulator_.scale(), latticePlacement_.scale()) * latticeGrip_.zoom;
        return nadoc_vr::latticeCellOffsetNanometers(
            cell, latticeOrigin_, latticeSquare_) * unitsPerNanometer;
    }

    [[nodiscard]] float latticeCellRadius() const {
        return nadoc_vr::kDnaHelixRadiusNanometers *
            nadoc_vr::latticePanelUnitsPerNanometer(
                normalizationScale_, manipulator_.scale(), latticePlacement_.scale()) * latticeGrip_.zoom;
    }

    [[nodiscard]] std::vector<nadoc_vr::LatticeCell> visibleLatticeCells() const {
        const float radius = latticeCellRadius();
        const float unitsPerNanometer = nadoc_vr::latticePanelUnitsPerNanometer(
            normalizationScale_, manipulator_.scale(), latticePlacement_.scale()) * latticeGrip_.zoom;
        if (radius <= 0.0F || unitsPerNanometer <= 0.0F) return {};
        const float xPitch = (latticeSquare_
            ? nadoc_vr::kSquareLatticePitchNanometers
            : nadoc_vr::kHoneycombColumnPitchNanometers) * unitsPerNanometer;
        const float yPitch = (latticeSquare_
            ? nadoc_vr::kSquareLatticePitchNanometers
            : nadoc_vr::kHoneycombRowPitchNanometers) * unitsPerNanometer;
        const float maximumX = std::max(
            std::abs(kLatticeGridBounds.minimum.x),
            std::abs(kLatticeGridBounds.maximum.x));
        const float maximumY = std::max(
            std::abs(kLatticeGridBounds.minimum.y),
            std::abs(kLatticeGridBounds.maximum.y));
        const float stagger = latticeSquare_ ? 0.0F
            : nadoc_vr::kHoneycombLatticeRadiusNanometers * unitsPerNanometer;
        const int columnRadius = std::clamp(
            static_cast<int>(std::ceil((maximumX + radius) / xPitch)) + 1,
            0, kMaximumLatticeAxisRadius);
        const int rowRadius = std::clamp(
            static_cast<int>(std::ceil((maximumY + radius + stagger) / yPitch)) + 1,
            0, kMaximumLatticeAxisRadius);
        std::vector<nadoc_vr::LatticeCell> cells;
        cells.reserve(static_cast<size_t>(2 * rowRadius + 1) *
                      static_cast<size_t>(2 * columnRadius + 1));
        for (int row = -rowRadius; row <= rowRadius; ++row) {
            for (int column = -columnRadius; column <= columnRadius; ++column) {
                const nadoc_vr::LatticeCell cell{
                    latticeOrigin_.row + row, latticeOrigin_.column + column};
                if (nadoc_vr::circleIntersectsBounds(
                        latticeCellPosition(cell), radius,
                        kLatticeGridBounds.minimum, kLatticeGridBounds.maximum)) {
                    cells.push_back(cell);
                }
            }
        }
        return cells;
    }

    [[nodiscard]] bool latticeExitContains(const glm::vec3& local) const {
        return local.x >= kLatticeExitBounds.minimum.x &&
               local.x <= kLatticeExitBounds.maximum.x &&
               local.y >= kLatticeExitBounds.minimum.y &&
               local.y <= kLatticeExitBounds.maximum.y;
    }

    [[nodiscard]] std::optional<nadoc_vr::LatticeCell> latticeHit(
        const nadoc_vr::HandPose& hand) const {
        if (!latticeOpen_) return std::nullopt;
        const auto local = latticePlacement_.rayPanelLocalPoint(
            hand, kLatticePanelBounds.minimum, kLatticePanelBounds.maximum);
        if (!local || latticeExitContains(*local) ||
            local->x < kLatticeGridBounds.minimum.x ||
            local->x > kLatticeGridBounds.maximum.x ||
            local->y < kLatticeGridBounds.minimum.y ||
            local->y > kLatticeGridBounds.maximum.y) return std::nullopt;
        std::optional<nadoc_vr::LatticeCell> nearest;
        float nearestDistance = latticeCellRadius() * 1.08F;
        for (const auto& cell : visibleLatticeCells()) {
            if(latticeCellOccupied(cell)) continue;
            const float distance = glm::length(
                glm::vec2(local->x, local->y) - latticeCellPosition(cell));
            if (distance <= nearestDistance) {
                nearestDistance = distance;
                nearest = cell;
            }
        }
        return nearest;
    }

    void appendLatticeGuides() {
        if (!latticeOpen_) return;
        const auto guideBegin = controllerGuides_.size();
        auto line = [&](const glm::vec3& first, const glm::vec3& second,
                        const glm::vec3& color) {
            controllerGuides_.push_back(
                {latticePlacement_.worldPoint(first), color, 1.0F});
            controllerGuides_.push_back(
                {latticePlacement_.worldPoint(second), color, 1.0F});
        };
        std::vector<Vertex> fills;
        auto fill = [&](nadoc_vr::MenuPanelBounds b, glm::vec3 color) {
            for (const auto& p : std::array<glm::vec2,6>{{{b.minimum.x,b.minimum.y},
                    {b.maximum.x,b.minimum.y},{b.maximum.x,b.maximum.y},{b.minimum.x,b.minimum.y},
                    {b.maximum.x,b.maximum.y},{b.minimum.x,b.maximum.y}}})
                fills.push_back({{p,0},color,1});
        };
        const auto grip = (latticePlacement_.resizeActive() || latticePlacement_.remoteMode()==2)
            ? nadoc_vr::GripFrameState::resizing
            : (latticePlacement_.dragHand() || latticePlacement_.remoteMode()==1)
                ? nadoc_vr::GripFrameState::moving
                : (latticePlacement_.remoteHovered || latticePlacement_.nearBorder(menuGripContacts()[0],kLatticePanelBounds.minimum,kLatticePanelBounds.maximum)
                    || latticePlacement_.nearBorder(menuGripContacts()[1],kLatticePanelBounds.minimum,kLatticePanelBounds.maximum))
                    ? nadoc_vr::GripFrameState::ready : nadoc_vr::GripFrameState::idle;
        latticeLayoutAudit_ = nadoc_vr::drawLatticePainterChrome(
            {extrudePlane_.plane,latticeSquare_,latticeGrip_.scaling,latticeExitHovered_,
                extrudeLatticeDraft_.cells().size(),existingLatticeCells().size(),grip,
                sweepPanel_.active || freeformDraft_.placed() || freeformDraft_.armed() || latticeContext_.find(extrudePlane_.plane)},
            line,fill,[&](const auto& text,float x,float y,float scale,glm::vec3 color) {
                appendPlacedText(latticePlacement_,text,x,y,scale,color);
            });
        for(size_t h=0;h<2;++h)if(latticeGrip_.nearby[h] || latticeGrip_.held[h]) {
            const auto p=latticePlacement_.localPoint(hands_[h].position);
            const glm::vec3 color=latticeGrip_.held[h]?glm::vec3(.4F,1.F,.6F):glm::vec3(1.F,.8F,.3F);
            line({p.x-.018F,p.y,.003F},{p.x+.018F,p.y,.003F},color);
            line({p.x,p.y-.018F,.003F},{p.x,p.y+.018F,.003F},color);
        }
        constexpr int segments = 20;
        const float radius = latticeCellRadius();
        for (const auto& cell : visibleLatticeCells()) {
            const glm::vec2 center = latticeCellPosition(cell);
            const bool selected = extrudeLatticeDraft_.selected(cell);
            const bool occupied = latticeCellOccupied(cell);
            const bool hovered = latticeHover_ && *latticeHover_ == cell;
            glm::vec3 color = cell.forward()
                ? glm::vec3(41.0F / 255.0F, 182.0F / 255.0F,
                            246.0F / 255.0F)
                : glm::vec3(239.0F / 255.0F, 83.0F / 255.0F,
                            80.0F / 255.0F);
            if (occupied) color = {.70F,.76F,.83F};
            if (selected) color = {1.0F, 0.78F, 0.22F};
            if (hovered) color = glm::mix(color, glm::vec3(1.0F), 0.65F);
            for (int segment = 0; segment < segments; ++segment) {
                const float first = glm::two_pi<float>() * segment / segments;
                const float second = glm::two_pi<float>() * (segment + 1) / segments;
                const auto clipped = nadoc_vr::clipLineToBounds(
                    {center.x + std::cos(first) * radius,
                     center.y + std::sin(first) * radius},
                    {center.x + std::cos(second) * radius,
                     center.y + std::sin(second) * radius},
                    kLatticeGridBounds.minimum, kLatticeGridBounds.maximum);
                if (clipped) {
                    line({clipped->first.x, clipped->first.y, 0.004F},
                         {clipped->second.x, clipped->second.y, 0.004F}, color);
                }
            }
            if(occupied) for(int segment=0;segment<segments;++segment) {
                const float first=glm::two_pi<float>()*segment/segments;
                const float second=glm::two_pi<float>()*(segment+1)/segments;
                const auto clipped=nadoc_vr::clipLineToBounds(
                    center+glm::vec2(std::cos(first),std::sin(first))*radius*.65F,
                    center+glm::vec2(std::cos(second),std::sin(second))*radius*.65F,
                    kLatticeGridBounds.minimum,kLatticeGridBounds.maximum);
                if(clipped) line({clipped->first,.004F},{clipped->second,.004F},color);
            }
            if (selected) {
                // A filled cross survives cached-surface minification at the
                // default tablet scale; thin line cores can disappear between pixels.
                for(const auto& half:std::array<glm::vec2,2>{{{radius*.55F,radius*.15F},{radius*.15F,radius*.55F}}}) {
                    const nadoc_vr::MenuPanelBounds mark{glm::max(center-half,kLatticeGridBounds.minimum),
                        glm::min(center+half,kLatticeGridBounds.maximum)};
                    if(mark.minimum.x<mark.maximum.x && mark.minimum.y<mark.maximum.y)fill(mark,color);
                }
                for (const auto& endpoints : std::array{
                         std::pair{glm::vec2(center.x - radius * 0.55F, center.y),
                                   glm::vec2(center.x + radius * 0.55F, center.y)},
                         std::pair{glm::vec2(center.x, center.y - radius * 0.55F),
                                   glm::vec2(center.x, center.y + radius * 0.55F)}}) {
                    const auto clipped = nadoc_vr::clipLineToBounds(
                        endpoints.first, endpoints.second,
                        kLatticeGridBounds.minimum, kLatticeGridBounds.maximum);
                    if (clipped) {
                        line({clipped->first.x, clipped->first.y, 0.006F},
                             {clipped->second.x, clipped->second.y, 0.006F}, color);
                    }
                }

            }
        }
        std::vector<Vertex> localGuides(controllerGuides_.begin()+guideBegin,controllerGuides_.end());
        controllerGuides_.resize(guideBegin);
        for(auto& guide:localGuides) guide.position=latticePlacement_.localPoint(guide.position);
        latticePanelSurface_.update(localGuides,kLatticePanelBounds,false,fills);
    }

    void appendRadialToolGuides() {
        radialToolMenu_.draw([&](auto a,auto b,auto color){controllerGuides_.push_back({a,color,1});controllerGuides_.push_back({b,color,1});},"");
    }

    [[nodiscard]] bool thumbwheelAvailable() const {
        const auto& menu=sidebarMenus_.menus[1];
        return extrudePanel_.active && menu.open && menu.customTab && menu.tab().key=="extrude" &&
               toolConfig_.active() && toolConfig_.mode()==nadoc_vr::ToolMode::extrude &&
               !toolShell_.executionPending();
    }

    void resetThumbwheels() {
        for(auto& wheel:thumbwheelControls_)wheel.reset();
        thumbwheelHovered_.reset();
        thumbwheelHand_.reset();
    }

    [[nodiscard]] std::optional<glm::vec3> thumbwheelLocalPoint(
        const nadoc_vr::HandPose& hand,size_t index,bool unconstrained=false) const {
        if(!thumbwheelAvailable())return std::nullopt;
        const auto& placement=sidebarMenus_.menus[1].placement;
        if(!unconstrained && !nadoc_vr::thumbwheelHit(nadoc_vr::extrudeWheelShape(),
                nadoc_vr::extrudeWheelCenter(index),placement,hand))return std::nullopt;
        return placement.rayPanelLocalPoint(hand,{-10,-10},{10,10});
    }

    void appendThumbwheelGuides() {
        if(!thumbwheelAvailable())return;
        const auto& placement=sidebarMenus_.menus[1].placement;
        for(size_t i=0;i<thumbwheelControls_.size();++i) {
            const auto& wheel=thumbwheelControls_[i];
            const glm::vec3 color=thumbwheelHovered_==i || wheel.dragging()
                ? glm::vec3(1.0F,.78F,.22F)
                : wheel.moving()?glm::vec3(.38F,1.0F,.58F):glm::vec3(.54F,.70F,.84F);
            solidWheels_.wheel(nadoc_vr::extrudeWheelShape(),wheel.phase(),
                nadoc_vr::extrudeWheelCenter(i),color,
                [&](auto p){return placement.worldPoint(p);});
        }
    }

    void cancelExtrudeInterface() {
        if(sweepPanel_.active) {cancelSweep();return;}
        if(toolShell_.executionPending())return;
        freeformDraft_.clear();
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        toolShell_.apply(nadoc_vr::ToolAction::cancel, selectedSelectionKind_);
        pendingToolTransform_.cancel();
        publishToolTransform();
        publishToolIntent(nadoc_vr::ToolAction::cancel);
        if (toolConfig_.clear()) publishToolConfiguration();
        latticeOpen_ = false;
        latticeHover_.reset();
        latticeExitHovered_ = false;
        latticePaintStroke_.reset();
        latticeGrip_.cancel();
        resetThumbwheels();
        extrudeLatticeDraft_.clear();
    }

    std::array<bool, 2> processLatticeInput(
        const std::array<bool, 2>& blocked = {}) {
        std::array<bool, 2> targeted = blocked;
        if (!latticeOpen_) return targeted;
        if (blocked[1]) {
            latticeHover_.reset();
            latticeExitHovered_ = false;
            latticePaintStroke_.reset();
            return targeted;
        }
        const auto panelHit = latticePlacement_.rayPanelLocalPoint(
            hands_[1], kLatticePanelBounds.minimum, kLatticePanelBounds.maximum);
        targeted[1] = panelHit.has_value();
        if (radialToolMenu_.open()) {
            latticeHover_.reset();
            latticeExitHovered_ = false;
            latticePaintStroke_.reset();
            targeted[1] = true;
            return targeted;
        }
        if (panelHit && nadoc_vr::centerPaintHit(*panelHit)) {
            latticeHover_.reset(); latticeExitHovered_ = false; latticePaintStroke_.reset();
            if (triggerClicked_[1]) {
                centerLatticePainting();
                pulse(1U, 0.40F);
            }
            return targeted;
        }
        const bool previousExitHover = latticeExitHovered_;
        latticeExitHovered_ = panelHit && latticeExitContains(*panelHit);
        if (latticeExitHovered_ && !previousExitHover) pulse(1U, 0.12F);
        if (latticeExitHovered_ && triggerClicked_[1]) {
            cancelExtrudeInterface();
            pulse(1U, 0.48F);
            return targeted;
        }
        const auto previous = latticeHover_;
        latticeHover_ = latticeHit(hands_[1]);
        if (latticeHover_ != previous && latticeHover_) pulse(1U, 0.10F);
        if (latticePaintStroke_.update(
                extrudeLatticeDraft_, latticeHover_, triggerPressed_[1])) {
            publishToolConfiguration();
            pulse(1U, latticePaintStroke_.selecting() ? 0.34F : 0.20F);
        }
        return targeted;
    }

    void openExtrudeLattice() {
        extrudeLatticeDraft_.clear();
        latticePaintStroke_.reset();
        latticeGrip_.cancel();
        resetThumbwheels();
        latticeOrigin_ = nadoc_vr::centeredPaintOrigin(existingLatticeCells());
        latticeSquare_ = extrudePlane_.lattice == "SQUARE";
        const auto& placement=sidebarMenus_.menus[1].placement;
        latticePlacement_.openDocked(
            placement.worldPoint({-1.20F, 0.0F, 0.0F}), placement.orientation());
        centerLatticePainting();
        latticeOpen_ = true;
        latticeHover_.reset();
        latticeExitHovered_ = false;
        publishToolConfiguration(); // Publish cleared cells and the new lattice together.
    }

    bool bendHasAngle() const {
        return !bendPanel_.selecting && std::abs(bendPanel_.twist?toolConfig_.twistAmount():toolConfig_.bendAngleDegrees())>1e-6;
    }

    void activateRadialEdit(size_t item) {
        if(sweepPanel_.active) {
            if(sweepDraft_.step==2)activateSweepAction(item==0?"sweep:delete-last-point":"sweep:add-point",1);
            return;
        }
        if(bendPanel_.active) {
            if(toolShell_.executionPending() || bendPanel_.hand || bendPanel_.wheelHand || bendPanel_.planeHand)return;
            if(item==0)activateSidebarAction(bendPanel_.selecting?"bend:back":"bend:cluster",1);
            else if(item==1) {
                if(bendPanel_.selecting)activateSidebarAction("bend:cluster",1);
                else if(bendHasAngle() && bendReady())activateSidebarAction("bend:confirm",1);
            }
            return;
        }
        if(!nadoc_vr::radialEditEnabled(item) || toolShell_.executionPending() || ligation_.waiting || endResize_.waitingVersion)return;
        if(item>=2) {
            if(!ligation_.version)return;
            if(movePanel_.active)cancelMove();
            ligation_.request(item==2?"undo":"redo",0,[&]{publishEventState();});
            pulse(1U,0.62F);
            return;
        }
        const bool wasEditing=ligation_.active||ligation_.nickActive;
        if((item==0&&ligation_.active)||(item==1&&ligation_.nickActive)) {
            ligation_.setActive(false);publishSelectionLevel(ligationPreviousLevel_);return;
        }
        const auto prior=wasEditing?ligationPreviousLevel_:selectionLevel_;
        if(movePanel_.active){cancelMove();movePanel_.exit(sidebarMenus_.menus);}
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        if(volumePanel_.active)volumePanel_.exit(sidebarMenus_.menus);
        if(dimensionPanel_.tool.active)dimensionPanel_.exit(sidebarMenus_.menus);
        activateAuthoringTool(4);
        latticeOpen_=false;
        ligationPreviousLevel_=prior;ligation_.setActive(item==0);ligation_.nickActive=item==1;publishSelectionLevel(item==0?"end":"base");
    }

    void activateAuthoringTool(size_t item) {
        if(toolShell_.executionPending())return;
        if(sweepPanel_.active)cancelSweep();
        if(bendPanel_.active) {bendPanel_.exit(sidebarMenus_.menus);clearPlanePick();clearPlaneGuides();}
        if(ligation_.active||ligation_.nickActive){ligation_.setActive(false);publishSelectionLevel(ligationPreviousLevel_);}

        static constexpr std::array<nadoc_vr::ToolMode, 5> modes = {
            nadoc_vr::ToolMode::extrude,
            nadoc_vr::ToolMode::twist,
            nadoc_vr::ToolMode::bend,
            nadoc_vr::ToolMode::move_rotate,
            nadoc_vr::ToolMode::inspect,
        };
        if (item >= modes.size()) return;
        const nadoc_vr::ToolMode mode = modes[item];
        if(extrudePanel_.active && mode!=nadoc_vr::ToolMode::extrude)
            extrudePanel_.exit(sidebarMenus_.menus);
        if(movePanel_.active && mode!=nadoc_vr::ToolMode::move_rotate) {
            cancelMove();movePanel_.exit(sidebarMenus_.menus);
        }
        if(volumePanel_.active)volumePanel_.exit(sidebarMenus_.menus);
        if(dimensionPanel_.tool.active)dimensionPanel_.exit(sidebarMenus_.menus);
        toolShell_.activate(mode, selectedSelectionKind_);
        pendingToolTransform_.cancel();
        publishToolTransform();
        publishToolIntent(nadoc_vr::ToolAction::activate);

        suppressManipulationUntilRelease_ = true;

        if (mode == nadoc_vr::ToolMode::extrude ||
            mode == nadoc_vr::ToolMode::twist ||
            mode == nadoc_vr::ToolMode::bend) {
            if (toolConfig_.bind(
                    mode, selectedIdentity_, selectedSelectionKind_, selectedOwnerTokens_)) {
                clearPlanePick();
                clearPlaneGuides();
                publishToolConfiguration();
            }
        } else {
            if (toolConfig_.clear()) publishToolConfiguration();
        }

        if (mode == nadoc_vr::ToolMode::extrude) {
            if(!sidebarMenus_.menus[1].open)
                toggleSidebar(1);
            openExtrudeLattice();
            radialToolMenu_.close();
            extrudePanel_.enter(sidebarMenus_.menus);
            const auto& placement=sidebarMenus_.menus[1].placement;
            latticePlacement_.openDocked(placement.worldPoint({-1.20F,0,0}),placement.orientation());
            refreshExtrudePanel();
        } else {
            latticeOpen_ = false;
            latticeHover_.reset();
            latticeExitHovered_ = false;
            latticePaintStroke_.reset();
            resetThumbwheels();
            extrudeLatticeDraft_.clear();
        }
        if(mode==nadoc_vr::ToolMode::bend || mode==nadoc_vr::ToolMode::twist) {
            if(!sidebarMenus_.menus[1].open)toggleSidebar(1);
            radialToolMenu_.close();
            bendPanel_.twist=mode==nadoc_vr::ToolMode::twist;
            bendPanel_.enter(sidebarMenus_.menus);bendPanel_.pickSlot.reset();
            bendPanel_.manual=false;
            bendPanel_.selecting=true;
            if(bendPanel_.twist)(void)toolConfig_.setTwist(0);
            else (void)toolConfig_.setBend(0,0);
            publishToolConfiguration();
            bendPanel_.describeSelection(selectedSelectionKind_,committedSelectionOwnerTokens_);
            refreshExtrudePanel();
        }
        if(mode==nadoc_vr::ToolMode::move_rotate) {
            if(!sidebarMenus_.menus[1].open)
                toggleSidebar(1);
            radialToolMenu_.close();
            movePanel_.enter(sidebarMenus_.menus);
            movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());
        }
    }

    std::array<bool,2> processThumbwheelInput(std::array<bool,2> blocked) {
        auto targeted=blocked;
        if(!thumbwheelAvailable()) {
            resetThumbwheels();
            return targeted;
        }
        const auto previousHover=thumbwheelHovered_;
        thumbwheelHovered_.reset();
        const auto& placement=sidebarMenus_.menus[1].placement;
        for(size_t hand=0;hand<hands_.size();++hand)if(!blocked[hand]) {
            if(thumbwheelHand_ && *thumbwheelHand_!=hand)continue;
            const auto& owned=sidebarMenus_.menus[hand];
            if(!thumbwheelHand_ && owned.open && owned.focus.active)continue;
            // A nearer tablet consumes the ray before a wheel behind it.
            const auto endpoint=sidebarMenus_.rayEndpoint(hands_[hand]);
            float foreground=endpoint?glm::length(*endpoint-hands_[hand].position):1e9F;
            auto surface=[&](const auto& surfacePlacement,const auto& point) {
                if(point)foreground=std::min(foreground,
                    glm::length(surfacePlacement.worldPoint(*point)-hands_[hand].position));
            };
            if(latticeOpen_)surface(latticePlacement_,latticePlacement_.rayPanelLocalPoint(
                hands_[hand],kLatticePanelBounds.minimum,kLatticePanelBounds.maximum));
            if(desktopPanel_.open)surface(desktopPanel_.placement,desktopPanel_.hit(hands_[hand]));
            if(viewTools_.open)if(const auto uv=viewTools_.hit(hands_[hand]))
                foreground=std::min(foreground,glm::length(viewTools_.world(*uv)-hands_[hand].position));
            for(size_t index=0;index<thumbwheelControls_.size();++index) {
                const auto hit=nadoc_vr::thumbwheelHit(nadoc_vr::extrudeWheelShape(),
                    nadoc_vr::extrudeWheelCenter(index),placement,hands_[hand]);
                if(!hit)continue;
                const float distance=glm::length(placement.worldPoint(*hit)-hands_[hand].position);
                if(foreground+.001F<distance)continue;
                thumbwheelHovered_=index;
                targeted[hand]=true;
                if(previousHover!=thumbwheelHovered_)pulse(hand,.12F);
                if(triggerClicked_[hand] && !thumbwheelHand_) {
                    const auto local=thumbwheelLocalPoint(hands_[hand],index,true);
                    if(local) {
                        for(auto& wheel:thumbwheelControls_)wheel.reset();
                        thumbwheelControls_[index].begin(local->y);
                        thumbwheelHand_=hand;
                        pulse(hand,.30F);
                    }
                }
                break;
            }
        }
        bool changed=false;
        for(size_t index=0;index<thumbwheelControls_.size();++index) {
            auto& wheel=thumbwheelControls_[index];
            int notches=0;
            if(wheel.dragging() && thumbwheelHand_) {
                const auto hand=*thumbwheelHand_;
                targeted[hand]=true;
                if(!triggerPressed_[hand] || !hands_[hand].valid || blocked[hand]) {
                    wheel.release();
                    thumbwheelHand_.reset();
                } else if(const auto local=thumbwheelLocalPoint(hands_[hand],index,true)) {
                    notches=wheel.drag(local->y,frameDeltaSeconds_);
                }
            } else notches=wheel.updateMomentum(frameDeltaSeconds_);
            if(notches && toolConfig_.adjustExtrudeLengthDetents(notches,
                    nadoc_vr::extrudeWheelStep(latticeSquare_,index))) {
                changed=true;
                pulse(thumbwheelHand_.value_or(1),wheel.dragging()?.16F:.10F);
            }
        }
        if(changed) {publishToolConfiguration();refreshExtrudePanel();}
        return targeted;
    }

    std::vector<nadoc_vr::RemotePanelTarget> remotePanelTargets() {
        std::vector<nadoc_vr::RemotePanelTarget> targets;
        auto add=[&](auto& placement,auto bounds,float width=.025F){targets.push_back({&placement,bounds,bounds,width});};
        for(auto& m:sidebarMenus_.menus)if(m.open)add(m.placement,m.bounds(),.04F);
        if(latticeOpen_)add(latticePlacement_,kLatticePanelBounds);
        if(viewTools_.open)add(viewTools_.placement,VRViewTools::panelBounds());
        if(desktopPanel_.open)targets.push_back({&desktopPanel_.placement,desktopPanel_.bounds(),desktopPanel_.chromeBounds()});
        if(representationLoading_.popup.active && representationLoading_.popup.anchored)
            add(representationLoading_.popup.placement,nadoc_vr::MenuPanelBounds{{-.53F,-.38F},{.53F,.38F}});
        return targets;
    }

    std::array<bool,2> processTrajectoryInput(std::array<bool,2> blocked,
                                             const std::array<float,2>& foreground) {
        auto& menu=sidebarMenus_.menus[0];
        if(!trajectoryPanel_.active || !menu.open || !menu.customTab || menu.tab().key!="trajectory" ||
           !trajectoryState_.active || trajectoryState_.frameCount==0) {
            trajectoryScrubHand_.reset();return blocked;
        }
        for(size_t hand=0;hand<hands_.size();++hand) {
            if(trajectoryScrubHand_ && *trajectoryScrubHand_!=hand)continue;
            if(hand==1U && radialToolMenu_.open()) {
                if(trajectoryScrubHand_==hand)trajectoryScrubHand_.reset();
                blocked[hand]=true;continue;
            }
            if(blocked[hand] || !hands_[hand].valid || !triggerPressed_[hand]) {
                if(trajectoryScrubHand_==hand)trajectoryScrubHand_.reset();
                continue;
            }
            const auto frame=nadoc_vr::TrajectoryPanel::frameAt(hands_[hand],menu,trajectoryState_);
            if(!trajectoryScrubHand_) {
                if(!frame || !triggerClicked_[hand])continue;
                const auto control=menu.hit(hands_[hand]);
                if(!control || !control->enabled || control->id!="trajectory:seek")continue;
                const auto local=menu.raySurfacePoint(hands_[hand]);
                if(!local)continue;
                const float distance=glm::length(menu.placement.worldPoint(*local)-hands_[hand].position);
                if(distance>=foreground[hand])continue;
                const auto& other=sidebarMenus_.menus[1];
                if(other.open)if(const auto point=other.raySurfacePoint(hands_[hand]))
                    if(glm::length(other.placement.worldPoint(*point)-hands_[hand].position)<distance)continue;
                if(menu.focus.active || sidebarMenus_.menus[hand].focus.active)continue;
                trajectoryScrubHand_=hand;trajectoryScrubFrame_=*frame;
                publishTrajectoryRequest("seek",*frame);pulse(hand,.22F);
            } else if(frame && *frame!=trajectoryScrubFrame_) {
                trajectoryScrubFrame_=*frame;publishTrajectoryRequest("seek",*frame);
            }
            blocked[hand]=true;
        }
        return blocked;
    }

    std::array<bool,2> processDesktopInput(std::array<bool,2> blocked) {
        desktopSurface_.hidePointer();desktopPanel_.magnifying=false;desktopPanel_.closeHovered=false;
        if(!desktopPanel_.open)return blocked;
        // One pointer owns the desktop each frame. Prefer a hand applying pressure.
        std::array<size_t,2> order{0,1};
        if(triggerValues_[1]>triggerValues_[0])order={1,0};
        bool pointerOwned=false;
        for(size_t h:order) {
            if(blocked[h])continue;
            const auto local=desktopPanel_.hit(hands_[h]);if(!local)continue;
            const float distance=glm::length(desktopPanel_.placement.worldPoint(*local)-hands_[h].position);
            if(viewTools_.open)if(const auto uv=viewTools_.hit(hands_[h]))
                if(glm::length(viewTools_.world(*uv)-hands_[h].position)<distance)continue;
            blocked[h]=true;
            if(desktopPanel_.placement.dragHand() || desktopPanel_.placement.resizeActive())continue;
            if(nadoc_vr::DesktopPanel::contains(desktopPanel_.closeBounds(),*local)) {
                desktopPanel_.closeHovered=true;
                if(triggerClicked_[h]) {desktopPanel_.open=false;desktopPanel_.magnifying=false;desktopSurface_.hidePointer();break;}
            } else if(!pointerOwned)if(const auto uv=desktopPanel_.uv(hands_[h])) {
                pointerOwned=true;desktopPanel_.pointer=*uv;
                desktopSurface_.setPointer(*uv,!witness_ && !liveSocket_.enabled());
                desktopPanel_.magnifying=triggerPartial_[h] && !triggerPressed_[h];
                if(triggerClicked_[h] && !witness_ && !liveSocket_.enabled())desktopSurface_.click();
            }
        }
        return blocked;
    }

    void updateDesktopFrame() {
        if(!desktopPanel_.open)return;
        const auto b=desktopPanel_.bounds(),content=desktopPanel_.content(),close=desktopPanel_.closeBounds();
        std::vector<Vertex> lines;
        auto line=[&](glm::vec3 a,glm::vec3 b,glm::vec3 color){lines.push_back({a,color,1});lines.push_back({b,color,1});};
        auto text=[&](const std::string& label,float x,float y,float scale,glm::vec3 color) {
            for(size_t c=0;c<label.size();++c) {
                const auto rows=nadoc_vr::glyph(label[c]);
                for(size_t r=0;r<rows.size();++r)for(int col=0;col<5;++col)if(rows[r]&(1U<<(4-col))) {
                    const float px=x+(c*6+col)*scale,py=y-r*scale;
                    line({px,py,0},{px+scale*.82F,py,0},color);
                }
            }
        };
        const auto state=(desktopPanel_.placement.resizeActive()||desktopPanel_.placement.remoteMode()==2)?nadoc_vr::GripFrameState::resizing:
            (desktopPanel_.placement.dragHand()||desktopPanel_.placement.remoteMode()==1)?nadoc_vr::GripFrameState::moving:desktopPanel_.placement.remoteHovered?nadoc_vr::GripFrameState::ready:nadoc_vr::GripFrameState::idle;
        nadoc_vr::drawGripFrame(b,state,line,[](nadoc_vr::MenuPanelBounds,glm::vec3){});
        nadoc_vr::ui_style::rounded(close,{},desktopPanel_.closeHovered?nadoc_vr::ui_style::focus:nadoc_vr::ui_style::danger,
            line,[](nadoc_vr::MenuPanelBounds,glm::vec3){});
        text("CLOSE",close.minimum.x+.035F,close.maximum.y-.018F,.005F,nadoc_vr::ui_style::text);
        text("DESKTOP",content.minimum.x,close.maximum.y-.012F,.006F,nadoc_vr::ui_style::text);
        text("LIGHT TRIGGER: 3X LENS / CLICK: SELECT",content.minimum.x+.36F,close.maximum.y-.02F,.0035F,nadoc_vr::ui_style::text);
        desktopFrameSurface_.update(lines,desktopPanel_.chromeBounds(),true);
    }

    void updateControllerGuides() {
        nadoc_vr::CalculationScope auditScope("updateControllerGuides");
        controllerGuides_.clear();
        solidWheels_.vertices.clear();
        controllerHandEnds_ = {};
        auto line = [&](const glm::vec3& a, const glm::vec3& b, const glm::vec3& color) {
            controllerGuides_.push_back(Vertex{a, color, 1.0F});
            controllerGuides_.push_back(Vertex{b, color, 1.0F});
        };
        componentGallery_.guides(hands_,line);
        qrCalibration_.drawAnchor(line);
        auto circle = [&](const glm::vec3& center, float radius,
                          int axisA, int axisB, const glm::vec3& color) {
            constexpr int segments = 24;
            for (int segment = 0; segment < segments; ++segment) {
                const float angleA = glm::two_pi<float>()
                                   * static_cast<float>(segment) / segments;
                const float angleB = glm::two_pi<float>()
                                   * static_cast<float>(segment + 1) / segments;
                glm::vec3 a = center;
                glm::vec3 b = center;
                a[axisA] += std::cos(angleA) * radius;
                a[axisB] += std::sin(angleA) * radius;
                b[axisA] += std::cos(angleB) * radius;
                b[axisB] += std::sin(angleB) * radius;
                line(a, b, color);
            }
        };
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            if (!hands_[hand].valid) {
                controllerHandEnds_[hand] = controllerGuides_.size();
                continue;
            }
            glm::vec3 color = hand == 0U
                ? glm::vec3(0.20F, 0.75F, 1.0F)
                : glm::vec3(1.0F, 0.55F, 0.18F);
            if (hands_[hand].pressed) color = {0.35F, 1.0F, 0.42F};
            if (hand == 1U && pendingToolTransform_.dragging()) {
                color = {1.0F, 0.72F, 0.18F};
            }
            if (manipulator_.mode() == nadoc_vr::ManipulationMode::two_hand) {
                color = {0.95F, 0.35F, 1.0F};
            }
            const glm::vec3 origin = hands_[hand].position;
            const glm::vec3 forward = hands_[hand].orientation * glm::vec3(0, 0, -1);
            const glm::vec3 right = hands_[hand].orientation * glm::vec3(1, 0, 0);
            const glm::vec3 up = hands_[hand].orientation * glm::vec3(0, 1, 0);
            const glm::vec3 sphereCenter = selectionVolumeCenter(hand);
            const glm::vec3 tip = sphereCenter;
            line(origin - forward * 0.045F, origin, color * 0.65F);
            line(origin, tip, color);
            line(tip - right * 0.008F, tip + right * 0.008F, color);
            line(tip - up * 0.008F, tip + up * 0.008F, color);
            if (const auto p = desktopPanel_.hit(hands_[hand])) line(tip,desktopPanel_.placement.worldPoint(*p),color*.55F);
            if(remotePanels_.rayPoints[hand])line(tip,*remotePanels_.rayPoints[hand],color*.55F);
            else if (const auto hit = routingPopup_.anyOpen()?routingPopup_.rayEndpoint(hands_[hand]):sidebarMenus_.rayEndpoint(hands_[hand])) {
                line(tip, *hit, color * 0.55F);
            }
            if (latticeOpen_ && hand == 1U) {
                if (const auto panelHit = latticePlacement_.rayPanelLocalPoint(
                        hands_[hand], kLatticePanelBounds.minimum,
                        kLatticePanelBounds.maximum)) {
                    line(tip, latticePlacement_.worldPoint(*panelHit), color * 0.55F);
                }
            }
            const glm::vec3 sphereColor = triggerPartial_[hand]
                ? glm::mix(color, glm::vec3(1.0F), 0.35F) : color * 0.52F;
            const float radius = selectionVolumes_[hand].radius();
            if(ligation_.nickActive && hand==1) ligation_.scissors(sphereCenter,hands_[hand].orientation,triggerValues_[hand],line);
            else if(movePanel_.selectionEnabled(hand)) {
            circle(sphereCenter, radius, 0, 1, sphereColor);
            circle(sphereCenter, radius, 0, 2, sphereColor);
            circle(sphereCenter, radius, 1, 2, sphereColor);
            }
            controllerHandEnds_[hand] = controllerGuides_.size();
        }
        if (hands_[0].valid && hands_[1].valid &&
            manipulator_.mode() == nadoc_vr::ManipulationMode::two_hand) {
            line(hands_[0].position, hands_[1].position, {0.95F, 0.35F, 1.0F});
        }
        // Surface paths follow the control under test. Retain the last wheel
        // after release so a completed drag stays reviewable beside its value.
        if (thumbwheelHovered_) controllerContactWheel_ = thumbwheelHovered_;
        for (size_t index=0;index<thumbwheelControls_.size();++index)
            if (thumbwheelControls_[index].dragging()) controllerContactWheel_=index;
        if (!thumbwheelHovered_ && !thumbwheelControls_[0].dragging()
            && !thumbwheelControls_[1].dragging() && latticeHover_)
            controllerContactWheel_.reset();
        const auto& contactPlacement=controllerContactWheel_
            ? sidebarMenus_.menus[1].placement : latticePlacement_;
        const auto contactPosition=controllerContactWheel_
            ? contactPlacement.worldPoint(nadoc_vr::extrudeWheelFront(*controllerContactWheel_))
            : contactPlacement.position();
        controllerPaths_.sample(hands_, latticeOpen_ || thumbwheelAvailable()
            ? std::optional<glm::vec3>(contactPosition) : std::nullopt,
            contactPlacement.orientation()*glm::vec3(0,0,1));
        controllerContactGuides_ = {};
        controllerPaths_.drawContact([&](const auto& a,const auto& b,const auto& color,bool actual) {
            auto& guides=controllerContactGuides_[actual ? 1 : 0];
            guides.push_back(Vertex{a,color,1.0F}); guides.push_back(Vertex{b,color,1.0F});
        });
        controllerPathGuides_.clear();
        controllerPaths_.draw([&](const glm::vec3& a, const glm::vec3& b, const glm::vec3& color) {
            controllerPathGuides_.push_back(Vertex{a, color, 1.0F});
            controllerPathGuides_.push_back(Vertex{b, color, 1.0F});
        });
        const bool deformationTool = toolConfig_.active() &&
            (toolConfig_.mode() == nadoc_vr::ToolMode::twist ||
             toolConfig_.mode() == nadoc_vr::ToolMode::bend);
        if (deformationTool) {
            const glm::mat4 transform = manipulator_.transform();
            auto worldPoint = [&](const glm::vec3& local) {
                return glm::vec3(transform * glm::vec4(local, 1.0F));
            };
            for (size_t slot = 0; slot < planeGuides_.size(); ++slot) {
                if (!planeGuides_[slot]) continue;
                const auto pose = deformationPlanePose(slot);
                const auto [axisU,axisV] = deformationPlaneAxes(pose.normal);
                const bool hovered=std::find(bendPanel_.planeHover.begin(),bendPanel_.planeHover.end(),slot)!=bendPanel_.planeHover.end();
                const glm::vec3 color = hovered?glm::vec3(.3F,1.F,1.F):slot == 0U
                    ? glm::vec3(1.0F, 0.95F, 0.35F)
                    : glm::vec3(1.0F, 0.52F, 0.18F);
                const glm::vec3 cornerA = pose.center
                    - axisU * pose.halfExtent - axisV * pose.halfExtent;
                const glm::vec3 cornerB = pose.center
                    + axisU * pose.halfExtent - axisV * pose.halfExtent;
                const glm::vec3 cornerC = pose.center
                    + axisU * pose.halfExtent + axisV * pose.halfExtent;
                const glm::vec3 cornerD = pose.center
                    - axisU * pose.halfExtent + axisV * pose.halfExtent;
                line(worldPoint(cornerA), worldPoint(cornerB), color);
                line(worldPoint(cornerB), worldPoint(cornerC), color);
                line(worldPoint(cornerC), worldPoint(cornerD), color);
                line(worldPoint(cornerD), worldPoint(cornerA), color);
                const float marker = glm::clamp(
                    pose.halfExtent * 0.08F, 0.006F, 0.05F);
                line(worldPoint(pose.center - axisU * marker),
                     worldPoint(pose.center + axisU * marker), color);
                line(worldPoint(pose.center - axisV * marker),
                     worldPoint(pose.center + axisV * marker), color);
                line(worldPoint(pose.center),
                     worldPoint(pose.center + pose.normal * marker * 2.0F), color);
            }
        }
        // The tablet is an overlay, so scene selection and tool feedback stay
        // visible while it is open.
        {
            if (const auto* feedback = currentToolContextFeedback();
                feedback && feedback->resolved && !extrudeConfirmation_) {
                const glm::vec3 facePosition = feedback->facePosition;
                const glm::vec3 faceNormal = feedback->faceNormal;
                const glm::vec3 previewOrigin = feedback->previewOrigin;
                const glm::vec3 localNormal = glm::normalize(faceNormal);
                const glm::vec3 reference = std::abs(localNormal.z) < 0.90F
                    ? glm::vec3(0, 0, 1) : glm::vec3(0, 1, 0);
                const glm::vec3 tangentA = glm::normalize(glm::cross(localNormal, reference));
                const glm::vec3 tangentB = glm::normalize(glm::cross(localNormal, tangentA));
                const glm::mat4 transform = manipulator_.transform();
                auto worldPoint = [&](const glm::vec3& local) {
                    return glm::vec3(transform * glm::vec4(local, 1.0F));
                };
                const glm::vec3 color = feedback->occupied
                    ? glm::vec3(1.0F, 0.25F, 0.15F)
                    : feedback->deformed
                        ? glm::vec3(0.85F, 0.32F, 1.0F)
                        : glm::vec3(0.25F, 0.95F, 1.0F);
                constexpr int kSegments = 24;
                constexpr float kRadius = 0.025F;
                constexpr float kNormalLength = 0.065F;
                for (int segment = 0; segment < kSegments; ++segment) {
                    const float angleA = glm::two_pi<float>()
                                       * static_cast<float>(segment) / kSegments;
                    const float angleB = glm::two_pi<float>()
                                       * static_cast<float>(segment + 1) / kSegments;
                    const glm::vec3 ringA = facePosition + kRadius * (
                        tangentA * std::cos(angleA) + tangentB * std::sin(angleA));
                    const glm::vec3 ringB = facePosition + kRadius * (
                        tangentA * std::cos(angleB) + tangentB * std::sin(angleB));
                    line(worldPoint(ringA), worldPoint(ringB), color);
                }
                line(worldPoint(facePosition),
                     worldPoint(facePosition + localNormal * kNormalLength), color);
                if (toolConfig_.mode() == nadoc_vr::ToolMode::extrude &&
                    feedback->footprintResolved && toolConfig_.lengthBp() > 0) {
                    const float radius = 1.0F * normalizationScale_;
                    const glm::vec3 end = nadoc_vr::extrusionPreviewEnd(
                        previewOrigin, localNormal, toolConfig_.lengthBp(),
                        toolConfig_.directionSign(),
                        nadoc_vr::kDnaBasePairRiseNanometers,
                        normalizationScale_);
                    const glm::vec3 previewColor = feedback->occupied
                        ? glm::vec3(1.0F, 0.20F, 0.12F)
                        : toolConfig_.directionSign() < 0
                            ? glm::vec3(1.0F, 0.55F, 0.15F)
                            : glm::vec3(0.20F, 0.85F, 1.0F);
                    constexpr int kPreviewSegments = 16;
                    for (int segment = 0; segment < kPreviewSegments; ++segment) {
                        const float angleA = glm::two_pi<float>()
                                           * static_cast<float>(segment)
                                           / kPreviewSegments;
                        const float angleB = glm::two_pi<float>()
                                           * static_cast<float>(segment + 1)
                                           / kPreviewSegments;
                        const glm::vec3 offsetA = radius * (
                            tangentA * std::cos(angleA) + tangentB * std::sin(angleA));
                        const glm::vec3 offsetB = radius * (
                            tangentA * std::cos(angleB) + tangentB * std::sin(angleB));
                        line(worldPoint(previewOrigin + offsetA),
                             worldPoint(previewOrigin + offsetB), previewColor);
                        line(worldPoint(end + offsetA), worldPoint(end + offsetB),
                             previewColor);
                        if (segment % 4 == 0) {
                            line(worldPoint(previewOrigin + offsetA),
                                 worldPoint(end + offsetA), previewColor);
                        }
                    }
                }
            }
            if(movePanel_.active && movePanel_.beamEnd && hands_[1].valid)
                line(hands_[1].position,*movePanel_.beamEnd,{.35F,1.F,.7F});
        }

        if(extrudePreviewVisible())freeformDraft_.preview(extrudeLatticeDraft_.cells(), latticeSquare_, extrudePlane_.plane,
            toolConfig_.lengthBp()*toolConfig_.directionSign(), manipulator_.transform(),
            normalizationCenter_, normalizationScale_, {0,0,-kViewDistanceMeters}, line);
        if(extrudePreviewVisible() && !freeformDraft_.placed() &&
           !freeformDraft_.armed() && toolConfig_.targetSelectionKind()=="none") {
            if(const auto* context=latticeContext_.find(extrudePlane_.plane))
                context->preview(extrudeLatticeDraft_.cells(),latticeSquare_,
                    toolConfig_.lengthBp()*toolConfig_.directionSign(),manipulator_.transform(),
                    normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters},line);
        }
        drawSweep(line);
        drawBend(line);
        if(!bendPanel_.active && !ligation_.active && !ligation_.nickActive) {
            endResize_.draw(manipulator_.transform(),normalizationScale_,line);
            endResize_.drawPointer(witnessObserverOrientation_,line,
                [&](const auto&... args){appendPlacedText(args...);});
        }
        ligation_.draw(manipulator_.transform(),line);
        ligation_.drawNick(manipulator_.transform(),line);
        appendRadialToolGuides();
        selectionWheel_.draw([&](auto a,auto b,auto color){controllerGuides_.push_back({a,color,1});controllerGuides_.push_back({b,color,1});},selectionLevel_);
        appendLatticeGuides();
        volumePanel_.draw(manipulator_.transform(),normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters},line);
        dimensionPanel_.tool.draw(manipulator_.transform(),normalizationScale_,witnessObserverOrientation_,line,
            [&](const auto&... args){appendPlacedText(args...);});
        trajectoryPanel_.refresh(sidebarMenus_.menus,trajectoryState_);
        sidebarMenus_.draw();
        routingPopup_.draw();
        updateDesktopFrame();
        appendThumbwheelGuides();
        witnessActorGuideCount_ = controllerGuides_.size();
        if (witness_) {
            const auto& head = witness_->input().head;
            const glm::vec3 color = witness_->failed()
                ? glm::vec3(1.0F, 0.18F, 0.12F)
                : witness_->finished()
                    ? glm::vec3(0.25F, 1.0F, 0.42F)
                    : glm::vec3(0.20F, 0.95F, 1.0F);
            const auto frustum = nadoc_vr::scrywrite::witnessHeadFrustum(head);
            for (size_t index = 0; index < frustum.size(); ++index) {
                line(frustum[index].first, frustum[index].second,
                     index % 2 == 0 ? color * 0.65F : color);
            }
            witnessStatusPlacement_.openDocked(
                head.position + head.orientation * glm::vec3(-0.18F, 0.16F, -0.55F),
                head.orientation);
            const char* state = witness_->failed() ? "FAILED"
                : witness_->finished() ? "PASSED"
                : witness_->paused() ? "PAUSED" : "RUNNING";
            appendPlacedText(
                witnessStatusPlacement_, std::string("SCRYWRITE ") + state +
                    " L" + std::to_string(witness_->currentLine()),
                0.0F, 0.0F, 0.006F, color, 0.002F);
        }
    }

    [[nodiscard]] std::array<nadoc_vr::HandPose,2> menuGripContacts() const {
        return nadoc_vr::MenuPlacement::borderContacts(hands_,
            {selectionVolumes_[0].radius(),selectionVolumes_[1].radius()});
    }

    [[nodiscard]] glm::vec3 selectionVolumeCenter(size_t hand) const {
        return hands_[hand].position
             + hands_[hand].orientation * glm::vec3(0.0F, 0.0F, -0.12F);
    }

    void updateSelectionVolumeCandidates(
        const std::array<bool, 2>& menuControlTargeted) {
        const std::string previous = sceneHover_ ? sceneHover_->identity : "";
        sceneHover_.reset();
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            snapSelectionHits_[hand].clear();
            snapSelectionOwnerTokens_[hand].clear();
            snapSelectionDirectIdentities_[hand].clear();
            if (!movePanel_.selectionEnabled(hand) || menuControlTargeted[hand] || !hands_[hand].valid ||
                !triggerPartial_[hand] || gripPressed_[hand]) {
                continue;
            }
            auto overlaps = glScene_->selectVolume(
                selectionVolumeCenter(hand), selectionVolumes_[hand].radius(),
                manipulator_.transform());
            if(bendPanel_.active && !bendPanel_.selecting && bendPanel_.twist && bendPanel_.pickSlot)
                std::erase_if(overlaps,[&](const auto& hit){return !glScene_->belongsToSelection(hit.identity,committedSelectionOwnerTokens_);});
            SelectionVolumeHits resolved = glScene_->resolveSelectionVolumeHits(
                overlaps, selectionLevel_, selectedSelectionKind_, selectedOwnerTokens_);
            if(bendPanel_.active && bendPanel_.elements && selectedSelectionKind_=="end" &&
               resolved.representatives.empty() && !overlaps.empty()) {
                resolved.representatives.push_back(overlaps.front());
                resolved.ownerTokens=selectedOwnerTokens_;
            }
            // Move/Rotate edits one exact target. A generous acquisition sphere
            // must not turn a nearby base pick into an unusable multi-selection.
            if((movePanel_.active || (bendPanel_.active && !bendPanel_.selecting)) && resolved.representatives.size()>1) {
                resolved.representatives.resize(1);
                if(resolved.ownerTokens.size()>1)resolved.ownerTokens.resize(1);
                if(resolved.directIdentities.size()>1)resolved.directIdentities.resize(1);
            }
            // A hit unsupported by the fixed level is not an empty-space click.
            // Let the browser reject it while preserving the accumulated selection.
            if (selectionLevel_ != "default" && resolved.representatives.empty() && !overlaps.empty())
                resolved.representatives.push_back(overlaps.front());
            snapSelectionHits_[hand] = std::move(resolved.representatives);
            snapSelectionOwnerTokens_[hand] = std::move(resolved.ownerTokens);
            snapSelectionDirectIdentities_[hand] = std::move(resolved.directIdentities);
            if (!snapSelectionHits_[hand].empty() &&
                (!sceneHover_ || snapSelectionHits_[hand].front().distance <
                    sceneHover_->distance)) {
                sceneHover_ = snapSelectionHits_[hand].front();
            }
        }
        std::vector<std::string> snapOwnerTokens;
        std::vector<std::string> snapDirectIdentities;
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            snapOwnerTokens.insert(
                snapOwnerTokens.end(), snapSelectionOwnerTokens_[hand].begin(),
                snapSelectionOwnerTokens_[hand].end());
            snapDirectIdentities.insert(
                snapDirectIdentities.end(),
                snapSelectionDirectIdentities_[hand].begin(),
                snapSelectionDirectIdentities_[hand].end());
        }
        glScene_->setSelectionHighlights(
            snapOwnerTokens, snapDirectIdentities,
            committedSelectionOwnerTokens_, committedSelectionIdentities_);
        const std::string current = sceneHover_ ? sceneHover_->identity : "";
        if (current != previous) {
            publishHover(current);
            if (!current.empty()) std::cout << "VR Selection Volume snap: " << current << '\n';
        }
    }

    void publishHover(const std::string& identity) {
        publishedHoverIdentity_ = identity;
        publishEventState();
    }

    void publishSelect(const std::vector<std::string>& identities) {
        static constexpr size_t kMaximumSelections = 16;
        static constexpr size_t kMaximumIdentityBytes = 2048;
        lastSelectIdentities_.clear();
        size_t bytes = 0;
        for (const std::string& identity : identities) {
            if (identity.empty() ||
                std::find(lastSelectIdentities_.begin(), lastSelectIdentities_.end(),
                          identity) != lastSelectIdentities_.end() ||
                lastSelectIdentities_.size() >= kMaximumSelections ||
                bytes + identity.size() > kMaximumIdentityBytes) {
                continue;
            }
            lastSelectIdentities_.push_back(identity);
            bytes += identity.size();
        }
        lastSelectIdentity_ = lastSelectIdentities_.empty()
            ? std::string{} : lastSelectIdentities_.front();
        ++selectSequence_;
        publishEventState();
    }

    void publishPlanePick(const std::string& identity) {
        if (!planePickSlot_ || activePlanePickSequence_ != 0 ||
            !toolConfig_.active() ||
            (toolConfig_.mode() != nadoc_vr::ToolMode::twist &&
             toolConfig_.mode() != nadoc_vr::ToolMode::bend)) {
            return;
        }
        activePlanePickSequence_ = ++planePickSequence_;
        planePickConfigSequence_ = toolConfigSequence_;
        planePickIdentity_ = identity;
        planePickStatus_ = std::string("VALIDATING PLANE ") +
                         (*planePickSlot_ == "a" ? "A" : "B");
        publishEventState();
    }

    void clearPlanePick(bool keepStatus = false) {
        bendPickExtent_.reset();
        planePickSlot_.reset();
        activePlanePickSequence_ = 0;
        planePickConfigSequence_ = 0;
        planePickIdentity_.clear();
        if (!keepStatus) planePickStatus_.clear();
    }

    void clearPlaneGuides() {
        planeGuides_.fill(std::nullopt);
    }

    void publishSelectionLevel(const std::string& level) {
        selectionLevel_ = level;
        selectionLevelGuard_.requested(selectSequence_);
        ++levelSequence_;
        publishEventState();
    }

    void publishStyleRequest(Representation representation, Coloring coloring) {
        if (glScene_ && !glScene_->supportsRepresentation(representation)) {
            if(representationLoading_.enabled){
                if(representationLoading_.target!=representation)glScene_->cancelPreparedStyle();
                representationLoading_.start(representation,coloring,sceneRefresh_.revision());
            }
            return;
        }
        if(representationLoading_.pending && representationLoading_.target!=representation){representationLoading_.cancel();glScene_->cancelPreparedStyle();}
        if (glScene_ && representation == glScene_->representation() &&
            coloring == glScene_->coloring()) return;
        if (witness_ && eventPath_.empty()) {
            // Witness Mode is already prohibited from opening the browser event
            // channel.  Apply style choices to its private snapshot directly so a
            // semantic menu replay can validate the real native geometry and GPU
            // uploads without mutating a design or pretending the browser acked it.
            glScene_->setStyle(representation, coloring);
            desktopRepresentation_ = representationName(representation);
            desktopColoring_ = coloringName(coloring);
            requestedRepresentation_ = desktopRepresentation_;
            requestedColoring_ = desktopColoring_;
            std::cout << "VR_METRIC event=process_progress phase=witness_style_applied"
                      << " representation=" << requestedRepresentation_
                      << " coloring=" << requestedColoring_ << std::endl;
            return;
        }
        if(representationLoading_.enabled && !representationLoading_.pending) {
            auto& loading=representationLoading_;
            loading.target=representation;loading.color=coloring;loading.generation=sceneRefresh_.revision();
            loading.pending=true;loading.percent=96;loading.phase="waiting";loading.detail="Applying display";
        }
        requestedRepresentation_ = representationName(representation);
        requestedColoring_ = coloringName(coloring);
        ++styleSequence_;
        // Do not mutate GlScene here. Desktop owns asynchronous simulation
        // representation changes and will acknowledge this request through one
        // atomic style+geometry visualization revision.
        publishEventState();
    }

    void publishTrajectoryRequest(const std::string& action, uint32_t frameIndex) {
        if (witness_ && eventPath_.empty()) {
            std::cout << "VR_METRIC event=process_progress phase=witness_trajectory_request"
                      << " action=" << action << " frame_idx=" << frameIndex << std::endl;
            return;
        }
        trajectoryAction_ = action;
        trajectoryRequestedFrameIndex_ = frameIndex;
        ++trajectoryRequestSequence_;
        publishEventState();
    }

    bool extrudePreviewVisible() const {
        return toolConfig_.active() && toolConfig_.mode()==nadoc_vr::ToolMode::extrude && !extrudeConfirmation_;
    }

    void dismissConfirmedExtrude() {
        if(extrudeConfirmation_)return;
        auto& menu=sidebarMenus_.menus[1];
        extrudeConfirmation_=ExtrudeConfirmation{menu.offset(),latticeOpen_};
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        menu.open=false;menu.focus.reset();menu.hovered.clear();menu.pressed.clear();
        radialToolMenu_.close();
        latticeOpen_=false;latticeHover_.reset();latticeExitHovered_=false;
        latticePaintStroke_.reset();latticeGrip_.cancel();resetThumbwheels();
        // Keep the submitted configuration untouched until the asynchronous
        // result arrives, so a refused commit can restore the exact draft.
    }

    void finishConfirmedExtrude(const nadoc_vr::ToolExecutionFeedback& feedback) {
        if(!extrudeConfirmation_ || feedback.mode!="extrude" || feedback.action!="confirm" ||
           feedback.status=="pending")return;
        const auto dismissed=*extrudeConfirmation_;
        extrudeConfirmation_.reset();
        if(feedback.status=="succeeded") {
            freeformDraft_.clear();extrudeLatticeDraft_.clear();
            toolContextFeedback_.reset();
            if(toolConfig_.clear())publishToolConfiguration();
        } else {
            // Browser validation plans are consumed by an attempted commit.
            // Republish the preserved draft so retry gets a fresh plan, even
            // when the user does not change any extrusion settings.
            publishToolConfiguration();
            extrudePanel_.enter(sidebarMenus_.menus);
            sidebarMenus_.menus[1].offsets[sidebarMenus_.menus[1].selected]=dismissed.settingsOffset;
            latticeOpen_=dismissed.painterOpen;
            refreshExtrudePanel();
        }
    }

    void publishToolIntent(nadoc_vr::ToolAction action) {
        lastToolAction_ = action;
        lastToolConfigSequence_ = toolConfigSequence_;
        // Bind the intent to the acknowledged target visible at controller-click
        // time. Browser polling is asynchronous; looking up its later selection
        // could otherwise redirect Preview or Confirm to a different object.
        lastToolTargetIdentity_ = selectedIdentity_;
        lastToolTargetOwnerTokens_ = selectedOwnerTokens_;
        lastToolTargetKind_ = selectedSelectionKind_;
        if(toolShell_.mode()==nadoc_vr::ToolMode::sweep) {
            lastToolTargetIdentity_.clear();lastToolTargetOwnerTokens_.clear();lastToolTargetKind_="none";
        }
        if(action==nadoc_vr::ToolAction::confirm && toolConfig_.active() &&
           toolConfig_.mode()==nadoc_vr::ToolMode::extrude) {
            // A failed commit restores its original draft. Selection feedback
            // may have advanced while that draft was awaiting its result.
            lastToolTargetIdentity_=toolConfig_.targetIdentity();
            lastToolTargetOwnerTokens_=toolConfig_.targetOwnerTokens();
            lastToolTargetKind_=toolConfig_.targetSelectionKind();
        }
        if(action==nadoc_vr::ToolAction::undo && toolShell_.mode()==nadoc_vr::ToolMode::extrude) {
            // Undo is bound to the saved feature, independently of whatever
            // object became selected after the extrusion editor closed.
            lastToolTargetIdentity_.clear();lastToolTargetOwnerTokens_.clear();
            lastToolTargetKind_="none";
        }
        ++toolSequence_;
        publishEventState();
        if(action==nadoc_vr::ToolAction::confirm && toolShell_.mode()==nadoc_vr::ToolMode::extrude &&
           toolShell_.executionPending())dismissConfirmedExtrude();
    }

    void publishToolTransform() {
        lastToolTransform_ = glScene_
            ? glScene_->viewSpaceToolTransform(pendingToolTransform_.transform())
            : glm::mat4(1.0F);
        ++transformSequence_;
        publishEventState();
    }

    bool freeformAvailable() const { return toolConfig_.mode()==nadoc_vr::ToolMode::extrude && toolConfig_.targetSelectionKind()=="none" && extrudePlane_.reason!="empty"; }
    void publishToolConfiguration() {
        if (!toolConfig_.active() || !freeformAvailable()) freeformDraft_.clear();
        ++toolConfigSequence_;
        toolPreflightFeedback_.reset();
        preflightFeedbackSequence_ = 0;
        publishEventState();
    }

    void publishPresenterPose() {
        nadoc_vr::CalculationScope auditScope("publishPresenterPose");
        const double now=glfwGetTime();
        if(eventPath_.empty() || now-avatarPublishedAt_<.05)return;
        avatarPublishedAt_=now;
        const auto trackedFlags=XR_VIEW_STATE_POSITION_TRACKED_BIT|XR_VIEW_STATE_ORIENTATION_TRACKED_BIT;
        const bool tracked=(currentViewStateFlags_&trackedFlags)==trackedFlags && sessionState_==XR_SESSION_STATE_FOCUSED;
        const auto path=eventPath_+".avatar";
        std::ostringstream out;
        out<<std::setprecision(9);
        auto pose=[&](const glm::vec3& p,const glm::quat& q) {
            out<<"{\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"],\"orientation\":["<<q.x<<','<<q.y<<','<<q.z<<','<<q.w<<"]}";
        };
        out<<"{\"enabled\":"<<(showVRAvatar_&&shareActive_?"true":"false")<<",\"tracked\":"<<(tracked?"true":"false")
           <<",\"presentation\":"<<nadoc_vr::livePresentationJson(manipulator_.transform(),normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters})<<",\"head\":";
        pose(witnessObserverPosition_,witnessObserverOrientation_);
        out<<",\"hands\":[";
        for(size_t h=0;h<2;++h) {if(h)out<<',';if(hands_[h].valid)pose(hands_[h].position,hands_[h].orientation);else out<<"null";}
        out<<"]";
        if(showVRAvatar_ && shareActive_ && tracked)presenterUI_.write(out,controllerGuides_,witnessActorGuideCount_,sidebarMenus_,viewTools_,desktopSurface_,desktopPanel_,desktopFrameSurface_);
        out<<"}";
        avatarWriter_.publish(path,out.str());
    }

    void publishEventState() {
        nadoc_vr::CalculationScope auditScope("publishEventState");
        if (eventPath_.empty()) return;
        std::ostringstream output;
        auto identity = [&](const std::string& value) {
            if (value.empty()) output << "null";
            else output << '\"' << value << '\"';
        };
        output << "{\"sequence\":" << ++eventSequence_ << ",\"hover_identity\":";
        identity(publishedHoverIdentity_);
        output << ",\"share_control\":{\"sequence\":" << shareSequence_ << ",\"action\":\"" << shareAction_ << "\"}";
        output << ",\"simulation\":{\"sequence\":" << simulationPanel_.sequence << ",\"version\":" << simulationPanel_.requestedVersion << ",\"id\":\"" << simulationPanel_.requested << "\"}";
        output << ",\"routing\":{\"sequence\":" << routingPanel_.sequence << ",\"version\":" << routingPanel_.requestedVersion << ",\"id\":\"" << routingPanel_.requested << "\"}";
        output << ",\"view_tool\":{\"sequence\":" << viewTools_.sequence << ",\"index\":" << viewTools_.requested << "}";
        output << ",\"ligation\":{\"sequence\":" << ligation_.sequence
               << ",\"action\":\"" << ligation_.committedAction << "\""
               << ",\"version\":" << ligation_.committedVersion
               << ",\"source\":" << ligation_.committedSource
               << ",\"target\":" << ligation_.committedTarget << '}';
        output << ",\"end_resize\":{\"sequence\":" << endResize_.sequence
               << ",\"version\":" << endResize_.committedVersion
               << ",\"delta\":" << endResize_.committedDelta << '}';
        output << ",\"select_sequence\":" << selectSequence_
               << ",\"select_identity\":";
        identity(lastSelectIdentity_);
        output << ",\"select_identities\":[";
        for (size_t index = 0; index < lastSelectIdentities_.size(); ++index) {
            if (index > 0) output << ',';
            identity(lastSelectIdentities_[index]);
        }
        output << ']';
        output << ",\"level_sequence\":" << levelSequence_
               << ",\"selection_level\":\"" << selectionLevel_ << "\"";
        output << ",\"style_sequence\":" << styleSequence_
               << ",\"representation\":\"" << requestedRepresentation_
               << "\",\"coloring\":\"" << requestedColoring_ << "\"";
        output << ",\"trajectory_sequence\":" << trajectoryRequestSequence_
               << ",\"trajectory_action\":\"" << trajectoryAction_
               << "\",\"trajectory_frame_idx\":"
               << trajectoryRequestedFrameIndex_;
        output << ",\"tool_sequence\":" << toolSequence_
               << ",\"tool_mode\":\"" << nadoc_vr::toolModeName(toolShell_.mode())
               << "\",\"tool_action\":\""
               << nadoc_vr::toolActionName(lastToolAction_) << "\"";
        output << ",\"tool_action_config_sequence\":" << lastToolConfigSequence_;
        output << ",\"tool_target_identity\":";
        identity(lastToolTargetIdentity_);
        output << ",\"tool_target_kind\":\"" << lastToolTargetKind_
               << "\",\"tool_target_owner_tokens\":[";
        for (size_t index = 0; index < lastToolTargetOwnerTokens_.size(); ++index) {
            if (index != 0) output << ',';
            output << '\"' << lastToolTargetOwnerTokens_[index] << '\"';
        }
        output << ']';
        output << ",\"tool_config_sequence\":" << toolConfigSequence_
               << ",\"tool_config\":";
        if (!toolConfig_.active()) {
            output << "null";
        } else {
            output << "{\"mode\":\"" << nadoc_vr::toolModeName(toolConfig_.mode())
                   << "\",\"target_identity\":";
            identity(toolConfig_.targetIdentity());
            output << ",\"target_kind\":\"" << toolConfig_.targetSelectionKind()
                   << "\",\"target_owner_tokens\":[";
            const auto& configTokens = toolConfig_.targetOwnerTokens();
            for (size_t index = 0; index < configTokens.size(); ++index) {
                if (index != 0) output << ',';
                output << '\"' << configTokens[index] << '\"';
            }
            output << ']';
            if (toolConfig_.mode() == nadoc_vr::ToolMode::extrude) {
                output << ",\"length_bp\":" << toolConfig_.lengthBp()
                       << ",\"extrude_from\":\"" << extrudePlane_.plane << "\""
                       << ",\"extrude_from_reason\":\"" << extrudePlane_.reason << "\""
            << ",\"freeform_armed\":" << (freeformDraft_.armed() ? "true" : "false")
            << ",\"freeform_placed\":" << (freeformDraft_.placed() ? "true" : "false")
                       << ",\"direction_sign\":" << toolConfig_.directionSign()
                       << ",\"strand_filter\":\""
                       << nadoc_vr::toolStrandFilterName(toolConfig_.strandFilter())
                       << "\",\"ligate_adjacent\":"
                       << (toolConfig_.ligateAdjacent() ? "true" : "false")
                       << ",\"footprint_state\":\"unresolved\"";
                freeformDraft_.appendJson(output);
                output << ",\"painted_footprint\":{\"lattice_type\":\""
                       << (latticeSquare_ ? "SQUARE" : "HONEYCOMB") << "\",\"cells\":[";
                for (size_t i = 0; i < extrudeLatticeDraft_.cells().size(); ++i) {
                    if (i) output << ',';
                    const auto& cell = extrudeLatticeDraft_.cells()[i];
                    output << '[' << cell.row << ',' << cell.column << ']';
                }
                output << "]}";
            } else if(toolConfig_.mode()==nadoc_vr::ToolMode::sweep) {
                writeSweepConfiguration(output);
            } else {
                auto optionalInteger = [&](const std::optional<int32_t>& value) {
                    if (value) output << *value;
                    else output << "null";
                };
                output << ",\"plane_a_bp\":";
                optionalInteger(toolConfig_.planeABp());
                output << ",\"plane_b_bp\":";
                optionalInteger(toolConfig_.planeBBp());
                if (toolConfig_.mode() == nadoc_vr::ToolMode::twist) {
                    output << ",\"amount_mode\":\""
                           << nadoc_vr::twistAmountModeName(toolConfig_.twistAmountMode())
                           << "\",\"amount\":" << toolConfig_.twistAmount();
                } else {
                    output << ",\"angle_deg\":" << toolConfig_.bendAngleDegrees()
                           << ",\"direction_deg\":"
                           << toolConfig_.bendDirectionDegrees();
                    if(bendPanel_.posed && (selectedSelectionKind_=="cluster" || selectedSelectionKind_=="end")) {
                        output<<",\"bend_endpoints\":[";
                        for(size_t i=0;i<2;++i) {
                            const auto q=((i==0?bendPanel_.arc.a:bendPanel_.arc.b)-glm::vec3(0,0,-kViewDistanceMeters))/normalizationScale_+normalizationCenter_;
                            if(i)output<<",";
                            output<<"["<<q.x<<","<<q.y<<","<<q.z<<"]";
                        }
                        output<<"]";
                        const auto mid=(bendPanel_.arc.point(.5F)-glm::vec3(0,0,-kViewDistanceMeters))/normalizationScale_+normalizationCenter_;
                        output<<",\"bend_midpoint\":["<<mid.x<<","<<mid.y<<","<<mid.z<<"]";
                    }
                }
            }
            output << '}';
        }
        if(bendPickExtent_ && activePlanePickSequence_)output<<",\"plane_pick_extent\":\""<<*bendPickExtent_<<"\"";
        if(bendPickPosition_ && bendPanel_.active && activePlanePickSequence_) {
            const auto& p=*bendPickPosition_;
            output<<",\"plane_pick_position\":["<<p.x<<","<<p.y<<","<<p.z<<"]";
        }
        output << ",\"plane_pick_sequence\":" << activePlanePickSequence_
               << ",\"plane_pick_config_sequence\":" << planePickConfigSequence_
               << ",\"plane_pick_slot\":";
        if (planePickSlot_ && activePlanePickSequence_ > 0) {
            output << '\"' << *planePickSlot_ << '\"';
        } else {
            output << "null";
        }
        output << ",\"plane_pick_identity\":";
        if (!planePickIdentity_.empty() && activePlanePickSequence_ > 0) {
            identity(planePickIdentity_);
        } else {
            output << "null";
        }
        output << ",\"transform_sequence\":" << transformSequence_
               << ",\"transform_matrix\":[";
        bool firstValue = true;
        for (size_t column = 0; column < 4; ++column) {
            for (size_t row = 0; row < 4; ++row) {
                if (!firstValue) output << ',';
                output << lastToolTransform_[column][row];
                firstValue = false;
            }
        }
        output << ']';
        output << ",\"ready_sequence\":" << readySequence_;
        if (readySequence_ == 0) {
            output << ",\"first_frame_at_ms\":null"
                   << ",\"first_frame_cpu_ms\":null"
                   << ",\"display_period_ms\":null";
        } else {
            output << std::setprecision(17)
                   << ",\"first_frame_at_ms\":" << firstFrameAtMilliseconds_
                   << ",\"first_frame_cpu_ms\":" << firstFrameCpuMilliseconds_
                   << ",\"display_period_ms\":" << displayPeriodMilliseconds_;
        }
        output << '}';
        eventWriter_.publish(eventPath_, output.str());
    }

    void pollSelectionFeedback() {
        if (feedbackPath_.empty() || (++feedbackPollFrame_ % 3U) != 0U) return;
        std::ifstream input(feedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size < 0 || size > 1048576) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        const auto feedback = nadoc_vr::parseSelectionFeedback(
            record, feedbackSequence_, selectSequence_);
        if (!feedback) return;
        feedbackSequence_ = feedback->sequence;
        committedSelectionIdentities_ = feedback->accepted
            ? feedback->selectionIdentities : std::vector<std::string>{};
        committedSelectionOwnerTokens_ = feedback->accepted
            ? feedback->selectionOwnerTokens : std::vector<std::string>{};
        const std::string previousIdentity = selectedIdentity_;
        const std::vector<std::string> previousOwnerTokens = selectedOwnerTokens_;
        const std::string previousSelectionKind = selectedSelectionKind_;
        if (selectionLevelGuard_.accepts(feedback->sequence)) selectionLevel_ = feedback->level;
        selectedIdentity_ = feedback->accepted && feedback->selected
            ? feedback->identity : "";
        selectedOwnerTokens_ = feedback->accepted && feedback->selected
            ? feedback->ownerTokens : std::vector<std::string>{};
        selectedSelectionKind_ = feedback->accepted && feedback->selected
            ? feedback->selectionKind : "none";
        if(bendPanel_.active) {
            bendPanel_.pendingSelection.clear();
            bendPanel_.describeSelection(selectedSelectionKind_,committedSelectionOwnerTokens_);
            if(!feedback->accepted || !feedback->selected)bendPanel_.defaultPlanes=false;
        }
        const bool targetChanged = selectedIdentity_ != previousIdentity ||
            selectedOwnerTokens_ != previousOwnerTokens ||
            selectedSelectionKind_ != previousSelectionKind;
        if(toolShell_.mode()!=nadoc_vr::ToolMode::sweep)toolShell_.syncSelection(selectedSelectionKind_, targetChanged);
        if (targetChanged && toolConfig_.mode()!=nadoc_vr::ToolMode::sweep && !extrudeConfirmation_ && toolConfig_.active() &&
            toolConfig_.bind(
                toolConfig_.mode(), selectedIdentity_, selectedSelectionKind_,
                selectedOwnerTokens_)) {
            clearPlanePick();
            clearPlaneGuides();
            bendPanel_.posed=false;
            publishToolConfiguration();
        }
        if(bendPanel_.active && !bendPanel_.selecting && feedback->accepted && feedback->selected &&
            nadoc_vr::BendPanel::supports(selectedSelectionKind_) && (targetChanged || bendPanel_.defaultPlanes)) {
            bendPanel_.reset();bendPanel_.defaultPlanes=true;bendPanel_.pickSlot.reset();
            clearPlanePick();clearPlaneGuides();bendPickPosition_.reset();
            requestBendDefaultPlane("a");
        }
        if(targetChanged)movePanel_.hand.reset();
        if (targetChanged ||
            !toolShell_.previewRequested()) {
            pendingToolTransform_.cancel();
        }
    }

    void pollToolExecutionFeedback() {
        if (toolExecutionFeedbackPath_.empty() ||
            (++toolExecutionFeedbackPollFrame_ % 3U) != 0U || toolSequence_ == 0) {
            return;
        }
        std::ifstream input(
            toolExecutionFeedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size < 0 || size > 4096) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        const auto feedback = nadoc_vr::parseToolExecutionFeedback(
            record, toolExecutionFeedbackSequence_, toolSequence_);
        if (!feedback || feedback->toolSequence != toolSequence_ ||
            feedback->mode != nadoc_vr::toolModeName(toolShell_.mode()) ||
            feedback->action != nadoc_vr::toolActionName(lastToolAction_)) {
            return;
        }
        if (feedback->action == "confirm" &&
            (feedback->selectionKind != lastToolTargetKind_ ||
             feedback->identity != lastToolTargetIdentity_)) {
            return;
        }
        if (feedback->action == "undo" && feedback->status == "succeeded" &&
            feedback->featureLogEntryId != committedFeatureLogEntryId_) {
            return;
        }
        toolExecutionFeedbackSequence_ = feedback->sequence;
        if (feedback->status == "succeeded") {
            if(feedback->mode=="bend" || feedback->mode=="twist") {bendPanel_.reset();clearPlaneGuides();clearPlanePick();}
            moveAwaitRefresh_=false;
            if (feedback->action == "confirm") {
                if (feedback->mode == "move_rotate" && sceneRefresh_.revision()==moveStartRevision_)
                    (void)glScene_->acceptToolCommit(); // A refreshed scene already contains the saved pose.
                committedFeatureLogEntryId_ = feedback->featureLogEntryId;
                if (feedback->mode == "move_rotate") {
                    pendingToolTransform_.activate();
                    publishToolTransform();
                }
            } else {
                if (feedback->mode == "move_rotate") (void)glScene_->acceptToolUndo();
                committedFeatureLogEntryId_.clear();
            }
        } else if (feedback->action == "undo" &&
                   feedback->status == "refused" &&
                   feedback->reason == "undo_stale_desktop_changed") {
            committedFeatureLogEntryId_.clear();
        }
        toolShell_.applyExecutionFeedback(*feedback);
        finishConfirmedExtrude(*feedback);
        if(feedback->mode=="sweep" && feedback->action=="confirm" && feedback->status!="pending") {
            if(feedback->status=="succeeded") {
                sweepPanel_.exit(sidebarMenus_.menus);latticeOpen_=false;
                sweepDraft_.reset(sweepDefaultDirection());extrudeLatticeDraft_.clear();
                if(toolConfig_.clear())publishToolConfiguration();
            } else publishToolConfiguration();
        }
    }

    [[nodiscard]] const nadoc_vr::ToolContextFeedback*
    currentToolContextFeedback() const {
        if (!toolContextFeedback_ || !toolConfig_.active() ||
            toolContextFeedback_->sequence != toolConfigSequence_ ||
            toolConfig_.targetSelectionKind() != "end" ||
            toolContextFeedback_->selectionKind != toolConfig_.targetSelectionKind() ||
            toolContextFeedback_->identity != toolConfig_.targetIdentity()) {
            return nullptr;
        }
        return &*toolContextFeedback_;
    }

    [[nodiscard]] const nadoc_vr::ToolPreflightFeedback*
    currentToolPreflightFeedback() const {
        if (!toolPreflightFeedback_ || !toolConfig_.active() ||
            toolPreflightFeedback_->toolConfigSequence != toolConfigSequence_ ||
            toolPreflightFeedback_->mode != nadoc_vr::toolModeName(toolConfig_.mode()) ||
            toolPreflightFeedback_->selectionKind !=
                toolConfig_.targetSelectionKind() ||
            toolPreflightFeedback_->identity != toolConfig_.targetIdentity()) {
            return nullptr;
        }
        return &*toolPreflightFeedback_;
    }

    [[nodiscard]] bool paintedExtrusionReady() const { return nadoc_vr::extrusionCommitReady(toolConfig_, extrudeLatticeDraft_.cells().size(), toolConfigSequence_, currentToolPreflightFeedback(), !eventPath_.empty()) && !toolShell_.executionPending() && !freeformDraft_.armed(); }

    void pollToolContextFeedback() {
        if (toolFeedbackPath_.empty() || (++toolFeedbackPollFrame_ % 3U) != 0U ||
            extrudeConfirmation_ || !toolConfig_.active() || toolConfigSequence_ == 0) {
            return;
        }
        std::ifstream input(toolFeedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size < 0 || size > 4096) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        auto feedback = nadoc_vr::parseToolContextFeedback(
            record, toolFeedbackSequence_, toolConfigSequence_);
        if (!feedback || feedback->selectionKind != toolConfig_.targetSelectionKind() ||
            feedback->identity != toolConfig_.targetIdentity()) {
            return;
        }
        toolFeedbackSequence_ = feedback->sequence;
        if (feedback->resolved) {
            feedback->facePosition = nadoc_vr::sourceToNormalizedPoint(
                feedback->facePosition, normalizationCenter_, normalizationScale_,
                {0.0F, 0.0F, -kViewDistanceMeters});
            if (feedback->footprintResolved) {
                const bool square = feedback->latticeType == "SQUARE";
                if (latticeSquare_ != square ||
                    latticeOrigin_ != feedback->footprintCell) {
                    latticeSquare_ = square;
                    latticeOrigin_ = feedback->footprintCell;
                    extrudeLatticeDraft_.clear();
                    publishToolConfiguration();
                    latticeHover_.reset();
                    latticePaintStroke_.reset();
                    resetThumbwheels();
                }
                feedback->previewOrigin = nadoc_vr::sourceToNormalizedPoint(
                    feedback->previewOrigin, normalizationCenter_, normalizationScale_,
                    {0.0F, 0.0F, -kViewDistanceMeters});
            }

        }
        toolContextFeedback_ = std::move(feedback);
    }

    void pollToolPreflightFeedback() {
        if (preflightFeedbackPath_.empty() ||
            (++preflightFeedbackPollFrame_ % 3U) != 0U ||
            !toolConfig_.active() || toolConfigSequence_ == 0) {
            return;
        }
        std::ifstream input(preflightFeedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size <= 0 || size > 4096) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        auto feedback = nadoc_vr::parseToolPreflightFeedback(
            record, toolConfigSequence_, preflightFeedbackSequence_);
        if (!feedback ||
            feedback->mode != nadoc_vr::toolModeName(toolConfig_.mode()) ||
            feedback->selectionKind != toolConfig_.targetSelectionKind() ||
            feedback->identity != toolConfig_.targetIdentity()) {
            return;
        }
        const bool changed = !toolPreflightFeedback_ ||
            toolPreflightFeedback_->preflightSequence !=
                feedback->preflightSequence ||
            toolPreflightFeedback_->status != feedback->status ||
            toolPreflightFeedback_->reason != feedback->reason;
        toolPreflightFeedback_ = std::move(feedback);
        preflightFeedbackSequence_ = toolPreflightFeedback_->preflightSequence;
        if (changed) {
            std::cout << "VR PREFLIGHT " << toolPreflightFeedback_->status
                      << " " << toolPreflightFeedback_->reason << '\n';
        }
    }

    void pollPlanePickFeedback() {
        if (planeFeedbackPath_.empty() || (++planeFeedbackPollFrame_ % 3U) != 0U ||
            !planePickSlot_ || activePlanePickSequence_ == 0 ||
            planePickConfigSequence_ != toolConfigSequence_) {
            return;
        }
        std::ifstream input(planeFeedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size < 0 || size > 4096) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        auto feedback = nadoc_vr::parsePlanePickFeedback(
            record, planePickFeedbackSequence_, activePlanePickSequence_,
            planePickConfigSequence_);
        if (!feedback || feedback->slot != *planePickSlot_ ||
            feedback->targetSelectionKind != toolConfig_.targetSelectionKind() ||
            feedback->targetIdentity != toolConfig_.targetIdentity() ||
            feedback->pickedIdentity != planePickIdentity_) {
            return;
        }
        planePickFeedbackSequence_ = feedback->sequence;
        const std::string slot = feedback->slot;
        const size_t slotIndex = slot == "a" ? 0U : 1U;
        const bool retainedGuide = planeGuides_[slotIndex].has_value();
        const bool accepted = feedback->resolved && feedback->frameResolved;
        bool changed = false;
        if (accepted) {
            DeformationPlaneGuide guide;
            guide.natural.center = nadoc_vr::sourceToNormalizedPoint(
                feedback->planeCenter, normalizationCenter_, normalizationScale_,
                {0.0F, 0.0F, -kViewDistanceMeters});
            guide.natural.normal = glm::normalize(feedback->planeNormal);
            guide.natural.halfExtent = feedback->planeHalfExtentNanometers
                                     * normalizationScale_;

            planeGuides_[slotIndex] = guide;
            if(bendPanel_.active) {
                bendPanel_.posed=false;bendPanel_.grabbed=1;
                (void)toolConfig_.setBend(0,0);
            }
            changed = toolConfig_.setPlaneBp(slot, feedback->planeBp);
            changed = changed || bendPanel_.active;
        }
        const auto reasonLabel = [&]() -> const char* {
            if (feedback->reason == "ambiguous_primitive") return "COARSE OR SPANNING HIT";
            if (feedback->reason == "synthetic_not_supported") return "SYNTHETIC HIT REJECTED";
            if (feedback->reason == "out_of_range") return "STALE BP";
            if (feedback->reason == "plane_frame_unavailable") return "PLANE FRAME UNAVAILABLE";
            if (feedback->reason == "stale_target") return "TARGET CHANGED";
            return "HIT NOT RESOLVED";
        };
        planePickStatus_ = accepted
            ? std::string("PLANE ") + (slot == "a" ? "A " : "B ") +
                std::to_string(feedback->planeBp) + (bendPanel_.active?" BP":" FRAMED - READ ONLY")
            : std::string("PLANE ") + (slot == "a" ? "A " : "B ") +
                (retainedGuide ? "RETAINED: " : "NOT SET: ") + reasonLabel();
        std::cout << "VR " << planePickStatus_ << '\n';
        clearPlanePick(true);
        if (changed) publishToolConfiguration();
        else publishEventState();
        if(bendPanel_.active) {
            if(bendPanel_.defaultPlanes) {
                if(accepted && slot=="a")requestBendDefaultPlane("b");
                else {bendPanel_.defaultPlanes=false;bendPanel_.pickSlot.reset();}
                refreshExtrudePanel();return;
            }
            if(!bendPanel_.planeHand && accepted) {
                if(planeGuides_[0] && planeGuides_[1])bendPanel_.pickSlot.reset();
                else bendPanel_.pickSlot=slot=="a"?"b":"a";
            }
            return;
        }
        suppressManipulationUntilRelease_ = true;
        pulse(1U, accepted ? 0.60F : 0.20F);
    }

    struct LiveEyeCapture {
        int width = 0, height = 0;
        std::vector<uint8_t> rgb, classes;
        std::vector<float> depth;
        std::vector<uint32_t> objectIds;
        XrView view{XR_TYPE_VIEW};
    };

    void failLiveCapture(const char* reason) {
        liveCaptureResult_ = "{\"status\":\"failed\",\"command_sequence\":" +
            std::to_string(liveCapturePending_.value_or(0)) + ",\"error\":\"" + reason + "\"}";
        liveCapturePending_.reset(); liveEyes_ = {};
    }

    void captureLiveEye(uint32_t index, const XrView& view, int width, int height) {
        if (!liveCapturePending_ || index >= liveEyes_.size()) return;
        auto& eye = liveEyes_[index];
        if (width <= 0 || height <= 0 || width > 4096 || height > 4096) {
            failLiveCapture("capture_dimensions"); return;
        }
        eye.width = width; eye.height = height; eye.view = view;
        const auto pixels = static_cast<size_t>(width) * height;
        eye.rgb.resize(pixels * 3); eye.classes.resize(pixels); eye.depth.resize(pixels);
        eye.objectIds.resize(pixels);
        GLint alignment = 4;
        glGetIntegerv(GL_PACK_ALIGNMENT, &alignment);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE, eye.rgb.data());
        glReadPixels(0, 0, width, height, GL_DEPTH_COMPONENT, GL_FLOAT, eye.depth.data());
        glReadPixels(0, 0, width, height, GL_STENCIL_INDEX, GL_UNSIGNED_BYTE, eye.classes.data());
        glReadBuffer(GL_COLOR_ATTACHMENT1);
        glReadPixels(0, 0, width, height, GL_RED_INTEGER, GL_UNSIGNED_INT, eye.objectIds.data());
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        // The final stencil describes panel/grid/controller occlusion, including
        // depth-free UI. IDs under those overlays must not be reported as visible.
        for (size_t pixel = 0; pixel < pixels; ++pixel) {
            if (eye.classes[pixel] != static_cast<uint8_t>(nadoc_vr::SpectatorRenderClass::design)) {
                eye.objectIds[pixel] = 0;
            }
        }
        glPixelStorei(GL_PACK_ALIGNMENT, alignment);
        if (glGetError() != GL_NO_ERROR) {
            failLiveCapture("framebuffer_readback_failed");
        }
    }

    void finishLiveCapture(bool submitted) {
        if (!liveCapturePending_ || !submitted || liveEyes_[0].rgb.empty() || liveEyes_[1].rgb.empty()) return;
        const auto sequence = *liveCapturePending_;
        const auto directory = liveDirectory_ / ("capture-" + liveSession_ + "-" + std::to_string(sequence));
        try {
            std::filesystem::create_directory(directory);
            std::filesystem::permissions(directory, std::filesystem::perms::owner_all);
            auto binary = [&](const std::string& name, const void* bytes, size_t size) {
                std::ofstream out(directory / name, std::ios::binary);
                out.write(static_cast<const char*>(bytes), static_cast<std::streamsize>(size));
                if (!out) throw std::runtime_error("capture write failed");
            };
            std::unordered_set<uint32_t> visible;
            for (const auto& eye : liveEyes_) {
                visible.insert(eye.objectIds.begin(), eye.objectIds.end());
            }
            std::vector<uint32_t> visibleIds(visible.begin(), visible.end());
            std::sort(visibleIds.begin(), visibleIds.end());
            const auto objects = glScene_->objectTable(visibleIds);
            binary("objects.json", objects.data(), objects.size());
            std::ostringstream metadata;
            metadata << "{\"mirror\":" << liveMirrorCapture_.save(directory) << ",\"source\":\"application_swapchain\",\"xr_end_frame_succeeded\":true,"
                "\"compositor_acknowledged\":false,\"object_ids_available\":true,"
                "\"object_id_format\":\"uint32-native-endian-bottom-up\","
                "\"object_id_scope\":\"viewer-session\",\"object_table\":\"objects.json\","
                "\"object_id_zero\":\"background-or-nondesign-overlay\","
                "\"object_id_visibility\":\"opaque-design-with-final-stencil-overlay-mask\","
                "\"depth_format\":\"float32-native-endian-window-depth-bottom-up\","
                "\"depth_near_m\":" << kNearMeters << ",\"depth_far_m\":" << kFarMeters
                << ",\"controller_classes\":{\"left\":4,\"right\":5},\"contact_classes\":{\"intended\":6,\"actual\":7}"
                << ",\"class_format\":\"uint8-bottom-up\",\"capture_command_sequence\":" << sequence
                << ",\"state\":" << liveState() << ",\"eyes\":[";
            for (size_t i = 0; i < liveEyes_.size(); ++i) {
                const auto& eye = liveEyes_[i];
                const std::string name = i == 0 ? "left" : "right";
                nadoc_vr::scrywrite::writeActorEyeCapture(directory, name, eye.rgb, eye.width, eye.height);
                binary(name + ".depth.f32", eye.depth.data(), eye.depth.size() * sizeof(float));
                binary(name + ".classes.u8", eye.classes.data(), eye.classes.size());
                binary(name + ".ids.u32", eye.objectIds.data(), eye.objectIds.size() * sizeof(uint32_t));
                if (i) metadata << ',';
                const auto& p = eye.view.pose;
                const auto& f = eye.view.fov;
                metadata << "{\"eye\":\"" << name << "\",\"width\":" << eye.width
                    << ",\"height\":" << eye.height << ",\"position\":[" << p.position.x << ',' << p.position.y << ',' << p.position.z
                    << "],\"orientation_xyzw\":[" << p.orientation.x << ',' << p.orientation.y << ',' << p.orientation.z << ',' << p.orientation.w
                    << "],\"fov_left_right_up_down\":[" << f.angleLeft << ',' << f.angleRight << ',' << f.angleUp << ',' << f.angleDown << "]}";
            }
            metadata << "]}";
            const auto data = metadata.str(); binary("evidence.json", data.data(), data.size());
            liveCaptureResult_ = "{\"status\":\"complete\",\"command_sequence\":" + std::to_string(sequence)
                + ",\"frame\":" + std::to_string(liveFrame_) + ",\"directory\":\""
                + nadoc_vr::scrywrite::visualJson(directory.string()) + "\"}";
        } catch (...) {
            failLiveCapture("capture_write_failed");
        }
        liveCapturePending_.reset(); liveEyes_ = {};
    }

    bool liveControlsEnabled() const {
        return liveSocket_.enabled() && liveMode_ != "inspect";
    }

    void neutralLiveInput(bool forgetPoses = true) {
        interruptSweepGesture();
        remotePanels_.cancel();
        ligation_.cancel();quiver_.reset();liveTriggerValues_.fill(0);
        if (forgetPoses) liveInput_ = {};
        else {
            liveInput_.menuPressed.fill(false);
            liveInput_.triggerPressed.fill(false);liveTriggerValues_.fill(0);
            liveInput_.gripPressed.fill(false);
        }
        selectionWheel_.cancel();
        liveTrackpadPressed_.fill(false);
        liveTrackpadAxis_.fill(glm::vec2(0));
        trajectoryScrubHand_.reset();
        for(auto& menu:sidebarMenus_.menus) menu.focus.reset();
        trackpadPressed_.fill(false);
        radialToolMenu_.close();
        latticePaintStroke_.reset();
        latticeGrip_.cancel();
        resetThumbwheels();
    }

    std::vector<nadoc_vr::scrywrite::WitnessMenuEntry> liveTargets() const {
        auto entries = witnessMenuEntries();
        if(desktopPanel_.open) {
            auto add=[&](const char* label,int hit,nadoc_vr::MenuPanelBounds b) {
                const auto& p=desktopPanel_.placement;
                nadoc_vr::scrywrite::WitnessMenuEntry e{label,hit,p.worldPoint({(b.minimum.x+b.maximum.x)*.5F,(b.minimum.y+b.maximum.y)*.5F,0}),
                    p.orientation()*glm::vec3((b.maximum.x-b.minimum.x)*.5F*p.scale(),0,0),
                    p.orientation()*glm::vec3(0,(b.maximum.y-b.minimum.y)*.5F*p.scale(),0)};
                e.id=label;entries.push_back(e);
            };
            add("desktop-close",-20,desktopPanel_.closeBounds());
            add("desktop-content",-21,desktopPanel_.content());
            const auto b=desktopPanel_.bounds();
            add("desktop-grip-left",-22,{{b.minimum.x-.01F,-.02F},{b.minimum.x+.01F,.02F}});
            add("desktop-grip-right",-23,{{b.maximum.x-.01F,-.02F},{b.maximum.x+.01F,.02F}});
        }
        // Preserve the coarse wheel's historical label for older live probes.
        if(thumbwheelAvailable())for(const auto& entry:sidebarMenus_.entries())
            if(entry.id==nadoc_vr::kExtrudeWheelIds[0]) {
                auto legacy=entry;legacy.label="EXTRUDE LENGTH WHEEL";legacy.id="";legacy.hit=-2;
                entries.push_back(legacy);break;
            }
        if (latticeOpen_) entries.push_back({"LATTICE EXIT", -3,
            latticePlacement_.worldPoint({
                (kLatticeExitBounds.minimum.x + kLatticeExitBounds.maximum.x) * 0.5F,
                (kLatticeExitBounds.minimum.y + kLatticeExitBounds.maximum.y) * 0.5F, 0.0F}),
            latticePlacement_.orientation()*glm::vec3((kLatticeExitBounds.maximum.x-kLatticeExitBounds.minimum.x)*0.5F*latticePlacement_.scale(),0,0),
            latticePlacement_.orientation()*glm::vec3(0,(kLatticeExitBounds.maximum.y-kLatticeExitBounds.minimum.y)*0.5F*latticePlacement_.scale(),0)});
        if (latticeOpen_) entries.push_back({"CENTER PAINT", -4,
            latticePlacement_.worldPoint({(nadoc_vr::kCenterPaintBounds.minimum+nadoc_vr::kCenterPaintBounds.maximum)*.5F,0}),
            latticePlacement_.orientation()*glm::vec3((nadoc_vr::kCenterPaintBounds.maximum.x-nadoc_vr::kCenterPaintBounds.minimum.x)*.5F*latticePlacement_.scale(),0,0),
            latticePlacement_.orientation()*glm::vec3(0,(nadoc_vr::kCenterPaintBounds.maximum.y-nadoc_vr::kCenterPaintBounds.minimum.y)*.5F*latticePlacement_.scale(),0)});
        return entries;
    }

    std::string liveState() const {
        auto quote = [](const std::string& value) {
            return "\"" + nadoc_vr::scrywrite::visualJson(value) + "\"";
        };
        auto point = [](const glm::vec3& p) {
            std::ostringstream out;
            out << '[' << p.x << ',' << p.y << ',' << p.z << ']';
            return out.str();
        };
        std::ostringstream out;
        out << "{\"protocol\":1,\"session\":" << quote(liveSession_)
            << ",\"mode\":" << quote(liveMode_)
            << ",\"frame\":" << liveFrame_
            << ",\"scene_visibility\":" << quote(liveSceneHidden_ ? "hidden" : "normal")
            << ",\"motion_detail_reduced\":" << (glScene_ && glScene_->motionDetailReduced()?"true":"false")
            << ",\"controller_path_generation\":" << controllerPaths_.generation()
            << ",\"command_sequence\":" << liveCommandSequence_
            << ",\"predicted_display_time\":" << currentPredictedDisplayTime_
            << ",\"view_state_flags\":" << currentViewStateFlags_
            << ",\"xr_session_state\":" << static_cast<int>(sessionState_)
            << ",\"focused\":" << (sessionState_ == XR_SESSION_STATE_FOCUSED ? "true" : "false")
            << ",\"space\":\"OpenXR_LOCAL\",\"units\":\"meters\""
            << ",\"representation_loading\":{\"pending\":" << (representationLoading_.pending?"true":"false")
            << ",\"representation\":" << quote(representationName(representationLoading_.target))
            << ",\"percent\":" << representationLoading_.percent << ",\"phase\":" << quote(representationLoading_.phase)
            << ",\"detail\":" << quote(representationLoading_.detail) << "}"
            << ",\"loading_diagnostics\":{\"avatar_write_max_ms\":" << avatarWriter_.maxWriteMs()
            << ",\"avatar_write_failures\":" << avatarWriter_.failures()
            << ",\"event_write_failures\":" << eventWriter_.failures()
            << ",\"lightweight_guard\":" << (representationLoading_.lightweight?"true":"false") << "}"
            << ",\"component_gallery\":" << componentGallery_.observation()
            << ",\"placement_integrity\":{\"blocked\":" << (placementIntegrity_.blocked()?"true":"false")
            << ",\"detail\":" << quote(placementIntegrity_.detail()) << "}"
            << ",\"startup\":{\"active\":" << (startup_.active?"true":"false")
            << ",\"percent\":" << startup_.percent << ",\"phase\":" << quote(startup_.phase)
            << ",\"detail\":" << quote(startup_.detail) << "}"
            << ",\"menu\":" << quote(menuPageName())
            << ",\"remote_border\":{\"active\":" << (remotePanels_.active?"true":"false")
            << ",\"resizing\":" << (remotePanels_.active && remotePanels_.resizing?"true":"false")
            << ",\"hand\":" << remotePanels_.hand << "}"
            << ",\"desktop_capture\":{\"ready\":" << (desktopSurface_.presenterTexture()?"true":"false")
            << ",\"version\":" << desktopSurface_.presenterVersion()
            << ",\"open\":" << (desktopPanel_.open?"true":"false")
            << ",\"magnifying\":" << (desktopPanel_.magnifying?"true":"false")
            << ",\"close_hovered\":" << (desktopPanel_.closeHovered?"true":"false")
            << ",\"pointer\":[" << desktopPanel_.pointer.x << ',' << desktopPanel_.pointer.y << ']'
            << ",\"scale\":" << desktopPanel_.placement.scale()
            << ",\"position\":" << point(desktopPanel_.placement.position())
            << ",\"moving\":" << (desktopPanel_.placement.dragHand()?"true":"false")
            << ",\"resizing\":" << (desktopPanel_.placement.resizeActive()?"true":"false") << "}"
            << ",\"hover\":" << quote(witnessHoverName())
            << ",\"scene_hover\":" << (sceneHover_?quote(sceneHover_->identity):"null")
            << ",\"tool\":" << quote(nadoc_vr::toolModeName(toolShell_.mode()))
            << ",\"status\":" << quote(toolShell_.status())
            << ",\"selection_level\":" << quote(selectionLevel_) << ",\"level_sequence\":" << levelSequence_
            << ",\"selection_identity\":" << quote(selectedIdentity_)
            << ",\"selection_kind\":" << quote(selectedSelectionKind_)
            << ",\"owner_tokens\":[";
        for (size_t i = 0; i < selectedOwnerTokens_.size(); ++i) {
            if (i) out << ',';
            out << quote(selectedOwnerTokens_[i]);
        }
        const auto moveCenter=glScene_?glScene_->ownerHandle(selectedOwnerTokens_,manipulator_.transform()):std::nullopt;
        out << "],\"qr_calibration\":" << qrCalibration_.json() << ",\"room_floor\":" << roomFloor_.json() << ",\"menu_glass\":{\"enabled\":true,\"gray_opacity\":0.10,\"blur_radius_px\":15},\"view_tools\":{\"open\":" << (viewTools_.open?"true":"false") << ",\"waiting\":" << (viewTools_.waiting?"true":"false")
            << ",\"sequence\":" << viewTools_.sequence << ",\"ack_sequence\":" << viewTools_.acknowledged << ",\"version\":" << viewTools_.version << ",\"flags\":" << viewTools_.flags << ",\"triangles\":" << viewTools_.triangles.size()/3
            << ",\"parse_ms\":" << viewTools_.parseMs << ",\"upload_ms\":" << viewTools_.uploadMs << ",\"instances\":" << viewTools_.instanceCount() << ",\"lines\":" << viewTools_.lines.size()/2 << ",\"sprites\":" << viewTools_.sprites.size() << ",\"hover\":[" << viewTools_.hover[0] << ',' << viewTools_.hover[1] << "],\"items\":[";
        for(size_t i=0;i<VRViewTools::keys.size();++i){if(i)out<<',';out<<"{\"key\":"<<quote(VRViewTools::keys[i])<<",\"active\":"<<((viewTools_.flags&(1<<(i<7?i:i+1)))?"true":"false")<<",\"center\":"<<point(viewTools_.world(VRViewTools::cell(i)))<<'}';}
        out << "]}";
        out << ",\"trajectory\":{\"panel_open\":" << (trajectoryPanel_.active && sidebarMenus_.menus[0].open?"true":"false")
            << ",\"active\":" << (trajectoryState_.active?"true":"false")
            << ",\"playing\":" << (trajectoryState_.playing?"true":"false")
            << ",\"frame_index\":" << trajectoryState_.frameIndex << ",\"frame_count\":" << trajectoryState_.frameCount
            << ",\"request_sequence\":" << trajectoryRequestSequence_ << '}';
        selectionWheel_.writeJson(out,selectionLevel_);
        out << ",\"radial_edit\":{\"open\":" << (radialToolMenu_.open()?"true":"false")
            << ",\"hovered\":" << (radialToolMenu_.hovered()?std::to_string(*radialToolMenu_.hovered()):"null") << ",\"items\":[";
        for(size_t i=0;i<radialToolMenu_.itemCount();++i) {
            if(i)out<<',';
            const auto axis=radialToolMenu_.itemDirection(i);
            out << "{\"label\":" << quote(radialToolMenu_.itemLabel(i))
                << ",\"enabled\":" << ((bendPanel_.active?(i==0 || (bendPanel_.selecting?nadoc_vr::BendPanel::supports(selectedSelectionKind_):bendHasAngle() && bendReady())):nadoc_vr::radialEditEnabled(i))?"true":"false")
                << ",\"axis\":[" << axis.x << ',' << axis.y << "]"
                << ",\"center\":" << point(radialToolMenu_.worldPoint({nadoc_vr::EditWheel::labelRadius*axis.x,nadoc_vr::EditWheel::labelRadius*axis.y,0})) << '}';
        }
        out << "]},\"ligation\":{\"active\":" << (ligation_.active?"true":"false")
            << ",\"grabbing\":" << (ligation_.hand?"true":"false")
            << ",\"waiting\":" << (ligation_.waiting?"true":"false")
            << ",\"version\":" << ligation_.version << ",\"status\":" << quote(ligation_.status)
            << ",\"source\":" << (ligation_.hand?std::to_string(ligation_.source):"null")
            << ",\"target\":" << (ligation_.target?std::to_string(*ligation_.target):"null")
            << ",\"preview_end\":" << (ligation_.hand?point(ligation_.previewEnd(manipulator_.transform())):"null")
            << ",\"hover\":[" << (ligation_.hover[0]?std::to_string(*ligation_.hover[0]):"null") << ','
            << (ligation_.hover[1]?std::to_string(*ligation_.hover[1]):"null") << "],\"ends\":[";
        for(size_t i=0;i<ligation_.ends.size();++i) {
            if(i)out<<',';
            const auto& e=ligation_.ends[i];
            out << "{\"role\":" << e.role << ",\"strand\":" << e.strand
                << ",\"identity\":" << quote(e.identity)
                << ",\"world\":" << point(ligation_.point(i,manipulator_.transform())) << '}';
        }
        out << "],\"quiver\":{\"sequence\":" << quiver_.sequence
            << ",\"armed\":[" << (quiver_.armed[0]?"true":"false") << ',' << (quiver_.armed[1]?"true":"false")
            << "],\"inside\":[" << (quiver_.inside[0]?"true":"false") << ',' << (quiver_.inside[1]?"true":"false") << "]}"
            << ",\"nick_active\":" << (ligation_.nickActive?"true":"false") << ",\"nick_hover\":[";
        for(size_t h=0;h<2;++h){if(h)out<<',';out<<(ligation_.nickHover[h]?std::to_string(*ligation_.nickHover[h]):"null");}
        out << "],\"scissor_angles\":[" << nadoc_vr::Ligation::scissorAngle(triggerValues_[0]) << ',' << nadoc_vr::Ligation::scissorAngle(triggerValues_[1]) << "],\"bonds\":[";
        // Inactive Nick geometry can dominate live replies on origami-sized parts.
        // Preserve its full observation contract outside Move/Rotate and Bend.
        const bool omitNickBonds = (movePanel_.active || bendPanel_.active) && !ligation_.nickActive;
        for(size_t i=0;!omitNickBonds && i<ligation_.bonds.size();++i){if(i)out<<',';out<<"{\"a\":"<<point(ligation_.bondPoint(i,false,manipulator_.transform()))<<",\"b\":"<<point(ligation_.bondPoint(i,true,manipulator_.transform()))<<'}';}
        out << "],\"bonds_omitted\":" << (omitNickBonds?"true":"false") << "}";
        out << ",\"end_resize\":{\"version\":" << endResize_.version
            << ",\"grabbing\":" << (endResize_.hand?"true":"false")
            << ",\"nearby\":" << (endResize_.nearby?"true":"false")
            << ",\"delta\":" << endResize_.delta
            << ",\"cancel_reason\":" << quote(endResize_.cancelReason)
            << ",\"hover_hand\":" << (endResize_.hoverHand?int(*endResize_.hoverHand):-1)
            << ",\"hovered_arrow\":" << (endResize_.hoverHand?int(endResize_.hovered):-1)
            << ",\"pointer_start\":" << point(endResize_.pointerStart)
            << ",\"pointer_end\":" << point(endResize_.pointerEnd)
            << ",\"label_position\":" << point(endResize_.labelPosition())
            << ",\"label\":" << quote(endResize_.hand?endResize_.label():"") << ",\"arrows\":[";
        for(size_t i=0;i<endResize_.arrows.size();++i) {
            if(i)out<<',';
            const auto& a=endResize_.arrows[i];const auto model=manipulator_.transform();
            const auto origin=endResize_.point(a,model,normalizationScale_,0);
            out << "{\"origin\":" << point(origin)
                << ",\"tip\":" << point(endResize_.point(a,model,normalizationScale_,endResize_.arrowLength(model,normalizationScale_)))
                << ",\"bp_step\":" << point(glm::vec3(model*glm::vec4(a.direction*.334F*normalizationScale_,0))) << '}';
        }
        out << "]}";
        out << ",\"" << (bendPanel_.twist?"twist":"bend") << "\":{\"active\":" << (bendPanel_.active?"true":"false")
            << ",\"grabbing\":" << (bendPanel_.hand?"true":"false")
            << ",\"ready\":" << (bendReady()?"true":"false")
            << ",\"plane1\":" << (toolConfig_.planeABp()?std::to_string(*toolConfig_.planeABp()):"null")
            << ",\"plane2\":" << (toolConfig_.planeBBp()?std::to_string(*toolConfig_.planeBBp()):"null")
            << ",\"amount\":" << toolConfig_.twistAmount()
            << ",\"amount_mode\":" << quote(nadoc_vr::twistAmountModeName(toolConfig_.twistAmountMode()))
            << ",\"total_degrees\":" << toolConfig_.twistTotalDegrees()
            << ",\"direction\":" << toolConfig_.bendDirectionDegrees()
            << ",\"hand\":" << (bendPanel_.hand?std::to_string(*bendPanel_.hand):"null")
            << ",\"grabbed\":" << bendPanel_.grabbed
            << ",\"manual\":" << (bendPanel_.manual?"true":"false")
            << ",\"default_planes\":" << (bendPanel_.defaultPlanes?"true":"false")
            << ",\"plane_hand\":" << (bendPanel_.planeHand?std::to_string(*bendPanel_.planeHand):"null")
            << ",\"plane_hover\":[" << (bendPanel_.planeHover[0]?std::to_string(*bendPanel_.planeHover[0]):"null") << ',' << (bendPanel_.planeHover[1]?std::to_string(*bendPanel_.planeHover[1]):"null") << ']'
            << ",\"cluster_label\":" << quote(bendPanel_.clusterLabel)
            << ",\"wheel_hand\":" << (bendPanel_.wheelHand?std::to_string(*bendPanel_.wheelHand):"null")
            << ",\"contour_m\":" << bendPanel_.arc.length*glm::length(glm::vec3(manipulator_.transform()[0]))
            << ",\"endpoints\":[" << point(glm::vec3(manipulator_.transform()*glm::vec4(bendPanel_.arc.a,1)))
            << ',' << point(glm::vec3(manipulator_.transform()*glm::vec4(bendPanel_.arc.b,1))) << ']'
            << ",\"tangents\":[" << point(glm::normalize(glm::mat3(manipulator_.transform())*bendPanel_.arc.endTangent(0)))
            << ',' << point(glm::normalize(glm::mat3(manipulator_.transform())*bendPanel_.arc.endTangent(1))) << ']'
            << ",\"targets\":" << (glScene_ && bendPanel_.active?glScene_->movePickPoints(manipulator_.transform()):"[]")
            << ",\"point_preview_count\":" << (glScene_ && bendPointPreviewActive()?glScene_->bendPointCount():0)
            << ",\"angle\":" << toolConfig_.bendAngleDegrees()
            << ",\"handles\":[";
        if(bendPanel_.active && planeGuides_[0] && planeGuides_[1])for(size_t i=0;i<2;++i) {
            if(i)out<<',';
            out<<point(glm::vec3(manipulator_.transform()*glm::vec4(bendPanel_.twist?twistHandle(i):bendHandle(i),1)));
        }
        out << "],\"planes\":[";
        if(bendPanel_.active && planeGuides_[0] && planeGuides_[1])for(size_t i=0;i<2;++i) {
            if(i)out<<',';
            const auto pose=deformationPlanePose(i);
            out<<"{\"center\":"<<point(glm::vec3(manipulator_.transform()*glm::vec4(pose.center,1)))
                <<",\"normal\":"<<point(glm::normalize(glm::mat3(manipulator_.transform())*pose.normal))<<'}';
        }
        out << "]}";
        out << ",\"move_targets\":" << (glScene_ && movePanel_.active?glScene_->movePickPoints(manipulator_.transform()):"[]")
            << ",\"move_handle\":" << (moveCenter?point(*moveCenter):"null")
            << ",\"move_beam_end\":" << (movePanel_.beamEnd?point(*movePanel_.beamEnd):"null")
            << ",\"move_point_preview_count\":" << (glScene_?glScene_->movePointCount():0)
            << ",\"move_grabbing\":" << (movePanel_.hand?"true":"false")
            << ",\"move_nearby\":" << ((movePanel_.nearby[0]||movePanel_.nearby[1])?"true":"false")
            << ",\"tool_sequence\":" << toolSequence_
            << ",\"extrude_status\":" << quote(extrudeStatus())
            << ",\"extrude_validation_reason\":" << quote(currentToolPreflightFeedback()?currentToolPreflightFeedback()->reason:"")
            << ",\"painted_commit_ready\":" << (paintedExtrusionReady() ? "true" : "false")
            << ",\"config_sequence\":" << toolConfigSequence_
            << ",\"execution_feedback_sequence\":" << toolExecutionFeedbackSequence_
            << ",\"committed_feature_id\":" << quote(committedFeatureLogEntryId_)
            << ",\"browser_events_connected\":" << (!eventPath_.empty() ? "true" : "false")
            << ",\"scene_revision\":" << sceneRefresh_.revision()
            << ",\"visualization_sequence\":" << visualizationSequence_
            << ",\"coordinate_sequence\":" << coordinateSequence_
            << ",\"haptic_requests\":[" << hapticRequests_[0] << ',' << hapticRequests_[1] << ']'
            << ",\"haptic_amplitude\":[" << hapticAmplitude_[0] << ',' << hapticAmplitude_[1] << ']'
            << ",\"menu_input_mode\":" << quote(observedSidebar().focus.active?"trackpad":"pointer")
            << ",\"menu_focus_hit\":" << quote(observedSidebar().focus.id)
            << ",\"representation\":" << quote(glScene_ ? representationName(glScene_->representation()) : "none")
            << ",\"layout\":" << quote(combinedMenuLayoutStatus())
            << ",\"layout_detail\":" << quote(sidebarMenus_.anyOpen() ? observedSidebar().audit.summary() : "")
            << ",\"menu_position\":" << point(observedSidebar().placement.position())
            << ",\"menu_docked\":" << (sidebarMenus_.anyOpen() && observedSidebar().placement.worldDocked() ? "true" : "false")
            << ",\"runtime_connected\":" << (instance_ != XR_NULL_HANDLE ? "true" : "false")
            << ",\"show_vr_model\":" << (showVRAvatar_?"true":"false")
            << ",\"head_position\":" << point(witnessObserverPosition_)
            << ",\"presentation\":" << nadoc_vr::livePresentationJson(manipulator_.transform(), normalizationCenter_, normalizationScale_, {0,0,-kViewDistanceMeters})
            << ",\"thumbwheel_position\":" << point(sidebarMenus_.menus[1].placement.worldPoint(nadoc_vr::extrudeWheelFront(0)))
            << ",\"controls\":[";
        const auto entries = liveTargets();
        for (size_t i = 0; i < entries.size(); ++i) {
            if (i) out << ',';
            out << "{\"label\":" << quote(entries[i].label)
                << ",\"hit\":" << entries[i].hit
                << ",\"position\":" << point(entries[i].worldPosition)
                << ",\"hit_half_right\":" << point(entries[i].hitHalfRight)
                << ",\"hit_half_up\":" << point(entries[i].hitHalfUp)
                << ",\"id\":" << quote(entries[i].id) << ",\"sidebar\":" << quote(entries[i].sidebar)
                << ",\"tab\":" << quote(entries[i].tab) << ",\"enabled\":" << (entries[i].enabled?"true":"false")
                << ",\"active\":" << (entries[i].active?"true":"false") << '}';
        }
        out << "],\"routing_popup\":" << routingPopup_.json() << ",\"sidebars\":" << sidebarMenus_.json() << ",\"dimensions\":" << dimensionPanel_.tool.json(normalizationScale_,manipulator_.transform());
        writeSweepObservation(out);
        const auto& volumeInteraction=volumePanel_.interaction;
        out << ",\"view_volumes\":{\"held_id\":" << quote(volumeInteraction.held)
            << ",\"hand\":" << (volumeInteraction.hand?int(*volumeInteraction.hand):-1)
            << ",\"resize_face\":" << (volumeInteraction.resizeFace?int(*volumeInteraction.resizeFace):-1)
            << ",\"centroid_range_m\":" << nadoc_vr::ViewVolumeInteraction::centroidRange
            << ",\"face_range_m\":" << nadoc_vr::ViewVolumeInteraction::faceRange
            << ",\"nearby_centroids\":[" << quote(volumeInteraction.nearby[0]) << ',' << quote(volumeInteraction.nearby[1])
            << "],\"nearby_faces\":[" << volumeInteraction.nearbyFace[0] << ',' << volumeInteraction.nearbyFace[1]
            << "],\"pending\":" << volumePanel_.pending.size() << ",\"entries\":[";
        const auto volumeFrame=nadoc_vr::ViewVolumeInteraction::frame(manipulator_.transform(),normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters});
        bool firstVolume=true;
        for(const auto& e:volumePanel_.entries) {
            if(!firstVolume)out << ',';
            firstVolume=false;
            out << "{\"id\":" << quote(e.id) << ",\"center_nm\":" << point(e.center) << ",\"half_nm\":" << point(e.half)
                << ",\"rotation_xyzw\":[" << e.rotation.x << ',' << e.rotation.y << ',' << e.rotation.z << ',' << e.rotation.w << ']'
                << ",\"representation\":" << quote(e.representation) << ",\"enabled\":" << (e.enabled?"true":"false")
                << ",\"world_center\":" << point(nadoc_vr::ViewVolumeInteraction::point(volumeFrame,e.center))
                << ",\"outline\":" << (e.outline?"true":"false") << ",\"faces\":[";
            for(size_t face=0;face<e.faceCount();++face) {
                if(face)out << ',';
                glm::vec3 center{};const auto indices=e.face(face);for(auto i:indices)center+=e.points[i];center/=float(indices.size());
                out << "{\"world_center\":" << point(nadoc_vr::ViewVolumeInteraction::point(volumeFrame,center))
                    << ",\"world_normal\":" << point(nadoc_vr::ViewVolumeInteraction::orientation(volumeFrame)*e.rotation*e.normal(face)) << '}';
            }
            out << "]}";
        }
        out << "]},\"hands\":[";
        for (size_t i = 0; i < hands_.size(); ++i) {
            if (i) out << ',';
            const auto& h = hands_[i];
            out << "{\"valid\":" << (h.valid ? "true" : "false")
                << ",\"input_owner\":" << quote(liveInputOwner_[i])
                << ",\"position\":" << point(h.position)
                << ",\"orientation_xyzw\":[" << h.orientation.x << ',' << h.orientation.y << ',' << h.orientation.z << ',' << h.orientation.w
                << "],\"trigger\":" << (triggerPressed_[i] ? "true" : "false")
                << ",\"grip\":" << (gripPressed_[i] ? "true" : "false") << '}';
        }
        out << "],\"extrude\":{\"open\":" << (latticeOpen_ ? "true" : "false")
            << ",\"editor_active\":" << (extrudePanel_.active?"true":"false")
            << ",\"configuration_active\":" << (toolConfig_.active() && toolConfig_.mode()==nadoc_vr::ToolMode::extrude?"true":"false")
            << ",\"confirm_pending\":" << (extrudeConfirmation_?"true":"false")
            << ",\"undo_available\":" << (toolShell_.undoAvailable()?"true":"false")
            << ",\"footprint_state\":\"unresolved\",\"commit_supported\":false"
            << ",\"view_origin\":[" << latticeOrigin_.row << ',' << latticeOrigin_.column << ']'
            << ",\"length_bp\":" << toolConfig_.lengthBp()
            << ",\"extrude_from\":\"" << extrudePlane_.plane << "\""
            << ",\"extrude_from_reason\":\"" << extrudePlane_.reason << "\""
            << ",\"freeform_armed\":" << (freeformDraft_.armed() ? "true" : "false")
            << ",\"freeform_placed\":" << (freeformDraft_.placed() ? "true" : "false")
            << ",\"direction_sign\":" << toolConfig_.directionSign()
            << ",\"wheel_hovered\":" << (thumbwheelHovered_.has_value() ? "true" : "false")
            << ",\"wheel_dragging\":" << (thumbwheelControls_[0].dragging() || thumbwheelControls_[1].dragging() ? "true" : "false")
            << ",\"square\":" << (latticeSquare_ ? "true" : "false")
            << ",\"wheel_notch_travel_m\":" << nadoc_vr::ThumbwheelControl::kNotchTravel * sidebarMenus_.menus[1].placement.scale()
            << ",\"base_pairs_per_detent\":" << nadoc_vr::latticeBasePairPeriod(latticeSquare_)
            << ",\"lattice_hit_radius_m\":" << latticeCellRadius() * 1.08F * latticePlacement_.scale()
            << ",\"menu_scale\":" << observedSidebar().placement.scale()
            << ",\"panel_orientation_xyzw\":[" << latticePlacement_.orientation().x << ',' << latticePlacement_.orientation().y << ',' << latticePlacement_.orientation().z << ',' << latticePlacement_.orientation().w << ']'
            << ",\"panel_scale\":" << latticePlacement_.scale()
            << ",\"lattice_zoom\":" << latticeGrip_.zoom
            << ",\"grid_scaling\":" << (latticeGrip_.scaling?"true":"false")
            << ",\"grid_grip_held\":[" << (latticeGrip_.held[0]?"true":"false") << ',' << (latticeGrip_.held[1]?"true":"false") << ']'
            << ",\"grid_grip_nearby\":[" << (latticeGrip_.nearby[0]?"true":"false") << ',' << (latticeGrip_.nearby[1]?"true":"false") << ']'
            << ",\"grid_grip_depth_m\":" << nadoc_vr::LatticeGrip::kDepthMeters
            << ",\"window_resizing\":" << (latticePlacement_.resizeActive()?"true":"false")
            << ",\"window_moving\":" << (latticePlacement_.dragHand()?"true":"false")
            << ",\"panel_position\":" << point(latticePlacement_.position())
            << ",\"hover\":";
        if (latticeHover_) out << '[' << latticeHover_->row << ',' << latticeHover_->column << ']';
        else out << "null";
        const auto& contactPlacement=controllerContactWheel_
            ? sidebarMenus_.menus[1].placement : latticePlacement_;
        const auto contactOrientation=contactPlacement.orientation();
        out << ",\"contact_surface\":{\"position\":" << point(controllerContactWheel_
                ? contactPlacement.worldPoint(nadoc_vr::extrudeWheelFront(*controllerContactWheel_))
                : contactPlacement.position())
            << ",\"orientation_xyzw\":[" << contactOrientation.x << ',' << contactOrientation.y
            << ',' << contactOrientation.z << ',' << contactOrientation.w << "]}";
        out << ",\"wheels\":[";
        const auto& wheelPlacement=sidebarMenus_.menus[1].placement;
        for(size_t i=0;i<thumbwheelControls_.size();++i) {
            if(i)out << ',';
            const auto orientation=wheelPlacement.orientation();
            out << "{\"id\":" << quote(nadoc_vr::kExtrudeWheelIds[i])
                << ",\"label\":" << quote(i==0?"coarse":"fine")
                << ",\"available\":" << (thumbwheelAvailable()?"true":"false")
                << ",\"hovered\":" << (thumbwheelHovered_==i?"true":"false")
                << ",\"dragging\":" << (thumbwheelControls_[i].dragging()?"true":"false")
                << ",\"base_pairs_per_detent\":" << nadoc_vr::extrudeWheelStep(latticeSquare_,i)
                << ",\"notch_travel_m\":" << nadoc_vr::ThumbwheelControl::kNotchTravel*wheelPlacement.scale()
                << ",\"position\":" << point(wheelPlacement.worldPoint(nadoc_vr::extrudeWheelFront(i)))
                << ",\"orientation_xyzw\":[" << orientation.x << ',' << orientation.y << ',' << orientation.z << ',' << orientation.w << ']'
                << ",\"scale\":" << wheelPlacement.scale() << '}';
        }
        out << "],\"cells\":[";
        for (size_t i = 0; i < extrudeLatticeDraft_.cells().size(); ++i) {
            if (i) out << ',';
            const auto& cell = extrudeLatticeDraft_.cells()[i];
            out << '[' << cell.row << ',' << cell.column << ']';
        }
        out << "],\"occupied_cells\":[";
        const auto& occupied=existingLatticeCells();
        for(size_t i=0;i<occupied.size();++i) {
            if(i)out << ',';
            out << '[' << occupied[i].row << ',' << occupied[i].column << ']';
        }
        const auto* latticeContext=latticeContext_.find(extrudePlane_.plane);
        out << "],\"lattice_context_resolved\":" << (latticeContext?"true":"false") << ",\"model_preview\":[";
        if(extrudePreviewVisible() && latticeContext && !freeformDraft_.placed() && !freeformDraft_.armed() &&
           toolConfig_.targetSelectionKind()=="none") {
            bool first=true;
            for(const auto& cell:extrudeLatticeDraft_.cells()) {
                if(latticeContext->occupied(cell))continue;
                if(!first)out << ',';
                first=false;
                const auto start=latticeContext->point(cell,latticeSquare_);
                const auto finish=latticeContext->point(cell,latticeSquare_,toolConfig_.lengthBp()*toolConfig_.directionSign()*nadoc_vr::kDnaBasePairRiseNanometers);
                const auto world=[&](const auto& p){return glm::vec3(manipulator_.transform()*glm::vec4(nadoc_vr::sourceToNormalizedPoint(p,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters}),1));};
                out << "{\"cell\":[" << cell.row << ',' << cell.column << "],\"start_nm\":" << point(start)
                    << ",\"end_nm\":" << point(finish) << ",\"start_world\":" << point(world(start)) << ",\"end_world\":" << point(world(finish)) << '}';
            }
        }
        out << "],\"visible_cells\":[";
        if (latticeOpen_) {
            const auto cells = visibleLatticeCells();
            for (size_t i = 0; i < std::min(cells.size(), size_t{512}); ++i) {
                if (i) out << ',';
                const auto p = latticeCellPosition(cells[i]);
                out << "{\"row\":" << cells[i].row << ",\"column\":" << cells[i].column
                    << ",\"occupied\":" << (latticeCellOccupied(cells[i])?"true":"false")
                    << ",\"position\":" << point(latticePlacement_.worldPoint({p.x, p.y, 0.0F})) << '}';
            }
        }
        out << "]},\"capture\":" << liveCaptureResult_ << ",\"measurement\":" << liveMeasure_.result() << '}';
        return out.str();
    }

    std::string liveCommand(const std::string& text) {
        if (text == "observe") return liveState();
        std::istringstream in(text);
        std::string session, operation, extra;
        uint64_t sequence = 0;
        if (!(in >> session >> sequence >> operation) || session != liveSession_ ||
            sequence != liveCommandSequence_ + 1) return "{\"error\":\"stale_session_or_sequence\"}";
        auto end = [&]() { if (in >> extra) throw std::runtime_error("trailing arguments"); };
        auto hand = [&]() { int h = -1; if (!(in >> h) || h < 0 || h > 1) throw std::runtime_error("invalid hand"); return size_t(h); };
        auto number = [&]() { float v = 0; if (!(in >> v) || !std::isfinite(v) || std::abs(v) > 100.0F) throw std::runtime_error("invalid finite number"); return v; };
        if (operation == "scene_visibility") {
            std::string visibility; in >> visibility; end();
            if (visibility != "normal" && visibility != "hidden") throw std::runtime_error("invalid scene visibility");
            liveSceneHidden_ = visibility == "hidden";
        } else if (operation == "measure") {
            std::array<double,4> roi{};
            for(auto& v:roi) if(!(in >> v)) throw std::runtime_error("missing ROI");
            end();
            if(liveCapturePending_ || liveMeasure_.pending()) return "{\"error\":\"capture_busy\"}";
            liveMeasure_.begin(sequence, roi);
        } else if (operation == "capture") {
            end();
            if (liveCapturePending_ || liveMeasure_.pending()) return "{\"error\":\"capture_busy\"}";
            liveCapturePending_ = sequence;
            liveEyes_ = {}; liveMirrorCapture_ = {};
            liveCaptureDeadline_ = std::chrono::steady_clock::now() + std::chrono::seconds(4);
            liveCaptureResult_ = "{\"status\":\"pending\",\"command_sequence\":" + std::to_string(sequence) + "}";
        } else {
            if (!liveControlsEnabled()) return "{\"error\":\"read_only\"}";
            if (operation != "release" && sessionState_ != XR_SESSION_STATE_FOCUSED)
                return "{\"error\":\"session_not_focused\"}";
            if (operation == "release") { end(); neutralLiveInput(); }
            else if(operation=="trigger_value") {
                const auto h=hand();const float v=number();end();
                if(v<0||v>1)throw std::runtime_error("trigger outside [0,1]");
                liveTriggerValues_[h]=v;
            }
            else if (operation == "pose") {
                const auto h = hand();
                const float x = number(), y = number(), z = number();
                const float qx = number(), qy = number(), qz = number(), qw = number();
                end();
                const glm::quat q(qw, qx, qy, qz);
                if (glm::length(q) < 0.99F || glm::length(q) > 1.01F) throw std::runtime_error("quaternion must be normalized");
                liveInput_.hands[h].position = {x,y,z};
                liveInput_.hands[h].orientation = glm::normalize(q);
                liveInput_.hands[h].valid = true;
            } else if (operation == "trackpad_axis") {
                const auto h=hand(); const float x=number(), y=number(); end();
                if(std::abs(x)>1 || std::abs(y)>1) throw std::runtime_error("axis outside [-1,1]");
                liveTrackpadAxis_[h]={x,y};
            } else if (operation == "button") {
                const auto h = hand(); std::string button; int pressed = -1;
                if (!(in >> button >> pressed) || (pressed != 0 && pressed != 1)) throw std::runtime_error("invalid button");
                end();
                if (button == "trigger") {liveInput_.triggerPressed[h] = pressed;liveTriggerValues_[h]=pressed?1.F:0.F;}
                else if (button == "grip") liveInput_.gripPressed[h] = pressed;
                else if (button == "menu") liveInput_.menuPressed[h] = pressed;
                else if (button == "trackpad") liveTrackpadPressed_[h] = pressed;
                else throw std::runtime_error("unknown button");
            } else if (operation == "aim" || operation == "aim_lattice" || operation == "aim_border") {
                const auto h = hand(); glm::vec3 target{};
                if (!liveInput_.hands[h].valid) throw std::runtime_error("set hand pose first");
                if (operation == "aim") {
                    std::string label; std::getline(in >> std::ws, label);
                    const auto entry = nadoc_vr::scrywrite::findWitnessMenuEntry(
                        liveTargets(), nadoc_vr::scrywrite::WitnessReplay::canonical(label));
                    if (!entry) throw std::runtime_error("control not present");
                    target = entry->worldPosition;
                } else if (operation == "aim_lattice") {
                    int row = 0, column = 0;
                    if (!(in >> row >> column) || !latticeOpen_) throw std::runtime_error("lattice unavailable");
                    end();
                    const auto cells = visibleLatticeCells();
                    const nadoc_vr::LatticeCell cell{row,column};
                    if (std::find(cells.begin(), cells.end(), cell) == cells.end()) throw std::runtime_error("cell not visible");
                    const auto p = glm::clamp(latticeCellPosition(cell),
                        kLatticeGridBounds.minimum, kLatticeGridBounds.maximum);
                    target = latticePlacement_.worldPoint({p.x,p.y,0.0F});
                } else {
                    std::string panel, edge;
                    if (!(in >> panel >> edge)) throw std::runtime_error("missing border");
                    end();
                    const bool lattice = panel == "lattice";
                    const bool sidebar=panel=="left" || panel=="right" || panel=="menu";
                    const size_t sidebarHand=panel=="left"?0:panel=="right"?1:(sidebarMenus_.menus[1].open?1:0);
                    const auto& menu=sidebarMenus_.menus[sidebarHand];
                    if ((!lattice && !sidebar) || (lattice ? !latticeOpen_ : !menu.open)) throw std::runtime_error("panel unavailable");
                    const auto bounds = lattice ? kLatticePanelBounds : menu.bounds();
                    glm::vec3 local((bounds.minimum.x + bounds.maximum.x) * 0.5F, (bounds.minimum.y + bounds.maximum.y) * 0.5F, 0.0F);
                    if (edge == "left") local.x = bounds.minimum.x;
                    else if (edge == "right") local.x = bounds.maximum.x;
                    else if (edge == "top") local.y = bounds.maximum.y;
                    else if (edge == "bottom") local.y = bounds.minimum.y;
                    else throw std::runtime_error("invalid edge");
                    target = (lattice ? latticePlacement_ : menu.placement).worldPoint(local);
                }
                const auto q = nadoc_vr::scrywrite::witnessAimOrientation(liveInput_.hands[h].position, target);
                if (!q) throw std::runtime_error("coincident target");
                liveInput_.hands[h].orientation = *q;
            } else if (operation == "activate") {
                // Semantic entry point; subsequent interactions still use production hit tests.
                std::string tool; in >> tool; end();
                if (toolShell_.executionPending()) return "{\"error\":\"transaction_pending\"}";
                const std::array<std::string, 4> names{"extrude", "twist", "bend", "move_rotate"};
                const auto it = std::find(names.begin(), names.end(), tool);
                if (it == names.end() || !liveInput_.hands[1].valid) throw std::runtime_error("invalid tool or right pose");
                activateAuthoringTool(static_cast<size_t>(it - names.begin()));
                radialToolMenu_.close();
            } else throw std::runtime_error("unknown operation");
            liveInputDeadline_ = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        }
        liveCommandSequence_ = sequence;
        return liveState();
    }

    void suspendControllerInput() {
        remotePanels_.cancel();
        neutralLiveInput();
        triggerValues_.fill(0);triggerPartial_.fill(false);triggerPressed_.fill(false);triggerClicked_.fill(false);
        gripPressed_.fill(false);gripClicked_.fill(false);trackpadPressed_.fill(false);trackpadScrolled_.fill(false);
        desktopTrackpadTouching_.fill(false);desktopTrackpadTravel_.fill(0);
        inputResumeBlocked_.fill(true);
        for(auto& hand:hands_){hand.valid=false;hand.pressed=false;}
        // Preserve world placement while ending stale grabs behind the dashboard.
        manipulator_.update(hands_);
        latticePlacement_.update(hands_);
        desktopPanel_.placement.update(hands_);desktopPanel_.magnifying=false;desktopSurface_.hidePointer();
        viewTools_.placement.update(hands_);
        for(auto& menu:sidebarMenus_.menus)menu.placement.update(hands_);
        volumePanel_.interaction.cancel();dimensionPanel_.tool.freeze();
        if(endResize_.hand)endResize_.cancelReason="focus_lost";
        endResize_.hand.reset();endResize_.hoverHand.reset();endResize_.delta=0;
        movePanel_.hand.reset();bendPanel_.hand.reset();bendPanel_.wheelHand.reset();bendPanel_.planeHand.reset();
        bendPanel_.wheel.reset();for(auto& wheel:bendPanel_.wheels)wheel.reset();
        bendPanel_.planeHover.fill(std::nullopt);bendPanel_.beamEnd.fill(std::nullopt);
        if(!bendPanel_.twist)bendPanel_.pickSlot.reset();
        trajectoryScrubHand_.reset();
    }

    void syncActions(XrTime displayTime) {
        if (liveControlsEnabled() && (sessionState_ != XR_SESSION_STATE_FOCUSED ||
            std::chrono::steady_clock::now() > liveInputDeadline_))
            neutralLiveInput(sessionState_ != XR_SESSION_STATE_FOCUSED);
        triggerClicked_.fill(false);
        gripClicked_.fill(false);
        if (sessionState_ != XR_SESSION_STATE_FOCUSED) {
            suspendControllerInput();
            lastActionDisplayTime_ = 0;
            return;
        }
        if (lastActionDisplayTime_ > 0 && displayTime > lastActionDisplayTime_) {
            frameDeltaSeconds_ = glm::clamp(
                static_cast<float>(displayTime - lastActionDisplayTime_) * 1.0e-9F,
                1.0F / 240.0F, 0.10F);
        }
        lastActionDisplayTime_ = displayTime;
        XrActiveActionSet active{actionSet_, XR_NULL_PATH};
        XrActionsSyncInfo syncInfo{XR_TYPE_ACTIONS_SYNC_INFO};
        syncInfo.countActiveActionSets = 1;
        syncInfo.activeActionSets = &active;
        frameAudit_.mark("input_prepare");
        checkXr(instance_, xrSyncActions(session_, &syncInfo), "xrSyncActions");
        frameAudit_.mark("xr_sync");

        if (witness_) {
            witness_->advance({
                menuPageName(), witnessHoverName(),
                nadoc_vr::toolModeName(toolShell_.mode()), toolShell_.status(),
                sidebarMenus_.anyOpen() ? (observedSidebar().placement.worldDocked() ? "docked" : "following")
                                       : "closed",
                observedSidebar().placement.position(),
                combinedMenuLayoutStatus(),
                sidebarMenus_.anyOpen() ? observedSidebar().audit.summary() : "layout not rendered yet",
                mirrorSourceInitialized_
                    ? (lastMirrorSubmittedEye_ ? "submitted" : "fallback")
                    : "pending",
                mirrorPoseInitialized_
                    ? (lastMirrorPoseTracked_ ? "tracked" : "valid")
                    : "pending",
                mirrorPixelSampleSequence_ == 0U
                    ? "pending"
                    : mirrorCoverageAssessment_.overlayFraction >= 0.001F
                        ? "visible" : "missing",
                witnessMenuFramingStatus(),
                glScene_ ? representationName(glScene_->representation()) : "none",
            });
            resolveWitnessAim();
            const auto& menu=observedSidebar();
            const auto bounds=menu.bounds();
            nadoc_vr::scrywrite::resolveWitnessMenuTouch(
                *witness_, menu.placement, bounds.minimum, bounds.maximum, menu.open);
            if (witness_->failed() && !witnessFailureReported_) {
                std::cerr << "ScryWrite Witness " << witness_->status() << '\n';
                witnessFailureReported_ = true;
            } else if (witness_->finished() && !witnessCompletionReported_) {
                std::cout << "ScryWrite Witness PASSED at frame "
                          << witness_->frame() << '\n';
                witnessCompletionReported_ = true;
                if (exitOnWitnessComplete_) exitLoop_ = true;
            }
        }

        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            hands_[hand].valid = false;
            XrActionStateGetInfo getInfo{XR_TYPE_ACTION_STATE_GET_INFO};
            getInfo.subactionPath = handPaths_[hand];

            getInfo.action = triggerAction_;
            XrActionStateFloat trigger{XR_TYPE_ACTION_STATE_FLOAT};
            checkXr(instance_, xrGetActionStateFloat(session_, &getInfo, &trigger),
                    "xrGetActionStateFloat");
            triggerValues_[hand] = trigger.isActive ? trigger.currentState : 0.0F;
            if (witness_) {
                triggerValues_[hand] = witness_->input().triggerPressed[hand] ? 1.0F : 0.0F;
            }
            if (liveControlsEnabled()) triggerValues_[hand] = liveTriggerValues_[hand];
            triggerPartial_[hand] = triggerValues_[hand] >= 0.15F;
            const bool wasPressed = triggerPressed_[hand];
            const float threshold = wasPressed ? 0.60F : 0.88F;
            triggerPressed_[hand] = triggerValues_[hand] >= threshold;
            triggerClicked_[hand] = !wasPressed && triggerPressed_[hand];

            getInfo.action = poseAction_;
            XrActionStatePose poseState{XR_TYPE_ACTION_STATE_POSE};
            checkXr(instance_, xrGetActionStatePose(session_, &getInfo, &poseState),
                    "xrGetActionStatePose");
            if (poseState.isActive) {
                XrSpaceLocation location{XR_TYPE_SPACE_LOCATION};
                checkXr(instance_, xrLocateSpace(
                    handSpaces_[hand], space_, displayTime, &location), "xrLocateSpace(hand)");
                const XrSpaceLocationFlags valid = XR_SPACE_LOCATION_POSITION_VALID_BIT |
                                                   XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
                if ((location.locationFlags & valid) == valid) {
                    hands_[hand] = handPoseFromXr(location.pose);
                }
            }
            if (witness_) hands_[hand] = witness_->input().hands[hand];
            if (liveControlsEnabled()) hands_[hand] = liveInput_.hands[hand];

            getInfo.action = menuAction_;
            XrActionStateBoolean menu{XR_TYPE_ACTION_STATE_BOOLEAN};
            checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &menu),
                    "xrGetActionStateBoolean");
            const bool physicalMenuClicked =
                menu.isActive && menu.changedSinceLastSync && menu.currentState;
            bool menuClicked = physicalMenuClicked;
            if (witness_) {
                if (physicalMenuClicked) {
                    if (hand == 0U) witness_->togglePaused();
                    else witness_->requestSingleStep();
                }
                const bool pressed = witness_->input().menuPressed[hand];
                menuClicked = pressed && !witnessMenuPressed_[hand];
                witnessMenuPressed_[hand] = pressed;
            }
            if (liveControlsEnabled()) {
                if (physicalMenuClicked) neutralLiveInput();
                const bool pressed = liveInput_.menuPressed[hand];
                menuClicked = pressed && !liveMenuPressed_[hand];
                liveMenuPressed_[hand] = pressed;
            }
            if (menuClicked && !inputResumeBlocked_[hand]) toggleMenu(hand);

            getInfo.action = gripAction_;
            XrActionStateBoolean grip{XR_TYPE_ACTION_STATE_BOOLEAN};
            checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &grip),
                    "xrGetActionStateBoolean(scene grip)");
            const bool wasGripPressed = gripPressed_[hand];
            gripPressed_[hand] = grip.isActive && grip.currentState;
            if (witness_) gripPressed_[hand] = witness_->input().gripPressed[hand];
            if (liveControlsEnabled()) gripPressed_[hand] = liveInput_.gripPressed[hand];
            gripClicked_[hand] = !wasGripPressed && gripPressed_[hand];
            hands_[hand].pressed = gripPressed_[hand];

            getInfo.action = trackpadAction_;
            XrActionStateBoolean trackpad{XR_TYPE_ACTION_STATE_BOOLEAN};
            checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &trackpad),
                    "xrGetActionStateBoolean(trackpad click)");
            const bool trackpadPressed = liveControlsEnabled() ? liveTrackpadPressed_[hand]
                : !witness_ && trackpad.isActive && trackpad.currentState;
            const bool wasTrackpadPressed = trackpadPressed_[hand];
            const bool trackpadClicked = trackpadPressed && !wasTrackpadPressed;
            trackpadPressed_[hand] = trackpadPressed;

            if(inputResumeBlocked_[hand]) {
                const bool held=triggerPartial_[hand] || gripPressed_[hand] || trackpadPressed ||
                    (menu.isActive && menu.currentState);
                inputResumeBlocked_[hand]=held;
                triggerValues_[hand]=0;triggerPartial_[hand]=triggerPressed_[hand]=triggerClicked_[hand]=false;
                gripPressed_[hand]=gripClicked_[hand]=trackpadPressed_[hand]=false;
                hands_[hand].valid=false;hands_[hand].pressed=false;
                continue;
            }

            getInfo.action = trackpadTouchAction_;
            XrActionStateBoolean trackpadTouch{XR_TYPE_ACTION_STATE_BOOLEAN};
            checkXr(instance_, xrGetActionStateBoolean(
                session_, &getInfo, &trackpadTouch),
                "xrGetActionStateBoolean(trackpad touch)");
            getInfo.action = trackpadAxisAction_;
            XrActionStateVector2f trackpadAxis{XR_TYPE_ACTION_STATE_VECTOR2F};
            checkXr(instance_, xrGetActionStateVector2f(
                session_, &getInfo, &trackpadAxis),
                "xrGetActionStateVector2f(trackpad axis)");
            const glm::vec2 navigationAxis=liveControlsEnabled()?liveTrackpadAxis_[hand]:glm::vec2(trackpadAxis.currentState.x,trackpadAxis.currentState.y);
            if(hand==0)selectionWheel_.input(trackpadPressed,navigationAxis,hands_[0],
                !routingPopup_.anyOpen() && !componentGallery_.active && !toolShell_.executionPending() && !moveAwaitRefresh_ && sessionState_==XR_SESSION_STATE_FOCUSED && (liveControlsEnabled() || trackpadAxis.isActive),
                [&](const char* level){if(movePanel_.active)cancelMove();publishSelectionLevel(level);},[&](float strength){pulse(0,strength);});
            const bool touching = !witness_ && !liveSocket_.enabled() && trackpadTouch.isActive && trackpadTouch.currentState &&
                                  trackpadAxis.isActive;
            const bool desktopActive = [&] {
                const auto local=desktopPanel_.hit(hands_[hand]);
                if(!local || !desktopPanel_.uv(hands_[hand]))return false;
                const auto other=sidebarMenus_.rayEndpoint(hands_[hand]);
                return !other || glm::length(*other-hands_[hand].position) >=
                    glm::length(desktopPanel_.placement.worldPoint(*local)-hands_[hand].position);
            }();
            auto& navigationMenus=routingPopup_.anyOpen()?routingPopup_:sidebarMenus_;
            const bool sidebarActive=!desktopActive && navigationMenus.scrollAt(hands_[hand]);
            const bool focusActive=navigationMenus.menus[hand].focus.active;
            const bool navigationMenuOpen=routingPopup_.anyOpen() || sidebarMenus_.menus[hand].open;
            if (touching && !trackpadPressed && !(hand==0?selectionWheel_.blocksInput():radialToolMenu_.blocksInput()) && !focusActive && (desktopActive || sidebarActive)) {
                const float y = glm::clamp(trackpadAxis.currentState.y, -1.0F, 1.0F);
                if (!desktopTrackpadTouching_[hand]) {
                    desktopTrackpadTouching_[hand] = true;
                    desktopTrackpadLastY_[hand] = y;
                    desktopTrackpadTravel_[hand] = 0.0F;
                } else {
                    desktopTrackpadTravel_[hand] += y - desktopTrackpadLastY_[hand];
                    desktopTrackpadLastY_[hand] = y;
                    if (std::abs(desktopTrackpadTravel_[hand]) >= 0.18F) {
                        if(sidebarActive) navigationMenus.scrollAt(hands_[hand],desktopTrackpadTravel_[hand]>0.0F?-1:1);
                        else desktopSurface_.scroll(desktopTrackpadTravel_[hand] > 0.0F);
                        desktopTrackpadTravel_[hand] = 0.0F;
                        trackpadScrolled_[hand] = true;
                    }
                }
                selectionVolumes_[hand].endScroll();
            } else if (touching && !trackpadPressed && !(hand==0?selectionWheel_.blocksInput():radialToolMenu_.blocksInput()) && movePanel_.selectionEnabled(hand) && !navigationMenuOpen && !(hand == 1U && trackpadPressed)) {
                desktopTrackpadTouching_[hand] = false;
                if (!selectionVolumes_[hand].scrolling()) {
                    selectionVolumes_[hand].beginScroll(trackpadAxis.currentState.y);
                } else if (selectionVolumes_[hand].updateScroll(
                               trackpadAxis.currentState.y)) {
                    trackpadScrolled_[hand] = true;
                }
            } else {
                desktopTrackpadTouching_[hand] = false;
                desktopTrackpadTravel_[hand] = 0.0F;
                selectionVolumes_[hand].endScroll();
                if (!trackpadPressed) trackpadScrolled_[hand] = false;
            }

            if(hand==1) {
                radialToolMenu_.setWorkflow(bendPanel_.active,bendHasAngle());
                const bool sweepWheel=sweepPanel_.active && sweepDraft_.step==2;
                radialToolMenu_.setSweep(sweepWheel);
                if(!sweepWheel && !bendPanel_.active && !radialToolMenu_.open() && trackpadClicked && (routingPopup_.anyOpen()?routingPopup_:sidebarMenus_).trackpad(hand,navigationAxis,hands_[hand]))pulse(hand,.12F);
                const auto result=radialToolMenu_.update(trackpadPressed,navigationAxis,hands_[hand],
                    (!navigationMenuOpen || ((bendPanel_.active || sweepWheel) && !routingPopup_.anyOpen())) && (bendPanel_.active || sweepWheel || !desktopActive || radialToolMenu_.open()) && !componentGallery_.active && !toolShell_.executionPending() &&
                    !moveAwaitRefresh_ && sessionState_==XR_SESSION_STATE_FOCUSED && (liveControlsEnabled() || trackpadAxis.isActive));
                if(result.hoverChanged)pulse(hand,.14F);
                if(result.commit) {activateRadialEdit(*result.commit);if(*result.commit<2)pulse(hand,.32F);}
            }
        }

        if(componentGallery_.active) {
            for(auto& menu:sidebarMenus_.menus)menu.open=false;
            componentGallery_.update(hands_,triggerClicked_,triggerPressed_,frameDeltaSeconds_,witnessObserverPosition_,witnessObserverOrientation_);
            updateControllerGuides();return;
        }
        frameAudit_.mark("poses_buttons");
        auto remoteBlocked=remotePanels_.update(remotePanelTargets(),hands_,routingPopup_.anyOpen()?std::array<bool,2>{}:radialToolMenu_.filter(selectionWheel_.filter(triggerClicked_)),routingPopup_.anyOpen()?std::array<bool,2>{}:radialToolMenu_.filter(selectionWheel_.filter(triggerPressed_)),witnessObserverPosition_,glfwGetTime());
        if(routingPopup_.anyOpen())remoteBlocked.fill(true);
        remoteBlocked[0]=remoteBlocked[0]||selectionWheel_.blocksInput();
        remoteBlocked[1]=remoteBlocked[1]||radialToolMenu_.blocksInput();
        viewTools_.syncPose();
        const auto gripContacts=menuGripContacts();
        const bool latticeOwnsGrip=latticeOpen_ && (latticePlacement_.dragHand() ||
            latticePlacement_.resizeActive() || latticeGrip_.held[0] || latticeGrip_.held[1]);
        const bool desktopOwnsGrip=desktopPanel_.open && (desktopPanel_.placement.dragHand() || desktopPanel_.placement.resizeActive());
        const bool viewOwnsGrip=viewTools_.open && (viewTools_.placement.dragHand() || viewTools_.placement.resizeActive());
        std::array<bool, 2> menuGripTargeted = (routingPopup_.anyOpen() || latticeOwnsGrip || viewOwnsGrip || desktopOwnsGrip) ? std::array<bool,2>{} : sidebarMenus_.grips(gripContacts, gripClicked_, [this](size_t hand,float strength) { suppressManipulationUntilRelease_=true; pulse(hand,strength); });
        if(!latticeOwnsGrip && !viewOwnsGrip)desktopPanel_.grips(gripContacts,gripClicked_,menuGripTargeted,[this](size_t hand,float strength){suppressManipulationUntilRelease_=true;pulse(hand,strength);});
        if(!latticeOwnsGrip)viewTools_.grips(gripContacts,gripClicked_,menuGripTargeted,[this](size_t hand,float strength){suppressManipulationUntilRelease_=true;pulse(hand,strength);});
        const auto latticeGripTargeted=latticeGrip_.update(latticePlacement_,gripContacts,gripClicked_,
            kLatticeGridBounds.minimum,kLatticeGridBounds.maximum,
            kLatticePanelBounds.minimum,kLatticePanelBounds.maximum,
            latticeOpen_ && !menuGripTargeted[0] && !menuGripTargeted[1] &&
            !latticePlacement_.dragHand() && !latticePlacement_.resizeActive());
        for(size_t h=0;h<2;++h) if(latticeGripTargeted[h]) {
            menuGripTargeted[h]=true;suppressManipulationUntilRelease_=true;
            if(gripClicked_[h])pulse(h,.40F);
        }
        if (latticeOpen_ && !menuGripTargeted[0] && !menuGripTargeted[1]) {
            const auto& bounds = kLatticePanelBounds;
            const float panelHalfWidth = (bounds.maximum.x - bounds.minimum.x) * 0.5F;
            latticePlacement_.update(gripContacts, panelHalfWidth);
            const bool gripStarted = gripClicked_[0] || gripClicked_[1];
            if (!latticePlacement_.resizeActive() && gripStarted &&
                latticePlacement_.beginBorderResize(
                    gripContacts, bounds.minimum, bounds.maximum)) {
                suppressManipulationUntilRelease_ = true;
                pulse(0, 0.52F);
                pulse(1, 0.52F);
            }
            if (!latticePlacement_.resizeActive() && !latticePlacement_.dragHand()) {
                for (size_t hand = 0; hand < gripContacts.size(); ++hand) {
                    if (gripClicked_[hand] && latticePlacement_.beginDrag(
                            hand, gripContacts, bounds.minimum, bounds.maximum)) {
                        suppressManipulationUntilRelease_ = true;
                        pulse(hand, 0.48F);
                        break;
                    }
                }
            }
            latticePlacement_.update(gripContacts, panelHalfWidth);
            if (latticePlacement_.resizeActive()) menuGripTargeted.fill(true);
            if (latticePlacement_.dragHand()) {
                menuGripTargeted[*latticePlacement_.dragHand()] = true;
            }
        }
        for(size_t h=0;h<2;++h)menuGripTargeted[h]=menuGripTargeted[h]||remoteBlocked[h];
        const nadoc_vr::ManipulationMode previous = manipulator_.mode();
        if (suppressManipulationUntilRelease_ &&
            std::none_of(gripPressed_.begin(), gripPressed_.end(), [](bool pressed) {
                return pressed;
            })) {
            suppressManipulationUntilRelease_ = false;
        }
        auto manipulationHands = hands_;
        if(routingPopup_.anyOpen())for(auto& hand:manipulationHands)hand.pressed=false;
        if(selectionWheel_.blocksInput())manipulationHands[0].pressed=false;
        if(radialToolMenu_.blocksInput())manipulationHands[1].pressed=false;
        const bool menuGripActive = std::any_of(
            menuGripTargeted.begin(), menuGripTargeted.end(),
            [](bool targeted) { return targeted; });
        if (menuGripActive) {
            for (nadoc_vr::HandPose& hand : manipulationHands) hand.pressed = false;
        }
        const bool inputSuppressed = suppressManipulationUntilRelease_;
        const bool rigidToolPreview =
            toolShell_.mode() == nadoc_vr::ToolMode::move_rotate &&
            toolShell_.previewRequested() &&
            (!toolShell_.executionPending() || sceneRefresh_.revision()==moveStartRevision_);
        // Grips retain scene manipulation in every tool; edit grabs use triggers.
        glScene_->setMovePointPreview(
            rigidToolPreview ? selectedOwnerTokens_ : std::vector<std::string>{},
            pendingToolTransform_.transform());
        if (inputSuppressed) {
            for (nadoc_vr::HandPose& hand : manipulationHands) hand.pressed = false;
        }
        const nadoc_vr::ManipulationMode next = manipulator_.update(manipulationHands);
        if (next != previous && next != nadoc_vr::ManipulationMode::none) {
            for (size_t hand = 0; hand < hands_.size(); ++hand) {
                if (hands_[hand].valid && hands_[hand].pressed) pulse(hand);
            }
        }
        volumePanel_.update(sidebarMenus_.menus);
        refreshExtrudePanel();
        const auto volumeTargeted=volumePanel_.input(hands_,triggerClicked_,triggerPressed_,
            manipulator_.transform(),normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters},
            !dimensionPanel_.tool.active && !radialToolMenu_.blocksInput() && !remoteBlocked[0] && !remoteBlocked[1],
            next!=nadoc_vr::ManipulationMode::none || previous!=nadoc_vr::ManipulationMode::none,
            [&](size_t hand){pulse(hand,.35F);});
        auto wheelTargeted = processThumbwheelInput(remoteBlocked);
        for(size_t h=0;h<2;++h)wheelTargeted[h]=wheelTargeted[h]||remoteBlocked[h];
        processBendWheel(wheelTargeted);
        std::array<float,2> foregroundDistance{1e9F,1e9F};
        if(viewTools_.open)for(size_t h=0;h<2;++h)if(auto uv=viewTools_.hit(hands_[h]))
            foregroundDistance[h]=std::min(foregroundDistance[h],glm::length(viewTools_.world(*uv)-hands_[h].position));
        for(size_t h=0;h<2;++h)if(auto p=desktopPanel_.hit(hands_[h]))
            foregroundDistance[h]=std::min(foregroundDistance[h],glm::length(desktopPanel_.placement.worldPoint(*p)-hands_[h].position));
        auto sidebarBlocked=wheelTargeted;
        // A held point/stroke keeps trigger ownership while crossing a menu.
        if(sweepHand_)sidebarBlocked[*sweepHand_]=true;
        for(size_t h=0;h<2;++h)sidebarBlocked[h]=sidebarBlocked[h]||volumeTargeted[h];
        sidebarBlocked=processTrajectoryInput(sidebarBlocked,foregroundDistance);
        if(routingPopup_.anyOpen()) {
            routingPopup_.input(hands_,triggerClicked_,triggerPressed_,{false,false},{1e9F,1e9F},glfwGetTime(),
                [&](const std::string& action,size_t hand){activateSidebarAction(action,hand);});
            sidebarBlocked.fill(true);
        }
        auto sidebarTargeted = sidebarMenus_.input(hands_, triggerClicked_, triggerPressed_, sidebarBlocked, foregroundDistance,glfwGetTime(),
            [&](const std::string& action, size_t hand) { activateSidebarAction(action,hand); });
        std::array<bool, 2> menuControlTargeted = sidebarTargeted;
        if(routingPopup_.anyOpen())menuControlTargeted.fill(true);
        for(size_t h=0;h<2;++h)menuControlTargeted[h]=menuControlTargeted[h]||volumeTargeted[h];
        menuControlTargeted = processDesktopInput(menuControlTargeted);
        for(size_t h=0;h<2;++h)menuControlTargeted[h]=menuControlTargeted[h] || wheelTargeted[h] || latticeGripTargeted[h];
        const auto latticeTargeted = processLatticeInput(menuControlTargeted);
        for (size_t hand = 0; hand < menuControlTargeted.size(); ++hand) {
            liveInputOwner_[hand] = (hand==0 && selectionWheel_.blocksInput()) ? "selection-wheel" : latticeGripTargeted[hand] ? "lattice-grip" : volumeTargeted[hand] ? "view-volume" : (hand == 1U && radialToolMenu_.blocksInput()) ? "radial"
                : wheelTargeted[hand] ? "wheel" : menuControlTargeted[hand] ? "menu"
                : latticeTargeted[hand] ? "lattice" : hands_[hand].valid ? "scene" : "none";
            menuControlTargeted[hand] = menuControlTargeted[hand] ||
                                        latticeTargeted[hand];
        }
        if (radialToolMenu_.blocksInput()) menuControlTargeted[1] = true;
        processSweepInput(menuControlTargeted,next!=nadoc_vr::ManipulationMode::none);
        frameAudit_.mark("menus_manipulation");
        dimensionPanel_.input(hands_,manipulator_.transform(),next!=nadoc_vr::ManipulationMode::none,
            triggerClicked_,menuControlTargeted,liveInputOwner_,sidebarMenus_.menus,normalizationScale_,
            [&](size_t hand){pulse(hand,.3F);});
        dimensionSync_.update(dimensionPanel_.tool,normalizationCenter_,normalizationScale_);
        if(volumePanel_.active) menuControlTargeted.fill(true);
        frameAudit_.mark("dimensions");
        simulationPanel_.poll(eventPath_);
        routingPanel_.poll(eventPath_,routingPopup_.menus[1],sidebarMenus_.menus[1]);
        { std::error_code error; const auto path=eventPath_+".share";
          const auto changed=std::filesystem::last_write_time(path,error);
          if(error || std::filesystem::file_time_type::clock::now()-changed>std::chrono::seconds(3)) {shareActive_=false;shareBusy_=true;}
          else {std::ifstream share(path); int active=0,perspective=0,busy=1,ack=0,failed=0;
            if(share>>active>>perspective>>busy>>ack>>failed) {shareActive_=active;sharePerspective_=perspective;shareBusy_=busy;shareAck_=ack;shareFailed_=failed;} }
        }
        if(viewTools_.poll(eventPath_,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters})) {
        }
        for(size_t h=0;h<2;++h)menuControlTargeted[h]=menuControlTargeted[h]||menuGripTargeted[h];
        viewTools_.input(hands_,triggerClicked_,menuControlTargeted,[&](size_t hand){publishEventState();pulse(hand,.3F);});
        // Alternate layouts have different positions from canonical edit targets.
        // Keep tablet input and world manipulation, but never cut an unseen bond.
        if(viewTools_.inspectionLayout()) menuControlTargeted.fill(true);
        frameAudit_.mark("feeds_view_tools");
        ligation_.poll(eventPath_,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters});
        ligation_.input(hands_,{selectionVolumeCenter(0),selectionVolumeCenter(1)},
            {selectionVolumes_[0].radius(),selectionVolumes_[1].radius()},triggerClicked_,triggerPressed_,
            menuControlTargeted,manipulator_.transform(),
            sessionState_==XR_SESSION_STATE_FOCUSED && next==nadoc_vr::ManipulationMode::none &&
            !menuGripActive && !radialToolMenu_.blocksInput() && !dimensionPanel_.tool.active && !volumePanel_.active,
            [&](const std::string& identity,size_t hand){publishSelect({identity});pulse(hand,.35F);},
            [&]{publishEventState();});
        if(ligation_.active)for(size_t h=0;h<2;++h)if(menuControlTargeted[h] && !(h==1 && radialToolMenu_.blocksInput()))liveInputOwner_[h]="ligate";
        ligation_.nickInput(hands_,{selectionVolumeCenter(0),selectionVolumeCenter(1)},
            {selectionVolumes_[0].radius(),selectionVolumes_[1].radius()},triggerValues_,triggerClicked_,menuControlTargeted,
            manipulator_.transform(),sessionState_==XR_SESSION_STATE_FOCUSED && next==nadoc_vr::ManipulationMode::none &&
            !menuGripActive && !radialToolMenu_.blocksInput() && !dimensionPanel_.tool.active && !volumePanel_.active,
            [&]{publishEventState();});
        if(ligation_.nickActive)for(size_t h=0;h<2;++h)if(menuControlTargeted[h] && !(h==1 && radialToolMenu_.blocksInput()))liveInputOwner_[h]="nick";
        frameAudit_.mark("nick_ligate");
        endResize_.poll(eventPath_,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters});
        endResize_.input(hands_,triggerClicked_,triggerPressed_,menuControlTargeted,
            manipulator_.transform(),normalizationScale_,
            sessionState_==XR_SESSION_STATE_FOCUSED && next==nadoc_vr::ManipulationMode::none &&
            !menuGripActive && !dimensionPanel_.tool.active && !volumePanel_.active &&
            !ligation_.active && !ligation_.nickActive && !ligation_.waiting && !movePanel_.active && !bendPanel_.active && !sweepPanel_.active && !toolShell_.executionPending() && !radialToolMenu_.blocksInput(),
            [&]{ publishEventState(); });
        if(endResize_.hand)liveInputOwner_[*endResize_.hand]="end-resize";
        frameAudit_.mark("end_resize");
        processMoveInput(menuControlTargeted,next!=nadoc_vr::ManipulationMode::none || menuGripActive);
        frameAudit_.mark("move_preview");
        processBendPlanes(menuControlTargeted,next!=nadoc_vr::ManipulationMode::none || menuGripActive);
        // Remote panel border hover reserves its pointer, but does not move the
        // model. Let the free hand cross that border to reach a Bend wheel
        // without cancelling the other hand's endpoint grab. Actual world
        // manipulation (and the model-matrix guard) still ends the grab.
        processBendHandles(menuControlTargeted,next!=nadoc_vr::ManipulationMode::none);
        frameAudit_.mark("bend");
        updateSelectionVolumeCandidates(menuControlTargeted);
        frameAudit_.mark("selection_candidates");
        processBendPlanePick(menuControlTargeted);
        if(bendPanel_.active && !bendPanel_.selecting)menuControlTargeted.fill(true);
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            if (!movePanel_.selectionEnabled(hand) || menuControlTargeted[hand] || !triggerClicked_[hand] ||
                !hands_[hand].valid) {
                continue;
            }
            if (freeformDraft_.armed()) {
                if (freeformDraft_.capture(hands_[hand],extrudePlane_.plane,manipulator_.transform(),normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters})) {
                    latticeOpen_=true; sidebarMenus_.menus[1].open=true;
                    publishToolConfiguration();
                }
                continue;
            }
            if (snapSelectionHits_[hand].empty()) {
                publishSelect({});
                continue;
            }
            if (planePickSlot_) {
                publishPlanePick(snapSelectionHits_[hand].front().identity);
            } else {
                std::vector<std::string> identities;
                identities.reserve(snapSelectionHits_[hand].size());
                for (const auto& hit : snapSelectionHits_[hand]) {
                    identities.push_back(hit.identity);
                }
                publishSelect(identities);
            }
            pulse(hand, 0.55F);
        }
        pollSelectionFeedback();
        pollToolContextFeedback();
        pollPlanePickFeedback();
        pollToolPreflightFeedback();
        pollToolExecutionFeedback();
        frameAudit_.mark("selection_feedback");
        sceneRefresh_.pollStaged(eventPath_, [normalization=std::make_pair(normalizationCenter_, normalizationScale_)](const std::string& path) {
            return loadScene(path, normalization);
        }, [&](SceneData scene) {
            pendingLatticeContext_=scene.latticeContext;
            glScene_->beginSceneRefresh(std::move(scene));
        }, [&] {
            if(glScene_->canStageSceneRefresh(visualizationSnapshot_)) {
                try {
                    if(!glScene_->advanceSceneRefresh(visualizationSnapshot_,representationLoading_.retired))return false;
                    glScene_->setSelectionHighlights({}, {}, committedSelectionOwnerTokens_, committedSelectionIdentities_, false);
                    if(pendingLatticeContext_)latticeContext_=std::move(*pendingLatticeContext_);
                    pendingLatticeContext_.reset();
                    return true;
                }
                catch(...) { representationLoading_.retired.retire(glScene_->takeSceneRefresh());throw; }
            }
            // Deformed/colored visualization snapshots retain the established
            // activation path until their CPU preparation has a staged equivalent.
            nadoc_vr::CalculationScope refreshScope("activateSceneRefresh");
            auto scene=glScene_->takeSceneRefresh();
            scene.initialRepresentation = glScene_->representation();
            scene.initialColoring = glScene_->coloring();
            auto candidate = std::make_unique<GlScene>(std::move(scene), liveSocket_.enabled(), glScene_->objectIdentities(), std::function<void(size_t)>{}, false, false);
            candidate->setSelectionHighlights({}, {}, committedSelectionOwnerTokens_, committedSelectionIdentities_, false);
            candidate->setVisualization(visualizationSnapshot_);
            glScene_.swap(candidate);
            if(pendingLatticeContext_)latticeContext_=std::move(*pendingLatticeContext_);
            pendingLatticeContext_.reset();
            if (!representationLoading_.retired.full()) candidate->retireSource(representationLoading_.retired);
            return true;
        });
        updateControllerGuides();
    }

    std::optional<size_t> nearestBendCluster(glm::vec3 origin,std::optional<glm::vec3> direction=std::nullopt) const {
        float best=direction?.08F:std::numeric_limits<float>::max();std::optional<size_t> found;
        const auto model=manipulator_.transform();
        for(size_t i=0;i<bendClusters_.size();++i)for(const auto& segment:bendClusters_[i].segments) {
            const auto a=glm::vec3(model*glm::vec4(segment.first,1)),b=glm::vec3(model*glm::vec4(segment.second,1));
            glm::vec3 p;
            if(direction) {
                // Closest points between the finite cluster axis and forward ray.
                const auto u=b-a,w=a-origin;const float uu=glm::dot(u,u),ud=glm::dot(u,*direction);
                const float denominator=uu-ud*ud;
                float t=denominator>1e-8F?glm::clamp((ud*glm::dot(w,*direction)-glm::dot(w,u))/denominator,0.F,1.F):0.F;
                p=a+t*u;const float d=glm::dot(p-origin,*direction);
                if(d<0 || d>10)continue;
                const float distance=glm::distance(p,origin+d* *direction);
                if(distance<best){best=distance;found=i;}
            } else {
                p=nadoc_vr::closestPointOnSegment(origin,a,b);
                const float distance=glm::distance(origin,p);if(distance<best){best=distance;found=i;}
            }
        }
        return found;
    }
    void selectBendCluster(size_t index) {
        if(index>=bendClusters_.size())return;
        const auto& cluster=bendClusters_[index];
        bendPanel_.reset();bendPanel_.pickSlot.reset();clearPlanePick();clearPlaneGuides();bendPickPosition_.reset();
        bendPanel_.clusterLabel=bendPanel_.clusters[index];bendPanel_.pendingSelection=cluster.identity;
        bendPanel_.defaultPlanes=true;publishSelectionLevel("cluster");
        if(selectedSelectionKind_=="cluster" && std::find(selectedOwnerTokens_.begin(),selectedOwnerTokens_.end(),cluster.token)!=selectedOwnerTokens_.end()) {
            bendPanel_.pendingSelection.clear();requestBendDefaultPlane("a");
        } else publishSelect({cluster.identity});
        refreshExtrudePanel();
    }
    void requestBendDefaultPlane(const std::string& slot) {
        bendPickPosition_.reset();bendPickExtent_=slot;planePickSlot_=slot;
        publishPlanePick(selectedIdentity_);
    }
    std::optional<glm::vec3> bendWheelPoint(size_t hand) const {
        if(!hands_[hand].valid)return std::nullopt;
        return sidebarMenus_.menus[1].placement.rayPanelLocalPoint(hands_[hand],{-10,-10},{10,10});
    }
    struct BendPlaneHit {size_t slot;glm::vec3 point;float distance;};
    std::pair<glm::vec3,glm::vec3> deformationPlaneAxes(glm::vec3 normal) const {
        const auto reference=std::abs(glm::dot(normal,sourceAxes_[1]))<.9F
            ?sourceAxes_[1]:sourceAxes_[0];
        const auto u=glm::normalize(glm::cross(normal,reference));
        return {u,glm::normalize(glm::cross(normal,u))};
    }
    std::optional<BendPlaneHit> bendPlaneHit(size_t hand) const {
        if(!hands_[hand].valid)return std::nullopt;
        const auto model=manipulator_.transform(),inverse=glm::inverse(model);
        const auto origin=glm::vec3(inverse*glm::vec4(hands_[hand].position,1));
        const auto direction=glm::normalize(glm::vec3(inverse*glm::vec4(hands_[hand].orientation*glm::vec3(0,0,-1),0)));
        const float scale=glm::length(glm::vec3(model[0]));
        std::optional<BendPlaneHit> hit;
        for(size_t slot=0;slot<2;++slot)if(planeGuides_[slot]) {
            const auto pose=deformationPlanePose(slot);
            const auto [u,v]=deformationPlaneAxes(pose.normal);
            const float denom=glm::dot(direction,pose.normal);
            float t=std::abs(denom)>1e-5F?glm::dot(pose.center-origin,pose.normal)/denom:-1;
            glm::vec3 point=origin+direction*t;
            const bool near=glm::distance(origin,pose.center)*scale<.055F || glm::distance(hands_[hand].position,glm::vec3(model*glm::vec4(bendHandle(slot),1)))<.055F;
            if(near){t=0;point=origin;}
            const auto delta=point-pose.center;
            if(t<0 || t*scale>10 || (!near && (std::abs(glm::dot(delta,u))>pose.halfExtent+.012F/scale || std::abs(glm::dot(delta,v))>pose.halfExtent+.012F/scale)))continue;
            if(!hit || t*scale<hit->distance)hit=BendPlaneHit{slot,glm::vec3(model*glm::vec4(point,1)),t*scale};
        }
        return hit;
    }
    void processBendPlanes(std::array<bool,2>& blocked,bool sceneMoving) {
        nadoc_vr::CalculationScope auditScope("processBendPlanes");
        bendPanel_.planeHover.fill(std::nullopt);bendPanel_.beamEnd.fill(std::nullopt);
        if(!bendPanel_.active || bendPanel_.twist || bendPanel_.selecting)return;
        if(sceneMoving || viewTools_.inspectionLayout() || toolShell_.executionPending()) {
            bendPanel_.planeHand.reset();bendPanel_.pickSlot.reset();return;
        }
        if(bendPanel_.planeHand) {
            const size_t h=*bendPanel_.planeHand;blocked[h]=true;
            if(!hands_[h].valid || !triggerPressed_[h] || manipulator_.transform()!=bendPanel_.startModel) {
                bendPanel_.planeHand.reset();bendPanel_.pickSlot.reset();return;
            }
            if(activePlanePickSequence_)return;
            const auto contact=hands_[h].position+hands_[h].orientation*glm::vec3(0,0,-bendSlideRayDistance_);
            bendPanel_.beamEnd[h]=contact;bendPanel_.planeHover[h]=*bendPanel_.pickSlot=="a"?0:1;
            const auto world=bendSlideStart_+contact-bendSlideHand_;
            const auto local=glm::vec3(glm::inverse(manipulator_.transform())*glm::vec4(world,1));
            const auto source=(local-glm::vec3(0,0,-kViewDistanceMeters))/normalizationScale_+normalizationCenter_;
            if(bendPickPosition_ && glm::distance(source,*bendPickPosition_)<.167F)return;
            bendPickPosition_=source;planePickSlot_=bendPanel_.pickSlot;publishPlanePick(selectedIdentity_);return;
        }
        if(!bendPanel_.pendingSelection.empty() || bendPanel_.defaultPlanes || bendPanel_.hand)return;
        prepareBendArc();
        for(size_t h=0;h<2;++h)if(!blocked[h] && hands_[h].valid) {
            if(const auto hit=bendPlaneHit(h)) {
                bendPanel_.planeHover[h]=hit->slot;bendPanel_.beamEnd[h]=hit->point;
                if(!bendPanel_.manual && triggerClicked_[h] && bendReady()) {
                    bendPanel_.planeHand=h;bendPanel_.pickSlot=hit->slot==0?"a":"b";
                    bendPanel_.startModel=manipulator_.transform();bendSlideRayDistance_=hit->distance;
                    bendSlideStart_=glm::vec3(manipulator_.transform()*glm::vec4(planeGuides_[hit->slot]->natural.center,1));
                    bendSlideHand_=hit->point;bendPickPosition_.reset();blocked[h]=true;
                    resetBendToPlanes();pulse(h,.3F);
                }
            }
        }
    }

    DeformationPlanePose deformationPlanePose(size_t slot) const {
        const DeformationPlaneGuide& guide = *planeGuides_[slot];
        DeformationPlanePose pose = guide.natural;
        if(bendPanel_.active && !bendPanel_.twist && bendPanel_.posed) {
            pose.center=slot==0?bendPanel_.arc.a:bendPanel_.arc.b;
            pose.normal=bendPanel_.arc.endTangent(float(slot));
        }

        return pose;
    }
    void prepareBendArc() {
        nadoc_vr::CalculationScope auditScope("prepareBendArc");
        if(bendPanel_.posed || !planeGuides_[0] || !planeGuides_[1] || !toolConfig_.planeABp() || !toolConfig_.planeBBp())return;
        auto& arc=bendPanel_.arc;
        arc.sourceAxes=sourceAxes_;
        arc.fixedEnd=1-bendPanel_.grabbed;
        arc.a=planeGuides_[0]->natural.center;
        arc.tangent=glm::normalize(planeGuides_[arc.fixedEnd]->natural.normal);
        const float phi=glm::radians(float(toolConfig_.bendDirectionDegrees()));
        arc.direction=glm::angleAxis(phi,arc.tangent)*arc.referenceDirection();
        arc.length=float(*toolConfig_.planeBBp()-*toolConfig_.planeABp())*.334F*normalizationScale_;
        arc.angle=glm::radians(float(toolConfig_.bendAngleDegrees()));
        arc.b=planeGuides_[1]->natural.center;
        if(arc.angle>0)arc.updateEndpoint();
    }
    void resetBendToPlanes() {
        bendPanel_.posed=false;
        (void)toolConfig_.setBend(0,0);
        prepareBendArc();
        refreshExtrudePanel();
    }
    void processBendWheel(std::array<bool,2>& blocked) {
        if(!bendPanel_.active || bendPanel_.selecting)return;
        if(bendPanel_.twist) {
            if(!bendPanel_.wheelHand)return;
            const size_t h=*bendPanel_.wheelHand;blocked[h]=true;
            if(!hands_[h].valid || !triggerPressed_[h] || toolShell_.executionPending()) {
                bendPanel_.wheelHand.reset();bendPanel_.wheel.reset();return;
            }
            const float y=sidebarMenus_.menus[1].placement.localPoint(hands_[h].position).y;
            const int steps=bendPanel_.wheel.drag(y,frameDeltaSeconds_);
            if(!steps)return;
            const double step=toolConfig_.twistAmountMode()==nadoc_vr::TwistAmountMode::total_degrees?1:.1;
            (void)toolConfig_.setTwist((std::round(toolConfig_.twistAmount()/step)+steps)*step);
            refreshExtrudePanel();publishToolConfiguration();pulse(h,.16F);return;
        }
        bendPanel_.wheelHover.fill(false);
        if(toolShell_.executionPending() || !planeGuides_[0] || !planeGuides_[1] || bendPanel_.defaultPlanes) {
            for(auto& w:bendPanel_.wheels)w.reset();
            bendPanel_.wheelHand.reset();return;
        }
        const auto& menu=sidebarMenus_.menus[1];
        for(size_t h=0;h<2;++h)if(!blocked[h] && menu.open && !bendPanel_.clustersOpen) {
            const auto point=bendWheelPoint(h);if(!point)continue;
            for(const auto& c:menu.controls())if(c.id.ends_with("-wheel") && nadoc_vr::thumbwheelHit(nadoc_vr::thumbwheelPreset(100),
                    {(c.bounds.minimum.x+c.bounds.maximum.x)*.5F,(c.bounds.minimum.y+c.bounds.maximum.y)*.5F,.012F},menu.placement,hands_[h])) {
                const size_t index=c.id=="bend:angle-wheel"?0:c.id=="bend:direction-wheel"?1:2;
                bendPanel_.wheelHover[index]=true;blocked[h]=true;
                if(triggerClicked_[h] && !bendPanel_.wheelHand && bendPanel_.hand!=h && !bendPanel_.planeHand)activateSidebarAction(c.id,h);
            }
        }
        for(size_t index=0;index<3;++index) {
            auto& wheel=bendPanel_.wheels[index];int steps=0;
            if(bendPanel_.wheelHand && bendPanel_.wheelIndex==index) {
                const size_t h=*bendPanel_.wheelHand;blocked[h]=true;
                if(!hands_[h].valid) {wheel.reset();bendPanel_.wheelHand.reset();}
                else if(!triggerPressed_[h]) {wheel.release();bendPanel_.wheelHand.reset();}
                else if(const auto point=bendWheelPoint(h))steps=wheel.drag(point->y,frameDeltaSeconds_);
                else {wheel.reset();bendPanel_.wheelHand.reset();}
            }
            if(!wheel.dragging())steps+=wheel.updateMomentum(frameDeltaSeconds_);
            if(!steps)continue;
            const int sign=index==2?-1:1;
            const double angle=index==1?toolConfig_.bendAngleDegrees():
                std::clamp(std::round(toolConfig_.bendAngleDegrees())+sign*steps,0.0,359.0);
            const double direction=index==1?
                std::fmod(std::round(toolConfig_.bendDirectionDegrees())+steps+720.0,360.0):toolConfig_.bendDirectionDegrees();
            applyBendAdjustment(angle,direction);
            if(bendPanel_.wheelHand)pulse(*bendPanel_.wheelHand,.16F);
        }
    }
    void applyBendAdjustment(double angle,double direction) {
        prepareBendArc();
        auto& arc=bendPanel_.arc;
        const float turn=glm::radians(float(direction-toolConfig_.bendDirectionDegrees()));
        arc.direction=glm::angleAxis(turn,arc.tangent)*arc.direction;
        arc.angle=glm::radians(float(angle));
        arc.updateEndpoint();
        if(bendPanel_.hand) {
            const auto position=glm::vec3(glm::inverse(manipulator_.transform())*glm::vec4(hands_[*bendPanel_.hand].position+hands_[*bendPanel_.hand].orientation*glm::vec3(0,0,-bendPanel_.grabRayDistance),1));
            bendPanel_.grabOffset=(bendPanel_.grabbed==0?arc.a:arc.b)-position;
        }
        (void)toolConfig_.setBend(angle,direction);
        bendPanel_.posed=arc.length>0;refreshExtrudePanel();publishToolConfiguration();
    }
    glm::vec3 bendHandle(size_t end) const {
        const auto& arc=bendPanel_.arc;
        const float offset=.028F/glm::length(glm::vec3(manipulator_.transform()[0]));
        return (end==0?arc.a:arc.b)+arc.endTangent(float(end))*(end==0?-offset:offset);
    }
    glm::vec3 twistHandle(size_t end) const {
        const auto& arc=bendPanel_.arc;
        const float angle=end?glm::radians(float(toolConfig_.twistTotalDegrees())):0;
        return (end?arc.b:arc.a)+glm::angleAxis(angle,arc.tangent)*arc.referenceDirection()*twistRadius();
    }
    float twistRadius() const {
        return std::max(.045F/glm::length(glm::vec3(manipulator_.transform()[0])),planeGuides_[1]->natural.halfExtent*1.3F);
    }
    void processTwistHandle(std::array<bool,2>& blocked,bool sceneMoving) {
        prepareBendArc();
        if(sceneMoving || toolShell_.executionPending() || viewTools_.inspectionLayout()) {
            if(bendPanel_.hand){bendPanel_.hand.reset();publishToolConfiguration();}return;
        }
        const auto model=manipulator_.transform();
        if(bendPanel_.hand) {
            const size_t h=*bendPanel_.hand;blocked[h]=true;
            if(!hands_[h].valid || !triggerPressed_[h] || model!=bendPanel_.startModel) {
                bendPanel_.hand.reset();publishToolConfiguration();return;
            }
            const auto& arc=bendPanel_.arc;
            auto radial=glm::vec3(glm::inverse(model)*glm::vec4(hands_[h].position,1))-arc.b;
            radial-=arc.tangent*glm::dot(radial,arc.tangent);
            if(glm::length(radial)<twistRadius()*.2F)return;
            radial=glm::normalize(radial);
            const double delta=glm::degrees(double(std::atan2(glm::dot(arc.tangent,glm::cross(bendPanel_.grabOffset,radial)),glm::dot(bendPanel_.grabOffset,radial))));
            const double divisor=toolConfig_.twistAmountMode()==nadoc_vr::TwistAmountMode::total_degrees?1:
                (*toolConfig_.planeBBp()-double(*toolConfig_.planeABp()))*.334;
            (void)toolConfig_.setTwist(toolConfig_.twistAmount()+delta/divisor);
            bendPanel_.grabOffset=radial;refreshExtrudePanel();return;
        }
        if(!bendReady() || bendPanel_.pickSlot)return;
        for(size_t h=0;h<2;++h)if(!blocked[h] && hands_[h].valid && triggerClicked_[h] &&
            glm::distance(hands_[h].position,glm::vec3(model*glm::vec4(twistHandle(1),1)))<.055F) {
            bendPanel_.hand=h;bendPanel_.grabbed=1;bendPanel_.startModel=model;
            auto radial=glm::vec3(glm::inverse(model)*glm::vec4(hands_[h].position,1))-bendPanel_.arc.b;
            radial-=bendPanel_.arc.tangent*glm::dot(radial,bendPanel_.arc.tangent);
            if(glm::length(radial)<1e-6F){bendPanel_.hand.reset();return;}
            bendPanel_.grabOffset=glm::normalize(radial);blocked[h]=true;pulse(h,.35F);return;
        }
    }
    void processBendHandles(std::array<bool,2>& blocked,bool sceneMoving) {
        nadoc_vr::CalculationScope auditScope("processBendHandles");
        if(bendPanel_.active && bendPanel_.twist){processTwistHandle(blocked,sceneMoving);return;}
        if(!bendPanel_.active || bendPanel_.selecting || !bendPanel_.manual)return;
        if(sceneMoving || toolShell_.executionPending() || viewTools_.inspectionLayout()) {
            if(bendPanel_.hand) {bendPanel_.hand.reset();publishToolConfiguration();}
            return;
        }
        prepareBendArc();
        const auto model=manipulator_.transform();
        if(bendPanel_.hand) {
            const size_t h=*bendPanel_.hand;blocked[h]=true;
            if(!hands_[h].valid || model!=bendPanel_.startModel) {bendPanel_.hand.reset();publishToolConfiguration();return;}
            if(!triggerPressed_[h]) {
                bendPanel_.hand.reset();publishToolConfiguration();return;
            }
            if(bendPanel_.wheelHand)return; // The other hand may tune the live preview.
            const auto contact=hands_[h].position+hands_[h].orientation*glm::vec3(0,0,-bendPanel_.grabRayDistance);
            bendPanel_.beamEnd[h]=contact;bendPanel_.planeHover[h]=bendPanel_.grabbed;
            auto target=glm::vec3(glm::inverse(model)*glm::vec4(contact,1))+bendPanel_.grabOffset;
            auto& arc=bendPanel_.arc;
            arc.move(bendPanel_.grabbed,target);
            const auto transverse=(arc.b-arc.a)-arc.tangent*glm::dot(arc.b-arc.a,arc.tangent);
            double direction=toolConfig_.bendDirectionDegrees();
            if(glm::length(transverse)>1e-6F) {
                const auto x=arc.referenceDirection();
                const auto y=glm::cross(arc.tangent,x);
                direction=std::fmod(glm::degrees(double(std::atan2(glm::dot(transverse,y),glm::dot(transverse,x))))+360.0,360.0);
                arc.direction=glm::normalize(transverse);
            }
            bendPanel_.posed=true;
            (void)toolConfig_.setBend(glm::degrees(double(arc.angle)),direction);
            refreshExtrudePanel();
            return;
        }
        if(!bendReady() || bendPanel_.pickSlot || bendPanel_.arc.length<=0)return;
        float best=10;size_t end=0,h=0;bool found=false;glm::vec3 contact{};
        for(size_t j=0;j<2;++j)if(!blocked[j] && triggerClicked_[j])if(const auto hit=bendPlaneHit(j)) {
            if(selectedSelectionKind_!="cluster" && selectedSelectionKind_!="end" && hit->slot==0)continue;
            if(hit->distance<best){best=hit->distance;end=hit->slot;h=j;contact=hit->point;found=true;}
        }
        if(found) {
            // Switching ends starts a new bend. The previously moved endpoint
            // returns to its original plane before becoming the fixed anchor.
            if(bendPanel_.posed && bendPanel_.grabbed!=end) {
                resetBendToPlanes();publishToolConfiguration();
            }
            bendPanel_.hand=h;bendPanel_.grabbed=end;bendPanel_.startModel=model;
            if(!bendPanel_.posed) {
                bendPanel_.arc.fixedEnd=1-end;
                bendPanel_.arc.tangent=glm::normalize(planeGuides_[1-end]->natural.normal);
                bendPanel_.arc.direction=bendPanel_.arc.referenceDirection();
            }
            bendPanel_.grabRayDistance=best;
            bendPanel_.grabOffset=(end==0?bendPanel_.arc.a:bendPanel_.arc.b)-glm::vec3(glm::inverse(model)*glm::vec4(contact,1));
            blocked[h]=true;pulse(h,.35F);
        }
    }
    void processBendPlanePick(std::array<bool,2>& blocked) {
        if(!bendPanel_.active || bendPanel_.selecting || !bendPanel_.twist || toolShell_.executionPending() || bendPanel_.hand)return;
        if(bendPanel_.planeHand && (!hands_[*bendPanel_.planeHand].valid || !triggerPressed_[*bendPanel_.planeHand])) {
            bendPanel_.planeHand.reset();
            if(!activePlanePickSequence_) {
                if(planeGuides_[0] && planeGuides_[1])bendPanel_.pickSlot.reset();
                else if(planeGuides_[0])bendPanel_.pickSlot="b";
                else if(planeGuides_[1])bendPanel_.pickSlot="a";
            }
        }
        if(!bendPanel_.pickSlot)return;
        if(!bendPanel_.planeHand)for(size_t h=0;h<2;++h)
            if(!blocked[h] && hands_[h].valid && triggerClicked_[h]) {bendPanel_.planeHand=h;break;}
        if(!bendPanel_.planeHand)return;
        const size_t h=*bendPanel_.planeHand;
        if(blocked[h])return;
        blocked[h]=true;
        if(snapSelectionHits_[h].empty() || activePlanePickSequence_)return;
        const auto& hit=snapSelectionHits_[h].front();
        // Selection acknowledgement must bind the target before a plane request.
        if(!glScene_->belongsToSelection(hit.identity,committedSelectionOwnerTokens_))return;
        bendPanel_.pendingSelection.clear();
        const auto local=glm::vec3(glm::inverse(manipulator_.transform())*glm::vec4(selectionVolumeCenter(h),1));
        const auto source=(local-glm::vec3(0,0,-kViewDistanceMeters))/normalizationScale_+normalizationCenter_;
        if(hit.identity==bendPanel_.lastPick && bendPickPosition_ && glm::distance(source,*bendPickPosition_)<.167F)return;
        bendPickPosition_=source;
        bendPanel_.lastPick=hit.identity;
        planePickSlot_=bendPanel_.pickSlot;
        publishPlanePick(hit.identity);
    }
    template<class Line> void drawBend(Line line) {
        if(!bendPanel_.active)return;
        prepareBendArc();
        for(size_t h=0;h<2;++h)if(bendPanel_.beamEnd[h])line(hands_[h].position,*bendPanel_.beamEnd[h],glm::vec3(.3F,1.F,1.F));
        const auto& menu=sidebarMenus_.menus[1];
        if(menu.open)for(const auto& c:menu.controls()) {
            if(c.id=="twist:amount") {
                const float x=c.bounds.maximum.x-.018F,y=(c.bounds.minimum.y+c.bounds.maximum.y)*.5F;
                for(int i=-3;i<=3;++i)line(menu.placement.worldPoint({x-.023F,y+i*.011F,.007F}),menu.placement.worldPoint({x,y+i*.011F,.007F}),glm::vec3(.4F,.9F,1));
                continue;
            }
            if(!c.id.ends_with("-wheel"))continue;
            const size_t index=c.id=="bend:angle-wheel"?0:c.id=="bend:direction-wheel"?1:2;
            const auto& wheel=bendPanel_.wheels[index];
            const glm::vec3 color=bendPanel_.wheelHover[index] || wheel.dragging()?glm::vec3(1,.78F,.22F):wheel.moving()?glm::vec3(.38F,1,.58F):glm::vec3(.54F,.70F,.84F);
            const float left=c.bounds.minimum.x+.006F,right=c.bounds.maximum.x-.006F;
            const float y=(c.bounds.minimum.y+c.bounds.maximum.y)*.5F;
            const auto shape=nadoc_vr::thumbwheelPreset(100);
            solidWheels_.wheel(shape,wheel.phase(),{(left+right)*.5F,y,.012F},color,
                [&](auto p){return menu.placement.worldPoint(p);});
        }
        if(!planeGuides_[0] || !planeGuides_[1] || bendPanel_.arc.length<=0)return;
        const auto model=manipulator_.transform();
        auto world=[&](glm::vec3 p){return glm::vec3(model*glm::vec4(p,1));};
        const glm::vec3 color(.25F,1,.8F);
        if(bendPanel_.twist) {
            const auto& arc=bendPanel_.arc;
            auto point=[&](float t,float phase) {
                return glm::mix(arc.a,arc.b,t)+glm::angleAxis(glm::radians(float(toolConfig_.twistTotalDegrees()))*t+phase,arc.tangent)*arc.referenceDirection()*twistRadius();
            };
            for(float phase:{0.F,glm::pi<float>()})for(int i=0;i<192;++i)
                line(world(point(i/192.F,phase)),world(point((i+1)/192.F,phase)),color);
            for(size_t end=0;end<2;++end) {
                const auto center=world(twistHandle(end));
                line(world(end?arc.b:arc.a),center,color);
                for(int axis=0;axis<3;++axis)for(int i=0;i<32;++i) {
                    glm::vec3 a(0),b(0);float t=glm::two_pi<float>()*i/32,u=glm::two_pi<float>()*(i+1)/32;
                    a[(axis+1)%3]=std::cos(t)*.019F;a[(axis+2)%3]=std::sin(t)*.019F;
                    b[(axis+1)%3]=std::cos(u)*.019F;b[(axis+2)%3]=std::sin(u)*.019F;
                    line(center+a,center+b,bendPanel_.hand && end==1?glm::vec3(1,1,.2F):color);
                }
            }
            return;
        }
        for(int i=0;i<96;++i)line(world(bendPanel_.arc.point(i/96.F)),world(bendPanel_.arc.point((i+1)/96.F)),color);
        for(size_t end=0;end<2;++end) {
            const auto center=world(bendHandle(end));
            const auto face=world(end==0?bendPanel_.arc.a:bendPanel_.arc.b);
            line(face,center,color);
            // Three rings remain visible from every approach direction.
            for(int axis=0;axis<3;++axis)for(int i=0;i<24;++i) {
                glm::vec3 a(0),b(0);const float t=glm::two_pi<float>()*i/24.F,u=glm::two_pi<float>()*(i+1)/24.F;
                a[(axis+1)%3]=std::cos(t)*.019F;a[(axis+2)%3]=std::sin(t)*.019F;
                b[(axis+1)%3]=std::cos(u)*.019F;b[(axis+2)%3]=std::sin(u)*.019F;
                line(center+a,center+b,bendPanel_.hand && bendPanel_.grabbed==end?glm::vec3(1,1,.2F):color);
            }
        }
    }

    void processMoveInput(std::array<bool,2>& blocked,bool sceneMoving) {
        nadoc_vr::CalculationScope auditScope("processMoveInput");
        if(!movePanel_.active)return;
        if(moveAwaitRefresh_ && !toolShell_.executionPending() &&
           (sceneRefresh_.revision()>moveStartRevision_ || toolShell_.status()=="COMMIT FAILED" || toolShell_.status()=="COMMIT REFUSED"))moveAwaitRefresh_=false;
        movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());
        movePanel_.nearby.fill(false);movePanel_.beamEnd.reset();
        const auto center=glScene_->ownerHandle(selectedOwnerTokens_,manipulator_.transform());
        const bool available=center && !toolShell_.executionPending() && !moveAwaitRefresh_ &&
            nadoc_vr::ToolShell::selectionCapability(nadoc_vr::ToolMode::move_rotate,selectedSelectionKind_)==nadoc_vr::ToolCapability::direct_preview;
        if(movePanel_.hand) {
            const size_t h=*movePanel_.hand;blocked[h]=true;liveInputOwner_[h]="move-rotate";
            if(h!=nadoc_vr::MovePanel::moveHand || !hands_[h].valid || sessionState_!=XR_SESSION_STATE_FOCUSED || sceneMoving || !available || sceneRefresh_.revision()!=moveStartRevision_) {cancelMove();return;}
            const auto delta=movePanel_.delta(hands_[h]);
            if(delta!=pendingToolTransform_.transform()) {
                pendingToolTransform_.setTransform(delta);publishToolTransform();
            }
            movePanel_.beamEnd=glm::vec3(movePanel_.startModel*delta*glm::inverse(movePanel_.startModel)*glm::vec4(movePanel_.grabPoint,1));
            if(!triggerPressed_[h]) {
                const auto delta=poseMatrix(hands_[h])*glm::inverse(movePanel_.startHand);
                const float angle=glm::angle(glm::quat_cast(glm::mat3(delta)));
                if(glm::distance(hands_[h].position,glm::vec3(movePanel_.startHand[3]))<.004F && angle<glm::radians(1.5F))cancelMove();
                else confirmMove();
            }
        } else if(available && !sceneMoving) {
            constexpr size_t h=nadoc_vr::MovePanel::moveHand;
            if(hands_[h].valid && !blocked[h])
                movePanel_.beamEnd=glScene_->pickSelected({hands_[h].position,hands_[h].orientation*glm::vec3(0,0,-1)},manipulator_.transform(),selectedOwnerTokens_);
            movePanel_.nearby[h]=movePanel_.beamEnd.has_value();
            if(movePanel_.nearby[h] && triggerClicked_[h]) {
                pendingToolTransform_.activate();moveStartRevision_=sceneRefresh_.revision();
                toolShell_.apply(nadoc_vr::ToolAction::preview,selectedSelectionKind_);
                publishToolIntent(nadoc_vr::ToolAction::preview);
                movePanel_.grabPoint=*movePanel_.beamEnd;
                movePanel_.begin(h,hands_[h],manipulator_.transform(),*center);
                blocked[h]=true;liveInputOwner_[h]="move-rotate";pulse(h,.35F);
            }
        }
        const bool preview=toolShell_.previewRequested() &&
            (!toolShell_.executionPending() || sceneRefresh_.revision()==moveStartRevision_);
        glScene_->setMovePointPreview(preview?selectedOwnerTokens_:std::vector<std::string>{},pendingToolTransform_.transform());
    }

    void applyPendingRecenter(uint32_t viewCount) {
        if (!recenterRequested_ || viewCount == 0) return;
        glm::vec3 headPosition{};
        for (uint32_t i = 0; i < viewCount; ++i) {
            headPosition += glm::vec3(
                views_[i].pose.position.x,
                views_[i].pose.position.y,
                views_[i].pose.position.z);
        }
        headPosition /= static_cast<float>(viewCount);
        const XrQuaternionf& orientation = views_[0].pose.orientation;
        manipulator_.fitInView(
            headPosition, {orientation.w, orientation.x, orientation.y, orientation.z},
            (viewTools_.flags&2048)?viewTools_.sceneBounds():glScene_->ownerBounds({}, glm::mat4(1.0F), true));
        shadowLight_.anchor({orientation.w, orientation.x, orientation.y, orientation.z});
        if (witness_) witnessShadowLight_.anchor(witness_->input().head.orientation);
        pulse(recenterHand_, 0.55F);
        recenterRequested_ = false;
        updateControllerGuides();
    }

    void applyInitialScenePlacement(uint32_t viewCount, bool fullyTracked) {
        if ((!initialScenePlacementRequested_ && !initialRoomPlacementRequested_) || viewCount == 0) return;
        if(startup_.active && startup_.completedAt<0)return;
        if (!fullyTracked) {
            initialPlacementGate_.observe(false, false, 0.0F, 0.0F);
            initialPlacementCandidateInitialized_ = false;
            return;
        }
        glm::vec3 headPosition{};
        nadoc_vr::ScenePlacementView targetView = initialScenePlacementRequested_
            ? sceneViewPlacement_.view : nadoc_vr::ScenePlacementView::head;
        if (targetView == nadoc_vr::ScenePlacementView::mirror) {
            targetView = mirrorEye_ == nadoc_vr::SpectatorMirrorEye::right
                ? nadoc_vr::ScenePlacementView::right
                : nadoc_vr::ScenePlacementView::left;
        }
        uint32_t orientationView = 0U;
        if (targetView == nadoc_vr::ScenePlacementView::head) {
            for (uint32_t i = 0; i < viewCount; ++i) {
                headPosition += glm::vec3(
                    views_[i].pose.position.x,
                    views_[i].pose.position.y,
                    views_[i].pose.position.z);
            }
            headPosition /= static_cast<float>(viewCount);
        } else {
            orientationView = targetView == nadoc_vr::ScenePlacementView::right
                ? 1U : 0U;
            if (orientationView >= viewCount) return;
            headPosition = glm::vec3(
                views_[orientationView].pose.position.x,
                views_[orientationView].pose.position.y,
                views_[orientationView].pose.position.z);
        }
        const XrQuaternionf& orientation =
            views_[orientationView].pose.orientation;
        const glm::quat headOrientation = glm::normalize(glm::quat(
            orientation.w, orientation.x, orientation.y, orientation.z));
        float translationMeters = 0.0F;
        float rotationDegrees = 0.0F;
        if (initialPlacementCandidateInitialized_) {
            translationMeters = glm::length(
                headPosition - initialPlacementCandidatePosition_);
            const float orientationDot = glm::clamp(
                std::abs(glm::dot(
                    headOrientation, initialPlacementCandidateOrientation_)),
                0.0F, 1.0F);
            rotationDegrees = glm::degrees(2.0F * std::acos(orientationDot));
        }
        const bool stable = initialPlacementGate_.observe(
            true, initialPlacementCandidateInitialized_,
            translationMeters, rotationDegrees);
        initialPlacementCandidatePosition_ = headPosition;
        initialPlacementCandidateOrientation_ = headOrientation;
        initialPlacementCandidateInitialized_ = true;
        if (!stable) return;
        if(initialScenePlacementRequested_) {
            // Explicit inspector/capture placement remains an opt-in override.
            manipulator_.placeInView(headPosition, headOrientation, sceneViewPlacement_);
        } else {
            manipulator_.placeAtRoomOrigin(headPosition, headOrientation,
                roomFloor_.located?std::optional(roomFloor_.stageToLocal):std::nullopt,
                -normalizationCenter_*normalizationScale_+glm::vec3(0,0,-kViewDistanceMeters),
                sourceAxes_);
        }
        initialRoomPlacementRequested_=false;
        shadowLight_.anchor(headOrientation);
        if (witness_) witnessShadowLight_.anchor(witness_->input().head.orientation);
        initialScenePlacementApplied_ = true;
        initialScenePlacementRequested_ = false;
        updateControllerGuides();
        std::cout << "ScryWrite placement applied: view="
                  << nadoc_vr::scenePlacementViewName(sceneViewPlacement_.view)
                  << " orientation="
                  << nadoc_vr::scenePlacementOrientationName(
                         sceneViewPlacement_.orientation)
                  << " distance_m=" << sceneViewPlacement_.distanceMeters
                  << " scale=" << sceneViewPlacement_.scale
                  << " yaw=" << sceneViewPlacement_.yawDegrees
                  << " pitch=" << sceneViewPlacement_.pitchDegrees
                  << " roll=" << sceneViewPlacement_.rollDegrees
                  << " stable_samples=" << initialPlacementGate_.stableSamples
                  << std::endl;
    }

    [[nodiscard]] bool spectatorClassificationEnabled() const {
        if (liveSocket_.enabled()) return true;
        return mirrorEye_ != nadoc_vr::SpectatorMirrorEye::off;
    }

    void setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass renderClass) const {
        if (!spectatorClassificationEnabled()) return;
        glEnable(GL_STENCIL_TEST);
        glStencilMask(0xFFU);
        glStencilFunc(
            GL_ALWAYS, static_cast<GLint>(renderClass), 0xFFU);
        glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
    }

    void finishSpectatorClassification() const {
        if (!spectatorClassificationEnabled()) return;
        glStencilMask(0xFFU);
        glDisable(GL_STENCIL_TEST);
    }

    void renderMenuSurface(const glm::mat4& viewProjection) {
        componentGallery_.render(viewProjection);
        solidWheels_.render(viewProjection);
        menuGlass_.capture();
        sidebarMenus_.render(viewProjection);
        routingPopup_.render(viewProjection);
        if(latticeOpen_) latticePanelSurface_.render(viewProjection,latticePlacement_,kLatticePanelBounds);
        viewTools_.renderPanel(viewProjection);
        if(desktopPanel_.open) {
            const auto b=desktopPanel_.content();const auto& p=desktopPanel_.placement;
            desktopSurface_.render(viewProjection,{{p.worldPoint({b.minimum.x,b.maximum.y,.004F}),
                p.worldPoint({b.minimum.x,b.minimum.y,.004F}),p.worldPoint({b.maximum.x,b.maximum.y,.004F}),
                p.worldPoint({b.maximum.x,b.minimum.y,.004F})}},desktopPanel_.magnifying);
            desktopFrameSurface_.render(viewProjection,p,desktopPanel_.chromeBounds(),.008F);
        }
    }

    bool bendPointPreviewActive() const {
        return bendPanel_.active && !bendPanel_.selecting &&
            !bendPanel_.defaultPlanes && !bendPanel_.pickSlot && !activePlanePickSequence_ &&
            bendPanel_.pendingSelection.empty() && planeGuides_[0] && planeGuides_[1] &&
            toolConfig_.planeABp() && toolConfig_.planeBBp() &&
            *toolConfig_.planeABp()<*toolConfig_.planeBBp() &&
            !viewTools_.overrideScene() && !toolShell_.executionPending();
    }
    void renderVolumeScene(const glm::mat4& vp,const glm::mat4& model,const std::vector<Vertex>& guides,bool ids=false) {
        if(placementIntegrity_.blocked())return;
        auto arc=bendPanel_.arc;
        if(bendPanel_.twist)arc.angle=glm::radians(float(toolConfig_.twistTotalDegrees()));
        glScene_->setBendPointArc(bendPointPreviewActive()?std::optional{arc}:std::nullopt,bendPanel_.twist);
        if(viewTools_.overrideScene()) {viewTools_.renderScene(vp,model,witnessObserverOrientation_);if(!guides.empty())glScene_->renderGuides(vp,guides);}
        else glScene_->renderVolumes(vp,model,guides,ids,volumePanel_.entries,representationLoading_.pending && representationLoading_.lightweight);
    }

    bool renderView(uint32_t index, const XrView& view,
                    XrCompositionLayerProjectionView& layerView) {
        Swapchain& swapchain = swapchains_[index];
        uint32_t imageIndex = 0;
        XrSwapchainImageAcquireInfo acquireInfo{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
        frameAudit_.mark("eye_setup");
        checkXr(instance_, xrAcquireSwapchainImage(
            swapchain.handle, &acquireInfo, &imageIndex), "xrAcquireSwapchainImage");
        XrSwapchainImageWaitInfo waitInfo{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
        waitInfo.timeout = XR_INFINITE_DURATION;
        checkXr(instance_, xrWaitSwapchainImage(
            swapchain.handle, &waitInfo), "xrWaitSwapchainImage");
        traceRender("swapchain_wait");

        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer_);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               swapchain.images[imageIndex].image, 0);
        glFramebufferRenderbuffer(
            GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER,
            swapchain.depth);
        const bool captureIds = liveCapturePending_.has_value();
        if (captureIds) {
            if (!liveObjectIdTexture_) glGenTextures(1, &liveObjectIdTexture_);
            glBindTexture(GL_TEXTURE_2D, liveObjectIdTexture_);
            if (liveObjectIdWidth_ != swapchain.width || liveObjectIdHeight_ != swapchain.height) {
                glTexImage2D(GL_TEXTURE_2D, 0, GL_R32UI, swapchain.width, swapchain.height,
                             0, GL_RED_INTEGER, GL_UNSIGNED_INT, nullptr);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
                liveObjectIdWidth_ = swapchain.width;
                liveObjectIdHeight_ = swapchain.height;
            }
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                                   GL_TEXTURE_2D, liveObjectIdTexture_, 0);
            const GLenum buffers[] = {GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1};
            glDrawBuffers(2, buffers);
            const GLuint zero[] = {0, 0, 0, 0};
            glClearBufferuiv(GL_COLOR, 1, zero);
            glDrawBuffer(GL_COLOR_ATTACHMENT0);
        }
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("OpenXR framebuffer is incomplete");
        }
        glViewport(0, 0, swapchain.width, swapchain.height);
        glClearColor(0.015F, 0.025F, 0.045F, 1.0F);
        GLbitfield clearMask = GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT;
        if (spectatorClassificationEnabled()) {
            glStencilMask(0xFFU);
            glClearStencil(static_cast<GLint>(
                nadoc_vr::SpectatorRenderClass::background));
            clearMask |= GL_STENCIL_BUFFER_BIT;
        }
        glClear(clearMask);
        const glm::mat4 projection = projectionFromFov(view.fov, kNearMeters, kFarMeters);
        const glm::mat4 viewProjection = projection * viewFromPose(view.pose);
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::reference_grid);
        roomFloor_.render(viewProjection);
        qrCalibration_.render(viewProjection,witnessObserverPosition_,witnessObserverOrientation_);
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::design);
        if (!liveSceneHidden_) renderVolumeScene(
            viewProjection, manipulator_.transform(),
            spectatorClassificationEnabled()
                ? std::vector<Vertex>{} : controllerGuides_, captureIds);
        if (spectatorClassificationEnabled()) {
            setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
            glScene_->renderGuides(viewProjection, controllerGuides_, &controllerHandEnds_);
        }
        if (referenceGrid_) {
            setSpectatorRenderClass(
                nadoc_vr::SpectatorRenderClass::reference_grid);
            glScene_->renderGuides(viewProjection, referenceGridGuides_);
        }
        if (componentGallery_.active || latticeOpen_ || sidebarMenus_.anyOpen() || viewTools_.open || desktopPanel_.open) {
            setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
            renderMenuSurface(viewProjection);
        }
        if (witness_) {
            setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
            witnessSurface_.renderPanel(
                viewProjection, witnessObserverPosition_, witnessObserverOrientation_);
        }
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
        glScene_->renderGuides(viewProjection, controllerPathGuides_);
        for(size_t pass=0;pass<3;++pass) {
            const size_t trace=pass==1 ? 1 : 0;
            setSpectatorRenderClass(trace ? nadoc_vr::SpectatorRenderClass::contact_actual : nadoc_vr::SpectatorRenderClass::contact_intended);
            // Opt-in surface diagnostics stay legible over frosted panels and
            // over one another; ordinary controllers retain physical depth.
            glScene_->renderGuides(viewProjection, controllerContactGuides_[trace], nullptr,
                pass==0 ? 17.0F : pass==1 ? 9.0F : 3.0F, false, false);
        }
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
        XrPosef head=views_[0].pose;
        if(views_.size()>1) {
            head.position.x=(head.position.x+views_[1].pose.position.x)*.5F;
            head.position.y=(head.position.y+views_[1].pose.position.y)*.5F;
            head.position.z=(head.position.z+views_[1].pose.position.z)*.5F;
        }
        startup_.render(viewProjection, head);
        representationLoading_.render(viewProjection, head);
        placementFailurePopup_.render(viewProjection, head, false, true);
        traceRender("eye_draw");
        captureLiveEye(index, view, swapchain.width, swapchain.height);
        liveMeasure_.readEye(index, swapchain.width, swapchain.height);
        if (captureIds) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, 0, 0);
        }
        traceRender("capture");
        presentSpectatorMirror(index, view, swapchain.width, swapchain.height);
        traceRender("mirror");
        finishSpectatorClassification();
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glFlush();

        XrSwapchainImageReleaseInfo releaseInfo{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
        checkXr(instance_, xrReleaseSwapchainImage(
            swapchain.handle, &releaseInfo), "xrReleaseSwapchainImage");

        layerView = {XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW};
        layerView.pose = view.pose;
        layerView.fov = view.fov;
        layerView.subImage.swapchain = swapchain.handle;
        layerView.subImage.imageRect.offset = {0, 0};
        layerView.subImage.imageRect.extent = {swapchain.width, swapchain.height};
        return true;
    }

    void updateSpectatorTelemetry(const XrView& view, bool submittedEye) {
        ++mirrorFrameSequence_;
        const glm::vec3 position(
            view.pose.position.x, view.pose.position.y, view.pose.position.z);
        const glm::quat orientation = glm::normalize(glm::quat(
            view.pose.orientation.w, view.pose.orientation.x,
            view.pose.orientation.y, view.pose.orientation.z));
        const XrViewStateFlags validFlags = XR_VIEW_STATE_POSITION_VALID_BIT |
                                            XR_VIEW_STATE_ORIENTATION_VALID_BIT;
        const XrViewStateFlags trackedFlags = XR_VIEW_STATE_POSITION_TRACKED_BIT |
                                              XR_VIEW_STATE_ORIENTATION_TRACKED_BIT;
        const bool poseValid = (currentViewStateFlags_ & validFlags) == validFlags;
        const bool poseTracked = (currentViewStateFlags_ & trackedFlags) == trackedFlags;
        if (!mirrorSourceInitialized_ || submittedEye != lastMirrorSubmittedEye_) {
            mirrorSourceInitialized_ = true;
            lastMirrorSubmittedEye_ = submittedEye;
            std::cout << "NADOC VR mirror source: "
                      << (submittedEye
                              ? "SUBMITTED EYE (runtime accepted HMD rendering)"
                              : "SPECTATOR FALLBACK (runtime suppressed HMD rendering)")
                      << std::endl;
        }
        if (!mirrorPoseInitialized_) {
            mirrorPoseInitialized_ = true;
            lastMirrorMotionPosition_ = position;
            lastMirrorMotionOrientation_ = orientation;
            lastMirrorPoseTracked_ = poseTracked;
            std::cout << "NADOC VR mirror pose: "
                      << (poseTracked ? "TRACKED" : "VALID BUT NOT TRACKED")
                      << " XYZ=" << position.x << ',' << position.y << ',' << position.z
                      << '\n';
        } else {
            const float positionDelta = glm::length(position - lastMirrorMotionPosition_);
            const float orientationDot = glm::clamp(
                std::abs(glm::dot(orientation, lastMirrorMotionOrientation_)),
                0.0F, 1.0F);
            const float angleDeltaDegrees = glm::degrees(2.0F * std::acos(orientationDot));
            const bool moved = positionDelta >= 0.005F || angleDeltaDegrees >= 0.5F;
            const bool trackingChanged = poseTracked != lastMirrorPoseTracked_;
            if ((moved || trackingChanged) &&
                mirrorFrameSequence_ >= lastMirrorMotionLogFrame_ + 15U) {
                ++mirrorMotionSequence_;
                lastMirrorMotionLogFrame_ = mirrorFrameSequence_;
                lastMirrorMotionPosition_ = position;
                lastMirrorMotionOrientation_ = orientation;
                lastMirrorPoseTracked_ = poseTracked;
                std::cout << "NADOC VR mirror motion M" << mirrorMotionSequence_
                          << ": " << (poseTracked ? "TRACKED" : "NOT TRACKED")
                          << " d=" << positionDelta << " m, a="
                          << angleDeltaDegrees << " deg, XYZ="
                          << position.x << ',' << position.y << ',' << position.z << '\n';
            }
        }
        if (mirrorFrameSequence_ == 1U || mirrorFrameSequence_ % 15U == 0U) {
            const glm::vec3 forward = orientation * glm::vec3(0.0F, 0.0F, -1.0F);
            nadoc_vr::SpectatorMirrorTelemetry telemetry;
            telemetry.frame = mirrorFrameSequence_;
            telemetry.motion = mirrorMotionSequence_;
            telemetry.poseValid = poseValid;
            telemetry.poseTracked = poseTracked;
            telemetry.submittedEye = submittedEye;
            telemetry.x = position.x;
            telemetry.y = position.y;
            telemetry.z = position.z;
            telemetry.yawDegrees = glm::degrees(std::atan2(forward.x, -forward.z));
            telemetry.pitchDegrees = glm::degrees(std::asin(glm::clamp(
                forward.y, -1.0F, 1.0F)));
            telemetry.pixelSample = mirrorPixelSampleSequence_;
            telemetry.pixelStatus = mirrorPixelAssessment_.status;
            telemetry.coverageStatus = mirrorCoverageAssessment_.status;
            telemetry.placementApplied = initialScenePlacementApplied_;
            if (initialScenePlacementApplied_) {
                telemetry.placementOrientation =
                    nadoc_vr::scenePlacementOrientationName(
                        sceneViewPlacement_.orientation);
                std::transform(
                    telemetry.placementOrientation.begin(),
                    telemetry.placementOrientation.end(),
                    telemetry.placementOrientation.begin(),
                    [](unsigned char character) {
                        return static_cast<char>(std::toupper(character));
                    });
            }
            telemetry.nonBlackFraction = mirrorPixelAssessment_.nonBlackFraction;
            telemetry.changedFraction = mirrorPixelAssessment_.changedFraction;
            const std::string title = nadoc_vr::spectatorMirrorTelemetryTitle(
                mirrorEye_, referenceGrid_, telemetry);
            glfwSetWindowTitle(window_, title.c_str());
        }
    }

    void sampleSpectatorPixels(
        const XrView& view, bool submittedEye,
        const nadoc_vr::SpectatorMirrorViewport& viewport,
        GLuint classificationFramebuffer,
        const nadoc_vr::SpectatorMirrorViewport& classificationViewport) {
        if (!mirrorDiagnosticsFramebuffer_ ||
            mirrorFrameSequence_ % kMirrorDiagnosticIntervalFrames != 0U) {
            return;
        }
        const auto sampleStarted = std::chrono::steady_clock::now();

        std::vector<uint8_t> pixels(
            static_cast<size_t>(kMirrorDiagnosticSize) * kMirrorDiagnosticSize * 4U);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        glReadBuffer(GL_BACK);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, mirrorDiagnosticsFramebuffer_);
        glBlitFramebuffer(
            viewport.x, viewport.y,
            viewport.x + viewport.width, viewport.y + viewport.height,
            0, 0, kMirrorDiagnosticSize, kMirrorDiagnosticSize,
            GL_COLOR_BUFFER_BIT, GL_LINEAR);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, mirrorDiagnosticsFramebuffer_);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        glReadPixels(
            0, 0, kMirrorDiagnosticSize, kMirrorDiagnosticSize,
            GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());

        std::vector<uint8_t> renderClasses(
            static_cast<size_t>(kMirrorDiagnosticSize) * kMirrorDiagnosticSize);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, classificationFramebuffer);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, mirrorDiagnosticsFramebuffer_);
        glBlitFramebuffer(
            classificationViewport.x, classificationViewport.y,
            classificationViewport.x + classificationViewport.width,
            classificationViewport.y + classificationViewport.height,
            0, 0, kMirrorDiagnosticSize, kMirrorDiagnosticSize,
            GL_STENCIL_BUFFER_BIT, GL_NEAREST);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, mirrorDiagnosticsFramebuffer_);
        glReadPixels(
            0, 0, kMirrorDiagnosticSize, kMirrorDiagnosticSize,
            GL_STENCIL_INDEX, GL_UNSIGNED_BYTE, renderClasses.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glReadBuffer(GL_BACK);

        const glm::vec3 position(
            view.pose.position.x, view.pose.position.y, view.pose.position.z);
        const glm::quat orientation = glm::normalize(glm::quat(
            view.pose.orientation.w, view.pose.orientation.x,
            view.pose.orientation.y, view.pose.orientation.z));
        const bool comparable = mirrorPixelPoseInitialized_ &&
                                submittedEye == previousMirrorPixelSubmittedEye_;
        float translationMeters = 0.0F;
        float rotationDegrees = 0.0F;
        if (comparable) {
            translationMeters = glm::length(position - previousMirrorPixelPosition_);
            const float orientationDot = glm::clamp(
                std::abs(glm::dot(orientation, previousMirrorPixelOrientation_)),
                0.0F, 1.0F);
            rotationDegrees = glm::degrees(2.0F * std::acos(orientationDot));
        }
        const std::vector<uint8_t>* previous = comparable
            ? &previousMirrorPixels_ : nullptr;
        mirrorPixelAssessment_ = nadoc_vr::assessSpectatorPixels(
            pixels, previous, translationMeters, rotationDegrees);
        mirrorCoverageAssessment_ =
            nadoc_vr::assessSpectatorCoverage(renderClasses);
        ++mirrorPixelSampleSequence_;
        const double sampleCpuMilliseconds =
            std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - sampleStarted).count();

        const bool unhealthy =
            mirrorPixelAssessment_.status == nadoc_vr::SpectatorPixelStatus::black ||
            mirrorPixelAssessment_.status ==
                nadoc_vr::SpectatorPixelStatus::frozen_suspected ||
            mirrorCoverageAssessment_.status ==
                nadoc_vr::SpectatorCoverageStatus::grid_only ||
            mirrorCoverageAssessment_.status ==
                nadoc_vr::SpectatorCoverageStatus::no_tags;
        const bool statusChanged =
            mirrorPixelAssessment_.status != lastLoggedMirrorPixelStatus_ ||
            mirrorCoverageAssessment_.status != lastLoggedMirrorCoverageStatus_;
        if (statusChanged || mirrorPixelSampleSequence_ == 1U ||
            (unhealthy &&
             mirrorFrameSequence_ >= lastMirrorPixelWarningFrame_ + 90U)) {
            if (unhealthy) lastMirrorPixelWarningFrame_ = mirrorFrameSequence_;
            lastLoggedMirrorPixelStatus_ = mirrorPixelAssessment_.status;
            lastLoggedMirrorCoverageStatus_ = mirrorCoverageAssessment_.status;
            std::cout << "NADOC VR mirror pixels P" << mirrorPixelSampleSequence_
                      << ": " << nadoc_vr::spectatorPixelStatusName(
                             mirrorPixelAssessment_.status)
                      << " source=" << (submittedEye ? "SUBMITTED" : "FALLBACK")
                      << " F=" << mirrorFrameSequence_
                      << " nonblack=" << mirrorPixelAssessment_.nonBlackFraction
                      << " changed=" << mirrorPixelAssessment_.changedFraction
                      << " coverage=" << nadoc_vr::spectatorCoverageStatusName(
                             mirrorCoverageAssessment_.status)
                      << " design=" << mirrorCoverageAssessment_.designFraction
                      << " grid=" << mirrorCoverageAssessment_.gridFraction
                      << " overlay=" << mirrorCoverageAssessment_.overlayFraction
                      << " pose_d=" << translationMeters
                      << " pose_a=" << rotationDegrees
                      << " cpu_ms=" << sampleCpuMilliseconds << std::endl;
        }

        if (mirrorDiagnosticsOutput_) {
            const auto timestampMilliseconds =
                std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
            mirrorDiagnosticsOutput_
                << "{\"sample\":" << mirrorPixelSampleSequence_
                << ",\"frame\":" << mirrorFrameSequence_
                << ",\"timestamp_ms\":" << timestampMilliseconds
                << ",\"openxr_predicted_display_time\":"
                << currentPredictedDisplayTime_
                << ",\"source\":\""
                << (submittedEye ? "submitted" : "spectator_fallback")
                << "\",\"status\":\""
                << nadoc_vr::spectatorPixelStatusName(mirrorPixelAssessment_.status)
                << "\",\"signature\":" << mirrorPixelAssessment_.signature
                << ",\"mean_luminance\":" << mirrorPixelAssessment_.meanLuminance
                << ",\"nonblack_fraction\":"
                << mirrorPixelAssessment_.nonBlackFraction
                << ",\"changed_fraction\":"
                << mirrorPixelAssessment_.changedFraction
                << ",\"classification_status\":\""
                << nadoc_vr::spectatorCoverageStatusName(
                       mirrorCoverageAssessment_.status)
                << "\",\"design_pixels\":"
                << mirrorCoverageAssessment_.designPixels
                << ",\"grid_pixels\":" << mirrorCoverageAssessment_.gridPixels
                << ",\"overlay_pixels\":"
                << mirrorCoverageAssessment_.overlayPixels
                << ",\"unknown_class_pixels\":"
                << mirrorCoverageAssessment_.unknownPixels
                << ",\"design_fraction\":"
                << mirrorCoverageAssessment_.designFraction
                << ",\"grid_fraction\":"
                << mirrorCoverageAssessment_.gridFraction
                << ",\"overlay_fraction\":"
                << mirrorCoverageAssessment_.overlayFraction
                << ",\"pose_translation_m\":" << translationMeters
                << ",\"pose_rotation_deg\":" << rotationDegrees
                << ",\"readback_cpu_ms\":" << sampleCpuMilliseconds
                << ",\"pose_moved\":"
                << (mirrorPixelAssessment_.poseMoved ? "true" : "false")
                << ",\"room_grid\":" << (referenceGrid_ ? "true" : "false")
                << ",\"placement_enabled\":"
                << (initialScenePlacementEnabled_ ? "true" : "false")
                << ",\"placement_applied\":"
                << (initialScenePlacementApplied_ ? "true" : "false")
                << ",\"placement_view\":\""
                << nadoc_vr::scenePlacementViewName(sceneViewPlacement_.view)
                << "\",\"placement_orientation\":\""
                << nadoc_vr::scenePlacementOrientationName(
                       sceneViewPlacement_.orientation)
                << "\",\"placement_distance_m\":"
                << sceneViewPlacement_.distanceMeters
                << ",\"placement_scale\":" << sceneViewPlacement_.scale
                << ",\"placement_yaw_deg\":"
                << sceneViewPlacement_.yawDegrees
                << ",\"placement_pitch_deg\":"
                << sceneViewPlacement_.pitchDegrees
                << ",\"placement_roll_deg\":"
                << sceneViewPlacement_.rollDegrees
                << "}\n";
            mirrorDiagnosticsOutput_.flush();
        }

        previousMirrorPixels_ = std::move(pixels);
        previousMirrorPixelPosition_ = position;
        previousMirrorPixelOrientation_ = orientation;
        previousMirrorPixelSubmittedEye_ = submittedEye;
        mirrorPixelPoseInitialized_ = true;
    }

    void finishSpectatorPresentation(
        const nadoc_vr::SpectatorMirrorViewport& viewport) {
        const GLboolean scissorEnabled = glIsEnabled(GL_SCISSOR_TEST);
        std::array<GLint, 4> previousScissor{};
        std::array<GLfloat, 4> previousClearColor{};
        glGetIntegerv(GL_SCISSOR_BOX, previousScissor.data());
        glGetFloatv(GL_COLOR_CLEAR_VALUE, previousClearColor.data());
        glEnable(GL_SCISSOR_TEST);
        glScissor(viewport.x + 12, viewport.y + 12, 18, 18);
        if (nadoc_vr::spectatorMirrorHeartbeatHigh(mirrorFrameSequence_)) {
            glClearColor(0.18F, 1.0F, 0.30F, 1.0F);
        } else {
            glClearColor(1.0F, 0.22F, 0.08F, 1.0F);
        }
        glClear(GL_COLOR_BUFFER_BIT);
        glScissor(previousScissor[0], previousScissor[1],
                  previousScissor[2], previousScissor[3]);
        if (scissorEnabled != GL_TRUE) glDisable(GL_SCISSOR_TEST);
        glClearColor(previousClearColor[0], previousClearColor[1],
                     previousClearColor[2], previousClearColor[3]);
        traceRender("mirror_blit");
        glfwSwapBuffers(window_);
        traceRender("mirror_swap");
    }

    void presentSpectatorMirror(
        uint32_t viewIndex, const XrView& view,
        int32_t sourceWidth, int32_t sourceHeight) {
        const auto selected = nadoc_vr::spectatorMirrorViewIndex(
            mirrorEye_, static_cast<uint32_t>(swapchains_.size()));
        if (!selected || *selected != viewIndex) return;
        updateSpectatorTelemetry(view, true);
        int destinationWidth = 0;
        int destinationHeight = 0;
        glfwGetFramebufferSize(window_, &destinationWidth, &destinationHeight);
        const auto viewport = nadoc_vr::fitSpectatorMirrorViewport(
            sourceWidth, sourceHeight, destinationWidth, destinationHeight);
        if (viewport.width <= 0 || viewport.height <= 0) return;

        std::array<GLfloat, 4> previousClearColor{};
        glGetFloatv(GL_COLOR_CLEAR_VALUE, previousClearColor.data());
        glDisable(GL_SCISSOR_TEST);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, framebuffer_);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glClearColor(0.0F, 0.0F, 0.0F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT);
        glBlitFramebuffer(
            0, 0, sourceWidth, sourceHeight,
            viewport.x, viewport.y,
            viewport.x + viewport.width, viewport.y + viewport.height,
            GL_COLOR_BUFFER_BIT, GL_LINEAR);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glClearColor(previousClearColor[0], previousClearColor[1],
                     previousClearColor[2], previousClearColor[3]);
        sampleSpectatorPixels(
            view, true, viewport, framebuffer_,
            {0, 0, sourceWidth, sourceHeight});
        if (liveCapturePending_) liveMirrorCapture_.read(destinationWidth,destinationHeight,viewIndex,viewport);
        finishSpectatorPresentation(viewport);
    }

    void renderSpectatorFallback(uint32_t viewIndex, const XrView& view) {
        const auto selected = nadoc_vr::spectatorMirrorViewIndex(
            mirrorEye_, static_cast<uint32_t>(swapchains_.size()));
        if (!selected || *selected != viewIndex) return;
        int destinationWidth = 0;
        int destinationHeight = 0;
        glfwGetFramebufferSize(window_, &destinationWidth, &destinationHeight);
        const Swapchain& source = swapchains_[viewIndex];
        const auto viewport = nadoc_vr::fitSpectatorMirrorViewport(
            source.width, source.height, destinationWidth, destinationHeight);
        if (viewport.width <= 0 || viewport.height <= 0) return;

        updateSpectatorTelemetry(view, false);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glDisable(GL_SCISSOR_TEST);
        glViewport(0, 0, destinationWidth, destinationHeight);
        glClearColor(0.0F, 0.0F, 0.0F, 1.0F);
        glStencilMask(0xFFU);
        glClearStencil(static_cast<GLint>(
            nadoc_vr::SpectatorRenderClass::background));
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        glViewport(viewport.x, viewport.y, viewport.width, viewport.height);
        const glm::mat4 projection = projectionFromFov(
            view.fov, kNearMeters, kFarMeters);
        const glm::mat4 viewProjection = projection * viewFromPose(view.pose);
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::reference_grid);
        roomFloor_.render(viewProjection);
        qrCalibration_.render(viewProjection,witnessObserverPosition_,witnessObserverOrientation_);
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::design);
        if (!liveSceneHidden_) renderVolumeScene(
            viewProjection, manipulator_.transform(), {});
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
        glScene_->renderGuides(viewProjection, controllerGuides_, &controllerHandEnds_);
        if (referenceGrid_) {
            setSpectatorRenderClass(
                nadoc_vr::SpectatorRenderClass::reference_grid);
            glScene_->renderGuides(viewProjection, referenceGridGuides_);
        }
        if (componentGallery_.active || latticeOpen_ || sidebarMenus_.anyOpen() || viewTools_.open || desktopPanel_.open) {
            setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
            renderMenuSurface(viewProjection);
        }
        if (witness_) {
            setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
            witnessSurface_.renderPanel(
                viewProjection, witnessObserverPosition_, witnessObserverOrientation_);
        }
        setSpectatorRenderClass(nadoc_vr::SpectatorRenderClass::overlay);
        startup_.render(viewProjection, view.pose);
        representationLoading_.render(viewProjection, view.pose);
        placementFailurePopup_.render(viewProjection, view.pose, false, true);
        glScene_->renderGuides(viewProjection, controllerPathGuides_);
        for(size_t pass=0;pass<3;++pass) {
            const size_t trace=pass==1 ? 1 : 0;
            setSpectatorRenderClass(trace ? nadoc_vr::SpectatorRenderClass::contact_actual : nadoc_vr::SpectatorRenderClass::contact_intended);
            glScene_->renderGuides(viewProjection, controllerContactGuides_[trace], nullptr,
                pass==0 ? 17.0F : pass==1 ? 9.0F : 3.0F, false, false);
        }
        sampleSpectatorPixels(view, false, viewport, 0, viewport);
        finishSpectatorClassification();
        finishSpectatorPresentation(viewport);
    }

    void captureWitnessView() {
        if (!witness_) return;
        const auto& head = witness_->input().head;
        const glm::mat4 headTransform = glm::translate(glm::mat4(1.0F), head.position)
                                      * glm::toMat4(head.orientation);
        const glm::mat4 projection = glm::perspective(
            glm::radians(72.0F),
            static_cast<float>(nadoc_vr::scrywrite::WitnessSurface::kWidth) /
                nadoc_vr::scrywrite::WitnessSurface::kHeight,
            kNearMeters, kFarMeters);
        const glm::mat4 viewProjection = projection * glm::inverse(headTransform);
        witnessSurface_.beginCapture();
        const std::vector<Vertex> actorGuides(
            controllerGuides_.begin(),
            controllerGuides_.begin() + static_cast<std::ptrdiff_t>(
                std::min(witnessActorGuideCount_, controllerGuides_.size())));
        roomFloor_.render(viewProjection);
        qrCalibration_.render(viewProjection,witnessObserverPosition_,witnessObserverOrientation_);
        if (!liveSceneHidden_) renderVolumeScene(
            viewProjection, manipulator_.transform(),
            actorGuides);
        if (referenceGrid_) {
            glScene_->renderGuides(viewProjection, referenceGridGuides_);
        }
        renderMenuSurface(viewProjection);
        if (witness_->pendingSnapshot()) {
            const std::string name = witness_->pendingSnapshot()->name;
            if (witnessCaptureDirectory_.empty()) {
                witness_->rejectSnapshot(
                    "snapshot requires --witness-captures <directory>");
            } else {
                try {
                    const auto pixels = witnessSurface_.readRgb();
                    const std::optional<std::filesystem::path> expectations =
                        witnessVisualExpectationDirectory_.empty()
                            ? std::nullopt
                            : std::optional<std::filesystem::path>(
                                  witnessVisualExpectationDirectory_);
                    const nadoc_vr::scrywrite::ActorEyeSnapshotMetadata metadata{
                        name,
                        witness_->frame(),
                        witness_->currentLine(),
                        witness_->currentCommand(),
                        menuPageName(),
                        witnessHoverName(),
                        nadoc_vr::toolModeName(toolShell_.mode()),
                        toolShell_.status(),
                        combinedMenuLayoutStatus(),
                        sidebarMenus_.anyOpen() ? observedSidebar().audit.summary()
                                           : "layout not rendered yet",
                    };
                    const auto result = nadoc_vr::scrywrite::writeActorEyeCapture(
                        witnessCaptureDirectory_, name, pixels,
                        nadoc_vr::scrywrite::WitnessSurface::kWidth,
                        nadoc_vr::scrywrite::WitnessSurface::kHeight,
                        expectations, metadata);
                    if (result.comparison && !result.comparison->passed) {
                        std::ostringstream error;
                        error << "visual regression failed for " << name
                              << ": mean_abs="
                              << result.comparison->meanAbsoluteDifference
                              << ", changed_cells="
                              << result.comparison->changedCellFraction;
                        witness_->rejectSnapshot(error.str());
                    } else {
                        std::cout << "ScryWrite actor-eye snapshot "
                                  << result.pngPath << '\n';
                        witness_->resolveSnapshot();
                    }
                } catch (const std::exception& error) {
                    witness_->rejectSnapshot(error.what());
                }
            }
        }
        witnessSurface_.endCapture();
    }

    void renderFrame() {
        renderTrace_.begin(liveSocket_.enabled());
        frameAudit_.mark("render_setup");
        XrFrameWaitInfo waitInfo{XR_TYPE_FRAME_WAIT_INFO};
        XrFrameState frameState{XR_TYPE_FRAME_STATE};
        checkXr(instance_, xrWaitFrame(session_, &waitInfo, &frameState), "xrWaitFrame");
        traceRender("xr_wait");
        ++liveFrame_;
        currentPredictedDisplayTime_ = frameState.predictedDisplayTime;
        roomFloor_.update(session_,space_,frameState.predictedDisplayTime);
        qrCalibration_.update(roomFloor_.located?std::optional<glm::mat4>(roomFloor_.stageToLocal):std::nullopt);
        if(const auto position=qrCalibration_.takePosition()) {
            manipulator_.anchorOrigin(*position, -normalizationCenter_*normalizationScale_+glm::vec3(0,0,-kViewDistanceMeters));
            initialScenePlacementRequested_=false;
            initialRoomPlacementRequested_=false;
            recenterRequested_=false;
        }
        const auto frameStarted = std::chrono::steady_clock::now();
        XrFrameBeginInfo beginInfo{XR_TYPE_FRAME_BEGIN_INFO};
        checkXr(instance_, xrBeginFrame(session_, &beginInfo), "xrBeginFrame");
        if(!startup_.active && !placementIntegrity_.blocked()) syncActions(frameState.predictedDisplayTime);
        traceRender("input");
        const auto inputFinished = std::chrono::steady_clock::now();
        desktopSurface_.update(desktopPanel_.open);
        desktopPanel_.aspect=desktopSurface_.aspectRatio();

        std::vector<XrCompositionLayerProjectionView> layerViews(views_.size());
        XrCompositionLayerProjection layer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
        const XrCompositionLayerBaseHeader* layers[] = {
            reinterpret_cast<const XrCompositionLayerBaseHeader*>(&layer)};
        uint32_t layerCount = 0;

        const bool spectatorRequested =
            mirrorEye_ != nadoc_vr::SpectatorMirrorEye::off;
        if (frameState.shouldRender || spectatorRequested) {
            XrViewLocateInfo locateInfo{XR_TYPE_VIEW_LOCATE_INFO};
            locateInfo.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
            locateInfo.displayTime = frameState.predictedDisplayTime;
            locateInfo.space = space_;
            XrViewState viewState{XR_TYPE_VIEW_STATE};
            uint32_t viewCount = 0;
            checkXr(instance_, xrLocateViews(
                session_, &locateInfo, &viewState, static_cast<uint32_t>(views_.size()),
                &viewCount, views_.data()), "xrLocateViews");
            currentViewStateFlags_ = viewState.viewStateFlags;
            const bool completeViewSet = viewCount == views_.size();
            const bool positionValid = completeViewSet &&
                (viewState.viewStateFlags & XR_VIEW_STATE_POSITION_VALID_BIT) != 0;
            const bool orientationValid = completeViewSet &&
                (viewState.viewStateFlags & XR_VIEW_STATE_ORIENTATION_VALID_BIT) != 0;
            const bool positionTracked = completeViewSet &&
                (viewState.viewStateFlags & XR_VIEW_STATE_POSITION_TRACKED_BIT) != 0;
            const bool orientationTracked = completeViewSet &&
                (viewState.viewStateFlags & XR_VIEW_STATE_ORIENTATION_TRACKED_BIT) != 0;
            const bool validViewSet = positionValid && orientationValid;
            if(!validViewSet || !positionTracked || !orientationTracked)quiver_.reset();
            if (completeViewSet) {
                applyInitialScenePlacement(
                    viewCount, nadoc_vr::spectatorPoseReadyForPlacement(
                        positionValid, orientationValid,
                        positionTracked, orientationTracked));
                witnessObserverPosition_ = {};
                for (uint32_t index = 0; index < viewCount; ++index) {
                    witnessObserverPosition_ += glm::vec3(
                        views_[index].pose.position.x,
                        views_[index].pose.position.y,
                        views_[index].pose.position.z);
                }
                witnessObserverPosition_ /= static_cast<float>(viewCount);
                witnessObserverOrientation_ = glm::normalize(glm::quat(
                    views_[0].pose.orientation.w, views_[0].pose.orientation.x,
                    views_[0].pose.orientation.y, views_[0].pose.orientation.z));
                const bool quiverEnabled=validViewSet && positionTracked && orientationTracked &&
                    sessionState_==XR_SESSION_STATE_FOCUSED &&
                    !sidebarMenus_.menus[0].open && !sidebarMenus_.menus[1].open && !radialToolMenu_.open() &&
                    !ligation_.waiting && !endResize_.waitingVersion && !toolShell_.executionPending() &&
                    !ligation_.hand && !endResize_.hand && !movePanel_.active && !volumePanel_.active &&
                    !dimensionPanel_.tool.active && !latticeOpen_ &&
                    !triggerPartial_[0] && !triggerPartial_[1] && !gripPressed_[0] && !gripPressed_[1] &&
                    !trackpadPressed_[0] && !trackpadPressed_[1];
                if(const auto hand=quiver_.update(hands_,witnessObserverPosition_,witnessObserverOrientation_,
                        double(frameState.predictedDisplayTime)/1e9,quiverEnabled)) {
                    if(*hand==1)activateRadialEdit(1);
                    else viewTools_.toggle(hands_[*hand].position,hands_[*hand].orientation);
                    pulse(*hand,(*hand==1?ligation_.nickActive:viewTools_.open)?.55F:.25F);
                    updateControllerGuides();
                }
                const XrQuaternionf& head = views_[0].pose.orientation;
                const glm::quat headOrientation(head.w, head.x, head.y, head.z);
                if (frameState.shouldRender && validViewSet) {
                    applyPendingRecenter(viewCount);
                }
                const auto keyLight = shadowLight_.update(
                    headOrientation, validViewSet && orientationTracked);
                if (frameState.shouldRender && validViewSet) {
                    frameAudit_.mark("tracking_ui");
                    gpuFrameTimer_.begin(sidebarMenus_.anyOpen());
                    if (witness_) {
                        const auto actorKeyLight = witnessShadowLight_.update(
                            witness_->input().head.orientation);
                        if(!placementIntegrity_.blocked())glScene_->renderShadowMap(manipulator_.transform(), actorKeyLight);
                        captureWitnessView();
                    }
                    if(!placementIntegrity_.blocked() && !representationLoading_.lightweight)glScene_->renderShadowMap(manipulator_.transform(), keyLight);
                    traceRender("shadow");
                    for (uint32_t offset = 0; offset < viewCount; ++offset) {
                        const auto i=nadoc_vr::spectatorRenderViewIndex(mirrorEye_,offset,viewCount);
                        renderView(i, views_[i], layerViews[i]);
                    }
                    gpuFrameTimer_.end();
                    layer.space = space_;
                    layer.viewCount = viewCount;
                    layer.views = layerViews.data();
                    layerCount = 1;
                } else if (spectatorRequested) {
                    // Some runtimes stop requesting submitted frames when their
                    // proximity sensor considers a propped-up HMD unworn. They
                    // can still provide a live tracked eye pose. Draw that pose
                    // straight to the desktop and label it as a fallback so this
                    // is never confused with the actual submitted-eye image.
                    if (witness_) {
                        const auto actorKeyLight = witnessShadowLight_.update(
                            witness_->input().head.orientation);
                        if(!placementIntegrity_.blocked())glScene_->renderShadowMap(manipulator_.transform(), actorKeyLight);
                        captureWitnessView();
                    }
                    if(!placementIntegrity_.blocked() && !representationLoading_.lightweight)glScene_->renderShadowMap(manipulator_.transform(), keyLight);
                    const auto selected = nadoc_vr::spectatorMirrorViewIndex(
                        mirrorEye_, viewCount);
                    if (selected) {
                        renderSpectatorFallback(*selected, views_[*selected]);
                    }
                }
            }
        }

        XrFrameEndInfo endInfo{XR_TYPE_FRAME_END_INFO};
        endInfo.displayTime = frameState.predictedDisplayTime;
        endInfo.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        endInfo.layerCount = layerCount;
        endInfo.layers = layerCount ? layers : nullptr;
        const auto sceneFinished = std::chrono::steady_clock::now();
        auditSubmitted_=layerCount>0; auditPeriod_=double(frameState.predictedDisplayPeriod)/1e6;
        frameAudit_.mark("submit_prepare");
        checkXr(instance_, xrEndFrame(session_, &endInfo), "xrEndFrame");
        traceRender("xr_end");
        const auto endFinished = std::chrono::steady_clock::now();
        representationLoading_.frameTiming(std::chrono::duration<double,std::milli>(endFinished-frameStarted).count(),double(frameState.predictedDisplayPeriod)/1e6);
        publishPresenterPose();traceRender("avatar_publish");
        finishLiveCapture(layerCount > 0);
        traceRender("capture_finish");
        liveMeasure_.finish(layerCount > 0, liveFrame_);
        traceRender("measure_finish");
        for (const auto& report : gpuFrameTimer_.takeReports()) {
            nadoc_vr::TraceRecord{} << "VR_METRIC event=process_progress phase=menu_gpu_timing"
                      << " menu_open=" << (report.menuOpen ? "true" : "false")
                      << " samples=" << report.summary.samples
                      << " gpu_p50_ms=" << report.summary.p50Milliseconds
                      << " gpu_p95_ms=" << report.summary.p95Milliseconds
                      << " gpu_p99_ms=" << report.summary.p99Milliseconds
                      << " gpu_max_ms=" << report.summary.maxMilliseconds
                      << " query_skips=" << gpuFrameTimer_.skipped()
                      << std::endl;
        }
        traceRender("gpu_results");
        if(layerCount>0 && startup_.active && startup_.completedAt>=0) {
            startup_.percent=100;startup_.detail="Part ready";
        }
        if (layerCount > 0 && readySequence_ == 0 && !startup_.active) {
            firstFrameAtMilliseconds_ = std::chrono::duration<double, std::milli>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            firstFrameCpuMilliseconds_ = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - frameStarted).count();
            displayPeriodMilliseconds_ =
                static_cast<double>(frameState.predictedDisplayPeriod) / 1.0e6;
            ++readySequence_;
            publishEventState();
            nadoc_vr::TraceRecord{} << "VR first frame submitted: CPU="
                      << firstFrameCpuMilliseconds_ << " ms, runtime period="
                      << displayPeriodMilliseconds_ << " ms" << std::endl;
        }
        if (layerCount > 0) {
            const double milliseconds = std::chrono::duration<double, std::milli>(
                endFinished - frameStarted).count();
            (void)frameInputTiming_.add(std::chrono::duration<double, std::milli>(
                inputFinished - frameStarted).count());
            (void)frameSceneTiming_.add(std::chrono::duration<double, std::milli>(
                sceneFinished - inputFinished).count());
            (void)frameEndTiming_.add(std::chrono::duration<double, std::milli>(
                endFinished - sceneFinished).count());
            if (frameCpuTiming_.add(milliseconds)) {
                const auto summary = frameCpuTiming_.takeSummary();
                const auto inputSummary = frameInputTiming_.takeSummary();
                const auto sceneSummary = frameSceneTiming_.takeSummary();
                const auto endSummary = frameEndTiming_.takeSummary();
                if (summary && inputSummary && sceneSummary && endSummary) {
                    const double runtimePeriod =
                        static_cast<double>(frameState.predictedDisplayPeriod) / 1.0e6;
                    nadoc_vr::TraceRecord{} << "VR_METRIC event=process_progress phase=frame_timing"
                              << " representation="
                              << representationName(glScene_->representation())
                              << " samples=" << summary->samples
                              << " runtime_period_ms=" << runtimePeriod
                              << " loop_p50_ms=" << summary->p50Milliseconds
                              << " loop_p95_ms=" << summary->p95Milliseconds
                              << " loop_p99_ms=" << summary->p99Milliseconds
                              << " loop_max_ms=" << summary->maxMilliseconds
                              << " input_p50_ms=" << inputSummary->p50Milliseconds
                              << " input_p95_ms=" << inputSummary->p95Milliseconds
                              << " scene_p50_ms=" << sceneSummary->p50Milliseconds
                              << " scene_p95_ms=" << sceneSummary->p95Milliseconds
                              << " xr_end_p50_ms=" << endSummary->p50Milliseconds
                              << " xr_end_p95_ms=" << endSummary->p95Milliseconds
                              // xrSyncActions/xrEndFrame are runtime scheduling points and
                              // may deliberately block until the compositor wants the next
                              // frame. Input also contains application/tool work; this scene-only
                              // flag is not a complete budget gate. Treating the paced loop
                              // as render time incorrectly reported a healthy
                              // 90 Hz SteamVR session as over budget.
                              << " scene_p95_within_budget="
                              << (sceneSummary->p95Milliseconds <= runtimePeriod ? "true" : "false")
                              << std::endl;
                }
            }
        }
        if (toolShell_.mode() == nadoc_vr::ToolMode::move_rotate &&
            toolShell_.previewRequested()) {
            const double milliseconds = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - frameStarted).count();
            if (previewFrameTiming_.add(milliseconds)) {
                const auto summary = previewFrameTiming_.takeSummary();
                if (summary) {
                    const double runtimePeriod =
                        static_cast<double>(frameState.predictedDisplayPeriod) / 1.0e6;
                    nadoc_vr::TraceRecord{} << "VR preview CPU frame ms (" << summary->samples
                              << " samples, runtime period=" << runtimePeriod
                              << "): p50=" << summary->p50Milliseconds
                              << " p95=" << summary->p95Milliseconds
                              << " p99=" << summary->p99Milliseconds
                              << " max=" << summary->maxMilliseconds << std::endl;
                }
            }
        }
    }

    void pollJobSnapshot() {
        if (jobPath_.empty() || (++jobSnapshotPollFrame_ % 30U) != 0U) return;
        try {
            auto next = nadoc_vr::loadJobSnapshot(jobPath_);
            if (next.sequence <= jobSnapshotSequence_) return;

            jobSnapshotSequence_ = next.sequence;
            if (!next.representation.empty()) {
                desktopRepresentation_ = std::move(next.representation);
                desktopColoring_ = std::move(next.coloring);
            }

            // Style is presentation state and is applied atomically with the
            // visualization snapshot. The jobs feed retains these fields only for
            // backward-compatible metadata; applying them here races the geometry.

        } catch (const std::exception&) {
            // Atomic publication makes this rare. Retain the last complete
            // metadata revision until the next complete publication.
        }
    }

    void pollVisualizationSnapshot() {
        if (visualizationPath_.empty()) return;
        ++visualizationSnapshotPollFrame_;
        // A production all-atom snapshot is several MB. The old path reparsed it
        // every ten HMD frames merely to rediscover the same sequence number,
        // creating a periodic render-thread stall even while playback was paused.
        // Stat each frame (cheap), and parse only an atomically published revision.
        std::error_code error;
        const auto modified = std::filesystem::last_write_time(
            visualizationPath_, error);
        if (error || (visualizationModified_ && *visualizationModified_ == modified)) {
            return;
        }
        visualizationModified_ = modified;
        const uintmax_t sourceBytes = std::filesystem::file_size(
            visualizationPath_, error);
        const auto started = std::chrono::steady_clock::now();
        try {
            auto next = nadoc_vr::loadVisualizationSnapshot(visualizationPath_);
            const auto parsedAt = std::chrono::steady_clock::now();
            if (next.sequence <= visualizationSequence_) return;
            // Startup already displays Full. The desktop may not publish a redundant
            // Full revision, so accept the first newer acknowledged style directly.
            if(representationLoading_.enabled && !next.representation.empty() &&
               !glScene_->supportsRepresentation(representationFromName(next.representation))) {
                if(!representationLoading_.pending && representationLoading_.phase!="error")
                    representationLoading_.start(representationFromName(next.representation),coloringFromName(next.coloring),sceneRefresh_.revision());
                return;
            }
            const uint64_t previousSequence = visualizationSequence_;
            visualizationSequence_ = next.sequence;
            visualizationSnapshot_ = std::move(next);
            coordinatePlayback_.clear();
            glScene_->setVisualization(visualizationSnapshot_);
            const auto appliedAt = std::chrono::steady_clock::now();
            if (!visualizationSnapshot_.representation.empty()) {
                desktopRepresentation_ = visualizationSnapshot_.representation;
                desktopColoring_ = visualizationSnapshot_.coloring;
            }
            ++visualizationUpdateCount_;
            const uint64_t sequenceGap = visualizationSequence_ > previousSequence
                ? visualizationSequence_ - previousSequence - 1U : 0U;
            visualizationSequenceGaps_ += sequenceGap;
            const double parseMilliseconds =
                std::chrono::duration<double, std::milli>(parsedAt - started).count();
            const double applyMilliseconds =
                std::chrono::duration<double, std::milli>(appliedAt - parsedAt).count();
            std::cout << "VR_METRIC event=process_progress phase=visualization_update"
                      << " sequence=" << visualizationSequence_
                      << " updates=" << visualizationUpdateCount_
                      << " sequence_gap=" << sequenceGap
                      << " sequence_gaps_total=" << visualizationSequenceGaps_
                      << " points=" << visualizationSnapshot_.points.size()
                      << " source_bytes=" << (error ? 0U : sourceBytes)
                      << " parse_ms=" << parseMilliseconds
                      << " apply_upload_ms=" << applyMilliseconds
                      << " total_ms=" << (parseMilliseconds + applyMilliseconds)
                      << " hmd_poll_frame=" << visualizationSnapshotPollFrame_
                      << " rss_mib=" << currentResidentMiB() << std::endl;
            std::cout << "VR desktop visualization: "
                      << visualizationSnapshot_.mode << " ("
                      << visualizationSnapshot_.points.size() << " positions)\n";
        } catch (const std::exception&) {
            // Atomic publication means a failed revision is never required for
            // progress. Retain the last complete desktop visualization.
        }
    }

    void pollTrajectoryFeeds() {
        if (!trajectoryPath_.empty()) {
            std::error_code error;
            const auto modified = std::filesystem::last_write_time(
                trajectoryPath_, error);
            if (!error && (!trajectoryModified_ || *trajectoryModified_ != modified)) {
                try {
                    std::ifstream input(trajectoryPath_);
                    auto next = nadoc_vr::loadTrajectoryState(input);
                    if (next.sequence >= trajectoryState_.sequence) {
                        trajectoryState_ = next;
                        if (!next.active || !next.playing) coordinatePlayback_.pause();
                    }
                    trajectoryModified_ = modified;
                } catch (const std::exception&) {
                    // Atomic publisher should make this exceptional; retain last state.
                }
            }
        }
        if (coordinatePath_.empty()) return;
        std::error_code error;
        const auto modified = std::filesystem::last_write_time(
            coordinatePath_, error);
        if (error || (coordinateModified_ && *coordinateModified_ == modified)) return;
        const uintmax_t sourceBytes = std::filesystem::file_size(coordinatePath_, error);
        const auto started = std::chrono::steady_clock::now();
        try {
            std::ifstream input(coordinatePath_, std::ios::binary);
            nadoc_vr::loadCoordinateFrame(input, coordinateFrameScratch_);
            const auto& frame = coordinateFrameScratch_;
            const auto parsed = std::chrono::steady_clock::now();
            coordinateModified_ = modified;
            if (frame.sequence <= coordinateSequence_) return;
            if (frame.positions.empty()) {
                coordinatePlayback_.clear();
                coordinateSequence_ = frame.sequence;
                return;
            }
            if (glScene_->representation() != Representation::ballstick &&
                glScene_->representation() != Representation::stick && glScene_->representation() != Representation::vdw) {
                // The compact feed contains atom XYZ only. Full also needs coarse
                // slab orientation and therefore arrives through the authoritative
                // visualization feed. Consume this revision so returning to an
                // atomistic mode does not report an intentional Full hold as loss.
                coordinateSequence_ = frame.sequence;
                coordinatePlayback_.clear();
                std::cout << "VR_METRIC event=process_progress phase=coordinate_update"
                          << " status=skipped_incompatible_representation"
                          << " sequence=" << frame.sequence
                          << " frame_idx=" << frame.frameIndex
                          << " atoms=" << frame.positions.size()
                          << " representation="
                          << representationName(glScene_->representation())
                          << std::endl;
                return;
            }
            double cpuMilliseconds = 0.0;
            double uploadMilliseconds = 0.0;
            coordinatePlayback_.push(frame, trajectoryState_.active && trajectoryState_.playing,
                std::chrono::duration<double>(parsed.time_since_epoch()).count());
            coordinatePlayback_.sample(std::chrono::duration<double>(parsed.time_since_epoch()).count());
            if (!glScene_->updateAtomCoordinates(
                    coordinatePlayback_.positions(), &cpuMilliseconds, &uploadMilliseconds)) {
                coordinatePlayback_.clear();
                std::cout << "VR_METRIC event=process_progress phase=coordinate_update"
                          << " status=rejected sequence=" << frame.sequence
                          << " frame_idx=" << frame.frameIndex
                          << " atoms=" << frame.positions.size() << std::endl;
                return;
            }
            const uint64_t previousSequence = coordinateSequence_;
            coordinateSequence_ = frame.sequence;
            ++coordinateUpdateCount_;
            const uint64_t sequenceGap = previousSequence > 0 &&
                    coordinateSequence_ > previousSequence
                ? coordinateSequence_ - previousSequence - 1U : 0U;
            coordinateSequenceGaps_ += sequenceGap;
            const double parseMilliseconds =
                std::chrono::duration<double, std::milli>(parsed - started).count();
            std::cout << "VR_METRIC event=process_progress phase=coordinate_update"
                      << " status=applied sequence=" << coordinateSequence_
                      << " updates=" << coordinateUpdateCount_
                      << " sequence_gap=" << sequenceGap
                      << " sequence_gaps_total=" << coordinateSequenceGaps_
                      << " frame_idx=" << frame.frameIndex
                      << " frame_count=" << frame.frameCount
                      << " atoms=" << frame.positions.size()
                      << " source_bytes=" << (error ? 0U : sourceBytes)
                      << " parse_ms=" << parseMilliseconds
                      << " cpu_update_ms=" << cpuMilliseconds
                      << " upload_ms=" << uploadMilliseconds
                      << " total_ms="
                      << (parseMilliseconds + cpuMilliseconds + uploadMilliseconds)
                      << " rss_mib=" << currentResidentMiB() << std::endl;
        } catch (const std::exception&) {
            // Retain the last complete frame and retry the next atomic revision.
        }
    }

    void pollLive() {
        liveMeasure_.expire();
        if (liveCapturePending_ && std::chrono::steady_clock::now() > liveCaptureDeadline_) {
            failLiveCapture("no_submitted_frame");
        }
        liveSocket_.poll([this](const std::string& command) {
            try { return liveCommand(command); }
            catch (const std::exception& error) {
                return std::string("{\"error\":\"invalid_command\",\"detail\":\"") +
                    nadoc_vr::scrywrite::visualJson(error.what()) + "\"}";
            }
        });
    }

    void eventLoop() {
        std::cout << "NADOC VR viewer ready. Grip: move; both grips: resize; "
                     "grip a menu border or Desktop surface: move panel; "
                     "both grips at a border: resize panel; "
                     "trigger: Selection Volume snap/select; hold right trackpad: Ligate/Nick/Undo/Redo wheel; "
                     "hold left trackpad: selection wheel; "
                     "menu: sidebar; Escape: exit.\n";
        if (mirrorEye_ != nadoc_vr::SpectatorMirrorEye::off) {
            std::cout << "NADOC VR desktop spectator: physical HMD "
                      << nadoc_vr::spectatorMirrorEyeName(mirrorEye_)
                      << " eye; submitted-eye copy when accepted, labeled live-pose "
                         "fallback when suppressed. Closing the mirror window ends VR.\n";
        }
        if (referenceGrid_) {
            std::cout << "NADOC VR room grid: 5 m cage centered on LOCAL origin; "
                         "+X red, -X cyan, +Y green, -Y magenta, +Z blue, -Z yellow.\n";
        }
        if (witness_) {
            std::cout << "ScryWrite Witness controls: physical left menu pauses/resumes; "
                         "physical right menu single-steps while paused. Scripted input "
                         "cannot publish design events.\n";
        }
        nadoc_vr::LoadingFrameTrace loadTrace;
        auto trace=[&](const char* phase){frameAudit_.mark(phase);loadTrace.mark(phase,representationLoading_.percent,representationName(representationLoading_.target));};
        while (!exitLoop_) {
            frameAudit_.begin();
            loadTrace.begin(liveSocket_.enabled());
            glfwPollEvents();trace("events_glfw");
            pollXrEvents();trace("events_xr");
            pollLive();trace("events_live");
            placementIntegrity_.poll(eventPath_);
            if(placementIntegrity_.blocked()) {
                placementFailurePopup_.active=true;placementFailurePopup_.phase="error";
                placementFailurePopup_.percent=0;placementFailurePopup_.detail=placementIntegrity_.detail();
            }
            if (exitRequested_ || glfwWindowShouldClose(window_) ||
                glfwGetKey(window_, GLFW_KEY_ESCAPE) == GLFW_PRESS || gStopRequested) {
                if (sessionRunning_) {
                    xrRequestExitSession(session_);
                } else {
                    exitLoop_ = true;
                }
                gStopRequested = false;
                exitRequested_ = false;
            }
            if (sessionRunning_) {
                trace("events");
                pollStartup();trace("startup");
                pollRepresentationLoading();trace("representation");
                pollJobSnapshot();trace("jobs");
                if(!startup_.active)pollVisualizationSnapshot();
                trace("visualization");
                const auto receivedSequence = coordinateSequence_;
                pollTrajectoryFeeds();
                if (glScene_->representation() == Representation::ballstick ||
                    glScene_->representation() == Representation::stick || glScene_->representation() == Representation::vdw) {
                    const double time = std::chrono::duration<double>(
                        std::chrono::steady_clock::now().time_since_epoch()).count();
                    // New packets already uploaded a sample in pollTrajectoryFeeds.
                    if (receivedSequence == coordinateSequence_ && coordinatePlayback_.sample(time)) {
                        if (!glScene_->updateAtomCoordinates(coordinatePlayback_.positions()))
                            coordinatePlayback_.clear();
                    }
                } else coordinatePlayback_.clear();
                trace("coordinates");
                renderFrame();trace("frame");
                frameAudit_.finish(liveFrame_, representationName(glScene_->representation()), nadoc_vr::toolModeName(toolShell_.mode()), auditPeriod_, auditSubmitted_, sessionState_==XR_SESSION_STATE_FOCUSED);
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
        }
    }

    nadoc_vr::scrywrite::LiveSocket liveSocket_;
    nadoc_vr::scrywrite::WitnessInput liveInput_;
    std::array<bool, 2> liveMenuPressed_{}, liveTrackpadPressed_{};
    std::array<glm::vec2,2> liveTrackpadAxis_{};
    std::array<float,2> liveTriggerValues_{};
    std::string liveSession_, liveMode_ = "inspect";
    std::array<LiveEyeCapture, 2> liveEyes_{};
    GLuint liveObjectIdTexture_ = 0;
    int liveObjectIdWidth_ = 0, liveObjectIdHeight_ = 0;
    std::optional<uint64_t> liveCapturePending_;
    std::string liveCaptureResult_ = "null";
    nadoc_metrics::LiveMeasure liveMeasure_;
    std::filesystem::path liveDirectory_;
    uint64_t liveFrame_ = 0, liveCommandSequence_ = 0;
    std::chrono::steady_clock::time_point liveInputDeadline_{}, liveCaptureDeadline_{};
    RepresentationLoading representationLoading_;
    StartupLoading startup_;
    nadoc_vr::PlacementIntegrityLatch placementIntegrity_;
    StartupLoading placementFailurePopup_;
    std::vector<std::string> startupOwners_;
    std::string startupKind_;
    SceneData sceneData_;
    nadoc_vr::SceneRefreshInbox<SceneData> sceneRefresh_;
    nadoc_vr::Ligation ligation_;
    nadoc_vr::QuiverGesture quiver_;
    std::string ligationPreviousLevel_="default";
    nadoc_vr::EndResize endResize_;
    std::string eventPath_;
    std::string feedbackPath_;
    std::string toolFeedbackPath_;
    std::string planeFeedbackPath_;
    std::string preflightFeedbackPath_;
    std::string toolExecutionFeedbackPath_;
    std::string jobPath_;
    std::string visualizationPath_;
    std::string trajectoryPath_;
    std::string coordinatePath_;
    uint64_t jobSnapshotSequence_ = 0;
    uint32_t jobSnapshotPollFrame_ = 0;
    nadoc_vr::VisualizationSnapshot visualizationSnapshot_;
    uint64_t visualizationSequence_ = 0;
    uint32_t visualizationSnapshotPollFrame_ = 0;
    std::optional<std::filesystem::file_time_type> visualizationModified_;
    uint64_t visualizationUpdateCount_ = 0;
    uint64_t visualizationSequenceGaps_ = 0;
    nadoc_vr::TrajectoryState trajectoryState_;
    std::optional<std::filesystem::file_time_type> trajectoryModified_;
    std::optional<std::filesystem::file_time_type> coordinateModified_;
    nadoc_vr::CoordinateFrame coordinateFrameScratch_;
    nadoc_vr::CoordinatePlayback coordinatePlayback_;
    uint64_t coordinateSequence_ = 0;
    uint64_t coordinateUpdateCount_ = 0;
    uint64_t coordinateSequenceGaps_ = 0;
    std::string desktopRepresentation_;
    std::string desktopColoring_;
    nadoc_vr::SpectatorMirrorEye mirrorEye_ = nadoc_vr::SpectatorMirrorEye::off;
    bool referenceGrid_ = false;
    bool initialRoomPlacementRequested_ = true;
    bool initialScenePlacementEnabled_ = false;
    bool initialScenePlacementRequested_ = false;
    bool initialScenePlacementApplied_ = false;
    nadoc_vr::SceneViewPlacement sceneViewPlacement_;
    nadoc_vr::SpectatorPlacementGate initialPlacementGate_;
    glm::vec3 initialPlacementCandidatePosition_{};
    glm::quat initialPlacementCandidateOrientation_{1.0F, 0.0F, 0.0F, 0.0F};
    bool initialPlacementCandidateInitialized_ = false;
    std::string mirrorDiagnosticsPath_;
    std::string witnessCaptureDirectory_;
    std::string witnessVisualExpectationDirectory_;
    bool exitOnWitnessComplete_ = false;
    std::ofstream mirrorDiagnosticsOutput_;
    glm::vec3 normalizationCenter_{};
    glm::mat3 sourceAxes_{1.0F};
    float normalizationScale_ = 1.0F;
    uint64_t eventSequence_ = 0;
    std::string publishedHoverIdentity_;
    uint64_t selectSequence_ = 0;
    std::string lastSelectIdentity_;
    std::vector<std::string> lastSelectIdentities_;
    uint64_t levelSequence_ = 0;
    nadoc_vr::SelectionLevelGuard selectionLevelGuard_;
    nadoc_vr::FreeformDraft freeformDraft_;
    std::string selectionLevel_ = "default";
    uint64_t styleSequence_ = 0;
    std::string requestedRepresentation_ = "full";
    std::string requestedColoring_ = "strand";
    uint64_t trajectoryRequestSequence_ = 0;
    std::string trajectoryAction_ = "none";
    uint32_t trajectoryRequestedFrameIndex_ = 0;
    uint64_t toolSequence_ = 0;
    uint64_t lastToolConfigSequence_ = 0;
    nadoc_vr::ToolAction lastToolAction_ = nadoc_vr::ToolAction::activate;
    std::string lastToolTargetIdentity_;
    std::vector<std::string> lastToolTargetOwnerTokens_;
    std::string lastToolTargetKind_ = "none";
    nadoc_vr::ToolShell toolShell_;
    uint64_t toolConfigSequence_ = 0;
    nadoc_vr::ToolConfigurationDraft toolConfig_;
    nadoc_vr::PendingRigidTransform pendingToolTransform_;
    uint64_t transformSequence_ = 0;
    glm::mat4 lastToolTransform_{1.0F};
    uint64_t readySequence_ = 0;
    uint64_t mirrorFrameSequence_ = 0;
    uint64_t mirrorMotionSequence_ = 0;
    uint64_t lastMirrorMotionLogFrame_ = 0;
    XrViewStateFlags currentViewStateFlags_ = 0;
    glm::vec3 lastMirrorMotionPosition_{};
    glm::quat lastMirrorMotionOrientation_{1.0F, 0.0F, 0.0F, 0.0F};
    bool mirrorPoseInitialized_ = false;
    bool lastMirrorPoseTracked_ = false;
    bool mirrorSourceInitialized_ = false;
    bool lastMirrorSubmittedEye_ = false;
    GLuint mirrorDiagnosticsFramebuffer_ = 0;
    GLuint mirrorDiagnosticsTexture_ = 0;
    GLuint mirrorDiagnosticsDepthStencil_ = 0;
    uint64_t mirrorPixelSampleSequence_ = 0;
    uint64_t lastMirrorPixelWarningFrame_ = 0;
    nadoc_vr::SpectatorPixelAssessment mirrorPixelAssessment_;
    nadoc_vr::SpectatorCoverageAssessment mirrorCoverageAssessment_;
    nadoc_vr::SpectatorPixelStatus lastLoggedMirrorPixelStatus_ =
        nadoc_vr::SpectatorPixelStatus::unavailable;
    nadoc_vr::SpectatorCoverageStatus lastLoggedMirrorCoverageStatus_ =
        nadoc_vr::SpectatorCoverageStatus::unavailable;
    std::vector<uint8_t> previousMirrorPixels_;
    glm::vec3 previousMirrorPixelPosition_{};
    glm::quat previousMirrorPixelOrientation_{1.0F, 0.0F, 0.0F, 0.0F};
    bool mirrorPixelPoseInitialized_ = false;
    bool previousMirrorPixelSubmittedEye_ = false;
    double firstFrameAtMilliseconds_ = 0.0;
    double firstFrameCpuMilliseconds_ = 0.0;
    double displayPeriodMilliseconds_ = 0.0;
    XrTime currentPredictedDisplayTime_ = 0;
    nadoc_vr::TimingWindow previewFrameTiming_{240};
    nadoc_vr::TimingWindow frameCpuTiming_{240};
    nadoc_vr::TimingWindow frameInputTiming_{240};
    nadoc_vr::TimingWindow frameSceneTiming_{240};
    nadoc_vr::TimingWindow frameEndTiming_{240};
    uint64_t feedbackSequence_ = 0;
    uint32_t feedbackPollFrame_ = 0;
    uint64_t toolFeedbackSequence_ = 0;
    uint32_t toolFeedbackPollFrame_ = 0;
    std::optional<nadoc_vr::ToolContextFeedback> toolContextFeedback_;
    uint32_t preflightFeedbackPollFrame_ = 0;
    uint64_t preflightFeedbackSequence_ = 0;
    std::optional<nadoc_vr::ToolPreflightFeedback> toolPreflightFeedback_;
    uint64_t toolExecutionFeedbackSequence_ = 0;
    uint32_t toolExecutionFeedbackPollFrame_ = 0;
    std::string committedFeatureLogEntryId_;
    uint64_t planePickSequence_ = 0;
    uint64_t activePlanePickSequence_ = 0;
    uint64_t planePickConfigSequence_ = 0;
    uint64_t planePickFeedbackSequence_ = 0;
    uint32_t planeFeedbackPollFrame_ = 0;
    std::optional<glm::vec3> bendPickPosition_;
    std::optional<std::string> bendPickExtent_;
    std::vector<GlScene::BendCluster> bendClusters_;
    glm::vec3 bendSlideStart_{}, bendSlideHand_{};
    float bendSlideRayDistance_=0;

    std::optional<std::string> planePickSlot_;
    std::string planePickIdentity_;
    std::string planePickStatus_;
    std::array<std::optional<DeformationPlaneGuide>, 2> planeGuides_{};
    std::string selectedIdentity_;
    std::vector<std::string> selectedOwnerTokens_;
    std::string selectedSelectionKind_ = "none";
    bool glfwInitialized_ = false;
    GLFWwindow* window_ = nullptr;
    XrInstance instance_ = XR_NULL_HANDLE;
    XrSystemId systemId_ = XR_NULL_SYSTEM_ID;
    XrSession session_ = XR_NULL_HANDLE;
    XrSpace space_ = XR_NULL_HANDLE;
    XrActionSet actionSet_ = XR_NULL_HANDLE;
    XrAction poseAction_ = XR_NULL_HANDLE;
    nadoc_vr::AnchoredShadowLight shadowLight_, witnessShadowLight_;
    XrAction triggerAction_ = XR_NULL_HANDLE;
    XrAction menuAction_ = XR_NULL_HANDLE;
    XrAction gripAction_ = XR_NULL_HANDLE;
    XrAction trackpadAction_ = XR_NULL_HANDLE;
    XrAction trackpadTouchAction_ = XR_NULL_HANDLE;
    XrAction trackpadAxisAction_ = XR_NULL_HANDLE;
    XrAction hapticAction_ = XR_NULL_HANDLE;
    std::array<XrPath, 2> handPaths_{XR_NULL_PATH, XR_NULL_PATH};
    std::array<XrSpace, 2> handSpaces_{XR_NULL_HANDLE, XR_NULL_HANDLE};
    std::array<nadoc_vr::HandPose, 2> hands_{};
    std::array<float, 2> triggerValues_{0.0F, 0.0F};
    std::array<bool, 2> triggerPartial_{false, false};
    std::array<bool, 2> inputResumeBlocked_{};
    std::array<bool, 2> triggerPressed_{false, false};
    std::array<bool, 2> triggerClicked_{false, false};
    XrTime lastActionDisplayTime_ = 0;
    float frameDeltaSeconds_ = 1.0F / 90.0F;
    std::array<bool, 2> gripPressed_{false, false};
    std::array<uint64_t,2> hapticRequests_{};
    std::array<float,2> hapticAmplitude_{};
    std::array<bool, 2> gripClicked_{false, false};
    std::array<bool, 2> trackpadPressed_{false, false};
    std::array<bool, 2> trackpadScrolled_{false, false};
    std::array<bool, 2> desktopTrackpadTouching_{false, false};
    std::array<float, 2> desktopTrackpadLastY_{0.0F, 0.0F};
    std::array<float, 2> desktopTrackpadTravel_{0.0F, 0.0F};
    std::array<nadoc_vr::SelectionVolumeControl, 2> selectionVolumes_{};
    std::array<std::vector<nadoc_vr::PickHit>, 2> snapSelectionHits_{};
    std::array<std::vector<std::string>, 2> snapSelectionOwnerTokens_{};
    std::array<std::vector<std::string>, 2> snapSelectionDirectIdentities_{};
    std::vector<std::string> committedSelectionIdentities_;
    std::vector<std::string> committedSelectionOwnerTokens_;
    nadoc_vr::SceneManipulator manipulator_;
    ComponentGallery componentGallery_;
    SolidUi solidWheels_;
    std::vector<Vertex> controllerGuides_;
    std::array<size_t, 2> controllerHandEnds_{};
    std::array<std::string,2> liveInputOwner_{"none","none"};
    bool liveSceneHidden_ = false;
    nadoc_vr::LiveMirrorCapture liveMirrorCapture_;
    nadoc_vr::ControllerPaths controllerPaths_;
    std::optional<size_t> controllerContactWheel_;
    std::vector<Vertex> controllerPathGuides_;
    std::array<std::vector<Vertex>,2> controllerContactGuides_;
    size_t witnessActorGuideCount_ = 0;
    std::vector<Vertex> referenceGridGuides_;
    std::optional<nadoc_vr::scrywrite::WitnessReplay> witness_;
    nadoc_vr::scrywrite::WitnessSurface witnessSurface_;
    nadoc_vr::MenuPlacement witnessStatusPlacement_;
    std::array<bool, 2> witnessMenuPressed_{};
    glm::vec3 witnessObserverPosition_{};
    glm::quat witnessObserverOrientation_{1.0F, 0.0F, 0.0F, 0.0F};
    bool witnessFailureReported_ = false;
    bool witnessCompletionReported_ = false;
    std::optional<nadoc_vr::PickHit> sceneHover_;
    nadoc_vr::EditWheel radialToolMenu_;
    nadoc_vr::SelectionWheel selectionWheel_;
    bool latticeOpen_ = false;
    nadoc_vr::MenuPlacement latticePlacement_;
    nadoc_vr::LatticeGrip latticeGrip_;
    nadoc_vr::ExtrudePanel extrudePanel_;
    nadoc_vr::SweepPanel sweepPanel_;
    nadoc_vr::SweepDraft sweepDraft_;
    std::optional<size_t> sweepHand_;
    std::array<std::optional<size_t>,2> sweepHovered_;
    glm::vec3 sweepDragStart_{},sweepPointStart_{};
    glm::mat4 sweepStartModel_{1};
    double sweepPublishedAt_=0;
    uint64_t sweepPublishedRevision_=0;
    float sweepStrokeMetresPerNm_=.01F;
    uint64_t sweepGeometryRevision_=std::numeric_limits<uint64_t>::max();
    std::vector<glm::vec3> sweepCurve_,sweepCloud_;
    struct ExtrudeConfirmation { size_t settingsOffset; bool painterOpen; };
    std::optional<ExtrudeConfirmation> extrudeConfirmation_;
    nadoc_vr::BendPanel bendPanel_;
    nadoc_vr::MovePanel movePanel_;
    uint64_t moveStartRevision_=0;
    bool moveAwaitRefresh_=false;
    nadoc_vr::ExtrudeLatticeDraft extrudeLatticeDraft_;
    nadoc_vr::LatticePaintStroke latticePaintStroke_;
    std::optional<nadoc_vr::LatticeCell> latticeHover_;
    bool latticeExitHovered_ = false;
    nadoc_vr::LatticeCell latticeOrigin_{};
    nadoc_vr::ExtrudePlane extrudePlane_;
    nadoc_vr::LatticeContext latticeContext_;
    std::optional<nadoc_vr::LatticeContext> pendingLatticeContext_;
    bool latticeSquare_ = false;
    std::array<nadoc_vr::ThumbwheelControl,2> thumbwheelControls_;
    std::optional<size_t> thumbwheelHovered_,thumbwheelHand_;
    bool suppressManipulationUntilRelease_ = false;
    RoomFloor roomFloor_;
    QrCalibration qrCalibration_;
    FrostedGlass menuGlass_;
    MenuPanelSurface latticePanelSurface_;
    nadoc_vr::MenuLayoutAudit latticeLayoutAudit_;
    SidebarRuntime sidebarMenus_;
    SidebarRuntime routingPopup_;
    nadoc_vr::RoutingPanel routingPanel_;
    nadoc_vr::ViewVolumePanel volumePanel_;
    nadoc_vr::DimensionPanel dimensionPanel_;
    nadoc_vr::DimensionSync dimensionSync_;
    nadoc_vr::LatestAtomicFile avatarWriter_;
    nadoc_vr::OrderedAtomicFile eventWriter_;
    nadoc_vr::FrameAudit frameAudit_;
    bool auditSubmitted_=false;
    double auditPeriod_=0;
    nadoc_vr::LoadingFrameTrace renderTrace_{"VR_RENDER_TRACE"};
    void traceRender(const char* phase){frameAudit_.mark(phase);renderTrace_.mark(phase,representationLoading_.percent,representationName(representationLoading_.target));}
    GpuFrameTimer gpuFrameTimer_;
    bool recenterRequested_ = false;
    size_t recenterHand_ = 0;
    XrSessionState sessionState_ = XR_SESSION_STATE_UNKNOWN;
    bool sessionRunning_ = false;
    bool exitLoop_ = false;
    bool exitRequested_ = false;
    GLuint framebuffer_ = 0;
    std::vector<XrViewConfigurationView> viewConfigs_;
    std::vector<XrView> views_;
    std::vector<Swapchain> swapchains_;
    std::unique_ptr<GlScene> glScene_;
    DesktopSurface desktopSurface_;
    nadoc_vr::DesktopPanel desktopPanel_;
    nadoc_vr::RemotePanelControl remotePanels_;
    MenuPanelSurface desktopFrameSurface_;
    bool showVRAvatar_=true;
    double avatarPublishedAt_=-1;
    nadoc_vr::PresenterUI presenterUI_;
    bool shareActive_=false,sharePerspective_=false,shareBusy_=true,shareFailed_=false;
    int shareSequence_=0,shareAck_=0;
    std::string shareAction_;
    nadoc_vr::SimulationPanel simulationPanel_;
    nadoc_vr::TrajectoryPanel trajectoryPanel_;
    std::optional<size_t> trajectoryScrubHand_;
    uint32_t trajectoryScrubFrame_=0;
    VRViewTools viewTools_;
};

}  // namespace

int main(int argc, char** argv) {
    if ((argc == 3 || argc == 4) &&
        std::string(argv[1]) == "--benchmark-atomistic") {
        try {
            return benchmarkAtomisticStyles(
                argv[2], argc == 4 ? argv[3] : std::string{});
        } catch (const std::exception& error) {
            std::cerr << "VR_METRIC event=process_end mode=benchmark_atomistic_styles"
                      << " status=error rss_mib=" << currentResidentMiB() << '\n';
            std::cerr << "NADOC VR benchmark error: " << error.what() << '\n';
            return 1;
        }
    }
    if (argc == 3 && std::string(argv[1]) == "--validate-witness") {
        try {
            std::ifstream input(argv[2]);
            if (!input) throw std::runtime_error("could not open witness script");
            (void)nadoc_vr::scrywrite::WitnessReplay::load(input);
            std::cout << "ScryWrite witness script is valid\n";
            return 0;
        } catch (const std::exception& error) {
            std::cerr << "ScryWrite witness error: " << error.what() << '\n';
            return 1;
        }
    }
    if (argc == 3 && std::string(argv[1]) == "--validate") {
        try {
            loadScene(argv[2]);
            std::cout << "NADOC VR scene is valid\n";
            return 0;
        } catch (const std::exception& error) {
            std::cerr << "NADOC VR error: " << error.what() << '\n';
            return 1;
        }
    }
    if (argc < 2) {
        std::cerr << "Usage: nadoc-vr-viewer "
                     "[--validate|--validate-witness|--benchmark-atomistic] <file> "
                     "[--events <event.json>] [--feedback <feedback.txt>] "
                     "[--tool-feedback <tool-feedback.txt>] "
                     "[--plane-feedback <plane-feedback.txt>] "
                     "[--preflight-feedback <preflight-feedback.txt>] "
                     "[--tool-execution-feedback <tool-execution-feedback.txt>] "
                     "[--jobs <jobs.txt>] "
                     "[--visualization <visualization.txt>] "
                     "[--trajectory <trajectory.txt>] "
                     "[--coordinates <coordinates.bin>] "
                     "[--selection-level <level>] "
                     "[--selected-owner <token>]... [--selected-kind <kind>] "
                     "[--mirror-eye <off|left|right>] "
                     "[--reference-grid <off|room>] "
                     "[--place-scene-in-view <off|on>] "
                     "[--scene-view <head|mirror|left|right>] "
                     "[--scene-orientation <front|back|left|right|top|bottom|isometric>] "
                     "[--scene-distance <meters>] [--scene-scale <factor>] "
                     "[--scene-yaw <degrees>] [--scene-pitch <degrees>] "
                     "[--scene-roll <degrees>] "
                     "[--mirror-diagnostics <trace.jsonl>] "
                     "[--controller-path <planned-path.txt>] "
                     "[--scrywrite-witness <script.scry>] "
                     "[--witness-captures <directory>] "
                     "[--witness-visual-expect <directory>] "
                     "[--witness-exit <on|off>] "
                     "[--scrywrite-live <private-socket-path>] "
                     "[--scrywrite-live-mode <inspect|control|transactions>]\n";
        return 2;
    }
    std::string eventPath;
    std::string feedbackPath;
    std::string toolFeedbackPath;
    std::string planeFeedbackPath;
    std::string preflightFeedbackPath;
    std::string toolExecutionFeedbackPath;
    std::string jobPath;
    std::string visualizationPath;
    std::string trajectoryPath;
    std::string coordinatePath;
    std::string loadingStatusPath;
    std::string liveSocketPath, liveMode = "inspect";
    std::string witnessPath;
    std::string mirrorDiagnosticsPath;
    std::string controllerPath;
    bool componentGallery=false, galleryDesktop=false, galleryButtons=false, galleryCards=false;
    std::string galleryOutput;
    std::string witnessCaptureDirectory;
    std::string witnessVisualExpectationDirectory;
    bool exitOnWitnessComplete = false;
    nadoc_vr::SpectatorMirrorEye mirrorEye = nadoc_vr::SpectatorMirrorEye::off;
    bool referenceGrid = false;
    bool placeSceneInView = false;
    nadoc_vr::SceneViewPlacement sceneViewPlacement;
    std::string selectionLevel = "default";
    std::string selectedSelectionKind = "none";
    std::vector<std::string> selectedOwnerTokens;
    const std::array<std::string, 7> validSelectionLevels = {
        "default", "cluster", "strand", "domain", "end", "xover", "base",
    };
    for (int index = 2; index < argc; index += 2) {
        if (index + 1 >= argc) {
            std::cerr << "NADOC VR error: missing value for " << argv[index] << '\n';
            return 2;
        }
        const std::string option(argv[index]);
        if(option=="--component-gallery") {
            const std::string component=argv[index+1];
            if(component!="thumbwheel" && component!="buttons" && component!="cards") {std::cerr<<"Unknown gallery component\n";return 2;}
            galleryButtons=component=="buttons";galleryCards=component=="cards";
            componentGallery=true;
        }
        else if(option=="--gallery-desktop") {
            const std::string value=argv[index+1];
            if(value!="on" && value!="off"){std::cerr<<"Expected on/off\n";return 2;}
            galleryDesktop=value=="on";
        }
        else if(option=="--gallery-output")galleryOutput=argv[index+1];
        else if (option == "--events") eventPath = argv[index + 1];
        else if (option == "--loading-status") loadingStatusPath = argv[index + 1];
        else if (option == "--feedback") feedbackPath = argv[index + 1];
        else if (option == "--tool-feedback") toolFeedbackPath = argv[index + 1];
        else if (option == "--plane-feedback") planeFeedbackPath = argv[index + 1];
        else if (option == "--preflight-feedback") preflightFeedbackPath = argv[index + 1];
        else if (option == "--tool-execution-feedback") {
            toolExecutionFeedbackPath = argv[index + 1];
        }
        else if (option == "--jobs") jobPath = argv[index + 1];
        else if (option == "--visualization") visualizationPath = argv[index + 1];
        else if (option == "--trajectory") trajectoryPath = argv[index + 1];
        else if (option == "--coordinates") coordinatePath = argv[index + 1];
        else if (option == "--scrywrite-live") liveSocketPath = argv[index + 1];
        else if (option == "--scrywrite-live-mode") liveMode = argv[index + 1];
        else if (option == "--scrywrite-witness") witnessPath = argv[index + 1];
        else if (option == "--witness-captures") {
            witnessCaptureDirectory = argv[index + 1];
        }
        else if (option == "--witness-visual-expect") {
            witnessVisualExpectationDirectory = argv[index + 1];
        }
        else if (option == "--witness-exit") {
            const std::string mode(argv[index + 1]);
            if (mode != "on" && mode != "off") {
                std::cerr << "NADOC VR error: witness exit must be on or off\n";
                return 2;
            }
            exitOnWitnessComplete = mode == "on";
        }
        else if (option == "--controller-path") { controllerPath = argv[index + 1]; }
        else if (option == "--mirror-diagnostics") {
            mirrorDiagnosticsPath = argv[index + 1];
        }
        else if (option == "--mirror-eye") {
            const auto parsed = nadoc_vr::parseSpectatorMirrorEye(argv[index + 1]);
            if (!parsed) {
                std::cerr << "NADOC VR error: mirror eye must be off, left, or right\n";
                return 2;
            }
            mirrorEye = *parsed;
        }
        else if (option == "--reference-grid") {
            const std::string mode(argv[index + 1]);
            if (mode != "off" && mode != "room") {
                std::cerr << "NADOC VR error: reference grid must be off or room\n";
                return 2;
            }
            referenceGrid = mode == "room";
        }
        else if (option == "--place-scene-in-view") {
            const std::string mode(argv[index + 1]);
            if (mode != "off" && mode != "on") {
                std::cerr << "NADOC VR error: place scene in view must be off or on\n";
                return 2;
            }
            placeSceneInView = mode == "on";
        }
        else if (option == "--scene-view") {
            const auto parsed = nadoc_vr::parseScenePlacementView(argv[index + 1]);
            if (!parsed) {
                std::cerr << "NADOC VR error: scene view must be head, mirror, left, or right\n";
                return 2;
            }
            sceneViewPlacement.view = *parsed;
        }
        else if (option == "--scene-orientation") {
            const auto parsed = nadoc_vr::parseScenePlacementOrientation(
                argv[index + 1]);
            if (!parsed) {
                std::cerr << "NADOC VR error: scene orientation must be front, back, "
                             "left, right, top, bottom, or isometric\n";
                return 2;
            }
            sceneViewPlacement.orientation = *parsed;
        }
        else if (option == "--scene-distance" || option == "--scene-scale" ||
                 option == "--scene-yaw" || option == "--scene-pitch" ||
                 option == "--scene-roll") {
            const auto parsed = parseFiniteFloat(argv[index + 1]);
            if (!parsed) {
                std::cerr << "NADOC VR error: invalid numeric value for "
                          << option << '\n';
                return 2;
            }
            if (option == "--scene-distance") {
                sceneViewPlacement.distanceMeters = *parsed;
            } else if (option == "--scene-scale") {
                sceneViewPlacement.scale = *parsed;
            } else if (option == "--scene-yaw") {
                sceneViewPlacement.yawDegrees = *parsed;
            } else if (option == "--scene-pitch") {
                sceneViewPlacement.pitchDegrees = *parsed;
            } else {
                sceneViewPlacement.rollDegrees = *parsed;
            }
        }
        else if (option == "--selection-level") selectionLevel = argv[index + 1];
        else if (option == "--selected-owner") {
            const std::string token(argv[index + 1]);
            if (token.empty() || token.size() > 2048 ||
                std::any_of(token.begin(), token.end(), [](unsigned char character) {
                    return std::isspace(character) != 0;
                }) || selectedOwnerTokens.size() >= 4097) {
                std::cerr << "NADOC VR error: invalid selected owner token\n";
                return 2;
            }
            selectedOwnerTokens.push_back(token);
        }
        else if (option == "--selected-kind") selectedSelectionKind = argv[index + 1];
        else {
            std::cerr << "NADOC VR error: unknown option " << option << '\n';
            return 2;
        }
    }
    if (std::find(validSelectionLevels.begin(), validSelectionLevels.end(), selectionLevel)
        == validSelectionLevels.end()) {
        std::cerr << "NADOC VR error: invalid selection level " << selectionLevel << '\n';
        return 2;
    }
    if (!nadoc_vr::validSceneViewPlacement(sceneViewPlacement)) {
        std::cerr << "NADOC VR error: placement distance must be 0.20-10 m, scale "
                     "0.05-20, and orientation offsets finite within +/-360 degrees\n";
        return 2;
    }
    const std::array<std::string, 12> validSelectionKinds = {
        "none", "selection", "cluster", "strand", "domain", "base", "end", "bond",
        "crossover", "overhang", "extension", "protein",
    };
    if (std::find(validSelectionKinds.begin(), validSelectionKinds.end(),
                  selectedSelectionKind) == validSelectionKinds.end() ||
        selectedOwnerTokens.empty() != (selectedSelectionKind == "none")) {
        std::cerr << "NADOC VR error: invalid selected owner kind\n";
        return 2;
    }
    if (liveMode != "inspect" && liveMode != "control" && liveMode != "transactions") {
        std::cerr << "NADOC VR error: live mode must be inspect, control, or transactions\n";
        return 2;
    }
    if (liveSocketPath.empty() && liveMode != "inspect") {
        std::cerr << "NADOC VR error: live mode requires --scrywrite-live\n";
        return 2;
    }
    if (!witnessPath.empty() && !eventPath.empty()) {
        std::cerr << "NADOC VR error: ScryWrite Witness Mode refuses an event output "
                     "to prevent scripted design mutation\n";
        return 2;
    }
    if ((!witnessCaptureDirectory.empty() ||
         !witnessVisualExpectationDirectory.empty()) && witnessPath.empty()) {
        std::cerr << "NADOC VR error: witness captures require --scrywrite-witness\n";
        return 2;
    }
    if (!witnessVisualExpectationDirectory.empty() &&
        witnessCaptureDirectory.empty()) {
        std::cerr << "NADOC VR error: visual expectations require --witness-captures\n";
        return 2;
    }
    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);
    try {
        if(galleryDesktop) {
            if(!componentGallery)throw std::runtime_error("Desktop gallery requires --component-gallery thumbwheel");
            return runComponentGalleryDesktop(galleryOutput,galleryButtons,galleryCards);
        }
        const auto processStarted = std::chrono::steady_clock::now();
        std::cout << "VR_METRIC event=process_start mode=openxr_viewer rss_mib="
                  << currentResidentMiB() << std::endl;
        SceneData initialScene;
        if(loadingStatusPath.empty())initialScene=loadScene(argv[1]);
        else {initialScene.emptyAuthoring=true;initialScene.available.fill(true);}
        const auto startupOwners=selectedOwnerTokens;
        const auto startupKind=selectedSelectionKind;
        Viewer viewer(
            std::move(initialScene), eventPath, feedbackPath, toolFeedbackPath,
            planeFeedbackPath, preflightFeedbackPath, toolExecutionFeedbackPath,
            jobPath,
            nadoc_vr::loadJobSnapshot(jobPath), visualizationPath,
            nadoc_vr::loadVisualizationSnapshot(visualizationPath),
            trajectoryPath, coordinatePath, selectionLevel,
            std::move(selectedOwnerTokens), std::move(selectedSelectionKind),
            witnessPath, mirrorEye, referenceGrid, placeSceneInView,
            sceneViewPlacement,
            mirrorDiagnosticsPath, witnessCaptureDirectory,
            witnessVisualExpectationDirectory, exitOnWitnessComplete, liveSocketPath, liveMode);
        if(!loadingStatusPath.empty())viewer.beginStartup(argv[1],loadingStatusPath,startupOwners,startupKind);
        if(componentGallery)viewer.enableComponentGallery(galleryButtons,galleryCards);
        viewer.loadControllerPath(controllerPath);
        const int result = viewer.run();
        const double milliseconds = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - processStarted).count();
        std::cout << "VR_METRIC event=process_end mode=openxr_viewer"
                  << " status=" << (result == 0 ? "ok" : "error")
                  << " elapsed_ms=" << milliseconds
                  << " rss_mib=" << currentResidentMiB() << std::endl;
        return result;
    } catch (const std::exception& error) {
        std::cerr << "VR_METRIC event=process_end mode=openxr_viewer"
                  << " status=error rss_mib=" << currentResidentMiB() << '\n';
        std::cerr << "NADOC VR error: " << error.what() << '\n';
        return 1;
    }
}
