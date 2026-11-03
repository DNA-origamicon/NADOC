#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <thread>
#include <vector>
#include "mirror_readback.hpp"
#include "stencil_color_readback.hpp"
int main() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    glfwWindowHint(GLFW_STENCIL_BITS,8);
    auto* window=glfwCreateWindow(64,64,"Mirror diagnostic parity",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    MirrorReadback readback;
    StencilColorReadback convert;convert.initialize(64);
    GLuint source=0,fbo=0;
    glGenTextures(1,&source);glBindTexture(GL_TEXTURE_2D,source);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_DEPTH_STENCIL_TEXTURE_MODE,GL_STENCIL_INDEX);
    glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH24_STENCIL8,64,64,0,GL_DEPTH_STENCIL,GL_UNSIGNED_INT_24_8,nullptr);
    glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,GL_TEXTURE_2D,source,0);
    glDrawBuffer(GL_NONE);glReadBuffer(GL_NONE);assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_FRAMEBUFFER,0);
    GLuint sentinel=0;glGenBuffers(1,&sentinel);glBindBuffer(GL_PIXEL_PACK_BUFFER,sentinel);
    glBufferData(GL_PIXEL_PACK_BUFFER,4,nullptr,GL_STREAM_READ);
    constexpr size_t pixelBytes=64*64*4,classBytes=64*64;
    for(int sample=0;sample<256;++sample) {
        glClearColor(sample%2?0:1,sample%2?1:0,0,1);glClearStencil(sample);
        glClear(GL_COLOR_BUFFER_BIT|GL_STENCIL_BUFFER_BIT);
        glReadBuffer(GL_BACK);
        readback.begin(pixelBytes+classBytes);
        glReadPixels(0,0,64,64,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,fbo);
        glBlitFramebuffer(0,0,64,64,0,0,64,64,GL_STENCIL_BUFFER_BIT,GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER,0);
        convert.read(source,reinterpret_cast<void*>(pixelBytes));
        readback.finish();glFlush();
        GLint binding=0;glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&binding);assert(GLuint(binding)==sentinel);
        std::optional<std::vector<uint8_t>> result;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
        while(!result && std::chrono::steady_clock::now()<deadline){result=readback.poll();std::this_thread::yield();}
        assert(result && result->size()==pixelBytes+classBytes && !readback.pending());
        for(size_t i=0;i<pixelBytes;i+=4){assert((*result)[i]==(sample%2?0:255));assert((*result)[i+1]==(sample%2?255:0));assert((*result)[i+2]==0);}
        for(size_t i=pixelBytes;i<result->size();++i)assert((*result)[i]==sample);
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&binding);assert(GLuint(binding)==sentinel);
        assert(!readback.poll());assert(glGetError()==GL_NO_ERROR);
    }
    // Cancellation does not wait or leave a stale sample for the next scene.
    readback.begin(pixelBytes);glReadPixels(0,0,64,64,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);readback.finish();
    readback.shutdown();assert(!readback.pending());assert(!readback.poll());
    convert.shutdown();glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&source);
    glDeleteBuffers(1,&sentinel);glfwDestroyWindow(window);glfwTerminate();
    std::cout<<"Mirror asynchronous RGB/classification parity, state restoration, reuse and cancellation passed\n";
}
