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

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

constexpr float kViewSizeMeters = 0.60F;
constexpr float kViewDistanceMeters = 0.90F;
constexpr float kNearMeters = 0.03F;
constexpr float kFarMeters = 100.0F;

std::atomic_bool gStopRequested{false};

struct Vertex {
    glm::vec3 position{};
    glm::vec3 color{};
    float size = 1.0F;
};

struct SceneData {
    std::vector<Vertex> points;
    std::vector<Vertex> lines;
};

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
        layout(location = 2) in float aSize;
        uniform mat4 uViewProjection;
        out vec3 vColor;
        void main() {
            gl_Position = uViewProjection * vec4(aPosition, 1.0);
            gl_PointSize = aSize;
            vColor = aColor;
        }
    )GLSL";
    static constexpr const char* fragmentSource = R"GLSL(
        #version 330 core
        in vec3 vColor;
        uniform int uRoundPoints;
        out vec4 outColor;
        void main() {
            float light = 1.0;
            if (uRoundPoints != 0) {
                vec2 p = gl_PointCoord * 2.0 - 1.0;
                float r2 = dot(p, p);
                if (r2 > 1.0) discard;
                light = 0.62 + 0.38 * sqrt(max(0.0, 1.0 - r2));
            }
            outColor = vec4(vColor * light, 1.0);
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

SceneData loadScene(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Could not open scene snapshot: " + path);

    std::string magic;
    int version = 0;
    input >> magic >> version;
    if (magic != "NADOCVR" || version != 1) {
        throw std::runtime_error("Unsupported NADOC VR scene format");
    }

    SceneData scene;
    char type = '\0';
    while (input >> type) {
        if (type == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (type == 'P') {
            Vertex vertex;
            input >> vertex.position.x >> vertex.position.y >> vertex.position.z
                  >> vertex.color.r >> vertex.color.g >> vertex.color.b >> vertex.size;
            scene.points.push_back(vertex);
        } else if (type == 'L') {
            Vertex a;
            Vertex b;
            input >> a.position.x >> a.position.y >> a.position.z
                  >> b.position.x >> b.position.y >> b.position.z
                  >> a.color.r >> a.color.g >> a.color.b;
            b.color = a.color;
            scene.lines.push_back(a);
            scene.lines.push_back(b);
        } else {
            throw std::runtime_error(std::string("Unknown scene record: ") + type);
        }
        if (!input) throw std::runtime_error("Malformed NADOC VR scene snapshot");
    }
    if (scene.points.empty() && scene.lines.empty()) {
        throw std::runtime_error("The scene snapshot contains no visible geometry");
    }

    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    auto include = [&](const Vertex& vertex) {
        lo = glm::min(lo, vertex.position);
        hi = glm::max(hi, vertex.position);
    };
    for (const Vertex& vertex : scene.points) include(vertex);
    for (const Vertex& vertex : scene.lines) include(vertex);
    const glm::vec3 center = (lo + hi) * 0.5F;
    const glm::vec3 extent = hi - lo;
    const float maxExtent = std::max({extent.x, extent.y, extent.z, 1.0e-6F});
    const float scale = kViewSizeMeters / maxExtent;
    auto fit = [&](Vertex& vertex) {
        vertex.position = (vertex.position - center) * scale;
        vertex.position.z -= kViewDistanceMeters;
    };
    for (Vertex& vertex : scene.points) fit(vertex);
    for (Vertex& vertex : scene.lines) fit(vertex);

    // A compact orientation triad under the model.
    const glm::vec3 origin(-0.28F, -0.28F, -kViewDistanceMeters);
    auto addAxis = [&](glm::vec3 delta, glm::vec3 color) {
        scene.lines.push_back(Vertex{origin, color, 1.0F});
        scene.lines.push_back(Vertex{origin + delta, color, 1.0F});
    };
    addAxis({0.10F, 0, 0}, {1.0F, 0.25F, 0.25F});
    addAxis({0, 0.10F, 0}, {0.25F, 1.0F, 0.35F});
    addAxis({0, 0, 0.10F}, {0.3F, 0.55F, 1.0F});
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

class GlScene {
  public:
    explicit GlScene(const SceneData& scene) {
        program_ = makeProgram();
        viewProjection_ = glGetUniformLocation(program_, "uViewProjection");
        roundPoints_ = glGetUniformLocation(program_, "uRoundPoints");
        upload(scene.lines, lineVao_, lineVbo_);
        upload(scene.points, pointVao_, pointVbo_);
        lineCount_ = static_cast<GLsizei>(scene.lines.size());
        pointCount_ = static_cast<GLsizei>(scene.points.size());
    }

    ~GlScene() {
        if (lineVbo_) glDeleteBuffers(1, &lineVbo_);
        if (pointVbo_) glDeleteBuffers(1, &pointVbo_);
        if (lineVao_) glDeleteVertexArrays(1, &lineVao_);
        if (pointVao_) glDeleteVertexArrays(1, &pointVao_);
        if (program_) glDeleteProgram(program_);
    }

    void render(const glm::mat4& viewProjection) const {
        glUseProgram(program_);
        glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
        glUniform1i(roundPoints_, 0);
        glBindVertexArray(lineVao_);
        glLineWidth(1.5F);
        glDrawArrays(GL_LINES, 0, lineCount_);
        glUniform1i(roundPoints_, 1);
        glBindVertexArray(pointVao_);
        glDrawArrays(GL_POINTS, 0, pointCount_);
        glBindVertexArray(0);
        glUseProgram(0);
    }

  private:
    static void upload(const std::vector<Vertex>& vertices, GLuint& vao, GLuint& vbo) {
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(
            GL_ARRAY_BUFFER,
            static_cast<GLsizeiptr>(vertices.size() * sizeof(Vertex)),
            vertices.data(),
            GL_STATIC_DRAW);
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
    GLuint lineVao_ = 0;
    GLuint lineVbo_ = 0;
    GLuint pointVao_ = 0;
    GLuint pointVbo_ = 0;
    GLint viewProjection_ = -1;
    GLint roundPoints_ = -1;
    GLsizei lineCount_ = 0;
    GLsizei pointCount_ = 0;
};

class Viewer {
  public:
    explicit Viewer(SceneData scene) : sceneData_(std::move(scene)) {}

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
        if (space_ != XR_NULL_HANDLE) xrDestroySpace(space_);
        if (session_ != XR_NULL_HANDLE) xrDestroySession(session_);
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
        window_ = glfwCreateWindow(540, 180, "NADOC VR — Escape to exit", nullptr, nullptr);
        if (!window_) throw std::runtime_error("Could not create the OpenGL companion window");
        glfwMakeContextCurrent(window_);
        glfwSwapInterval(0);
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
        glScene_ = std::make_unique<GlScene>(sceneData_);
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
        glScene_->render(projection * viewFromPose(view.pose));
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
        std::cout << "NADOC VR viewer ready; put on the headset. Press Escape to exit.\n";
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
    bool glfwInitialized_ = false;
    GLFWwindow* window_ = nullptr;
    XrInstance instance_ = XR_NULL_HANDLE;
    XrSystemId systemId_ = XR_NULL_SYSTEM_ID;
    XrSession session_ = XR_NULL_HANDLE;
    XrSpace space_ = XR_NULL_HANDLE;
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
    if (argc != 2) {
        std::cerr << "Usage: nadoc-vr-viewer <scene.nadocvr>\n";
        return 2;
    }
    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);
    try {
        Viewer viewer(loadScene(argv[1]));
        return viewer.run();
    } catch (const std::exception& error) {
        std::cerr << "NADOC VR error: " << error.what() << '\n';
        return 1;
    }
}
