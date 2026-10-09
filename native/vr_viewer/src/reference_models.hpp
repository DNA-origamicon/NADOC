#pragma once
#include "interaction.hpp"
#include "selection_wheel.hpp"
#include "latest_atomic_file.hpp"
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <future>

namespace nadoc_vr {
struct ReferenceWheelSpec {
    static constexpr size_t hand=1;
    static constexpr float phase=0,winding=1;
    static constexpr std::array<const char*,5> levels{"reset","color","opacity","duplicate","delete"};
    static constexpr std::array<const char*,5> labels{"RESET","COLOR","OPACITY","DUPLICATE","DELETE"};
};
struct ReferenceMesh {
    std::string id;
    std::vector<glm::vec3> vertices;
    glm::mat4 pose{1};
    glm::vec3 color{.55F,.66F,.77F};
    float opacity=1;
    GLuint vao=0,vbo=0;
};
// Mesh-local, double-sided Moller-Trumbore intersection. Transform the direction
// without normalizing it so t remains a tracking-space distance at any scale.
inline std::optional<float> referenceTriangleHit(glm::vec3 origin,glm::vec3 direction,
        glm::vec3 a,glm::vec3 b,glm::vec3 c) {
    const auto edge=b-a,other=c-a,p=glm::cross(direction,other);
    const float determinant=glm::dot(edge,p);
    if(std::abs(determinant)<1e-12F)return {};
    const auto offset=origin-a;const float u=glm::dot(offset,p)/determinant;
    if(u<0 || u>1)return {};
    const auto q=glm::cross(offset,edge);const float v=glm::dot(direction,q)/determinant;
    if(v<0 || u+v>1)return {};
    const float t=glm::dot(other,q)/determinant;
    return t>0?std::optional<float>(t):std::nullopt;
}

class ReferenceModels {
public:
    std::vector<ReferenceMesh> models;
    std::string selected;
    TouchpadWheel<ReferenceWheelSpec> wheel;
    bool hasSelection() const {return !selected.empty();}
    glm::mat4 normalization{1};
    int revision=-1;
    ReferenceMesh* selection() {
        for(auto& m:models)if(m.id==selected)return &m;
        return nullptr;
    }
    void poll(const std::string& eventPath,glm::vec3 center,float scale,glm::vec3 offset,double now) {
        path=eventPath;
        if(loading.valid() && loading.wait_for(std::chrono::seconds(0))==std::future_status::ready && !active) {
            auto next=loading.get();
            if(next) {
                clearMeshes();models=std::move(next->models);revision=next->revision;
                sourceRotation=next->rotation;pendingAction.clear();selected=next->selected;
                if(!selection())selected.clear();
            }
        }
        normalization=glm::translate(glm::mat4(1),offset)*glm::scale(glm::mat4(1),glm::vec3(scale))*glm::translate(glm::mat4(1),-center)*sourceRotation;
        if(path.empty() || now-lastPoll<.2 || loading.valid() || active)return;
        lastPoll=now;
        std::error_code error;const auto stamp=std::filesystem::last_write_time(path+".references",error);
        if(error || stamp==modified)return;
        modified=stamp;
        // Large ASCII meshes are parsed away from the headset frame thread.
        loading=std::async(std::launch::async,[file=path+".references"]{return read(file);});
    }
    std::optional<std::pair<size_t,float>> pick(const HandPose& hand,const glm::mat4& world) const {
        if(!hand.valid)return {};
        std::optional<std::pair<size_t,float>> nearest;
        for(size_t i=0;i<models.size();++i) {
            const auto inverse=glm::inverse(world*normalization*models[i].pose);
            const auto origin=glm::vec3(inverse*glm::vec4(hand.position,1));
            const auto direction=glm::vec3(inverse*glm::vec4(hand.orientation*glm::vec3(0,0,-1),0));
            const auto& v=models[i].vertices;
            for(size_t j=0;j+2<v.size();j+=3)if(auto t=referenceTriangleHit(origin,direction,v[j],v[j+1],v[j+2]))
                if(!nearest || *t<nearest->second)nearest=std::make_pair(i,*t);
        }
        return nearest;
    }
    void publish(const char* action="") {
        if(path.empty())return;
        if(*action)pendingAction=action;
        std::ostringstream out;out<<std::setprecision(9)<<"{\"sequence\":"<<++sequence<<",\"revision\":"<<revision<<",\"id\":\""<<selected<<"\",\"action\":\""<<pendingAction<<"\"";
        if(auto* mesh=selection()) {
            out<<",\"matrix\":[";
            for(int i=0;i<16;++i){if(i)out<<',';out<<mesh->pose[i/4][i%4];}out<<']';
        }
        out<<'}';writer.publish(path+".references-event",out.str());
    }
    void radial(bool pressed,glm::vec2 axis,const HandPose& hand,bool enabled) {
        const auto result=wheel.update(pressed,axis,hand,enabled && hasSelection() && !active && pendingAction.empty());
        if(result.commit)publish(ReferenceWheelSpec::levels[*result.commit]);
    }
    void input(const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,
            const std::array<bool,2>& held,std::array<bool,2>& blocked,const glm::mat4& world,double now) {
        if(wheel.blocksInput())blocked[1]=true;
        if(!pendingAction.empty()){blocked.fill(true);return;}
        if(active) {
            blocked[hand]=true;
            auto* mesh=selection();
            if(!mesh || !hands[hand].valid || !held[hand]) {
                if(mesh) {last=selected;lastHand=hand;releasedAt=now;publish();}
                active=false;twoHand=false;
            } else {
                const auto& h=hands[hand];
                glm::mat4 transform(1);
                if(twoHand && hands[1-hand].valid && held[1-hand]) {
                    blocked[1-hand]=true;
                    std::array<glm::vec3,2> points;
                    for(size_t i=0;i<2;++i)points[i]=hands[i].position+hands[i].orientation*glm::vec3(0,0,-distances[i]);
                    const auto span=points[1]-points[0];
                    const float ratio=glm::clamp(glm::length(span)/glm::length(initialSpan),.001F,1000.F);
                    const auto rotation=glm::length(span)>1e-5F?glm::rotation(glm::normalize(initialSpan),glm::normalize(span)):glm::quat(1,0,0,0);
                    transform=glm::translate(glm::mat4(1),(points[0]+points[1])*.5F)*glm::toMat4(rotation)*glm::scale(glm::mat4(1),glm::vec3(ratio))*glm::translate(glm::mat4(1),-initialMidpoint);
                } else if(twoHand) {
                    twoHand=false;resizing=false;initialPose=world*normalization*mesh->pose;initialHand=poseMatrix(h);
                } else if(resizing) {
                    // Exponential hand/ray travel supports resizing even when the
                    // user double-clicks the center, where radial scaling is singular.
                    const auto point=h.position+h.orientation*glm::vec3(0,0,-distances[hand]);
                    const auto up=glm::vec3(initialHand[1]);
                    const float ratio=std::exp(glm::clamp(glm::dot(point-initialPoint,up)*3.F,-6.9F,6.9F));
                    const auto pivot=glm::vec3(initialPose[3]);
                    transform=glm::translate(glm::mat4(1),pivot)*glm::scale(glm::mat4(1),glm::vec3(ratio))*glm::translate(glm::mat4(1),-pivot);
                } else transform=poseMatrix(h)*glm::inverse(initialHand);
                mesh->pose=glm::inverse(world*normalization)*transform*initialPose;
                const float size=glm::length(glm::vec3(mesh->pose[0]));
                if(std::isfinite(size) && size>0)for(int axis=0;axis<3;++axis)
                    mesh->pose[axis]*=glm::clamp(size,1e-6F,1e6F)/size;
                if(now-lastPublish>.1){publish();lastPublish=now;}
            }
        }
        for(size_t h=0;h<2;++h)if(!blocked[h] && clicked[h] && hands[h].valid) {
            const auto hit=pick(hands[h],world);
            if(!hit) {if(!active && hasSelection()){selected.clear();wheel.close();publish();}continue;}
            blocked[h]=true;
            auto& mesh=models[hit->first];
            if(active) {
                if(h!=hand && mesh.id==selected) {
                    distances[h]=hit->second;
                    std::array<glm::vec3,2> points;
                    for(size_t i=0;i<2;++i)points[i]=hands[i].position+hands[i].orientation*glm::vec3(0,0,-distances[i]);
                    initialSpan=points[1]-points[0];
                    if(glm::length(initialSpan)>.01F){twoHand=true;initialMidpoint=(points[0]+points[1])*.5F;initialPose=world*normalization*mesh.pose;}
                }
                continue;
            }
            selected=mesh.id;active=true;hand=h;
            resizing=last==selected && lastHand==h && now-releasedAt<.35;last.clear();
            distances[h]=hit->second;initialHand=poseMatrix(hands[h]);initialPose=world*normalization*mesh.pose;
            initialPoint=hands[h].position+hands[h].orientation*glm::vec3(0,0,-hit->second);
            publish();
        }
    }
    void render(const glm::mat4& vp,const glm::mat4& world) {
        if(models.empty())return;
        initialize();
        glUseProgram(program);glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);
        glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        for(auto& mesh:models) {
            if(!mesh.vao) {
                glGenVertexArrays(1,&mesh.vao);glGenBuffers(1,&mesh.vbo);glBindVertexArray(mesh.vao);
                glBindBuffer(GL_ARRAY_BUFFER,mesh.vbo);glBufferData(GL_ARRAY_BUFFER,mesh.vertices.size()*sizeof(glm::vec3),mesh.vertices.data(),GL_STATIC_DRAW);
                glEnableVertexAttribArray(0);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(glm::vec3),nullptr);
            }
            const auto model=world*normalization*mesh.pose,mvp=vp*model;
            glUniformMatrix4fv(glGetUniformLocation(program,"mvp"),1,GL_FALSE,&mvp[0][0]);
            glUniformMatrix4fv(glGetUniformLocation(program,"model"),1,GL_FALSE,&model[0][0]);
            const auto color=mesh.id==selected?glm::mix(mesh.color,glm::vec3(.3F,.75F,1),.45F):mesh.color;
            glUniform4f(glGetUniformLocation(program,"tint"),color.x,color.y,color.z,mesh.opacity);
            glDepthMask(mesh.opacity>=1?GL_TRUE:GL_FALSE);glBindVertexArray(mesh.vao);
            glDrawArrays(GL_TRIANGLES,0,GLsizei(mesh.vertices.size()));
        }
        glBindVertexArray(0);glDepthMask(GL_TRUE);glDisable(GL_BLEND);glUseProgram(0);
    }
    void shutdown() {clearMeshes();if(program)glDeleteProgram(program);program=0;}
private:
    struct Loaded {std::vector<ReferenceMesh> models;glm::mat4 rotation{1};int revision=-1;std::string selected;};
    std::future<std::optional<Loaded>> loading;
    glm::mat4 sourceRotation{1};
    static std::optional<Loaded> read(const std::string& file) {
        std::ifstream in(file);std::string magic;int version=0;size_t count=0;Loaded result;
        if(!(in>>magic>>version>>result.revision>>count) || magic!="NADOC_REFERENCES" || version!=1 || count>64)return {};
        for(int r=0;r<3;++r)for(int c=0;c<3;++c)in>>result.rotation[c][r];
        in>>result.selected;if(result.selected=="-")result.selected.clear();
        size_t total=0;
        for(size_t i=0;i<count;++i) {
            ReferenceMesh mesh;size_t n=0;in>>mesh.id>>n>>mesh.opacity;
            total+=n;if(n==0 || n%3 || total>3000000)return {};
            in>>mesh.color.x>>mesh.color.y>>mesh.color.z;
            for(int j=0;j<16;++j)in>>mesh.pose[j/4][j%4];
            mesh.vertices.resize(n);for(auto& p:mesh.vertices)in>>p.x>>p.y>>p.z;
            if(!in)return {};
            result.models.push_back(std::move(mesh));
        }
        return result;
    }
    std::string path,last,pendingAction;
    std::filesystem::file_time_type modified{};
    double lastPoll=-1,lastPublish=-1,releasedAt=-1;
    uint64_t sequence=0;
    bool active=false,resizing=false,twoHand=false;
    size_t hand=0,lastHand=0;
    std::array<float,2> distances{};
    glm::mat4 initialHand{1},initialPose{1};
    glm::vec3 initialPoint{},initialSpan{},initialMidpoint{};
    LatestAtomicFile writer;
    GLuint program=0;
    void clearMeshes(){for(auto& m:models){if(m.vbo)glDeleteBuffers(1,&m.vbo);if(m.vao)glDeleteVertexArrays(1,&m.vao);}models.clear();}
    void initialize() {
        if(program)return;
        auto compile=[](GLenum type,const char* source) {
            const auto shader=glCreateShader(type);glShaderSource(shader,1,&source,nullptr);glCompileShader(shader);
            GLint ok=0;glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
            if(!ok){glDeleteShader(shader);throw std::runtime_error("Reference shader compilation failed");}
            return shader;
        };
        const auto vs=compile(GL_VERTEX_SHADER,R"(#version 330 core
layout(location=0) in vec3 position;uniform mat4 mvp,model;out vec3 worldPoint;
void main(){worldPoint=(model*vec4(position,1)).xyz;gl_Position=mvp*vec4(position,1);})");
        const auto fs=compile(GL_FRAGMENT_SHADER,R"(#version 330 core
in vec3 worldPoint;uniform vec4 tint;layout(location=0) out vec4 color;layout(location=1) out uint objectId;
void main(){vec3 n=normalize(cross(dFdx(worldPoint),dFdy(worldPoint)));float light=.35+.65*abs(dot(n,normalize(vec3(.3,.8,.5))));color=vec4(tint.rgb*light,tint.a);objectId=0u;})");
        program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);glDeleteShader(vs);glDeleteShader(fs);
        GLint ok=0;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)throw std::runtime_error("Reference mesh shader link failed");
    }
};
}
