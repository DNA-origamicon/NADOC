#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include "stereo_recording.hpp"
#include <cassert>
#include <iostream>

int main(int argc,char** argv) {
    using namespace nadoc_vr;
    RecordingClock clock;clock.arm(100);
    assert(!clock.collecting(101.999));assert(clock.collecting(102));
    assert(clock.collecting(106.999));assert(!clock.collecting(107));assert(clock.finished(107));
    assert(clock.label(100)=="Starting in 2s");assert(clock.label(102)=="Recording 5s");
    StereoRecording idle;assert(idle.label()=="Record app eyes 5s");
    if(argc<2)return 0;
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(64,48,"Stereo capture integration",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    const std::filesystem::path output=argv[1];std::filesystem::create_directories(output);
    setenv("NADOC_VR_RECORDINGS_DIR",output.c_str(),1);
    GLuint framebuffer,texture;glGenFramebuffers(1,&framebuffer);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
    glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,64,48,0,GL_RGB,GL_UNSIGNED_BYTE,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
    assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    StereoRecording recording;recording.start(0,48);assert(!recording.busy());
    recording.start(64,48,"{\"fixture\":\"asymmetric_stereo\"}");assert(recording.busy());
    recording.start(0,0); // Repeated selection must not restart or invalidate it.
    const auto start=std::chrono::steady_clock::now();uint64_t frame=0;
    while(recording.busy()) {
        const auto elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        assert(elapsed<30);
        recording.poll();recording.begin(++frame,int64_t(elapsed*1e9),11111111,elapsed<4.5,true,"stick");
        for(unsigned offset=0;offset<2;++offset) {
            const unsigned eye=(offset+frame)%2; // Both eye render orders are valid.
            glViewport(0,0,64,48);glDisable(GL_SCISSOR_TEST);
            glClearColor(eye?0.0F:1.0F,0,eye?1.0F:0.0F,1);glClear(GL_COLOR_BUFFER_BIT);
            glEnable(GL_SCISSOR_TEST);glScissor(int(frame%48),0,8,12);
            glClearColor(0,1,0,1);glClear(GL_COLOR_BUFFER_BIT);glDisable(GL_SCISSOR_TEST);
            XrView view{};view.type=XR_TYPE_VIEW;view.pose.orientation.w=1;view.pose.position.x=eye?.032F:-.032F;
            recording.eye(eye,view,64,48);
        }
        recording.submitted(true);
        std::this_thread::sleep_until(start+std::chrono::microseconds(frame*11111));
    }
    std::cout<<recording.json()<<'\n';assert(recording.json().find("\"error\":\"\"")!=std::string::npos);
    recording.shutdown();glDeleteTextures(1,&texture);glDeleteFramebuffers(1,&framebuffer);
    glfwDestroyWindow(window);glfwTerminate();
}
