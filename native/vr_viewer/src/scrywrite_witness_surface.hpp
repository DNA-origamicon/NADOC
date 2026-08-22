#pragma once

#include <GL/gl.h>

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

#include <array>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace nadoc_vr::scrywrite {

struct WitnessPanelVertex {
    glm::vec3 position{};
    glm::vec2 uv{};
};

class WitnessSurface {
  public:
    static constexpr int kWidth = 960;
    static constexpr int kHeight = 540;

    void initialize(GLuint textureProgram) {
        program_ = textureProgram;
        viewProjection_ = glGetUniformLocation(program_, "uViewProjection");
        textureUniform_ = glGetUniformLocation(program_, "uDesktop");
        pointerUniform_ = glGetUniformLocation(program_, "uPointer");
        pointerVisibleUniform_ = glGetUniformLocation(program_, "uPointerVisible");
        glGenTextures(1, &texture_);
        glBindTexture(GL_TEXTURE_2D, texture_);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, kWidth, kHeight, 0, GL_RGB,
                     GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glGenRenderbuffers(1, &depth_);
        glBindRenderbuffer(GL_RENDERBUFFER, depth_);
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, kWidth, kHeight);
        glGenFramebuffers(1, &framebuffer_);
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer_);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               texture_, 0);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                  GL_RENDERBUFFER, depth_);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw std::runtime_error("ScryWrite actor-eye framebuffer is incomplete");
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(WitnessPanelVertex) * 4, nullptr,
                     GL_DYNAMIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(WitnessPanelVertex),
                              reinterpret_cast<void*>(offsetof(WitnessPanelVertex, position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(WitnessPanelVertex),
                              reinterpret_cast<void*>(offsetof(WitnessPanelVertex, uv)));
        glBindVertexArray(0);
    }

    void shutdown() {
        if (framebuffer_) glDeleteFramebuffers(1, &framebuffer_);
        if (depth_) glDeleteRenderbuffers(1, &depth_);
        if (texture_) glDeleteTextures(1, &texture_);
        if (vbo_) glDeleteBuffers(1, &vbo_);
        if (vao_) glDeleteVertexArrays(1, &vao_);
        if (program_) glDeleteProgram(program_);
        framebuffer_ = depth_ = texture_ = vbo_ = vao_ = program_ = 0;
    }

    void beginCapture() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &previousFramebuffer_);
        glGetIntegerv(GL_VIEWPORT, previousViewport_.data());
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer_);
        glViewport(0, 0, kWidth, kHeight);
        glClearColor(0.015F, 0.025F, 0.045F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }

    void endCapture() {
        glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(previousFramebuffer_));
        glViewport(previousViewport_[0], previousViewport_[1],
                   previousViewport_[2], previousViewport_[3]);
    }

    [[nodiscard]] std::vector<uint8_t> readRgb() const {
        std::vector<uint8_t> pixels(
            static_cast<size_t>(kWidth) * kHeight * 3U);
        GLint previousAlignment = 4;
        glGetIntegerv(GL_PACK_ALIGNMENT, &previousAlignment);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadPixels(0, 0, kWidth, kHeight, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
        glPixelStorei(GL_PACK_ALIGNMENT, previousAlignment);
        return pixels;
    }

    void renderPanel(
        const glm::mat4& viewProjection, const glm::vec3& observerPosition,
        const glm::quat& observerOrientation) const {
        const glm::vec3 center = observerPosition +
            observerOrientation * glm::vec3(0.0F, -0.16F, -0.82F);
        const glm::vec3 right = observerOrientation * glm::vec3(0.31F, 0.0F, 0.0F);
        const glm::vec3 up = observerOrientation * glm::vec3(0.0F, 0.174F, 0.0F);
        const std::array<WitnessPanelVertex, 4> vertices = {{
            {center - right + up, {0.0F, 1.0F}},
            {center - right - up, {0.0F, 0.0F}},
            {center + right + up, {1.0F, 1.0F}},
            {center + right - up, {1.0F, 0.0F}},
        }};
        glDisable(GL_DEPTH_TEST);
        glUseProgram(program_);
        glUniformMatrix4fv(viewProjection_, 1, GL_FALSE, &viewProjection[0][0]);
        glUniform2f(pointerUniform_, 0.5F, 0.5F);
        glUniform1i(pointerVisibleUniform_, 0);
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
        glEnable(GL_DEPTH_TEST);
    }

  private:
    GLuint program_ = 0;
    GLuint framebuffer_ = 0;
    GLuint depth_ = 0;
    GLuint texture_ = 0;
    GLuint vao_ = 0;
    GLuint vbo_ = 0;
    GLint viewProjection_ = -1;
    GLint textureUniform_ = -1;
    GLint pointerUniform_ = -1;
    GLint pointerVisibleUniform_ = -1;
    GLint previousFramebuffer_ = 0;
    std::array<GLint, 4> previousViewport_{};
};

}  // namespace nadoc_vr::scrywrite
