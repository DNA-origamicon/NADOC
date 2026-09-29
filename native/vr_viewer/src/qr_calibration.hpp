#pragma once
#include <filesystem>
#include <fstream>
#include <sys/wait.h>
#include <spawn.h>
#include <signal.h>
#include <fcntl.h>
#include <unistd.h>

#ifndef NADOC_QR_ROOT
#define NADOC_QR_ROOT "."
#endif

// USB capture and decoding live in a bounded child process, never the render loop.
class QrCalibration {
    pid_t child_=-1;
    std::filesystem::path folder_;
    std::chrono::steady_clock::time_point started_{}, poll_{}, received_{}, cancelledAt_{};
    uint64_t sequence_=~uint64_t(0);
    GLuint texture_=0,program_=0,vao_=0;
    int width_=0,height_=0;size_t edgePixels_=0;
    bool cancelled_=false;
    std::optional<glm::mat4> pending_;
    static double now() { return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
 public:
    std::string status="QR not calibrated";
    std::optional<glm::mat4> anchor;
    bool running() const {return child_>0;}
    void start() {
        if(running()){cancel();return;}
        char path[]="/tmp/nadoc-vr-qr-XXXXXX";
        if(!mkdtemp(path)){status="Cannot start camera helper";return;}
        folder_=path;sequence_=~uint64_t(0);pending_.reset();cancelled_=false;width_=height_=0;
        started_=std::chrono::steady_clock::now();status="Starting Vive camera...";
        std::string uv="uv";
        if(const char* home=std::getenv("HOME")) {const auto candidate=std::filesystem::path(home)/".local/bin/uv";if(std::filesystem::exists(candidate))uv=candidate.string();}
        const auto log=(folder_/"worker.log").string();
        std::vector<std::string> words={uv,"run","--offline","--no-project","--python","3.12","--with","openvr==2.12.1401","--with","opencv-python-headless==4.12.0.88","python","-m","tools.vr_qr.worker","--output",path};
        std::vector<char*> args;for(auto& word:words)args.push_back(word.data());args.push_back(nullptr);
        posix_spawn_file_actions_t files;posix_spawn_file_actions_init(&files);
        posix_spawn_file_actions_addopen(&files,STDOUT_FILENO,log.c_str(),O_WRONLY|O_CREAT|O_TRUNC,0600);
        posix_spawn_file_actions_adddup2(&files,STDOUT_FILENO,STDERR_FILENO);
        posix_spawn_file_actions_addchdir_np(&files,NADOC_QR_ROOT);
        posix_spawnattr_t attributes;posix_spawnattr_init(&attributes);
        posix_spawnattr_setflags(&attributes,POSIX_SPAWN_SETPGROUP);posix_spawnattr_setpgroup(&attributes,0);
        const int error=posix_spawnp(&child_,uv.c_str(),&files,&attributes,args.data(),::environ);
        posix_spawn_file_actions_destroy(&files);posix_spawnattr_destroy(&attributes);
        if(error){child_=-1;status="Cannot start camera helper";std::filesystem::remove_all(folder_);folder_.clear();}

    }
    void cancel(){if(child_>0)kill(-child_,SIGTERM);cancelled_=true;cancelledAt_=std::chrono::steady_clock::now();pending_.reset();width_=height_=0;status="QR calibration cancelled";}
    void update(const std::optional<glm::mat4>& stageToLocal) {
        const auto clock=std::chrono::steady_clock::now();
        if(std::chrono::duration<double>(clock-poll_).count()<.08)return;
        poll_=clock;
        if(child_<=0)return;
        if(std::chrono::duration<double>(clock-started_).count()>100){cancel();kill(-child_,SIGKILL);status="QR calibration timed out";}
        std::ifstream input(folder_/"frame.bin",std::ios::binary);
        std::string magic,line;uint64_t seq;int w,h,valid;double timestamp;
        if(!cancelled_ && std::getline(input,magic) && magic=="NADOCQR1" && input>>seq>>w>>h>>valid>>timestamp && seq!=sequence_ && w>=0 && h>=0 && w<=1280 && h<=1280 && now()-timestamp>=0 && now()-timestamp<1){
            glm::mat4 pose(1);bool finite=true;
            for(int row=0;row<4;++row)for(int col=0;col<4;++col){input>>pose[col][row];finite=finite&&std::isfinite(pose[col][row]);}
            std::getline(input,line);std::getline(input,line);
            std::vector<unsigned char> pixels(static_cast<size_t>(w)*h*4);
            if(!pixels.empty())input.read(reinterpret_cast<char*>(pixels.data()),pixels.size());
            if(input && finite){
                edgePixels_=0;for(size_t i=3;i<pixels.size();i+=4)if(pixels[i]>0)++edgePixels_;
                sequence_=seq;status=line;received_=clock;width_=w;height_=h;
                if(w && h){
                    if(!texture_)glGenTextures(1,&texture_);
                    glBindTexture(GL_TEXTURE_2D,texture_);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
                    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());glBindTexture(GL_TEXTURE_2D,0);
                }
                if(valid==1){
                    if(stageToLocal){pending_=*stageToLocal*pose;anchor=pending_;status="QR registered - scene origin snapped";}
                    else status="Room tracking unavailable; model not moved";
                }
            }
        }
        if(cancelled_ && std::chrono::duration<double>(clock-cancelledAt_).count()>1)kill(-child_,SIGKILL);
        int result=0;
        if(waitpid(child_,&result,WNOHANG)==child_){
            child_=-1;
            if(sequence_==~uint64_t(0) && !cancelled_){status="Camera helper unavailable - see QR setup guide";std::ifstream log(folder_/"worker.log");char error[2048]{};log.read(error,sizeof(error)-1);std::cerr<<"QR camera helper: "<<error<<'\n';}
            std::filesystem::remove_all(folder_);folder_.clear();
        }
    }
    std::optional<glm::vec3> takePosition(){if(!pending_)return {};auto p=glm::vec3((*pending_)[3]);pending_.reset();return p;}
    void render(const glm::mat4& vp, const glm::vec3& head, const glm::quat& orientation){
        if(!texture_ || !width_ || cancelled_ || std::chrono::duration<double>(std::chrono::steady_clock::now()-received_).count()>.75)return;
        if(!program_){
            const auto vs=compileShader(GL_VERTEX_SHADER,R"(#version 330 core
uniform mat4 matrix;out vec2 uv;void main(){vec2 p=vec2((gl_VertexID==1||gl_VertexID==2)?1:-1,gl_VertexID>=2?1:-1);uv=vec2((p.x+1)*.5,(1-p.y)*.5);gl_Position=matrix*vec4(p,0,1);})");
            const auto fs=compileShader(GL_FRAGMENT_SHADER,R"(#version 330 core
uniform sampler2D camera;in vec2 uv;layout(location=0)out vec4 color;layout(location=1)out uint objectId;void main(){vec4 p=texture(camera,uv);color=vec4(p.rgb,max(.12,p.a*.75));objectId=0u;})");
            program_=glCreateProgram();glAttachShader(program_,vs);glAttachShader(program_,fs);glLinkProgram(program_);glDeleteShader(vs);glDeleteShader(fs);glGenVertexArrays(1,&vao_);
        }
        // Explicit mono preview panel, not a depth-correct passthrough claim.
        const auto matrix=vp*glm::translate(glm::mat4(1),head)*glm::toMat4(orientation)*glm::translate(glm::mat4(1),glm::vec3(0,0,-1))*glm::scale(glm::mat4(1),glm::vec3(.72,.72*height_/width_,1));
        glUseProgram(program_);glUniformMatrix4fv(glGetUniformLocation(program_,"matrix"),1,GL_FALSE,&matrix[0][0]);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,texture_);glUniform1i(glGetUniformLocation(program_,"camera"),0);
        glDisable(GL_DEPTH_TEST);glDepthMask(GL_FALSE);glDisable(GL_CULL_FACE);glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);glBindVertexArray(vao_);glDrawArrays(GL_TRIANGLE_FAN,0,4);
        glBindVertexArray(0);glBindTexture(GL_TEXTURE_2D,0);glDisable(GL_BLEND);glDepthMask(GL_TRUE);glEnable(GL_DEPTH_TEST);glUseProgram(0);
    }
    template<class Line> void drawAnchor(Line&& line) const {
        if(!anchor)return;
        const auto p=glm::vec3((*anchor)[3]);
        for(int axis=0;axis<3;++axis){glm::vec3 color(0);color[axis]=1;line(p,p+glm::vec3((*anchor)[axis])*.08F,color);}
    }
    std::string json() const {std::ostringstream s;s<<"{\"running\":"<<(running()?"true":"false")<<",\"preview_width\":"<<width_<<",\"preview_height\":"<<height_<<",\"edge_pixels\":"<<edgePixels_<<",\"registered\":"<<(anchor?"true":"false")<<",\"status\":"<<std::quoted(status)<<"}";return s.str();}
    void shutdown(){if(child_>0){kill(-child_,SIGKILL);waitpid(child_,nullptr,0);child_=-1;}if(!folder_.empty())std::filesystem::remove_all(folder_);if(texture_)glDeleteTextures(1,&texture_);if(program_)glDeleteProgram(program_);if(vao_)glDeleteVertexArrays(1,&vao_);}
};
