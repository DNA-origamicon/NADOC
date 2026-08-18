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

#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>

#include "interaction.hpp"
#include "picking.hpp"

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cctype>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

constexpr float kViewSizeMeters = 0.60F;
constexpr float kViewDistanceMeters = 1.30F;
constexpr float kNearMeters = 0.02F;
constexpr float kFarMeters = 100.0F;

std::atomic_bool gStopRequested{false};

struct Vertex {
    glm::vec3 position{};
    glm::vec3 color{};
    float size = 1.0F;
};

struct Cylinder {
    glm::vec3 start{};
    glm::vec3 end{};
    float radius = 0.01F;
    glm::vec3 color{};
};

struct Box {
    glm::vec3 center{};
    glm::vec3 axisX{};
    glm::vec3 axisY{};
    glm::vec3 axisZ{};
    glm::vec3 color{};
};

struct CylinderMeshVertex {
    glm::vec3 position{};
    glm::vec3 normal{};
};

enum class Representation : size_t { cylinders = 0, full = 1, ballstick = 2, stick = 3 };
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
};

struct StyledCylinder {
    std::string identity;
    glm::vec3 start{};
    glm::vec3 end{};
    float radius = 0.01F;
    ColorSet colors{};
};

struct StyledBox {
    std::string identity;
    glm::vec3 center{};
    glm::vec3 axisX{};
    glm::vec3 axisY{};
    glm::vec3 axisZ{};
    ColorSet colors{};
};

struct OwnerHandle {
    std::string token;
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
};

struct SceneData {
    std::array<RepresentationData, 4> representations;
    std::array<RepresentationData, 4> expandedRepresentations;
    bool hasExpanded = false;
    Representation initialRepresentation = Representation::full;
    Coloring initialColoring = Coloring::strand;
};

Representation representationFromName(const std::string& name) {
    if (name == "cylinders") return Representation::cylinders;
    if (name == "full") return Representation::full;
    if (name == "ballstick") return Representation::ballstick;
    if (name == "stick") return Representation::stick;
    throw std::runtime_error("Unknown VR representation: " + name);
}

Coloring coloringFromName(const std::string& name) {
    if (name == "strand") return Coloring::strand;
    if (name == "base") return Coloring::base;
    if (name == "cluster") return Coloring::cluster;
    if (name == "cpk") return Coloring::cpk;
    throw std::runtime_error("Unknown VR coloring: " + name);
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
        out vec3 vColor;
        void main() {
            gl_Position = uViewProjection * vec4(aPosition, 1.0);
            vColor = aColor;
        }
    )GLSL";
    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec3 vColor;
        out vec4 outColor;
        void main() {
            outColor = vec4(vColor, 1.0);
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
    throw std::runtime_error("OpenGL program link failed: " + log);
}

constexpr const char* kLitFragmentSource = R"GLSL(
    #version 330 core
    in vec3 vColor;
    in vec3 vNormal;
    in vec3 vWorldPosition;
    uniform sampler2DShadow uShadowMap;
    uniform mat4 uLightViewProjection;
    uniform vec3 uLightDirection;
    out vec4 outColor;

    float shadowVisibility(vec3 normal) {
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
        vec3 normal = normalize(vNormal);
        float diffuse = max(dot(normal, uLightDirection), 0.0);
        float lighting = 0.20 + 0.90 * diffuse * shadowVisibility(normal);
        outColor = vec4(vColor * lighting, 1.0);
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
        out vec3 vColor;
        out vec3 vNormal;
        out vec3 vWorldPosition;
        void main() {
            vec3 localPosition = aCenter + aUnitPosition * aRadius;
            vec4 worldPosition = uModel * vec4(localPosition, 1.0);
            gl_Position = uViewProjection * worldPosition;
            vNormal = normalize(mat3(uModel) * aUnitPosition);
            vWorldPosition = worldPosition.xyz;
            vColor = aColor;
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, kLitFragmentSource);
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
        layout(location = 4) in vec3 aColor;
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        out vec3 vColor;
        out vec3 vNormal;
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
                               + radial * aRadius;
            vec3 localNormal = basisX * aUnitNormal.x
                             + basisY * aUnitNormal.y
                             + axis * aUnitNormal.z;
            vec4 worldPosition = uModel * vec4(localPosition, 1.0);
            gl_Position = uViewProjection * worldPosition;
            vNormal = normalize(mat3(uModel) * localNormal);
            vWorldPosition = worldPosition.xyz;
            vColor = aColor;
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, kLitFragmentSource);
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
        uniform mat4 uViewProjection;
        uniform mat4 uModel;
        out vec3 vColor;
        out vec3 vNormal;
        out vec3 vWorldPosition;
        void main() {
            vec3 localPosition = aCenter
                + aAxisX * aUnitPosition.x
                + aAxisY * aUnitPosition.y
                + aAxisZ * aUnitPosition.z;
            vec3 localNormal = normalize(
                normalize(aAxisX) * aUnitNormal.x
                + normalize(aAxisY) * aUnitNormal.y
                + normalize(aAxisZ) * aUnitNormal.z);
            vec4 worldPosition = uModel * vec4(localPosition, 1.0);
            gl_Position = uViewProjection * worldPosition;
            vNormal = normalize(mat3(uModel) * localNormal);
            vWorldPosition = worldPosition.xyz;
            vColor = aColor;
        }
    )GLSL";

    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, kLitFragmentSource);
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

SceneData loadScene(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Could not open scene snapshot: " + path);

    std::string magic;
    int version = 0;
    std::string initialRepresentation;
    std::string initialColoring;
    input >> magic >> version >> initialRepresentation >> initialColoring;
    if (magic != "NADOCVR" || (version < 4 || version > 10)) {
        throw std::runtime_error("Unsupported NADOC VR scene format");
    }

    SceneData scene;
    scene.initialRepresentation = representationFromName(initialRepresentation);
    scene.initialColoring = coloringFromName(initialColoring);
    RepresentationData* active = nullptr;
    size_t activeIndex = 0;
    size_t legacyIdentityIndex = 0;
    std::array<std::array<std::unordered_set<std::string>, 4>, 2> identities;
    std::array<std::array<std::unordered_set<std::string>, 4>, 2> aliasIdentities;
    std::array<std::array<std::unordered_set<std::string>, 4>, 2> handleTokens;
    std::array<std::array<std::unordered_set<std::string>, 4>, 2> transformIdentities;
    size_t poseIndex = 0;
    auto readIdentity = [&](char recordType) {
        std::string identity;
        if (version >= 6) {
            input >> identity;
            if (identity.empty()) {
                throw std::runtime_error("VR primitive has an empty identity");
            }
            if (!identities[poseIndex][activeIndex].insert(identity).second) {
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
        if (type == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (type == 'R') {
            std::string name;
            input >> name;
            activeIndex = static_cast<size_t>(representationFromName(name));
            poseIndex = 0;
            active = &scene.representations[activeIndex];
        } else if (type == 'E' && version >= 7) {
            std::string name;
            input >> name;
            activeIndex = static_cast<size_t>(representationFromName(name));
            poseIndex = 1;
            scene.hasExpanded = true;
            active = &scene.expandedRepresentations[activeIndex];
        } else if (type == 'A' && version >= 8) {
            if (!active) {
                throw std::runtime_error(
                    "Owner aliases appear before representation block");
            }
            nadoc_vr::OwnerAliasEntry aliases;
            size_t count = 0;
            input >> aliases.identity >> count;
            if (aliases.identity.empty() || count == 0 || count > 8 ||
                !identities[poseIndex][activeIndex].contains(aliases.identity) ||
                !aliasIdentities[poseIndex][activeIndex]
                     .insert(aliases.identity).second) {
                throw std::runtime_error("Invalid VR primitive owner aliases");
            }
            aliases.tokens.resize(count);
            std::unordered_set<std::string> uniqueTokens;
            for (std::string& token : aliases.tokens) {
                input >> token;
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
                !handleTokens[poseIndex][activeIndex].insert(handle.token).second ||
                !std::isfinite(handle.center.x) || !std::isfinite(handle.center.y) ||
                !std::isfinite(handle.center.z)) {
                throw std::runtime_error("Invalid VR cluster handle");
            }
            active->ownerHandles.push_back(std::move(handle));
        } else if (type == 'T' && version >= 10) {
            if (!active) {
                throw std::runtime_error(
                    "Transform ownership appears before representation block");
            }
            TransformOwnership ownership;
            size_t count = 0;
            input >> ownership.identity >> count;
            if (ownership.identity.empty() || count == 0 || count > 8 ||
                !identities[poseIndex][activeIndex].contains(ownership.identity) ||
                !transformIdentities[poseIndex][activeIndex]
                     .insert(ownership.identity).second) {
                throw std::runtime_error("Invalid VR transform ownership");
            }
            ownership.owners.resize(count);
            std::unordered_set<std::string> uniqueTokens;
            for (TransformOwner& owner : ownership.owners) {
                input >> owner.token >> owner.startWeight >> owner.endWeight;
                if (owner.token.empty() || owner.token.size() > 2048 ||
                    !handleTokens[poseIndex][activeIndex].contains(owner.token) ||
                    !uniqueTokens.insert(owner.token).second ||
                    !std::isfinite(owner.startWeight) ||
                    !std::isfinite(owner.endWeight) ||
                    owner.startWeight < 0.0F || owner.startWeight > 1.0F ||
                    owner.endWeight < 0.0F || owner.endWeight > 1.0F) {
                    throw std::runtime_error("Invalid VR transform owner");
                }
            }
            active->transformOwnership.push_back(std::move(ownership));
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
    if (std::all_of(scene.representations.begin(), scene.representations.end(),
                    [](const RepresentationData& rep) {
                        return rep.points.empty() && rep.cylinders.empty()
                            && rep.halfCylinders.empty() && rep.boxes.empty();
                    })) {
        throw std::runtime_error("The scene snapshot contains no visible geometry");
    }
    if (scene.hasExpanded) {
        for (size_t index = 0; index < scene.representations.size(); ++index) {
            if (identities[0][index] != identities[1][index]) {
                throw std::runtime_error(
                    "Expanded VR pose does not match natural primitive identities");
            }
            if (scene.representations[index].ownerAliases !=
                scene.expandedRepresentations[index].ownerAliases) {
                throw std::runtime_error(
                    "Expanded VR pose does not match natural owner aliases");
            }
            if (handleTokens[0][index] != handleTokens[1][index]) {
                throw std::runtime_error(
                    "Expanded VR pose does not match natural cluster handles");
            }
            if (scene.representations[index].transformOwnership !=
                scene.expandedRepresentations[index].transformOwnership) {
                throw std::runtime_error(
                    "Expanded VR pose does not match natural transform ownership");
            }
        }
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
            for (float x : {-0.5F, 0.5F}) {
                for (float y : {-0.5F, 0.5F}) {
                    for (float z : {-0.5F, 0.5F}) {
                        include(box.center + box.axisX * x + box.axisY * y + box.axisZ * z);
                    }
                }
            }
        }
    }
    const glm::vec3 center = (lo + hi) * 0.5F;
    const glm::vec3 extent = hi - lo;
    const float maxExtent = std::max({extent.x, extent.y, extent.z, 1.0e-6F});
    const float scale = kViewSizeMeters / maxExtent;
    auto normalize = [&](RepresentationData& rep, bool appendViewerAxes) {
        for (StyledPoint& point : rep.points) {
            point.position = (point.position - center) * scale;
            point.position.z -= kViewDistanceMeters;
            point.size *= scale;
        }
        for (StyledCylinder& cylinder : rep.cylinders) {
            cylinder.start = (cylinder.start - center) * scale;
            cylinder.end = (cylinder.end - center) * scale;
            cylinder.start.z -= kViewDistanceMeters;
            cylinder.end.z -= kViewDistanceMeters;
            cylinder.radius *= scale;
        }
        for (StyledCylinder& cylinder : rep.halfCylinders) {
            cylinder.start = (cylinder.start - center) * scale;
            cylinder.end = (cylinder.end - center) * scale;
            cylinder.start.z -= kViewDistanceMeters;
            cylinder.end.z -= kViewDistanceMeters;
            cylinder.radius *= scale;
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

        if (!appendViewerAxes) return;
        const glm::vec3 origin(-0.28F, -0.28F, -kViewDistanceMeters);
        auto addAxis = [&](const char* name, glm::vec3 delta, glm::vec3 color) {
            ColorSet colors;
            colors.values.fill(color);
            rep.cylinders.push_back(
                StyledCylinder{name, origin, origin + delta, 0.003F, colors});
        };
        addAxis("viewer:axis:x", {0.10F, 0, 0}, {1.0F, 0.25F, 0.25F});
        addAxis("viewer:axis:y", {0, 0.10F, 0}, {0.25F, 1.0F, 0.35F});
        addAxis("viewer:axis:z", {0, 0, 0.10F}, {0.3F, 0.55F, 1.0F});
    };
    for (size_t index = 0; index < scene.representations.size(); ++index) {
        normalize(scene.representations[index], true);
        if (scene.hasExpanded) {
            normalize(scene.expandedRepresentations[index], true);
        }
    }
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

std::array<uint8_t, 7> glyph(char value) {
    switch (value) {
        case 'A': return {14, 17, 17, 31, 17, 17, 17};
        case 'B': return {30, 17, 17, 30, 17, 17, 30};
        case 'C': return {14, 17, 16, 16, 16, 17, 14};
        case 'D': return {30, 17, 17, 17, 17, 17, 30};
        case 'E': return {31, 16, 16, 30, 16, 16, 31};
        case 'F': return {31, 16, 16, 30, 16, 16, 16};
        case 'G': return {14, 17, 16, 23, 17, 17, 14};
        case 'H': return {17, 17, 17, 31, 17, 17, 17};
        case 'I': return {31, 4, 4, 4, 4, 4, 31};
        case 'K': return {17, 18, 20, 24, 20, 18, 17};
        case 'L': return {16, 16, 16, 16, 16, 16, 31};
        case 'M': return {17, 27, 21, 21, 17, 17, 17};
        case 'N': return {17, 25, 21, 19, 17, 17, 17};
        case 'O': return {14, 17, 17, 17, 17, 17, 14};
        case 'P': return {30, 17, 17, 30, 16, 16, 16};
        case 'R': return {30, 17, 17, 30, 20, 18, 17};
        case 'S': return {15, 16, 16, 14, 1, 1, 30};
        case 'T': return {31, 4, 4, 4, 4, 4, 4};
        case 'U': return {17, 17, 17, 17, 17, 17, 14};
        case 'V': return {17, 17, 17, 17, 17, 10, 4};
        case 'W': return {17, 17, 17, 21, 21, 21, 10};
        case 'X': return {17, 17, 10, 4, 10, 17, 17};
        case 'Y': return {17, 17, 10, 4, 4, 4, 4};
        case '+': return {0, 4, 4, 31, 4, 4, 0};
        default: return {};
    }
}

class GlScene {
  public:
    explicit GlScene(SceneData scene) : scene_(std::move(scene)) {
        program_ = makeProgram();
        viewProjection_ = glGetUniformLocation(program_, "uViewProjection");
        upload({}, lineVao_, lineVbo_);
        upload({}, guideVao_, guideVbo_, GL_DYNAMIC_DRAW);
        uploadSpheres();
        uploadCylinders();
        uploadHalfCylinders();
        uploadBoxes();
        initializeShadowMap();
        setStyle(scene_.initialRepresentation, scene_.initialColoring);
    }

    void setStyle(Representation representation, Coloring coloring) {
        representation_ = representation;
        coloring_ = coloring;
        const RepresentationData& source =
            expanded_ && scene_.hasExpanded
                ? scene_.expandedRepresentations[static_cast<size_t>(representation)]
                : scene_.representations[static_cast<size_t>(representation)];

        std::vector<Vertex> points;
        points.reserve(source.points.size());
        for (const StyledPoint& point : source.points) {
            points.push_back(Vertex{point.position, point.colors.get(coloring), point.size});
        }
        glBindBuffer(GL_ARRAY_BUFFER, sphereInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(points.size() * sizeof(Vertex)),
                     points.data(), GL_DYNAMIC_DRAW);
        sphereCount_ = static_cast<GLsizei>(points.size());

        std::vector<Cylinder> cylinders;
        cylinders.reserve(source.cylinders.size());
        for (const StyledCylinder& cylinder : source.cylinders) {
            cylinders.push_back(Cylinder{
                cylinder.start, cylinder.end, cylinder.radius, cylinder.colors.get(coloring)});
        }
        glBindBuffer(GL_ARRAY_BUFFER, cylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(cylinders.size() * sizeof(Cylinder)),
                     cylinders.data(), GL_DYNAMIC_DRAW);
        cylinderCount_ = static_cast<GLsizei>(cylinders.size());

        std::vector<Cylinder> halfCylinders;
        halfCylinders.reserve(source.halfCylinders.size());
        for (const StyledCylinder& cylinder : source.halfCylinders) {
            halfCylinders.push_back(Cylinder{
                cylinder.start, cylinder.end, cylinder.radius, cylinder.colors.get(coloring)});
        }
        glBindBuffer(GL_ARRAY_BUFFER, halfCylinderInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(halfCylinders.size() * sizeof(Cylinder)),
                     halfCylinders.data(), GL_DYNAMIC_DRAW);
        halfCylinderCount_ = static_cast<GLsizei>(halfCylinders.size());

        std::vector<Box> boxes;
        boxes.reserve(source.boxes.size());
        for (const StyledBox& box : source.boxes) {
            boxes.push_back(Box{
                box.center, box.axisX, box.axisY, box.axisZ, box.colors.get(coloring)});
        }
        glBindBuffer(GL_ARRAY_BUFFER, boxInstanceVbo_);
        glBufferData(GL_ARRAY_BUFFER,
                     static_cast<GLsizeiptr>(boxes.size() * sizeof(Box)),
                     boxes.data(), GL_DYNAMIC_DRAW);
        boxCount_ = static_cast<GLsizei>(boxes.size());

        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        auto include = [&](const glm::vec3& point, float radius = 0.0F) {
            lo = glm::min(lo, point - glm::vec3(radius));
            hi = glm::max(hi, point + glm::vec3(radius));
        };
        for (const StyledPoint& point : source.points) include(point.position, point.size);
        for (const StyledCylinder& cylinder : source.cylinders) {
            include(cylinder.start, cylinder.radius);
            include(cylinder.end, cylinder.radius);
        }
        for (const StyledCylinder& cylinder : source.halfCylinders) {
            include(cylinder.start, cylinder.radius);
            include(cylinder.end, cylinder.radius);
        }
        for (const StyledBox& box : source.boxes) {
            for (float x : {-0.5F, 0.5F}) {
                for (float y : {-0.5F, 0.5F}) {
                    for (float z : {-0.5F, 0.5F}) {
                        include(box.center + box.axisX * x + box.axisY * y + box.axisZ * z);
                    }
                }
            }
        }
        if (source.points.empty() && source.cylinders.empty()
            && source.halfCylinders.empty() && source.boxes.empty()) {
            localCenter_ = {0.0F, 0.0F, -kViewDistanceMeters};
            localRadius_ = 0.5F;
        } else {
            localCenter_ = (lo + hi) * 0.5F;
            localRadius_ = std::max(glm::length(hi - lo) * 0.5F, 0.01F);
        }
    }

    [[nodiscard]] Representation representation() const { return representation_; }
    [[nodiscard]] Coloring coloring() const { return coloring_; }
    [[nodiscard]] bool expanded() const { return expanded_; }
    void setExpanded(bool expanded) {
        if (expanded_ == expanded || (expanded && !scene_.hasExpanded)) return;
        expanded_ = expanded;
        setStyle(representation_, coloring_);
    }

    [[nodiscard]] std::optional<nadoc_vr::PickHit> pick(
        const nadoc_vr::Ray& worldRay, const glm::mat4& modelTransform) const {
        const glm::mat4 worldToModel = glm::inverse(modelTransform);
        nadoc_vr::Ray ray;
        ray.origin = glm::vec3(worldToModel * glm::vec4(worldRay.origin, 1.0F));
        ray.direction = glm::normalize(
            glm::vec3(worldToModel * glm::vec4(worldRay.direction, 0.0F)));
        const RepresentationData& source =
            expanded_ && scene_.hasExpanded
                ? scene_.expandedRepresentations[static_cast<size_t>(representation_)]
                : scene_.representations[static_cast<size_t>(representation_)];
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
            consider(point.identity, nadoc_vr::raySphere(ray, point.position, point.size));
        }
        for (const StyledCylinder& cylinder : source.cylinders) {
            consider(cylinder.identity, nadoc_vr::rayCapsule(
                ray, cylinder.start, cylinder.end, cylinder.radius));
        }
        for (const StyledCylinder& cylinder : source.halfCylinders) {
            consider(cylinder.identity, nadoc_vr::rayHalfCylinder(
                ray, cylinder.start, cylinder.end, cylinder.radius));
        }
        for (const StyledBox& box : source.boxes) {
            consider(box.identity, nadoc_vr::rayBox(
                ray, box.center, box.axisX, box.axisY, box.axisZ));
        }
        return nearest;
    }

    [[nodiscard]] std::optional<nadoc_vr::PickHit> anchor(
        const std::string& identity,
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform) const {
        if (identity.empty()) return std::nullopt;
        const RepresentationData& source =
            expanded_ && scene_.hasExpanded
                ? scene_.expandedRepresentations[static_cast<size_t>(representation_)]
                : scene_.representations[static_cast<size_t>(representation_)];
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
                return result(point.position, point.size);
            }
        }
        auto cylinderAnchor = [&](const std::vector<StyledCylinder>& cylinders)
            -> std::optional<nadoc_vr::PickHit> {
            for (const StyledCylinder& cylinder : cylinders) {
                if (cylinder.identity == resolvedIdentity) {
                    return result((cylinder.start + cylinder.end) * 0.5F, cylinder.radius);
                }
            }
            return std::nullopt;
        };
        if (auto found = cylinderAnchor(source.cylinders)) return found;
        if (auto found = cylinderAnchor(source.halfCylinders)) return found;
        for (const StyledBox& box : source.boxes) {
            if (box.identity == resolvedIdentity) {
                const float radius = 0.5F * std::min({
                    glm::length(box.axisX),
                    glm::length(box.axisY),
                    glm::length(box.axisZ),
                });
                return result(box.center, radius);
            }
        }
        return std::nullopt;
    }

    /** Bounds of every primitive carrying the most-specific available owner token.
     * Unlike anchor(), this describes the selected owner rather than one fallback
     * primitive, so tool affordances remain stable across representation changes. */
    [[nodiscard]] std::optional<nadoc_vr::BoundsSummary> ownerBounds(
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform) const {
        const RepresentationData& source =
            expanded_ && scene_.hasExpanded
                ? scene_.expandedRepresentations[static_cast<size_t>(representation_)]
                : scene_.representations[static_cast<size_t>(representation_)];
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
        if (identities.empty()) return std::nullopt;

        nadoc_vr::BoundsAccumulator bounds;
        for (const StyledPoint& point : source.points) {
            if (identities.contains(point.identity)) {
                bounds.includePoint(point.position, point.size);
            }
        }
        auto includeCylinders = [&](const std::vector<StyledCylinder>& cylinders) {
            for (const StyledCylinder& cylinder : cylinders) {
                if (identities.contains(cylinder.identity)) {
                    bounds.includeSegment(cylinder.start, cylinder.end, cylinder.radius);
                }
            }
        };
        includeCylinders(source.cylinders);
        includeCylinders(source.halfCylinders);
        for (const StyledBox& box : source.boxes) {
            if (identities.contains(box.identity)) {
                bounds.includeBox(box.center, box.axisX, box.axisY, box.axisZ);
            }
        }
        return bounds.summary(modelTransform);
    }

    /** Desktop-equivalent current gizmo center projected by scene v9. */
    [[nodiscard]] std::optional<glm::vec3> ownerHandle(
        const std::vector<std::string>& ownerTokens,
        const glm::mat4& modelTransform) const {
        const RepresentationData& source =
            expanded_ && scene_.hasExpanded
                ? scene_.expandedRepresentations[static_cast<size_t>(representation_)]
                : scene_.representations[static_cast<size_t>(representation_)];
        for (const std::string& token : ownerTokens) {
            const auto handle = std::find_if(
                source.ownerHandles.begin(), source.ownerHandles.end(),
                [&](const OwnerHandle& candidate) { return candidate.token == token; });
            if (handle != source.ownerHandles.end()) {
                return glm::vec3(modelTransform * glm::vec4(handle->center, 1.0F));
            }
        }
        return std::nullopt;
    }

    void renderShadowMap(const glm::mat4& modelTransform, glm::vec3 lightDirection) {
        lightDirection_ = glm::normalize(lightDirection);
        const glm::vec3 worldCenter = glm::vec3(
            modelTransform * glm::vec4(localCenter_, 1.0F));
        const float modelScale = std::max({
            glm::length(glm::vec3(modelTransform[0])),
            glm::length(glm::vec3(modelTransform[1])),
            glm::length(glm::vec3(modelTransform[2])),
        });
        const float radius = std::max(localRadius_ * modelScale * 1.08F, 0.02F);
        const glm::vec3 eye = worldCenter + lightDirection_ * (2.0F * radius);
        glm::vec3 up(0, 1, 0);
        if (std::abs(glm::dot(up, lightDirection_)) > 0.95F) up = {1, 0, 0};
        lightViewProjection_ = glm::ortho(
            -radius, radius, -radius, radius, radius * 0.05F, radius * 4.0F)
            * glm::lookAt(eye, worldCenter, up);

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
                GL_TRIANGLES, cylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr, cylinderCount_);
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
                GL_TRIANGLES, boxIndexCount_, GL_UNSIGNED_SHORT, nullptr, boxCount_);
        }
        glDisable(GL_POLYGON_OFFSET_FILL);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glBindVertexArray(0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    ~GlScene() {
        if (lineVbo_) glDeleteBuffers(1, &lineVbo_);
        if (guideVbo_) glDeleteBuffers(1, &guideVbo_);
        if (sphereMeshVbo_) glDeleteBuffers(1, &sphereMeshVbo_);
        if (sphereIndexVbo_) glDeleteBuffers(1, &sphereIndexVbo_);
        if (sphereInstanceVbo_) glDeleteBuffers(1, &sphereInstanceVbo_);
        if (cylinderInstanceVbo_) glDeleteBuffers(1, &cylinderInstanceVbo_);
        if (cylinderMeshVbo_) glDeleteBuffers(1, &cylinderMeshVbo_);
        if (cylinderIndexVbo_) glDeleteBuffers(1, &cylinderIndexVbo_);
        if (halfCylinderInstanceVbo_) glDeleteBuffers(1, &halfCylinderInstanceVbo_);
        if (halfCylinderMeshVbo_) glDeleteBuffers(1, &halfCylinderMeshVbo_);
        if (halfCylinderIndexVbo_) glDeleteBuffers(1, &halfCylinderIndexVbo_);
        if (boxInstanceVbo_) glDeleteBuffers(1, &boxInstanceVbo_);
        if (boxMeshVbo_) glDeleteBuffers(1, &boxMeshVbo_);
        if (boxIndexVbo_) glDeleteBuffers(1, &boxIndexVbo_);
        if (lineVao_) glDeleteVertexArrays(1, &lineVao_);
        if (guideVao_) glDeleteVertexArrays(1, &guideVao_);
        if (sphereVao_) glDeleteVertexArrays(1, &sphereVao_);
        if (cylinderVao_) glDeleteVertexArrays(1, &cylinderVao_);
        if (halfCylinderVao_) glDeleteVertexArrays(1, &halfCylinderVao_);
        if (boxVao_) glDeleteVertexArrays(1, &boxVao_);
        if (program_) glDeleteProgram(program_);
        if (sphereProgram_) glDeleteProgram(sphereProgram_);
        if (cylinderProgram_) glDeleteProgram(cylinderProgram_);
        if (boxProgram_) glDeleteProgram(boxProgram_);
        if (shadowTexture_) glDeleteTextures(1, &shadowTexture_);
        if (shadowFramebuffer_) glDeleteFramebuffers(1, &shadowFramebuffer_);
    }

    void render(const glm::mat4& viewProjection, const glm::mat4& modelTransform,
                const std::vector<Vertex>& guides) const {
        glUseProgram(program_);
        const glm::mat4 modelViewProjection = viewProjection * modelTransform;
        glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &modelViewProjection[0][0]);
        glBindVertexArray(lineVao_);
        glLineWidth(1.5F);
        glDrawArrays(GL_LINES, 0, lineCount_);

        if (sphereCount_ > 0) {
            glUseProgram(sphereProgram_);
            glUniformMatrix4fv(sphereViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(sphereModel_, 1, GL_FALSE, &modelTransform[0][0]);
            applyLightingUniforms(
                sphereLightViewProjection_, sphereLightDirection_, sphereShadowMap_);
            glBindVertexArray(sphereVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, sphereIndexCount_, GL_UNSIGNED_SHORT, nullptr, sphereCount_);
        }

        if (cylinderCount_ > 0) {
            glUseProgram(cylinderProgram_);
            glUniformMatrix4fv(cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
            applyLightingUniforms(
                cylinderLightViewProjection_, cylinderLightDirection_, cylinderShadowMap_);
            glBindVertexArray(cylinderVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, cylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr, cylinderCount_);
        }

        if (halfCylinderCount_ > 0) {
            glUseProgram(cylinderProgram_);
            glUniformMatrix4fv(cylinderViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(cylinderModel_, 1, GL_FALSE, &modelTransform[0][0]);
            applyLightingUniforms(
                cylinderLightViewProjection_, cylinderLightDirection_, cylinderShadowMap_);
            glBindVertexArray(halfCylinderVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, halfCylinderIndexCount_, GL_UNSIGNED_SHORT, nullptr,
                halfCylinderCount_);
        }

        if (boxCount_ > 0) {
            glUseProgram(boxProgram_);
            glUniformMatrix4fv(boxViewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glUniformMatrix4fv(boxModel_, 1, GL_FALSE, &modelTransform[0][0]);
            applyLightingUniforms(boxLightViewProjection_, boxLightDirection_, boxShadowMap_);
            glBindVertexArray(boxVao_);
            glDrawElementsInstanced(
                GL_TRIANGLES, boxIndexCount_, GL_UNSIGNED_SHORT, nullptr, boxCount_);
        }

        if (!guides.empty()) {
            glDisable(GL_DEPTH_TEST);
            glUseProgram(program_);
            glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
            glBindBuffer(GL_ARRAY_BUFFER, guideVbo_);
            glBufferData(GL_ARRAY_BUFFER,
                         static_cast<GLsizeiptr>(guides.size() * sizeof(Vertex)),
                         guides.data(), GL_DYNAMIC_DRAW);
            glBindVertexArray(guideVao_);
            glLineWidth(3.0F);
            glDrawArrays(GL_LINES, 0, static_cast<GLsizei>(guides.size()));
            glEnable(GL_DEPTH_TEST);
        }
        glBindVertexArray(0);
        glUseProgram(0);
    }

  private:
    void applyLightingUniforms(
        GLint lightProjection, GLint lightDirection, GLint shadowMap) const {
        glUniformMatrix4fv(
            lightProjection, 1, GL_FALSE, &lightViewProjection_[0][0]);
        glUniform3fv(lightDirection, 1, &lightDirection_[0]);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, shadowTexture_);
        glUniform1i(shadowMap, 0);
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

        constexpr float goldenRatio = 1.6180339887498948482F;
        std::vector<glm::vec3> mesh = {
            {-1, goldenRatio, 0}, {1, goldenRatio, 0},
            {-1, -goldenRatio, 0}, {1, -goldenRatio, 0},
            {0, -1, goldenRatio}, {0, 1, goldenRatio},
            {0, -1, -goldenRatio}, {0, 1, -goldenRatio},
            {goldenRatio, 0, -1}, {goldenRatio, 0, 1},
            {-goldenRatio, 0, -1}, {-goldenRatio, 0, 1},
        };
        for (glm::vec3& vertex : mesh) vertex = glm::normalize(vertex);
        static constexpr std::array<GLushort, 60> indices = {
            0, 11, 5,  0, 5, 1,   0, 1, 7,   0, 7, 10,  0, 10, 11,
            1, 5, 9,   5, 11, 4,  11, 10, 2, 10, 7, 6,   7, 1, 8,
            3, 9, 4,   3, 4, 2,   3, 2, 6,   3, 6, 8,    3, 8, 9,
            4, 9, 5,   2, 4, 11,  6, 2, 10,  8, 6, 7,    9, 8, 1,
        };
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
    }

    void uploadCylinders() {
        cylinderProgram_ = makeCylinderProgram();
        cylinderViewProjection_ = glGetUniformLocation(cylinderProgram_, "uViewProjection");
        cylinderModel_ = glGetUniformLocation(cylinderProgram_, "uModel");
        cylinderLightViewProjection_ =
            glGetUniformLocation(cylinderProgram_, "uLightViewProjection");
        cylinderLightDirection_ = glGetUniformLocation(cylinderProgram_, "uLightDirection");
        cylinderShadowMap_ = glGetUniformLocation(cylinderProgram_, "uShadowMap");

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
    }

    void uploadBoxes() {
        boxProgram_ = makeBoxProgram();
        boxViewProjection_ = glGetUniformLocation(boxProgram_, "uViewProjection");
        boxModel_ = glGetUniformLocation(boxProgram_, "uModel");
        boxLightViewProjection_ = glGetUniformLocation(boxProgram_, "uLightViewProjection");
        boxLightDirection_ = glGetUniformLocation(boxProgram_, "uLightDirection");
        boxShadowMap_ = glGetUniformLocation(boxProgram_, "uShadowMap");

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
    SceneData scene_;
    Representation representation_ = Representation::full;
    Coloring coloring_ = Coloring::strand;
    bool expanded_ = false;
    GLuint lineVao_ = 0;
    GLuint lineVbo_ = 0;
    GLuint guideVao_ = 0;
    GLuint guideVbo_ = 0;
    GLuint sphereProgram_ = 0;
    GLuint sphereVao_ = 0;
    GLuint sphereMeshVbo_ = 0;
    GLuint sphereIndexVbo_ = 0;
    GLuint sphereInstanceVbo_ = 0;
    GLuint cylinderProgram_ = 0;
    GLuint cylinderVao_ = 0;
    GLuint cylinderMeshVbo_ = 0;
    GLuint cylinderIndexVbo_ = 0;
    GLuint cylinderInstanceVbo_ = 0;
    GLuint halfCylinderVao_ = 0;
    GLuint halfCylinderMeshVbo_ = 0;
    GLuint halfCylinderIndexVbo_ = 0;
    GLuint halfCylinderInstanceVbo_ = 0;
    GLuint boxProgram_ = 0;
    GLuint boxVao_ = 0;
    GLuint boxMeshVbo_ = 0;
    GLuint boxIndexVbo_ = 0;
    GLuint boxInstanceVbo_ = 0;
    GLuint shadowFramebuffer_ = 0;
    GLuint shadowTexture_ = 0;
    GLint viewProjection_ = -1;
    GLint sphereViewProjection_ = -1;
    GLint sphereModel_ = -1;
    GLint sphereLightViewProjection_ = -1;
    GLint sphereLightDirection_ = -1;
    GLint sphereShadowMap_ = -1;
    GLint cylinderViewProjection_ = -1;
    GLint cylinderModel_ = -1;
    GLint cylinderLightViewProjection_ = -1;
    GLint cylinderLightDirection_ = -1;
    GLint cylinderShadowMap_ = -1;
    GLint boxViewProjection_ = -1;
    GLint boxModel_ = -1;
    GLint boxLightViewProjection_ = -1;
    GLint boxLightDirection_ = -1;
    GLint boxShadowMap_ = -1;
    GLsizei lineCount_ = 0;
    GLsizei sphereIndexCount_ = 0;
    GLsizei sphereCount_ = 0;
    GLsizei cylinderIndexCount_ = 0;
    GLsizei cylinderCount_ = 0;
    GLsizei halfCylinderIndexCount_ = 0;
    GLsizei halfCylinderCount_ = 0;
    GLsizei boxIndexCount_ = 0;
    GLsizei boxCount_ = 0;
    glm::vec3 localCenter_{0.0F, 0.0F, -kViewDistanceMeters};
    float localRadius_ = 0.5F;
    glm::mat4 lightViewProjection_{1.0F};
    glm::vec3 lightDirection_{-0.577F, 0.577F, 0.577F};
    static constexpr GLsizei kShadowMapSize = 2048;
};

class Viewer {
  public:
    explicit Viewer(SceneData scene, std::string eventPath = {},
                    std::string feedbackPath = {},
                    std::string selectionLevel = "default",
                    std::vector<std::string> selectedOwnerTokens = {},
                    std::string selectedSelectionKind = "none")
        : sceneData_(std::move(scene)), eventPath_(std::move(eventPath)),
          feedbackPath_(std::move(feedbackPath)),
          selectionLevel_(std::move(selectionLevel)) {
        const RepresentationData& initial = sceneData_.representations[
            static_cast<size_t>(sceneData_.initialRepresentation)];
        const auto identity = nadoc_vr::resolveOwnerIdentity(
            initial.ownerAliases, selectedOwnerTokens);
        if (identity && selectedSelectionKind != "none") {
            selectedIdentity_ = *identity;
            selectedOwnerTokens_ = std::move(selectedOwnerTokens);
            selectedSelectionKind_ = std::move(selectedSelectionKind);
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
        glScene_.reset();
        for (Swapchain& swapchain : swapchains_) {
            if (swapchain.depth) glDeleteRenderbuffers(1, &swapchain.depth);
            if (swapchain.handle != XR_NULL_HANDLE) xrDestroySwapchain(swapchain.handle);
        }
        if (framebuffer_) glDeleteFramebuffers(1, &framebuffer_);
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
        window_ = glfwCreateWindow(
            720, 180,
            "NADOC VR — trigger grab · trackpad select · right grip expand · menu options",
            nullptr, nullptr);
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
                         const std::array<const char*, 12>& componentPaths) {
        std::vector<XrActionSuggestedBinding> bindings;
        bindings.reserve(componentPaths.size());
        for (size_t hand = 0; hand < handPaths_.size(); ++hand) {
            const size_t offset = hand * 6U;
            const std::array<XrAction, 6> actions = {
                poseAction_, triggerAction_, menuAction_, gripAction_,
                selectAction_, hapticAction_};
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
        triggerAction_ = createAction(XR_ACTION_TYPE_FLOAT_INPUT, "grab", "Grab model");
        menuAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "vr_menu", "VR menu");
        gripAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "expanded_view", "Expanded Quick View");
        selectAction_ = createAction(
            XR_ACTION_TYPE_BOOLEAN_INPUT, "select_element", "Select element");
        hapticAction_ = createAction(
            XR_ACTION_TYPE_VIBRATION_OUTPUT, "haptic", "Navigation haptic");

        suggestBindings(
            "/interaction_profiles/htc/vive_controller",
            {"/user/hand/left/input/grip/pose",
             "/user/hand/left/input/trigger/value",
             "/user/hand/left/input/menu/click",
             nullptr,
             nullptr,
             "/user/hand/left/output/haptic",
             "/user/hand/right/input/grip/pose",
             "/user/hand/right/input/trigger/value",
             "/user/hand/right/input/menu/click",
             "/user/hand/right/input/squeeze/click",
             "/user/hand/right/input/trackpad/click",
             "/user/hand/right/output/haptic"});
        suggestBindings(
            "/interaction_profiles/khr/simple_controller",
            {"/user/hand/left/input/grip/pose",
             "/user/hand/left/input/select/click",
             "/user/hand/left/input/menu/click",
             nullptr,
             nullptr,
             "/user/hand/left/output/haptic",
             "/user/hand/right/input/grip/pose",
             "/user/hand/right/input/select/click",
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
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24,
                                  swapchain.width, swapchain.height);
        }

        glGenFramebuffers(1, &framebuffer_);
        glScene_ = std::make_unique<GlScene>(std::move(sceneData_));
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

    glm::vec3 menuWorld(float x, float y, float z = 0.0F) const {
        return menuPosition_ + menuOrientation_ * glm::vec3(x, y, z);
    }

    void appendMenuText(const std::string& text, float x, float y, float scale,
                        const glm::vec3& color) {
        for (size_t character = 0; character < text.size(); ++character) {
            const auto rows = glyph(static_cast<char>(
                std::toupper(static_cast<unsigned char>(text[character]))));
            for (size_t row = 0; row < rows.size(); ++row) {
                for (int column = 0; column < 5; ++column) {
                    if ((rows[row] & (1U << (4 - column))) == 0) continue;
                    const float px = x + static_cast<float>(character * 6U + column) * scale;
                    const float py = y - static_cast<float>(row) * scale;
                    controllerGuides_.push_back(
                        Vertex{menuWorld(px, py, 0.002F), color, 1.0F});
                    controllerGuides_.push_back(
                        Vertex{menuWorld(px + scale * 0.82F, py, 0.002F), color, 1.0F});
                }
            }
        }
    }

    enum class MenuPage { options, tools };

    struct MenuItem {
        const char* label;
        float x;
        float y;
        float halfWidth;
    };
    static constexpr std::array<const char*, 7> kSelectionLevels = {
        "default", "cluster", "strand", "domain", "end", "xover", "base",
    };
    static constexpr std::array<MenuItem, 18> kOptionsMenuItems = {{
        {"CYLINDERS", -0.16F, 0.190F, 0.145F},
        {"FULL", -0.16F, 0.135F, 0.145F},
        {"BALL + STICK", -0.16F, 0.080F, 0.145F},
        {"STICK ONLY", -0.16F, 0.025F, 0.145F},
        {"STRAND", 0.16F, 0.190F, 0.145F},
        {"BASE", 0.16F, 0.135F, 0.145F},
        {"CLUSTER", 0.16F, 0.080F, 0.145F},
        {"CPK", 0.16F, 0.025F, 0.145F},
        {"AUTO / DRILL", -0.16F, -0.105F, 0.145F},
        {"CLUSTER", -0.16F, -0.160F, 0.145F},
        {"STRAND", -0.16F, -0.215F, 0.145F},
        {"DOMAIN", -0.16F, -0.270F, 0.145F},
        {"END", 0.16F, -0.105F, 0.145F},
        {"CROSSOVER", 0.16F, -0.160F, 0.145F},
        {"BASE", 0.16F, -0.215F, 0.145F},
        {"TOOLS", -0.16F, -0.350F, 0.145F},
        {"RECENTER", 0.16F, -0.350F, 0.145F},
        {"CLOSE", 0.0F, -0.415F, 0.305F},
    }};
    static constexpr std::array<MenuItem, 10> kToolMenuItems = {{
        {"INSPECT", -0.16F, 0.190F, 0.145F},
        {"MOVE ROTATE", -0.16F, 0.135F, 0.145F},
        {"EXTRUDE", -0.16F, 0.080F, 0.145F},
        {"TWIST", -0.16F, 0.025F, 0.145F},
        {"BEND", -0.16F, -0.030F, 0.145F},
        {"PREVIEW", 0.16F, 0.190F, 0.145F},
        {"CONFIRM", 0.16F, 0.135F, 0.145F},
        {"CANCEL", 0.16F, 0.080F, 0.145F},
        {"UNDO", 0.16F, 0.025F, 0.145F},
        {"BACK", 0.0F, -0.260F, 0.305F},
    }};

    void appendMenuGuides() {
        if (!menuOpen_) return;
        auto line = [&](const glm::vec3& a, const glm::vec3& b, const glm::vec3& color) {
            controllerGuides_.push_back(Vertex{a, color, 1.0F});
            controllerGuides_.push_back(Vertex{b, color, 1.0F});
        };
        auto itemBox = [&](const MenuItem& item, const glm::vec3& color) {
            const float left = item.x - item.halfWidth;
            const float right = item.x + item.halfWidth;
            line(menuWorld(left, item.y + 0.023F),
                 menuWorld(right, item.y + 0.023F), color * 0.7F);
            line(menuWorld(right, item.y + 0.023F),
                 menuWorld(right, item.y - 0.023F), color * 0.7F);
            line(menuWorld(right, item.y - 0.023F),
                 menuWorld(left, item.y - 0.023F), color * 0.7F);
            line(menuWorld(left, item.y - 0.023F),
                 menuWorld(left, item.y + 0.023F), color * 0.7F);
            appendMenuText(
                item.label, left + 0.012F, item.y + 0.012F, 0.0036F, color);
        };
        const glm::vec3 border(0.22F, 0.42F, 0.62F);
        line(menuWorld(-0.33F, 0.33F), menuWorld(0.33F, 0.33F), border);
        line(menuWorld(0.33F, 0.33F), menuWorld(0.33F, -0.455F), border);
        line(menuWorld(0.33F, -0.455F), menuWorld(-0.33F, -0.455F), border);
        line(menuWorld(-0.33F, -0.455F), menuWorld(-0.33F, 0.33F), border);
        appendMenuText(
            menuPage_ == MenuPage::options ? "VR MENU" : "VR TOOLS READ ONLY",
            menuPage_ == MenuPage::options ? -0.105F : -0.235F,
            0.305F, 0.006F, {0.65F, 0.88F, 1.0F});

        if (menuPage_ == MenuPage::tools) {
            appendMenuText("TOOL", -0.305F, 0.255F, 0.0042F, {0.42F, 0.72F, 0.95F});
            appendMenuText("TRANSACTION", 0.015F, 0.255F, 0.0042F,
                           {0.42F, 0.72F, 0.95F});
            appendMenuText("SELECTION " + selectionLevel_, -0.305F, -0.115F,
                           0.0038F, {0.65F, 0.70F, 0.78F});
            appendMenuText("STATUS " + toolShell_.status(), -0.305F, -0.165F,
                           0.0038F, {0.95F, 0.72F, 0.28F});
            for (size_t index = 0; index < kToolMenuItems.size(); ++index) {
                const bool selected = index < 5 &&
                    static_cast<size_t>(toolShell_.mode()) == index;
                glm::vec3 color = selected ? glm::vec3(0.30F, 1.0F, 0.48F)
                                           : glm::vec3(0.65F, 0.70F, 0.78F);
                if (static_cast<int>(index) == menuHover_) color = {1.0F, 0.78F, 0.22F};
                itemBox(kToolMenuItems[index], color);
            }
            return;
        }

        appendMenuText("REPRESENTATION", -0.305F, 0.255F, 0.0042F, {0.42F, 0.72F, 0.95F});
        appendMenuText("COLORING", 0.015F, 0.255F, 0.0042F, {0.42F, 0.72F, 0.95F});
        appendMenuText("SELECTION LEVEL", -0.305F, -0.035F, 0.0042F, {0.42F, 0.72F, 0.95F});

        const int selectedRepresentation = static_cast<int>(glScene_->representation());
        const int selectedColoring = static_cast<int>(glScene_->coloring());
        for (size_t index = 0; index < kOptionsMenuItems.size(); ++index) {
            const bool selected = (index < 4 && static_cast<int>(index) == selectedRepresentation)
                || (index >= 4 && index < 8
                    && static_cast<int>(index - 4) == selectedColoring)
                || (index >= 8 && index < 15
                    && selectionLevel_ == kSelectionLevels[index - 8]);
            glm::vec3 color = selected ? glm::vec3(0.30F, 1.0F, 0.48F)
                                       : glm::vec3(0.65F, 0.70F, 0.78F);
            if (static_cast<int>(index) == menuHover_) color = {1.0F, 0.78F, 0.22F};
            itemBox(kOptionsMenuItems[index], color);
        }
    }

    int menuHit(const nadoc_vr::HandPose& hand) const {
        if (!menuOpen_ || !hand.valid) return -1;
        const glm::vec3 direction = hand.orientation * glm::vec3(0, 0, -1);
        const glm::vec3 normal = menuOrientation_ * glm::vec3(0, 0, 1);
        const float denominator = glm::dot(direction, normal);
        if (std::abs(denominator) < 1.0e-5F) return -1;
        const float distance = glm::dot(menuPosition_ - hand.position, normal) / denominator;
        if (distance <= 0.0F || distance > 5.0F) return -1;
        const glm::vec3 local = glm::inverse(menuOrientation_)
                              * (hand.position + direction * distance - menuPosition_);
        const MenuItem* items = menuPage_ == MenuPage::options
            ? kOptionsMenuItems.data() : kToolMenuItems.data();
        const size_t itemCount = menuPage_ == MenuPage::options
            ? kOptionsMenuItems.size() : kToolMenuItems.size();
        for (size_t index = 0; index < itemCount; ++index) {
            const MenuItem& item = items[index];
            if (std::abs(local.x - item.x) <= item.halfWidth &&
                std::abs(local.y - item.y) <= 0.025F) {
                return static_cast<int>(index);
            }
        }
        return -1;
    }

    void processMenuInput() {
        menuHover_ = -1;
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            const int hit = menuHit(hands_[hand]);
            if (hit >= 0 && menuHover_ < 0) menuHover_ = hit;
            if (hit < 0 || !triggerClicked_[hand]) continue;
            if (menuPage_ == MenuPage::tools) {
                if (hit < 5) {
                    const auto mode = static_cast<nadoc_vr::ToolMode>(hit);
                    toolShell_.activate(mode, selectedSelectionKind_);
                    pendingToolTransform_.cancel();
                    publishToolIntent(nadoc_vr::ToolAction::activate);
                } else if (hit < 9) {
                    const auto action = static_cast<nadoc_vr::ToolAction>(hit - 4);
                    toolShell_.apply(action, selectedSelectionKind_);
                    if (action == nadoc_vr::ToolAction::preview &&
                        toolShell_.previewRequested()) {
                        pendingToolTransform_.activate();
                    } else if (action == nadoc_vr::ToolAction::cancel) {
                        pendingToolTransform_.cancel();
                    }
                    publishToolIntent(action);
                } else {
                    menuPage_ = MenuPage::options;
                    menuHover_ = -1;
                }
                pulse(hand, 0.50F);
                continue;
            }
            if (hit < 4) {
                glScene_->setStyle(static_cast<Representation>(hit), glScene_->coloring());
            } else if (hit < 8) {
                glScene_->setStyle(
                    glScene_->representation(), static_cast<Coloring>(hit - 4));
            } else if (hit < 15) {
                publishSelectionLevel(kSelectionLevels[hit - 8]);
            } else if (hit == 15) {
                menuPage_ = MenuPage::tools;
                menuHover_ = -1;
            } else if (hit == 16) {
                recenterRequested_ = true;
                recenterHand_ = hand;
                menuOpen_ = false;
                menuHover_ = -1;
                suppressManipulationUntilRelease_ = true;
            } else {
                menuOpen_ = false;
                menuHover_ = -1;
                suppressManipulationUntilRelease_ = true;
            }
            pulse(hand, 0.50F);
        }
    }

    void updateControllerGuides() {
        controllerGuides_.clear();
        auto line = [&](const glm::vec3& a, const glm::vec3& b, const glm::vec3& color) {
            controllerGuides_.push_back(Vertex{a, color, 1.0F});
            controllerGuides_.push_back(Vertex{b, color, 1.0F});
        };
        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            if (!hands_[hand].valid) continue;
            glm::vec3 color = hand == 0U
                ? glm::vec3(0.20F, 0.75F, 1.0F)
                : glm::vec3(1.0F, 0.55F, 0.18F);
            if (hands_[hand].pressed) color = {0.35F, 1.0F, 0.42F};
            if (hand == 1U && pendingToolTransform_.dragging()) {
                color = {1.0F, 0.72F, 0.18F};
            }
            if (hand == 1U && gripPressed_) color = {0.35F, 0.95F, 1.0F};
            if (manipulator_.mode() == nadoc_vr::ManipulationMode::two_hand) {
                color = {0.95F, 0.35F, 1.0F};
            }
            const glm::vec3 origin = hands_[hand].position;
            const glm::vec3 forward = hands_[hand].orientation * glm::vec3(0, 0, -1);
            const glm::vec3 right = hands_[hand].orientation * glm::vec3(1, 0, 0);
            const glm::vec3 up = hands_[hand].orientation * glm::vec3(0, 1, 0);
            const glm::vec3 tip = hand == 1U && sceneHover_ && !menuOpen_
                ? sceneHover_->position
                : origin + forward * (menuOpen_ ? 1.2F : 0.18F);
            line(origin - forward * 0.045F, origin, color * 0.65F);
            line(origin, tip, color);
            line(tip - right * 0.008F, tip + right * 0.008F, color);
            line(tip - up * 0.008F, tip + up * 0.008F, color);
        }
        if (hands_[0].valid && hands_[1].valid &&
            manipulator_.mode() == nadoc_vr::ManipulationMode::two_hand) {
            line(hands_[0].position, hands_[1].position, {0.95F, 0.35F, 1.0F});
        }
        if (sceneHover_ && !menuOpen_) {
            constexpr float markerRadius = 0.009F;
            const glm::vec3 center = sceneHover_->position;
            const glm::vec3 color(0.35F, 0.95F, 1.0F);
            line(center - glm::vec3(markerRadius, 0, 0),
                 center + glm::vec3(markerRadius, 0, 0), color);
            line(center - glm::vec3(0, markerRadius, 0),
                 center + glm::vec3(0, markerRadius, 0), color);
            line(center - glm::vec3(0, 0, markerRadius),
                 center + glm::vec3(0, 0, markerRadius), color);
        }
        if (!menuOpen_) {
            const auto anchor = glScene_->anchor(
                selectedIdentity_, selectedOwnerTokens_, manipulator_.transform());
            if (anchor) {
                const float markerRadius = anchor->distance + 0.006F;
                const glm::vec3 center = anchor->position;
                const glm::vec3 color(0.30F, 1.0F, 0.48F);
                line(center - glm::vec3(markerRadius, 0, 0),
                     center + glm::vec3(markerRadius, 0, 0), color);
                line(center - glm::vec3(0, markerRadius, 0),
                     center + glm::vec3(0, markerRadius, 0), color);
                line(center - glm::vec3(0, 0, markerRadius),
                     center + glm::vec3(0, 0, markerRadius), color);
            }
            if (toolShell_.mode() == nadoc_vr::ToolMode::move_rotate &&
                toolShell_.previewRequested() && selectedSelectionKind_ == "cluster") {
                const glm::mat4 previewTransform = manipulator_.transform()
                                                 * pendingToolTransform_.transform();
                const auto bounds = glScene_->ownerBounds(
                    selectedOwnerTokens_, previewTransform);
                if (bounds) {
                    const glm::vec3 center = glScene_->ownerHandle(
                        selectedOwnerTokens_, previewTransform)
                        .value_or(bounds->center);
                    const float handleRadius = glm::clamp(
                        bounds->radius * 0.20F, 0.050F, 0.220F);
                    line(center - glm::vec3(handleRadius, 0, 0),
                         center + glm::vec3(handleRadius, 0, 0), {1.0F, 0.25F, 0.20F});
                    line(center - glm::vec3(0, handleRadius, 0),
                         center + glm::vec3(0, handleRadius, 0), {0.25F, 1.0F, 0.35F});
                    line(center - glm::vec3(0, 0, handleRadius),
                         center + glm::vec3(0, 0, handleRadius), {0.25F, 0.55F, 1.0F});
                }
            }
        }
        appendMenuGuides();
    }

    void updateSceneHover() {
        const std::string previous = sceneHover_ ? sceneHover_->identity : "";
        sceneHover_.reset();
        if (!menuOpen_ && !menuOpenRequested_ && hands_[1].valid &&
            !triggerPressed_[0] && !triggerPressed_[1]) {
            const glm::vec3 direction = hands_[1].orientation * glm::vec3(0, 0, -1);
            sceneHover_ = glScene_->pick(
                nadoc_vr::Ray{hands_[1].position, glm::normalize(direction)},
                manipulator_.transform());
        }
        const std::string current = sceneHover_ ? sceneHover_->identity : "";
        if (current != previous) {
            publishHover(current);
            if (!current.empty()) std::cout << "VR hover: " << current << '\n';
        }
    }

    void publishHover(const std::string& identity) {
        publishedHoverIdentity_ = identity;
        publishEventState();
    }

    void publishSelect(const std::string& identity) {
        lastSelectIdentity_ = identity;
        ++selectSequence_;
        publishEventState();
    }

    void publishSelectionLevel(const std::string& level) {
        selectionLevel_ = level;
        ++levelSequence_;
        publishEventState();
    }

    void publishToolIntent(nadoc_vr::ToolAction action) {
        lastToolAction_ = action;
        ++toolSequence_;
        publishEventState();
    }

    void publishEventState() {
        if (eventPath_.empty()) return;
        std::ofstream output(eventPath_, std::ios::out | std::ios::trunc);
        if (!output) return;
        auto identity = [&](const std::string& value) {
            if (value.empty()) output << "null";
            else output << '\"' << value << '\"';
        };
        output << "{\"sequence\":" << ++eventSequence_ << ",\"hover_identity\":";
        identity(publishedHoverIdentity_);
        output << ",\"select_sequence\":" << selectSequence_
               << ",\"select_identity\":";
        identity(lastSelectIdentity_);
        output << ",\"level_sequence\":" << levelSequence_
               << ",\"selection_level\":\"" << selectionLevel_ << "\"";
        output << ",\"tool_sequence\":" << toolSequence_
               << ",\"tool_mode\":\"" << nadoc_vr::toolModeName(toolShell_.mode())
               << "\",\"tool_action\":\""
               << nadoc_vr::toolActionName(lastToolAction_) << "\"";
        output << '}';
    }

    void pollSelectionFeedback() {
        if (feedbackPath_.empty() || (++feedbackPollFrame_ % 3U) != 0U) return;
        std::ifstream input(feedbackPath_, std::ios::in | std::ios::binary);
        if (!input) return;
        input.seekg(0, std::ios::end);
        const std::streamoff size = input.tellg();
        if (size < 0 || size > 4096) return;
        input.seekg(0);
        std::string record(static_cast<size_t>(size), '\0');
        input.read(record.data(), size);
        const auto feedback = nadoc_vr::parseSelectionFeedback(
            record, feedbackSequence_, selectSequence_);
        if (!feedback) return;
        feedbackSequence_ = feedback->sequence;
        const std::vector<std::string> previousOwnerTokens = selectedOwnerTokens_;
        const std::string previousSelectionKind = selectedSelectionKind_;
        selectionLevel_ = feedback->level;
        selectedIdentity_ = feedback->accepted && feedback->selected
            ? feedback->identity : "";
        selectedOwnerTokens_ = feedback->accepted && feedback->selected
            ? feedback->ownerTokens : std::vector<std::string>{};
        selectedSelectionKind_ = feedback->accepted && feedback->selected
            ? feedback->selectionKind : "none";
        toolShell_.syncSelection(selectedSelectionKind_);
        if (selectedOwnerTokens_ != previousOwnerTokens ||
            selectedSelectionKind_ != previousSelectionKind ||
            !toolShell_.previewRequested()) {
            pendingToolTransform_.cancel();
        }
    }

    void syncActions(XrTime displayTime) {
        triggerClicked_.fill(false);
        if (sessionState_ != XR_SESSION_STATE_FOCUSED) return;
        XrActiveActionSet active{actionSet_, XR_NULL_PATH};
        XrActionsSyncInfo syncInfo{XR_TYPE_ACTIONS_SYNC_INFO};
        syncInfo.countActiveActionSets = 1;
        syncInfo.activeActionSets = &active;
        checkXr(instance_, xrSyncActions(session_, &syncInfo), "xrSyncActions");

        for (size_t hand = 0; hand < hands_.size(); ++hand) {
            hands_[hand].valid = false;
            XrActionStateGetInfo getInfo{XR_TYPE_ACTION_STATE_GET_INFO};
            getInfo.subactionPath = handPaths_[hand];

            getInfo.action = triggerAction_;
            XrActionStateFloat trigger{XR_TYPE_ACTION_STATE_FLOAT};
            checkXr(instance_, xrGetActionStateFloat(session_, &getInfo, &trigger),
                    "xrGetActionStateFloat");
            const bool wasPressed = triggerPressed_[hand];
            const float threshold = wasPressed ? 0.40F : 0.55F;
            triggerPressed_[hand] = trigger.isActive && trigger.currentState >= threshold;
            triggerClicked_[hand] = !wasPressed && triggerPressed_[hand];
            hands_[hand].pressed = triggerPressed_[hand];

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
                    const bool pressed = hands_[hand].pressed;
                    hands_[hand] = handPoseFromXr(location.pose);
                    hands_[hand].pressed = pressed;
                }
            }

            getInfo.action = menuAction_;
            XrActionStateBoolean menu{XR_TYPE_ACTION_STATE_BOOLEAN};
            checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &menu),
                    "xrGetActionStateBoolean");
            if (menu.isActive && menu.changedSinceLastSync && menu.currentState) {
                menuHand_ = hand;
                if (menuOpen_) {
                    menuOpen_ = false;
                    menuHover_ = -1;
                    suppressManipulationUntilRelease_ = true;
                } else {
                    menuOpenRequested_ = true;
                }
                pulse(hand, 0.45F);
            }

            if (hand == 1U) {
                getInfo.action = gripAction_;
                XrActionStateBoolean grip{XR_TYPE_ACTION_STATE_BOOLEAN};
                checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &grip),
                        "xrGetActionStateBoolean(expanded view)");
                const bool expanded = grip.isActive && grip.currentState;
                if (expanded != gripPressed_) {
                    gripPressed_ = expanded;
                    glScene_->setExpanded(expanded);
                    pulse(hand, expanded ? 0.30F : 0.18F);
                }

                getInfo.action = selectAction_;
                XrActionStateBoolean select{XR_TYPE_ACTION_STATE_BOOLEAN};
                checkXr(instance_, xrGetActionStateBoolean(session_, &getInfo, &select),
                        "xrGetActionStateBoolean(select element)");
                const bool selectPressed = select.isActive && select.currentState;
                if (selectPressed && !selectPressed_ && sceneHover_) {
                    publishSelect(sceneHover_->identity);
                    pulse(hand, 0.55F);
                }
                selectPressed_ = selectPressed;
            }
        }

        const nadoc_vr::ManipulationMode previous = manipulator_.mode();
        if (suppressManipulationUntilRelease_ &&
            std::none_of(triggerPressed_.begin(), triggerPressed_.end(), [](bool pressed) {
                return pressed;
            })) {
            suppressManipulationUntilRelease_ = false;
        }
        auto manipulationHands = hands_;
        const bool inputSuppressed = menuOpen_ || menuOpenRequested_
                                  || suppressManipulationUntilRelease_;
        const bool clusterToolPreview =
            toolShell_.mode() == nadoc_vr::ToolMode::move_rotate &&
            toolShell_.previewRequested() && selectedSelectionKind_ == "cluster";
        const bool rightToolDrag = clusterToolPreview && !inputSuppressed &&
                                   hands_[1].valid && hands_[1].pressed &&
                                   !(hands_[0].valid && hands_[0].pressed);
        pendingToolTransform_.update(
            hands_[1], manipulator_.transform(), rightToolDrag);
        if (rightToolDrag) manipulationHands[1].pressed = false;
        if (inputSuppressed) {
            for (nadoc_vr::HandPose& hand : manipulationHands) hand.pressed = false;
        }
        const nadoc_vr::ManipulationMode next = manipulator_.update(manipulationHands);
        if (next != previous && next != nadoc_vr::ManipulationMode::none) {
            for (size_t hand = 0; hand < hands_.size(); ++hand) {
                if (hands_[hand].valid && hands_[hand].pressed) pulse(hand);
            }
        }
        if (menuOpen_) processMenuInput();
        updateSceneHover();
        pollSelectionFeedback();
        updateControllerGuides();
    }

    void applyPendingMenu(uint32_t viewCount) {
        if (!menuOpenRequested_ || viewCount == 0) return;
        glm::vec3 headPosition{};
        for (uint32_t i = 0; i < viewCount; ++i) {
            headPosition += glm::vec3(
                views_[i].pose.position.x,
                views_[i].pose.position.y,
                views_[i].pose.position.z);
        }
        headPosition /= static_cast<float>(viewCount);
        const XrQuaternionf& orientation = views_[0].pose.orientation;
        menuOrientation_ = glm::normalize(glm::quat(
            orientation.w, orientation.x, orientation.y, orientation.z));
        menuPosition_ = headPosition
                      + menuOrientation_ * glm::vec3(0.0F, 0.04F, -1.00F);
        menuOpen_ = true;
        menuPage_ = MenuPage::options;
        menuOpenRequested_ = false;
        menuHover_ = -1;
        pulse(menuHand_, 0.30F);
        updateControllerGuides();
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
        manipulator_.recenter(
            headPosition,
            {orientation.w, orientation.x, orientation.y, orientation.z});
        pulse(recenterHand_, 0.55F);
        recenterRequested_ = false;
        updateControllerGuides();
    }

    bool renderView(uint32_t index, const XrView& view,
                    XrCompositionLayerProjectionView& layerView) {
        Swapchain& swapchain = swapchains_[index];
        uint32_t imageIndex = 0;
        XrSwapchainImageAcquireInfo acquireInfo{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
        checkXr(instance_, xrAcquireSwapchainImage(
            swapchain.handle, &acquireInfo, &imageIndex), "xrAcquireSwapchainImage");
        XrSwapchainImageWaitInfo waitInfo{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
        waitInfo.timeout = XR_INFINITE_DURATION;
        checkXr(instance_, xrWaitSwapchainImage(
            swapchain.handle, &waitInfo), "xrWaitSwapchainImage");

        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer_);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               swapchain.images[imageIndex].image, 0);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER,
                                  swapchain.depth);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("OpenXR framebuffer is incomplete");
        }
        glViewport(0, 0, swapchain.width, swapchain.height);
        glClearColor(0.015F, 0.025F, 0.045F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        const glm::mat4 projection = projectionFromFov(view.fov, kNearMeters, kFarMeters);
        glScene_->render(
            projection * viewFromPose(view.pose),
            manipulator_.transform(),
            controllerGuides_);
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

    void renderFrame() {
        XrFrameWaitInfo waitInfo{XR_TYPE_FRAME_WAIT_INFO};
        XrFrameState frameState{XR_TYPE_FRAME_STATE};
        checkXr(instance_, xrWaitFrame(session_, &waitInfo, &frameState), "xrWaitFrame");
        XrFrameBeginInfo beginInfo{XR_TYPE_FRAME_BEGIN_INFO};
        checkXr(instance_, xrBeginFrame(session_, &beginInfo), "xrBeginFrame");
        syncActions(frameState.predictedDisplayTime);

        std::vector<XrCompositionLayerProjectionView> layerViews(views_.size());
        XrCompositionLayerProjection layer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
        const XrCompositionLayerBaseHeader* layers[] = {
            reinterpret_cast<const XrCompositionLayerBaseHeader*>(&layer)};
        uint32_t layerCount = 0;

        if (frameState.shouldRender) {
            XrViewLocateInfo locateInfo{XR_TYPE_VIEW_LOCATE_INFO};
            locateInfo.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
            locateInfo.displayTime = frameState.predictedDisplayTime;
            locateInfo.space = space_;
            XrViewState viewState{XR_TYPE_VIEW_STATE};
            uint32_t viewCount = 0;
            checkXr(instance_, xrLocateViews(
                session_, &locateInfo, &viewState, static_cast<uint32_t>(views_.size()),
                &viewCount, views_.data()), "xrLocateViews");
            const XrViewStateFlags valid = XR_VIEW_STATE_POSITION_VALID_BIT |
                                           XR_VIEW_STATE_ORIENTATION_VALID_BIT;
            if ((viewState.viewStateFlags & valid) == valid && viewCount == views_.size()) {
                applyPendingMenu(viewCount);
                applyPendingRecenter(viewCount);
                const XrQuaternionf& head = views_[0].pose.orientation;
                const glm::quat headOrientation(head.w, head.x, head.y, head.z);
                const glm::vec3 keyDirection = headOrientation * glm::normalize(
                    glm::vec3(-0.577F, 0.577F, 0.577F));
                glScene_->renderShadowMap(manipulator_.transform(), keyDirection);
                for (uint32_t i = 0; i < viewCount; ++i) renderView(i, views_[i], layerViews[i]);
                layer.space = space_;
                layer.viewCount = viewCount;
                layer.views = layerViews.data();
                layerCount = 1;
            }
        }

        XrFrameEndInfo endInfo{XR_TYPE_FRAME_END_INFO};
        endInfo.displayTime = frameState.predictedDisplayTime;
        endInfo.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        endInfo.layerCount = layerCount;
        endInfo.layers = layerCount ? layers : nullptr;
        checkXr(instance_, xrEndFrame(session_, &endInfo), "xrEndFrame");
    }

    void eventLoop() {
        std::cout << "NADOC VR viewer ready. Trigger: grab; both triggers: resize; "
                     "right trackpad: select; right grip: Expanded Quick View; "
                     "menu: options; Escape: exit.\n";
        while (!exitLoop_) {
            glfwPollEvents();
            pollXrEvents();
            if (glfwWindowShouldClose(window_) ||
                glfwGetKey(window_, GLFW_KEY_ESCAPE) == GLFW_PRESS || gStopRequested) {
                if (sessionRunning_) {
                    xrRequestExitSession(session_);
                } else {
                    exitLoop_ = true;
                }
                gStopRequested = false;
            }
            if (sessionRunning_) {
                renderFrame();
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
        }
    }

    SceneData sceneData_;
    std::string eventPath_;
    std::string feedbackPath_;
    uint64_t eventSequence_ = 0;
    std::string publishedHoverIdentity_;
    uint64_t selectSequence_ = 0;
    std::string lastSelectIdentity_;
    uint64_t levelSequence_ = 0;
    std::string selectionLevel_ = "default";
    uint64_t toolSequence_ = 0;
    nadoc_vr::ToolAction lastToolAction_ = nadoc_vr::ToolAction::activate;
    nadoc_vr::ToolShell toolShell_;
    nadoc_vr::PendingRigidTransform pendingToolTransform_;
    uint64_t feedbackSequence_ = 0;
    uint32_t feedbackPollFrame_ = 0;
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
    XrAction triggerAction_ = XR_NULL_HANDLE;
    XrAction menuAction_ = XR_NULL_HANDLE;
    XrAction gripAction_ = XR_NULL_HANDLE;
    XrAction selectAction_ = XR_NULL_HANDLE;
    XrAction hapticAction_ = XR_NULL_HANDLE;
    std::array<XrPath, 2> handPaths_{XR_NULL_PATH, XR_NULL_PATH};
    std::array<XrSpace, 2> handSpaces_{XR_NULL_HANDLE, XR_NULL_HANDLE};
    std::array<nadoc_vr::HandPose, 2> hands_{};
    std::array<bool, 2> triggerPressed_{false, false};
    std::array<bool, 2> triggerClicked_{false, false};
    bool gripPressed_ = false;
    bool selectPressed_ = false;
    nadoc_vr::SceneManipulator manipulator_;
    std::vector<Vertex> controllerGuides_;
    std::optional<nadoc_vr::PickHit> sceneHover_;
    bool menuOpen_ = false;
    MenuPage menuPage_ = MenuPage::options;
    bool menuOpenRequested_ = false;
    bool suppressManipulationUntilRelease_ = false;
    int menuHover_ = -1;
    glm::vec3 menuPosition_{};
    glm::quat menuOrientation_{1.0F, 0.0F, 0.0F, 0.0F};
    size_t menuHand_ = 0;
    bool recenterRequested_ = false;
    size_t recenterHand_ = 0;
    XrSessionState sessionState_ = XR_SESSION_STATE_UNKNOWN;
    bool sessionRunning_ = false;
    bool exitLoop_ = false;
    GLuint framebuffer_ = 0;
    std::vector<XrViewConfigurationView> viewConfigs_;
    std::vector<XrView> views_;
    std::vector<Swapchain> swapchains_;
    std::unique_ptr<GlScene> glScene_;
};

}  // namespace

int main(int argc, char** argv) {
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
        std::cerr << "Usage: nadoc-vr-viewer [--validate] <scene.nadocvr> "
                     "[--events <event.json>] [--feedback <feedback.txt>] "
                     "[--selection-level <level>] "
                     "[--selected-owner <token>]... [--selected-kind <kind>]\n";
        return 2;
    }
    std::string eventPath;
    std::string feedbackPath;
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
        if (option == "--events") eventPath = argv[index + 1];
        else if (option == "--feedback") feedbackPath = argv[index + 1];
        else if (option == "--selection-level") selectionLevel = argv[index + 1];
        else if (option == "--selected-owner") {
            const std::string token(argv[index + 1]);
            if (token.empty() || token.size() > 2048 ||
                std::any_of(token.begin(), token.end(), [](unsigned char character) {
                    return std::isspace(character) != 0;
                }) || selectedOwnerTokens.size() >= 8) {
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
    const std::array<std::string, 11> validSelectionKinds = {
        "none", "cluster", "strand", "domain", "base", "end", "bond",
        "crossover", "overhang", "extension", "protein",
    };
    if (std::find(validSelectionKinds.begin(), validSelectionKinds.end(),
                  selectedSelectionKind) == validSelectionKinds.end() ||
        selectedOwnerTokens.empty() != (selectedSelectionKind == "none")) {
        std::cerr << "NADOC VR error: invalid selected owner kind\n";
        return 2;
    }
    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);
    try {
        Viewer viewer(
            loadScene(argv[1]), eventPath, feedbackPath, selectionLevel,
            std::move(selectedOwnerTokens), std::move(selectedSelectionKind));
        return viewer.run();
    } catch (const std::exception& error) {
        std::cerr << "NADOC VR error: " << error.what() << '\n';
        return 1;
    }
}
