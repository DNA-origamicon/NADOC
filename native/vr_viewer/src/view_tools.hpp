#pragma once
#include <fstream>
#include <array>
#include <vector>

// Included after GL helpers: one native stereo display stream plus the exact
// desktop-icon tablet. No desktop window capture or emulated mouse input.
class VRViewTools {
 public:
    struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal{};};
    struct Sprite {glm::vec3 p;glm::vec2 size;glm::vec4 color;glm::vec4 uv;glm::vec2 center;};
    struct Instance {glm::mat4 matrix;glm::vec4 color;};
    struct Batch {std::vector<V> vertices;std::vector<Instance> instances;GLuint vertexBuffer=0,instanceBuffer=0;};
    std::vector<Batch> batches;
    bool open=false,waiting=false;
    uint32_t version=0,flags=256,acknowledged=0;
    double parseMs=0,uploadMs=0;
    uint64_t sequence=0;int requested=0;
    std::array<int,2> hover{-1,-1};
    std::array<bool,2> closeHover{};
    nadoc_vr::MenuPlacement placement;
    nadoc_vr::GripFrameState gripState=nadoc_vr::GripFrameState::idle;
    static constexpr float half=.34666667F;
    // The browser texture fills the content square. Keep the native 25 mm grip
    // rails outside it so they cannot cross its header, icons or status text.
    static constexpr float frameHalf=half+.045F;
    static nadoc_vr::MenuPanelBounds panelBounds(){return {{-frameHalf,-frameHalf},{frameHalf,frameHalf}};}
    glm::vec3 position{};glm::quat orientation{1,0,0,0};
    std::vector<V> triangles,lines;std::vector<Sprite> sprites;
    static constexpr std::array<const char*,8> keys{"lengthHeatmap","sequences","undefinedBases","loopSkips","grid","overhangNames","clashes","deform"};
    GLuint program=0,vao=0,vbo=0,triangleVbo=0,lineVbo=0,texture=0;unsigned frames=0;
    size_t instanceCount() const {size_t n=0;for(const auto& b:batches)n+=b.instances.size();return n;}
    std::optional<nadoc_vr::BoundsSummary> sceneBounds() const {
        nadoc_vr::BoundsAccumulator bounds;
        for(const auto* vertices:{&triangles,&lines})for(const auto& v:*vertices)bounds.includePoint(v.p,0);
        for(const auto& batch:batches) {
            glm::vec3 lo(1e30F),hi(-1e30F);
            for(const auto& v:batch.vertices){lo=glm::min(lo,v.p);hi=glm::max(hi,v.p);}
            for(const auto& instance:batch.instances)for(int i=0;i<8;++i)
                bounds.includePoint(glm::vec3(instance.matrix*glm::vec4(i&1?hi.x:lo.x,i&2?hi.y:lo.y,i&4?hi.z:lo.z,1)),0);
        }
        for(const auto& sprite:sprites)bounds.includePoint(sprite.p,glm::length(sprite.size)*.5F);
        return bounds.summary(glm::mat4(1));
    }
    bool inspectionLayout() const {return overrideScene() && !(flags&256);}
    bool overrideScene() const {return version && flags!=256;}
    void initialize() {
        const auto vs=compileShader(GL_VERTEX_SHADER,R"(#version 330 core
layout(location=0) in vec3 p;layout(location=1) in vec4 color;layout(location=2) in vec2 uv;
layout(location=3) in mat4 instanceMatrix;layout(location=7) in vec4 instanceColor;
layout(location=8) in vec3 normal;
uniform mat4 vp,worldModel;uniform bool instanced;
out vec4 c;out vec2 t;out vec3 vNormal;out vec3 vWorldPosition;
out vec3 vColor;flat out int vTwoSided;flat out uint vSelection;flat out uint vObjectId;
void main(){mat4 m=instanced?instanceMatrix:mat4(1);vec4 point=m*vec4(p,1);
gl_Position=vp*point;c=color*(instanced?instanceColor:vec4(1));t=uv;
vWorldPosition=(worldModel*point).xyz;vNormal=transpose(inverse(mat3(worldModel*m)))*normal;
vColor=c.rgb;vTwoSided=1;vSelection=0u;vObjectId=0u;})");
        // Share the canonical diffuse/shadow function and coefficients. Atlas
        // text and lines remain unlit; recolored molecular surfaces stay lit.
        std::string fragment=kLitFragmentSource;
        fragment.resize(fragment.find("    void main() {"));
        fragment+=std::string("in vec4 c;in vec2 t;uniform sampler2D atlas;uniform bool shadowPass;\n")+frostedGlassShader+R"(
void main(){
    vec4 tex=t.x<0?vec4(1):texture(atlas,t);
    float alpha=c.a*tex.a;if(alpha<.02)discard;
    if(shadowPass){if(dot(vNormal,vNormal)<1e-12)discard;outColor=vec4(1);outObjectId=0u;return;}
    vec3 color=pow(max(c.rgb,vec3(0)),vec3(1.0/2.2))*tex.rgb;
    if(dot(vNormal,vNormal)>1e-12){vec3 n=normalize(vNormal)*(gl_FrontFacing?1.0:-1.0);
        color*=sceneLighting(n);}
    outColor=frostedMenu(vec4(color,alpha));outObjectId=0u;
})";
        const auto fs=compileShader(GL_FRAGMENT_SHADER,fragment.c_str());
        program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);glDeleteShader(vs);glDeleteShader(fs);
        GLint ok;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)throw std::runtime_error("VR view tools shader failed");
        glGenBuffers(1,&triangleVbo);glGenBuffers(1,&lineVbo);glGenVertexArrays(1,&vao);glGenBuffers(1,&vbo);glBindVertexArray(vao);glBindBuffer(GL_ARRAY_BUFFER,vbo);
        glEnableVertexAttribArray(0);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));
        glEnableVertexAttribArray(1);glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
        glEnableVertexAttribArray(2);glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));glEnableVertexAttribArray(8);glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));glBindVertexArray(0);
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    }
    void clearBatches(){for(auto& b:batches){if(b.vertexBuffer)glDeleteBuffers(1,&b.vertexBuffer);if(b.instanceBuffer)glDeleteBuffers(1,&b.instanceBuffer);}batches.clear();}
    void shutdown(){clearBatches();if(triangleVbo)glDeleteBuffers(1,&triangleVbo);if(lineVbo)glDeleteBuffers(1,&lineVbo);if(texture)glDeleteTextures(1,&texture);if(vbo)glDeleteBuffers(1,&vbo);if(vao)glDeleteVertexArrays(1,&vao);if(program)glDeleteProgram(program);}
    void close() {
        open=false;hover={-1,-1};closeHover={};
        placement.openDocked(placement.position(),placement.orientation());
    }
    std::optional<glm::vec3> rayEndpoint(const nadoc_vr::HandPose& hand) const {
        if(!open)return std::nullopt;
        const auto b=panelBounds();
        const auto p=placement.rayPanelLocalPoint(hand,b.minimum,b.maximum);
        return p?std::optional{placement.worldPoint(*p)}:std::nullopt;
    }
    void syncPose(){position=placement.position();orientation=placement.orientation();}
    void toggle(glm::vec3 controller,glm::quat facing,float distance=.8F) {open=!open;hover={-1,-1};if(open){placement.openFromController({true,false,controller,facing},distance);syncPose();}}
    void toggleFromQuiver(const std::array<nadoc_vr::HandPose,2>& hands) {
        open=!open;hover={-1,-1};
        if(open){placement.open(0,hands,hands[0].position,hands[0].orientation);updateFollowing(hands);}
    }
    void updateFollowing(const std::array<nadoc_vr::HandPose,2>& hands) {
        if(open){placement.update(hands,frameHalf);syncPose();}
    }
    glm::vec3 world(glm::vec2 uv) const {return placement.worldPoint({(uv.x-.5F)*2*half,(.5F-uv.y)*2*half,0});}
    template<class Feedback> void grips(const std::array<nadoc_vr::HandPose,2>& hands,const std::array<bool,2>& clicked,std::array<bool,2>& blocked,Feedback feedback) {
        if(!open)return;
        const auto bounds=panelBounds();
        placement.update(hands,frameHalf);
        if(!blocked[0]&&!blocked[1]&&(clicked[0]||clicked[1])&&placement.beginBorderResize(hands,bounds.minimum,bounds.maximum)) {feedback(0,.52F);feedback(1,.52F);}
        if(!placement.resizeActive()&&!placement.dragHand())for(size_t h=0;h<2;++h)
            if(!blocked[h]&&clicked[h]&&placement.beginDrag(h,hands,bounds.minimum,bounds.maximum)){feedback(h,.48F);break;}
        placement.update(hands,frameHalf);syncPose();
        if(placement.resizeActive())blocked.fill(true);
        if(placement.dragHand())blocked[*placement.dragHand()]=true;
        const bool near=placement.nearBorder(hands[0],bounds.minimum,bounds.maximum)||placement.nearBorder(hands[1],bounds.minimum,bounds.maximum);
        gripState=(placement.resizeActive()||placement.remoteMode()==2)?nadoc_vr::GripFrameState::resizing:(placement.dragHand()||placement.remoteMode()==1)?nadoc_vr::GripFrameState::moving:(near||placement.remoteHovered)?nadoc_vr::GripFrameState::ready:nadoc_vr::GripFrameState::idle;
    }
    static glm::vec2 cell(size_t i){return {(16.F+(i%2)*376+180)/768,(62.F+(i/2)*112+50)/768};}
    std::optional<glm::vec2> hit(const nadoc_vr::HandPose& hand) const {
        if(!open||!hand.valid)return std::nullopt;
        const auto p=placement.rayPanelLocalPoint(hand,{-half,-half},{half,half},30);
        if(!p)return std::nullopt;
        return glm::vec2(p->x/(2*half)+.5F,.5F-p->y/(2*half));
    }

    template<class Commit> void input(const std::array<nadoc_vr::HandPose,2>& hands,const std::array<bool,2>& clicked,std::array<bool,2>& blocked,Commit commit){
        hover={-1,-1};closeHover={};if(!open)return;
        for(size_t h=0;h<2;++h)if(auto uv=hit(hands[h])) {
            if(blocked[h])continue;
            blocked[h]=true;
            const float px=uv->x*768,py=uv->y*768;
            closeHover[h]=px>=620 && px<=744 && py>=8 && py<=52;
            if(clicked[h] && closeHover[h]){close();return;}
            if(clicked[h] && px>=24 && px<=344 && py>=620 && py<=684) {placement.toggleDock(0,hands,frameHalf);syncPose();continue;}
            for(int i=0;i<int(keys.size());++i){const auto c=cell(i)*768.F;if(std::abs(px-c.x)<180 && std::abs(py-c.y)<50){hover[h]=i;break;}}
            if(clicked[h]&&hover[h]>=0&&!waiting&&version){requested=hover[h];waiting=true;++sequence;commit(h);}
        }
    }
    bool poll(const std::string& path,glm::vec3 center,float scale,glm::vec3 origin) {
        if(path.empty()||++frames%15)return false;
        const double started=glfwGetTime();
        std::ifstream in(path+".viewtools",std::ios::binary);char magic[8];std::array<uint32_t,10> h{};
        if(!in.read(magic,8)||std::string(magic,8)!="NADOCVT1"||!in.read((char*)h.data(),40)||(h[0]!=4&&h[0]!=5)||h[1]==version)return false;
        if((h[2]>=4096 || (h[2]&(128|512|1024)))||h[3]+uint64_t(h[4])>4000000||h[3]%3||h[4]%2||h[5]>100000||h[6]!=2048||h[7]!=2048||h[8]>10000)return false;
        std::vector<V> t(h[3]),l(h[4]);std::vector<Sprite> s(h[5]);std::vector<unsigned char> rgba(2048*2048*4);
        static_assert(sizeof(V)==48 && sizeof(Sprite)==60 && sizeof(Instance)==80);
        auto readVertices=[&](std::vector<V>& values){
            if(h[0]==5)return bool(in.read((char*)values.data(),values.size()*sizeof(V)));
            for(auto& v:values)if(!in.read((char*)&v,36))return false;
            return true;
        };
        if(!readVertices(t)||!readVertices(l)||!in.read((char*)s.data(),s.size()*sizeof(Sprite)))return false;
        std::vector<Batch> next;uint64_t vertices=t.size()+l.size(),instances=0;
        const auto normalization=glm::translate(glm::mat4(1),origin)*glm::scale(glm::mat4(1),glm::vec3(scale))*glm::translate(glm::mat4(1),-center);
        for(uint32_t i=0;i<h[8];++i) {
            std::array<uint32_t,2> counts{};if(!in.read((char*)counts.data(),8))return false;
            vertices+=counts[0];instances+=counts[1];
            if(!counts[0]||counts[0]%3||!counts[1]||vertices>4000000||instances>1000000)return false;
            Batch b;b.vertices.resize(counts[0]);b.instances.resize(counts[1]);
            if(!readVertices(b.vertices)||!in.read((char*)b.instances.data(),b.instances.size()*sizeof(Instance)))return false;
            for(auto& instance:b.instances)instance.matrix=normalization*instance.matrix;
            next.push_back(std::move(b));
        }
        if(!in.read((char*)rgba.data(),rgba.size())||in.peek()!=std::char_traits<char>::eof())return false;
        const double uploading=glfwGetTime();parseMs=(uploading-started)*1000;
        clearBatches();batches=std::move(next);
        for(auto& b:batches) {
            glGenBuffers(1,&b.vertexBuffer);glBindBuffer(GL_ARRAY_BUFFER,b.vertexBuffer);glBufferData(GL_ARRAY_BUFFER,b.vertices.size()*sizeof(V),b.vertices.data(),GL_STATIC_DRAW);
            glGenBuffers(1,&b.instanceBuffer);glBindBuffer(GL_ARRAY_BUFFER,b.instanceBuffer);glBufferData(GL_ARRAY_BUFFER,b.instances.size()*sizeof(Instance),b.instances.data(),GL_STATIC_DRAW);
        }
        for(auto* list:{&t,&l})for(auto& v:*list)v.p=(v.p-center)*scale+origin;
        for(auto& v:s){v.p=(v.p-center)*scale+origin;v.size*=scale;}
        triangles=std::move(t);lines=std::move(l);sprites=std::move(s);version=h[1];flags=h[2];acknowledged=h[9];if(acknowledged>=sequence)waiting=false;
        glBindBuffer(GL_ARRAY_BUFFER,triangleVbo);glBufferData(GL_ARRAY_BUFFER,triangles.size()*sizeof(V),triangles.data(),GL_STATIC_DRAW);
        glBindBuffer(GL_ARRAY_BUFFER,lineVbo);glBufferData(GL_ARRAY_BUFFER,lines.size()*sizeof(V),lines.data(),GL_STATIC_DRAW);
        glBindTexture(GL_TEXTURE_2D,texture);glPixelStorei(GL_UNPACK_ALIGNMENT,1);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,2048,2048,0,GL_RGBA,GL_UNSIGNED_BYTE,rgba.data());glBindTexture(GL_TEXTURE_2D,0);uploadMs=(glfwGetTime()-uploading)*1000;return true;
    }
    void draw(const glm::mat4& vp,const std::vector<V>& data,GLenum mode,bool glass=false,const glm::mat4& worldModel=glm::mat4(1)){
        if(data.empty()||!version)return;
        glUseProgram(program);FrostedGlass::bind(program,glass);glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&vp[0][0]);
        glUniform1i(glGetUniformLocation(program,"instanced"),0);glUniformMatrix4fv(glGetUniformLocation(program,"worldModel"),1,GL_FALSE,&worldModel[0][0]);
        glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,texture);glUniform1i(glGetUniformLocation(program,"atlas"),1);
        glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        glBindVertexArray(vao);
        const GLuint buffer=&data==&triangles?triangleVbo:&data==&lines?lineVbo:vbo;
        glBindBuffer(GL_ARRAY_BUFFER,buffer);if(buffer==vbo)glBufferData(GL_ARRAY_BUFFER,data.size()*sizeof(V),data.data(),GL_STREAM_DRAW);
        glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));
        glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
        glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));
        glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));
        glDrawArrays(mode,0,data.size());glBindVertexArray(0);glUseProgram(0);glDisable(GL_BLEND);
    }
    static void quad(std::vector<V>& out,const std::array<glm::vec3,4>& p,glm::vec4 uv,glm::vec4 color){
        const std::array<glm::vec2,4> u{{{uv.x,uv.y},{uv.x,uv.w},{uv.z,uv.y},{uv.z,uv.w}}};
        for(int i:{0,1,2,2,1,3})out.push_back({p[i],color,u[i]});
    }
    void renderPanel(const glm::mat4& vp){if(!open)return;std::vector<V> v;
        quad(v,{{world({0,0}),world({0,1}),world({1,0}),world({1,1})}},{0,0,768.F/2048,768.F/2048},{1,1,1,1});draw(vp,v,GL_TRIANGLES,true);
        std::vector<V> border;
        for(int i:hover)if(i>=0){const auto c=cell(i);const glm::vec2 d{180.F/768,50.F/768};
            const std::array<glm::vec2,4> corners{{c-d,c+glm::vec2(d.x,-d.y),c+d,c+glm::vec2(-d.x,d.y)}};
            for(int j=0;j<4;++j)for(int k:{j,(j+1)%4})border.push_back({world(corners[k])+orientation*glm::vec3(0,0,.001F),{1,.7F,.1F,1},{-1,-1}});}
        if(closeHover[0]||closeHover[1]) {
            const std::array<glm::vec2,4> corners{{{620.F/768,8.F/768},{744.F/768,8.F/768},{744.F/768,52.F/768},{620.F/768,52.F/768}}};
            for(int j=0;j<4;++j)for(int k:{j,(j+1)%4})border.push_back({world(corners[k])+orientation*glm::vec3(0,0,.001F),{1,.7F,.1F,1},{-1,-1}});
        }
        nadoc_vr::drawGripFrame(panelBounds(),gripState,
            [&](glm::vec3 a,glm::vec3 b,glm::vec3 color){for(auto p:{a,b})border.push_back({placement.worldPoint(p),glm::vec4(color,1),{-1,-1}});},
            [](nadoc_vr::MenuPanelBounds,glm::vec3){});
        draw(vp,border,GL_LINES);
    }
    void renderScene(const glm::mat4& vp,const glm::mat4& model,glm::quat camera,bool shadow=false){
        glUseProgram(program);glUniform1i(glGetUniformLocation(program,"shadowPass"),shadow);
        draw(vp*model,triangles,GL_TRIANGLES,false,model);if(!shadow)draw(vp*model,lines,GL_LINES,false,model);
        if(!batches.empty()) {
            glUseProgram(program);FrostedGlass::bind(program,false);const auto matrix=vp*model;
            glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&matrix[0][0]);
            glUniformMatrix4fv(glGetUniformLocation(program,"worldModel"),1,GL_FALSE,&model[0][0]);
            glUniform1i(glGetUniformLocation(program,"instanced"),1);
            glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,texture);glUniform1i(glGetUniformLocation(program,"atlas"),1);
            glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
            glBindVertexArray(vao);
            for(const auto& b:batches) {
                glBindBuffer(GL_ARRAY_BUFFER,b.vertexBuffer);
                glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));
                glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
                glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));
                glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));
                glBindBuffer(GL_ARRAY_BUFFER,b.instanceBuffer);
                for(GLuint a=3;a<=7;++a){glEnableVertexAttribArray(a);glVertexAttribDivisor(a,1);glVertexAttribPointer(a,4,GL_FLOAT,GL_FALSE,sizeof(Instance),(void*)(uintptr_t)((a-3)*sizeof(glm::vec4)));}
                glDrawArraysInstanced(GL_TRIANGLES,0,b.vertices.size(),b.instances.size());
            }
            for(GLuint a=3;a<=7;++a){glVertexAttribDivisor(a,0);glDisableVertexAttribArray(a);}
            glBindVertexArray(0);glUseProgram(0);glDisable(GL_BLEND);
        }
        if(shadow){glUseProgram(program);glUniform1i(glGetUniformLocation(program,"shadowPass"),0);glUseProgram(0);return;}
        const float scale=glm::length(glm::vec3(model[0]));std::vector<V> billboards;billboards.reserve(sprites.size()*6);
        for(const auto& s:sprites){const auto p=glm::vec3(model*glm::vec4(s.p,1));const auto a=camera*glm::vec3(s.size.x*scale,0,0),b=camera*glm::vec3(0,s.size.y*scale,0);
            const auto bottom=p-a*s.center.x-b*s.center.y;
            quad(billboards,{{bottom+b,bottom,bottom+a+b,bottom+a}},s.uv,s.color);}
        draw(vp,billboards,GL_TRIANGLES);
    }
};
