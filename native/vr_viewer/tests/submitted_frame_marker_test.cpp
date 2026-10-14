#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include "submitted_frame_marker.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <vector>
#include <filesystem>
using namespace nadoc_vr;
std::vector<GLint> state() {
    std::vector<GLint> out;
    for(GLenum key:{GL_CURRENT_PROGRAM,GL_VERTEX_ARRAY_BINDING,GL_DRAW_FRAMEBUFFER_BINDING,GL_READ_FRAMEBUFFER_BINDING,
        GL_STENCIL_FUNC,GL_STENCIL_REF,GL_STENCIL_VALUE_MASK,GL_STENCIL_WRITEMASK,GL_STENCIL_FAIL,GL_STENCIL_PASS_DEPTH_FAIL,GL_STENCIL_PASS_DEPTH_PASS,
        GL_STENCIL_BACK_FUNC,GL_STENCIL_BACK_REF,GL_STENCIL_BACK_VALUE_MASK,GL_STENCIL_BACK_WRITEMASK,GL_STENCIL_BACK_FAIL,GL_STENCIL_BACK_PASS_DEPTH_FAIL,GL_STENCIL_BACK_PASS_DEPTH_PASS}) {
        GLint value=0;glGetIntegerv(key,&value);out.push_back(value);
    }
    GLint viewport[4]{},polygon[2]{};glGetIntegerv(GL_VIEWPORT,viewport);glGetIntegerv(GL_POLYGON_MODE,polygon);
    out.insert(out.end(),viewport,viewport+4);out.insert(out.end(),polygon,polygon+2);
    GLint count=0;glGetIntegerv(GL_MAX_DRAW_BUFFERS,&count);
    for(int i=0;i<count;++i){GLint value=0;glGetIntegerv(GL_DRAW_BUFFER0+i,&value);out.push_back(value);}
    for(GLenum cap:{GL_DEPTH_TEST,GL_STENCIL_TEST,GL_SCISSOR_TEST,GL_CULL_FACE,GL_RASTERIZER_DISCARD,GL_COLOR_LOGIC_OP,
        GL_DITHER,GL_SAMPLE_ALPHA_TO_COVERAGE,GL_SAMPLE_COVERAGE,GL_SAMPLE_MASK,GL_POLYGON_SMOOTH})out.push_back(glIsEnabled(cap));
    for(unsigned i=0;i<8;++i)out.push_back(glIsEnabled(GL_CLIP_DISTANCE0+i));
    for(unsigned i=0;i<2;++i){out.push_back(glIsEnabledi(GL_BLEND,i));GLboolean mask[4]{};glGetBooleani_v(GL_COLOR_WRITEMASK,i,mask);out.insert(out.end(),mask,mask+4);}
    return out;
}
int main(int argc,char** argv) {
    SubmittedFrameMarker off;off.initialize();assert(!off.draw(100,0,0,0,true,true,3,true).rendered);off.shutdown();
    assert(off.json()=="{\"enabled\":false}"); // Disabled requires no GL context.
    SubmittedFrameMarker idle;idle.configure(frame_identity::Mode::recording,"1-2",true);
    assert(idle.enabled() && idle.json().find("\"recording_only\":true")!=std::string::npos);
    assert(!idle.draw(100,0,0,0,true,true,3,false).rendered); // No context/initialization/valid eye needed while idle.
    bool rejected=false;try {idle.configure(frame_identity::Mode::recording,"1-2",false);}catch(const std::runtime_error&){rejected=true;}
    assert(rejected);
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
    auto* window=glfwCreateWindow(64,64,"Frame marker contract",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    constexpr int width=512,height=512;
    GLuint fbo=0,color=0,ids=0,depth=0,vao=0;glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    glGenTextures(1,&ids);glBindTexture(GL_TEXTURE_2D,ids);glTexImage2D(GL_TEXTURE_2D,0,GL_R32UI,width,height,0,GL_RED_INTEGER,GL_UNSIGNED_INT,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,ids,0);
    glGenRenderbuffers(1,&depth);glBindRenderbuffer(GL_RENDERBUFFER,depth);glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH24_STENCIL8,width,height);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,GL_RENDERBUFFER,depth);
    const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,buffers);
    assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    const GLfloat background[4]={.125F,.25F,.375F,1};const GLuint id[4]={99,99,99,99};glClearBufferfv(GL_COLOR,0,background);glClearBufferuiv(GL_COLOR,1,id);
    glClearStencil(1);glClear(GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT);
    glGenVertexArrays(1,&vao);glBindVertexArray(vao);glViewport(7,9,317,289);
    glEnable(GL_SCISSOR_TEST);glScissor(0,0,1,1);glEnable(GL_DEPTH_TEST);glEnable(GL_CULL_FACE);glCullFace(GL_FRONT_AND_BACK);
    glEnable(GL_STENCIL_TEST);glStencilFuncSeparate(GL_FRONT,GL_NEVER,5,0x37);glStencilMaskSeparate(GL_FRONT,0x16);
    glStencilOpSeparate(GL_FRONT,GL_INCR,GL_DECR,GL_ZERO);glStencilFuncSeparate(GL_BACK,GL_EQUAL,6,0x73);glStencilMaskSeparate(GL_BACK,0x61);
    glStencilOpSeparate(GL_BACK,GL_INVERT,GL_REPLACE,GL_INCR);
    glEnablei(GL_BLEND,0);glDisablei(GL_BLEND,1);glColorMaski(0,GL_FALSE,GL_TRUE,GL_FALSE,GL_TRUE);glColorMaski(1,GL_TRUE,GL_FALSE,GL_TRUE,GL_FALSE);
    glEnable(GL_RASTERIZER_DISCARD);glEnable(GL_SAMPLE_COVERAGE);glSampleCoverage(0,GL_FALSE);glEnable(GL_SAMPLE_MASK);glSampleMaski(0,0);
    glEnable(GL_CLIP_DISTANCE0);glPolygonMode(GL_FRONT_AND_BACK,GL_LINE);
    SubmittedFrameMarker marker;marker.configure(frame_identity::Mode::recording,"305419896-81985529216486895",true);
    const auto before=state();marker.initialize();assert(state()==before);assert(glGetError()==GL_NO_ERROR);
    const auto idleReceipt=marker.draw(1,width,height,42,true,true,3,false);
    assert(!idleReceipt.rendered && idleReceipt.hostStartNs==0 && idleReceipt.hostEndNs==0);
    assert(state()==before);assert(glGetError()==GL_NO_ERROR);
    std::vector<uint8_t> idlePixels(width*height*3);
    glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,idlePixels.data());
    for(size_t i=0;i<idlePixels.size();i+=3)assert(idlePixels[i]==32 && idlePixels[i+1]==64 && idlePixels[i+2]==96);
    const auto receipt=marker.draw(1,width,height,0xfedcba9876543210ULL,true,true,3,true);
    assert(receipt.rendered && receipt.packetCrc32==0x9fc2de62U && receipt.hostEndNs>=receipt.hostStartNs && receipt.hostStartNs>0);
    assert(state()==before);assert(glGetError()==GL_NO_ERROR);
    // Test readbacks are an oracle only; the production marker has no readback.
    std::vector<uint8_t> rgb(width*height*3),classes(width*height);std::vector<uint32_t> objectIds(width*height);
    glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
    glReadBuffer(GL_COLOR_ATTACHMENT1);glReadPixels(0,0,width,height,GL_RED_INTEGER,GL_UNSIGNED_INT,objectIds.data());
    glReadPixels(0,0,width,height,GL_STENCIL_INDEX,GL_UNSIGNED_BYTE,classes.data());
    // Cancelling/finishing the journal stops marker draws immediately. Even a
    // different valid packet cannot change the acquired texture while idle.
    assert(!marker.draw(0,width,height,123,true,true,3,false).rendered);
    glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,idlePixels.data());
    assert(idlePixels==rgb);assert(state()==before);assert(glGetError()==GL_NO_ERROR);
    const auto packet=frame_identity::encode({0x12345678,0x0123456789abcdefULL},0xfedcba9876543210ULL,1);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
        const auto index=size_t(height-1-y)*width+x;
        const bool inside=x>=receipt.rect.x && x<receipt.rect.x+receipt.rect.width && y>=receipt.rect.y && y<receipt.rect.y+receipt.rect.height;
        if(inside) {
            const auto expected=frame_identity::cell(packet,unsigned(x-receipt.rect.x)/8,unsigned(y-receipt.rect.y)/8);
            for(size_t c=0;c<3;++c)assert(rgb[index*3+c]==expected[c]);
            assert(objectIds[index]==0 && classes[index]==3);
        }else {assert(objectIds[index]==99 && classes[index]==1);assert(rgb[index*3]==32 && rgb[index*3+1]==64 && rgb[index*3+2]==96);}
    }
    // No ID attachment: location1 is explicitly disabled and previous mappings restored.
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,0,0);glDrawBuffer(GL_COLOR_ATTACHMENT0);
    SubmittedFrameMarker always;always.configure(true,"305419896-81985529216486895",true);always.initialize();
    const auto singleBefore=state();const auto left=always.draw(0,width,height,0,false,false,3,false);
    assert(left.rendered && left.hostStartNs==0 && left.hostEndNs==0);assert(state()==singleBefore);assert(glGetError()==GL_NO_ERROR);
    if(argc==2) {
        std::filesystem::create_directories(argv[1]);
        std::ofstream image(std::filesystem::path(argv[1])/"native-right.ppm",std::ios::binary);image<<"P6\n"<<width<<' '<<height<<"\n255\n";
        for(int y=height-1;y>=0;--y)image.write(reinterpret_cast<const char*>(rgb.data()+size_t(y)*width*3),width*3);
        std::ofstream meta(std::filesystem::path(argv[1])/"native-right.json");meta<<"{\"frame_identity\":"<<marker.json()<<",\"receipt\":"<<frame_identity::receiptJson(receipt)<<"}\n";
    }
    always.shutdown();marker.shutdown();glDeleteVertexArrays(1,&vao);glDeleteRenderbuffers(1,&depth);glDeleteTextures(1,&color);glDeleteTextures(1,&ids);glDeleteFramebuffers(1,&fbo);
    glfwDestroyWindow(window);glfwTerminate();std::cout<<"Actual GL marker pixels, ID/class exclusion, disabled mode and state restoration passed\n";
}
