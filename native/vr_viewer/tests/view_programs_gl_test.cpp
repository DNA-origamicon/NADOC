#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include "view_programs.hpp"
#include <cassert>
#include <iostream>
#include <vector>
struct Driver {
    std::vector<GLuint> createdShaders,createdPrograms;
    unsigned linkChecks=0;
    GLuint compile(bool vertex,const char* source) {
        auto shader=glCreateShader(vertex?GL_VERTEX_SHADER:GL_FRAGMENT_SHADER);createdShaders.push_back(shader);
        glShaderSource(shader,1,&source,nullptr);glCompileShader(shader);GLint ok=0;glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
        if(!ok){glDeleteShader(shader);throw std::runtime_error("expected compile failure");}return shader;
    }
    GLuint create(){auto p=glCreateProgram();createdPrograms.push_back(p);return p;}
    void attach(GLuint p,GLuint s){glAttachShader(p,s);}
    void link(GLuint p){glLinkProgram(p);}
    bool linked(GLuint p){++linkChecks;GLint ok=0;glGetProgramiv(p,GL_LINK_STATUS,&ok);return ok;}
    void deleteShader(GLuint s){glDeleteShader(s);}
    void deleteProgram(GLuint p){glDeleteProgram(p);}
};
int main() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
    auto* window=glfwCreateWindow(32,32,"Optional program fallback",nullptr,nullptr);if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    using namespace nadoc_vr::view_programs;
    const char* vertex="#version 330 core\nuniform vec3 sharedValue;out vec3 bridge;void main(){bridge=sharedValue+vec3(.2,.4,.6);gl_Position=vec4(0,0,0,1);}";
    const char* fragment="#version 330 core\nin vec3 bridge;out vec4 color;void main(){color=vec4(bridge,1);}";
    const char* mismatch="#version 330 core\nuniform vec4 sharedValue;in vec3 bridge;out vec4 color;void main(){color=vec4(bridge,1)+sharedValue;}";
    Driver legacy;auto fallback=build(legacy,vertex,fragment);assert(fallback);
    for(unsigned trial=0;trial<3;++trial) {
        Driver driver;
        auto result=optional([&]{return build(driver,trial==0?"invalid vertex":vertex,trial==1?"invalid fragment":mismatch);});
        assert(!result.program);
        assert(driver.linkChecks==(trial==2?1U:0U));
        for(auto p:driver.createdPrograms)assert(!glIsProgram(p));
        for(auto s:driver.createdShaders)assert(!glIsShader(s));
        // The required program still renders after each optional compile/link failure.
        GLuint vao=0;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glUseProgram(fallback);
        glViewport(0,0,32,32);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);glDrawArrays(GL_POINTS,0,1);
        unsigned char pixels[32*32*4]{};glReadPixels(0,0,32,32,GL_RGBA,GL_UNSIGNED_BYTE,pixels);bool colored=false;
        for(size_t i=0;i<sizeof(pixels);i+=4)colored|=pixels[i]>40 && pixels[i+1]>90 && pixels[i+2]>140;
        assert(colored && glGetError()==GL_NO_ERROR);glBindVertexArray(0);glDeleteVertexArrays(1,&vao);glUseProgram(0);
    }
    glDeleteProgram(fallback);for(auto s:legacy.createdShaders)assert(!glIsShader(s));
    glfwDestroyWindow(window);glfwTerminate();
    std::cout<<"Actual GL vertex/fragment compile and link failures clean up and preserve legacy rendered pixels\n";
}
