#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GLFW/glfw3.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>
#include <array>
#include <chrono>
#include <optional>
#include <vector>
#include <string>
#include <sstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>

GLuint compileShader(GLenum kind,const char* source) {
    auto shader=glCreateShader(kind);glShaderSource(shader,1,&source,nullptr);glCompileShader(shader);
    GLint ok;glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[4096];glGetShaderInfoLog(shader,sizeof(log),nullptr,log);throw std::runtime_error(log);}
    return shader;
}
#define NADOC_QR_TESTING
#include "qr_calibration.hpp"

struct QrCalibrationTest {
    static void run(const std::filesystem::path& output) {
        QrCalibration preview;
        preview.cubeMode_=true;
        // The same packet parser used by the camera helper must locate a map
        // without producing a scene-placement request.
        std::ostringstream packet;
        packet<<"NADOCQR2\n1 1 1 2 "<<std::setprecision(16)<<QrCalibration::now()<<"\n"
              <<"1 0 0 0 0 1 0 0 0 0 1 -0.5 0 0 0 1\n1/5 faces calibrated\n.15 1 0 0 0 0 0\n";
        packet.write("RGBA",4);
        std::istringstream input(packet.str());
        const auto stage=glm::translate(glm::mat4(1),glm::vec3(.3F,0,0));
        preview.readFrame(input,stage,std::chrono::steady_clock::now());
        if(!preview.cubePose_ || preview.cubeStates_[0]!=1 || std::abs((*preview.cubePose_)[3].x-.3F)>.001F
            || preview.takePosition() || preview.anchor || preview.width_!=1 || preview.height_!=1)
            throw std::runtime_error("Cube packet must map faces in local coordinates without moving scene");
        auto invalid=packet.str();invalid.replace(invalid.find(".15 1 0"),7,".15 9 0");
        std::istringstream badInput(invalid);preview.sequence_=0;
        preview.readFrame(badInput,stage,std::chrono::steady_clock::now());
        if(preview.cubeStates_[0]!=1)throw std::runtime_error("Malformed face state accepted");

        preview.cubePose_=glm::translate(glm::mat4(1),glm::vec3(0,0,-.5F))
            *glm::rotate(glm::mat4(1),.35F,glm::vec3(1,0,0))
            *glm::rotate(glm::mat4(1),-.45F,glm::vec3(0,1,0));
        std::filesystem::create_directories(output);
        for(int phase=0;phase<3;++phase)for(int eye=0;eye<2;++eye) {
            preview.cubeStates_.fill(0);
            if(phase==1)preview.cubeStates_[0]=1;
            const auto vp=glm::perspective(glm::radians(65.F),1.F,.01F,10.F)
                *glm::translate(glm::mat4(1),glm::vec3(eye?-.032F:.032F,0,0));
            if(phase==2)preview.cubePose_=glm::translate(glm::mat4(1),glm::vec3(20,0,-.5F));
            glViewport(0,0,512,512);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            preview.renderCube(vp);glFinish();
            std::vector<unsigned char> rgb(512*512*3);glReadPixels(0,0,512,512,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            int red=0,green=0;
            for(size_t i=0;i<rgb.size();i+=3){red+=rgb[i]>40 && rgb[i]>rgb[i+1]*2;green+=rgb[i+1]>40 && rgb[i+1]>rgb[i]*2;}
            if(phase==0 && (red<1000 || green))throw std::runtime_error("Unscanned cube must visibly render red in each eye");
            if(phase==1 && (red<500 || green<500))throw std::runtime_error("Accepted face must visibly turn green while unscanned faces stay red");
            if(phase==2 && (red || green))throw std::runtime_error("Offscreen negative control must contain no colored cube");
            const auto name=std::string(phase==0?"unscanned":phase==1?"partly-calibrated":"offscreen")+(eye?"-right.ppm":"-left.ppm");
            std::ofstream image(output/name,std::ios::binary);image<<"P6\n512 512\n255\n";
            for(int row=511;row>=0;--row)image.write(reinterpret_cast<char*>(rgb.data()+row*512*3),512*3);
            std::cout<<name<<" red="<<red<<" green="<<green<<'\n';
        }
        preview.shutdown();
        if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("OpenGL error in cube preview");
    }
};
int main(int argc,char** argv) {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"QR cube preview validation",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);
    QrCalibrationTest::run(argc>1?argv[1]:"qr-cube-evidence");
    glfwDestroyWindow(window);glfwTerminate();
}
