#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include "gpu_pass_timing.hpp"
#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>
#include <vector>
void saved(const nadoc_vr::GpuPassSample& sample,void* context){static_cast<std::vector<nadoc_vr::GpuPassSample>*>(context)->push_back(sample);}
int main() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
    auto* window=glfwCreateWindow(64,64,"GPU pass timestamp coexistence",nullptr,nullptr);if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    nadoc_vr::GlPassTimestampDriver driver;std::vector<nadoc_vr::GpuPassSample> samples;
    nadoc_vr::GpuPassTimingRing<nadoc_vr::GlPassTimestampDriver,4> ring(driver,saved,&samples);ring.initialize(true);
    if(ring.json().find("\"supported\":true")==std::string::npos){ring.shutdown();glfwDestroyWindow(window);glfwTerminate();return 77;}
    GLuint total=0;glGenQueries(1,&total);glBeginQuery(GL_TIME_ELAPSED,total);
    ring.begin(17,false,42,257,1,1000);glClearColor(.1F,.2F,.3F,1);glClear(GL_COLOR_BUFFER_BIT);ring.afterShadow(true);
    glClearColor(.3F,.2F,.1F,1);glClear(GL_COLOR_BUFFER_BIT);ring.afterEye(1);glClearColor(.2F,.1F,.3F,1);glClear(GL_COLOR_BUFFER_BIT);ring.afterEye(0);ring.end();
    glEndQuery(GL_TIME_ELAPSED);glFlush();assert(glGetError()==GL_NO_ERROR);
    const auto started=std::chrono::steady_clock::now();unsigned polls=0;
    while(samples.empty() && std::chrono::steady_clock::now()-started<std::chrono::seconds(2)) {
        ring.collect(2000+polls++);if(samples.empty())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(samples.size()==1 && samples[0].valid && samples[0].frame==17 && samples[0].eyeOrder[0]==1 && samples[0].eyeOrder[1]==0);
    assert(samples[0].totalNs==samples[0].shadowNs+samples[0].leftNs+samples[0].rightNs);
    GLint ready=0;
    while(!ready && std::chrono::steady_clock::now()-started<std::chrono::seconds(2)) {
        glGetQueryObjectiv(total,GL_QUERY_RESULT_AVAILABLE,&ready);if(!ready)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(ready==GL_TRUE);GLuint64 elapsed=0;glGetQueryObjectui64v(total,GL_QUERY_RESULT,&elapsed);
    assert(elapsed>=samples[0].totalNs);assert(glGetError()==GL_NO_ERROR);
    std::cout<<"GL_TIMESTAMP coexists with GL_TIME_ELAPSED; right-first scopes measured; total_ns="<<samples[0].totalNs<<" enclosing_ns="<<elapsed<<" polls="<<polls<<'\n';
    ring.shutdown();glDeleteQueries(1,&total);glfwDestroyWindow(window);glfwTerminate();
}
