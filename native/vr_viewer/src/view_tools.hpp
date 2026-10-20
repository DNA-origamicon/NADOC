#pragma once
#include <fstream>
#include <array>
#include <vector>
#include <future>
#include <chrono>
#include <memory>

// Included after GL helpers: one native stereo display stream plus the exact
// desktop-icon tablet. No desktop window capture or emulated mouse input.
class VRViewTools {
 public:
    struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal{};};
    struct Sprite {glm::vec3 p;glm::vec2 size;glm::vec4 color;glm::vec4 uv;glm::vec2 center;};
    struct Instance {glm::mat4 matrix;glm::vec4 color;};
    static_assert(sizeof(glm::mat4)==64 && sizeof(Instance)==80 && offsetof(Instance,color)==64,"Grouped texture view requires exact matrix+color wire layout");
    static_assert(sizeof(V)==48 && offsetof(V,p)==0 && offsetof(V,color)==12 && offsetof(V,uv)==28 && offsetof(V,normal)==36,"Exact indexing requires the complete padding-free wire vertex");
    struct Batch {std::vector<V> vertices,groupedVertices,indexedVertices,indexedGroupVertices;std::vector<uint32_t> indices,indexedGroupIndices;std::vector<Instance> instances;GLuint vertexBuffer=0,instanceBuffer=0,groupedVertexBuffer=0,instanceTexture=0,indexedVertexBuffer=0,indexBuffer=0,indexedGroupVertexBuffer=0,indexedGroupIndexBuffer=0;nadoc_vr::view_groups::Plan groupPlan;nadoc_vr::view_indexed::Plan indexPlan;nadoc_vr::view_indexed::GroupPlan indexedGroupPlan;uint32_t indexUploadGlError=0,indexedGroupUploadGlError=0;};
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
    std::optional<nadoc_vr::BoundsSummary> cachedSceneBounds;
    bool opaqueRequested=false;
    nadoc_vr::view_opaque::Eligibility opaqueEligibility;
    GLuint legacyProgram=0,opaqueProgram=0,groupedLegacyProgram=0,groupedOpaqueProgram=0;
    bool indexedRequested=false,indexedGroupsRequested=false;const char* indexedSelectionSource="default";const char* indexedGroupsSelectionSource="default";uint64_t indexedBatchDraws=0,indexedShadowBatchDraws=0,indexedGroupBatchDraws=0,indexedGroupLogicalInstances=0,indexedGroupHardwareInstances=0;
    bool groupsRequested=false;nadoc_vr::view_groups::Limits groupLimits;
    const char* opaqueSelectionSource="default";const char* groupsSelectionSource="default";
    const char* opaqueProgramReason="disabled";const char* groupsProgramReason="disabled";
    bool groupsAvailable()const{return nadoc_vr::view_programs::groupsAvailable(groupsRequested,legacyProgram,opaqueProgram,groupedLegacyProgram,groupedOpaqueProgram);}
    uint64_t groupedBatchDraws=0,legacyBatchDraws=0,groupedLogicalInstances=0,groupedHardwareInstances=0;
    std::string indexedMeshesJson()const {
        size_t eligible=0,grouped=0,cpuBytes=0,gpuBytes=0;std::string entries="[";
        for(size_t i=0;i<batches.size();++i){const auto& b=batches[i];const bool active=indexedRequested && b.indexPlan.eligible && b.indexedVertexBuffer && b.indexBuffer;
            const bool group=active && indexedGroupsRequested && groupsAvailable() && b.indexedGroupPlan.eligible && b.indexedGroupVertexBuffer && b.indexedGroupIndexBuffer && b.instanceTexture;
            eligible+=active;grouped+=group;cpuBytes+=b.indexPlan.derivedBytes+b.indexedGroupPlan.derivedBytes;
            gpuBytes+=b.indexedVertices.size()*sizeof(V)+b.indices.size()*sizeof(uint32_t)+b.indexedGroupVertices.size()*sizeof(V)+b.indexedGroupIndices.size()*sizeof(uint32_t);
            if(i)entries+=",";
            entries+="{\"active\":"+std::string(active?"true":"false")+",\"reason\":\""+b.indexPlan.reason+"\",\"original_vertices\":"+std::to_string(b.vertices.size())+",\"unique_vertices\":"+std::to_string(b.indexPlan.uniqueVertices)+",\"index_count\":"+std::to_string(b.indexPlan.indexCount)+",\"instances\":"+std::to_string(b.instances.size())+",\"upload_gl_error\":"+std::to_string(b.indexUploadGlError)+
                ",\"grouped_active\":"+(group?"true":"false")+",\"grouped_reason\":\""+b.indexedGroupPlan.reason+"\",\"grouped_vertices\":"+std::to_string(b.indexedGroupVertices.size())+",\"grouped_indices\":"+std::to_string(b.indexedGroupIndices.size())+",\"grouped_upload_gl_error\":"+std::to_string(b.indexedGroupUploadGlError)+"}";}
        entries+="]";
        return "{\"requested\":"+std::string(indexedRequested?"true":"false")+",\"default_enabled\":true,\"selection_source\":\""+indexedSelectionSource+"\",\"active_batches\":"+std::to_string(eligible)+
            ",\"grouping_requested\":"+(indexedGroupsRequested?"true":"false")+",\"grouping_default_enabled\":true,\"grouping_selection_source\":\""+indexedGroupsSelectionSource+"\",\"group_size\":8,\"grouped_active_batches\":"+std::to_string(grouped)+
            ",\"derived_cpu_bytes\":"+std::to_string(cpuBytes)+",\"derived_gpu_bytes\":"+std::to_string(gpuBytes)+",\"cpu_budget_bytes\":"+std::to_string(nadoc_vr::view_indexed::maxDerivedBytes)+",\"indexed_batch_draws\":"+std::to_string(indexedBatchDraws)+",\"indexed_shadow_batch_draws\":"+std::to_string(indexedShadowBatchDraws)+
            ",\"grouped_batch_draws\":"+std::to_string(indexedGroupBatchDraws)+",\"grouped_logical_instances\":"+std::to_string(indexedGroupLogicalInstances)+",\"grouped_hardware_instances\":"+std::to_string(indexedGroupHardwareInstances)+",\"batches\":"+entries+",\"equivalence\":\"byte-exact attributes and original batch/instance/triangle order; unchanged normal arithmetic\"}";
    }
    std::string instanceGroupsJson()const {
        size_t eligible=0,bytes=0;for(const auto& b:batches){eligible+=b.groupPlan.eligible;bytes+=b.groupedVertices.size()*sizeof(V);}
        std::string reasons="[";for(size_t i=0;i<batches.size();++i){if(i)reasons+=",";reasons+='"';reasons+=batches[i].groupPlan.reason;reasons+='"';}reasons+="]";
        return "{\"requested\":"+std::string(groupsRequested?"true":"false")+",\"default_enabled\":true,\"selection_source\":\""+groupsSelectionSource+"\",\"program_available\":"+(groupsAvailable()?"true":"false")+",\"program_reason\":\""+groupsProgramReason+"\",\"group_size\":8,\"eligible_batches\":"+std::to_string(eligible)+
            ",\"total_batches\":"+std::to_string(batches.size())+",\"texture_texel_limit\":"+std::to_string(groupLimits.textureTexels)+
            ",\"expanded_cpu_bytes\":"+std::to_string(bytes)+",\"expanded_gpu_bytes\":"+std::to_string(bytes)+
            ",\"grouped_batch_draws\":"+std::to_string(groupedBatchDraws)+",\"legacy_batch_draws\":"+std::to_string(legacyBatchDraws)+
            ",\"grouped_logical_instances\":"+std::to_string(groupedLogicalInstances)+",\"grouped_hardware_instances\":"+std::to_string(groupedHardwareInstances)+
            ",\"batch_eligibility_reasons\":"+reasons+",\"primitive_order\":\"original batch then instance then triangle\",\"shadow_batches\":\"legacy shader; eligible large meshes indexed\",\"indexed_meshes\":"+indexedMeshesJson()+"}";
    }
    uint64_t opaqueSceneCalls=0,legacyColorSceneCalls=0,ineligibleColorSceneCalls=0,unavailableProgramColorSceneCalls=0,legacyShadowSceneCalls=0;
    bool lastColorOpaque=false;
    bool opaqueActive(bool shadow=false)const{return nadoc_vr::view_opaque::active(opaqueRequested && opaqueProgram,opaqueEligibility,shadow);}
    void selectSceneProgram(bool shadow,bool grouped=false){program=grouped?(opaqueActive(shadow)?groupedOpaqueProgram:groupedLegacyProgram):(opaqueActive(shadow)?opaqueProgram:legacyProgram);}
    template<class Bind> void bindSceneLighting(Bind bind){selectSceneProgram(false);bind(legacyProgram);if(program!=legacyProgram)bind(program);if(groupsAvailable())bind(opaqueActive()?groupedOpaqueProgram:groupedLegacyProgram);}
    std::string opaqueShaderJson()const {
        return "{\"requested\":"+std::string(opaqueRequested?"true":"false")+",\"default_enabled\":true,\"selection_source\":\""+opaqueSelectionSource+"\",\"program_available\":"+(opaqueProgram?"true":"false")+",\"program_reason\":\""+opaqueProgramReason+"\",\"eligible\":"+(opaqueEligibility.eligible?"true":"false")+
            ",\"eligibility_reason\":\""+opaqueEligibility.reason+"\",\"last_color_opaque\":"+(lastColorOpaque?"true":"false")+
            ",\"opaque_color_scene_calls\":"+std::to_string(opaqueSceneCalls)+",\"legacy_color_scene_calls\":"+std::to_string(legacyColorSceneCalls)+
            ",\"ineligible_color_scene_calls\":"+std::to_string(ineligibleColorSceneCalls)+",\"program_unavailable_color_scene_calls\":"+std::to_string(unavailableProgramColorSceneCalls)+",\"legacy_shadow_scene_calls\":"+std::to_string(legacyShadowSceneCalls)+
            ",\"lines_sprites_panels\":\"always_legacy\",\"primitive_order\":\"unchanged\"}";
    }
    size_t instanceCount() const {size_t n=0;for(const auto& b:batches)n+=b.instances.size();return n;}
    std::optional<nadoc_vr::BoundsSummary> sceneBounds() const {return cachedSceneBounds;}
    bool inspectionLayout() const {return overrideScene() && !(flags&256);}
    bool overrideScene() const {return version && flags!=256;}
    void initialize() {
        opaqueRequested=nadoc_vr::view_opaque::requestedFromEnvironment();
        groupsRequested=nadoc_vr::view_groups::requestedFromEnvironment();
        indexedRequested=nadoc_vr::view_indexed::requestedFromEnvironment();
        indexedGroupsRequested=nadoc_vr::view_indexed::groupsRequestedFromEnvironment();
        indexedGroupsSelectionSource=nadoc_vr::view_programs::selectionSource(std::getenv("NADOC_VR_GROUPED_INDEXED_MESHES"));
        indexedSelectionSource=nadoc_vr::view_programs::selectionSource(std::getenv("NADOC_VR_INDEXED_VIEW_MESHES"));
        opaqueSelectionSource=nadoc_vr::view_programs::selectionSource(std::getenv("NADOC_VR_OPAQUE_VIEW_SHADER"));
        groupsSelectionSource=nadoc_vr::view_programs::selectionSource(std::getenv("NADOC_VR_GROUPED_VIEW_INSTANCES"));
        if(groupsRequested){GLint texels=0,vertexSamplers=0,units=0;glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE,&texels);glGetIntegerv(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS,&vertexSamplers);glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,&units);groupLimits={uint64_t(std::max(0,texels)),vertexSamplers>0,units>int(nadoc_vr::view_groups::textureUnit)};}
        struct Driver {
            GLuint compile(bool vertex,const char* source){return compileShader(vertex?GL_VERTEX_SHADER:GL_FRAGMENT_SHADER,source);}
            GLuint create(){return glCreateProgram();}
            void attach(GLuint p,GLuint shader){glAttachShader(p,shader);}
            void link(GLuint p){glLinkProgram(p);}
            bool linked(GLuint p){GLint ok=0;glGetProgramiv(p,GL_LINK_STATUS,&ok);return ok!=0;}
            void deleteShader(GLuint shader){glDeleteShader(shader);}
            void deleteProgram(GLuint p){glDeleteProgram(p);}
        } driver;
        auto makeProgram=[&](bool opaque,bool grouped=false) {
            const auto vertex=grouped?nadoc_vr::view_groups::vertexShader(nadoc_vr::view_opaque::vertexSource):std::string(nadoc_vr::view_opaque::vertexSource);
            const auto source=nadoc_vr::view_opaque::fragment(kLitFragmentSource,frostedGlassShader,opaque);
            return nadoc_vr::view_programs::build(driver,vertex.c_str(),source.c_str());
        };
        legacyProgram=makeProgram(false);program=legacyProgram;
        if(opaqueRequested){const auto result=nadoc_vr::view_programs::optional([&]{return makeProgram(true);});opaqueProgram=result.program;opaqueProgramReason=result.reason;}
        if(groupsRequested){groupsProgramReason="texture_sampler_unavailable";
            if(groupLimits.vertexSampler && groupLimits.textureUnitAvailable && groupLimits.textureTexels){
                const auto result=nadoc_vr::view_programs::optional([&]{return makeProgram(false,true);});groupedLegacyProgram=result.program;groupsProgramReason=result.reason;
                if(groupedLegacyProgram && opaqueProgram){const auto opaqueResult=nadoc_vr::view_programs::optional([&]{return makeProgram(true,true);});groupedOpaqueProgram=opaqueResult.program;groupsProgramReason=opaqueResult.reason;}
                if(!groupsAvailable()){if(groupedLegacyProgram)glDeleteProgram(groupedLegacyProgram);if(groupedOpaqueProgram)glDeleteProgram(groupedOpaqueProgram);groupedLegacyProgram=groupedOpaqueProgram=0;}
            }
        }
        glGenBuffers(1,&triangleVbo);glGenBuffers(1,&lineVbo);glGenVertexArrays(1,&vao);glGenBuffers(1,&vbo);glBindVertexArray(vao);glBindBuffer(GL_ARRAY_BUFFER,vbo);
        glEnableVertexAttribArray(0);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));
        glEnableVertexAttribArray(1);glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
        glEnableVertexAttribArray(2);glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));glEnableVertexAttribArray(8);glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));glBindVertexArray(0);
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    }
    void clearBatches(){for(auto& b:batches){if(b.indexedGroupVertexBuffer)glDeleteBuffers(1,&b.indexedGroupVertexBuffer);if(b.indexedGroupIndexBuffer)glDeleteBuffers(1,&b.indexedGroupIndexBuffer);if(b.indexedVertexBuffer)glDeleteBuffers(1,&b.indexedVertexBuffer);if(b.indexBuffer)glDeleteBuffers(1,&b.indexBuffer);if(b.vertexBuffer)glDeleteBuffers(1,&b.vertexBuffer);if(b.instanceTexture)glDeleteTextures(1,&b.instanceTexture);if(b.groupedVertexBuffer)glDeleteBuffers(1,&b.groupedVertexBuffer);if(b.instanceBuffer)glDeleteBuffers(1,&b.instanceBuffer);}batches.clear();}
    void shutdown(){cancelStaging();clearBatches();if(triangleVbo)glDeleteBuffers(1,&triangleVbo);if(lineVbo)glDeleteBuffers(1,&lineVbo);if(texture)glDeleteTextures(1,&texture);if(vbo)glDeleteBuffers(1,&vbo);if(vao)glDeleteVertexArrays(1,&vao);if(legacyProgram)glDeleteProgram(legacyProgram);if(opaqueProgram)glDeleteProgram(opaqueProgram);if(groupedLegacyProgram)glDeleteProgram(groupedLegacyProgram);if(groupedOpaqueProgram)glDeleteProgram(groupedOpaqueProgram);program=legacyProgram=opaqueProgram=groupedLegacyProgram=groupedOpaqueProgram=0;}
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
#include "view_tools_stream.inc"
    void draw(const glm::mat4& vp,const std::vector<V>& data,GLenum mode,bool glass=false,const glm::mat4& worldModel=glm::mat4(1),bool opaqueScene=false){
        if(data.empty()||!version)return;
        program=opaqueScene?opaqueProgram:legacyProgram;glUseProgram(program);FrostedGlass::bind(program,glass);glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&vp[0][0]);
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
        selectSceneProgram(shadow);const bool useOpaque=opaqueActive(shadow);
        if(shadow)++legacyShadowSceneCalls;
        else {lastColorOpaque=useOpaque;if(useOpaque)++opaqueSceneCalls;else {++legacyColorSceneCalls;if(opaqueRequested){if(!opaqueProgram)++unavailableProgramColorSceneCalls;else if(!opaqueEligibility.eligible)++ineligibleColorSceneCalls;}}}
        glUseProgram(program);glUniform1i(glGetUniformLocation(program,"shadowPass"),shadow);
        draw(vp*model,triangles,GL_TRIANGLES,false,model,useOpaque);if(!shadow)draw(vp*model,lines,GL_LINES,false,model);
        if(!batches.empty()) {
            selectSceneProgram(shadow);glUseProgram(program);FrostedGlass::bind(program,false);const auto matrix=vp*model;
            glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&matrix[0][0]);
            glUniformMatrix4fv(glGetUniformLocation(program,"worldModel"),1,GL_FALSE,&model[0][0]);
            glUniform1i(glGetUniformLocation(program,"instanced"),1);
            glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,texture);glUniform1i(glGetUniformLocation(program,"atlas"),1);
            glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
            glBindVertexArray(vao);
            bool boundGrouped=false;
            for(const auto& b:batches) {
                const bool indexed=indexedRequested && b.indexPlan.eligible && b.indexedVertexBuffer && b.indexBuffer;
                const bool indexedGroup=!shadow && indexed && indexedGroupsRequested && groupsAvailable() && b.indexedGroupPlan.eligible && b.indexedGroupVertexBuffer && b.indexedGroupIndexBuffer && b.instanceTexture;
                const bool grouped=indexedGroup || (!shadow && groupsAvailable() && b.groupPlan.eligible && b.groupedVertexBuffer && b.instanceTexture);
                if(grouped!=boundGrouped){selectSceneProgram(shadow,grouped);glUseProgram(program);FrostedGlass::bind(program,false);
                    glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&matrix[0][0]);glUniformMatrix4fv(glGetUniformLocation(program,"worldModel"),1,GL_FALSE,&model[0][0]);
                    glUniform1i(glGetUniformLocation(program,"instanced"),1);glUniform1i(glGetUniformLocation(program,"shadowPass"),shadow);glUniform1i(glGetUniformLocation(program,"atlas"),1);boundGrouped=grouped;}
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,indexedGroup?b.indexedGroupIndexBuffer:indexed?b.indexBuffer:0);
                glBindBuffer(GL_ARRAY_BUFFER,indexedGroup?b.indexedGroupVertexBuffer:grouped?b.groupedVertexBuffer:indexed?b.indexedVertexBuffer:b.vertexBuffer);
                glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));
                glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
                glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));
                glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));
                if(grouped){
                    for(GLuint a=3;a<=7;++a){glVertexAttribDivisor(a,0);glDisableVertexAttribArray(a);}
                    glActiveTexture(GL_TEXTURE0+nadoc_vr::view_groups::textureUnit);glBindTexture(GL_TEXTURE_BUFFER,b.instanceTexture);glActiveTexture(GL_TEXTURE1);
                    glUniform1i(glGetUniformLocation(program,"uGroupedInstances"),nadoc_vr::view_groups::textureUnit);glUniform1i(glGetUniformLocation(program,"uGroupBaseVertices"),int(indexedGroup?b.indexPlan.uniqueVertices:b.vertices.size()));
                    if(indexedGroup){
                        for(const auto& call:nadoc_vr::view_indexed::groupDraws(b.indices.size(),b.instances.size()))if(call.instances){glUniform1i(glGetUniformLocation(program,"uGroupFirstInstance"),call.firstInstance);glDrawElementsInstanced(GL_TRIANGLES,call.indexCount,GL_UNSIGNED_INT,nullptr,call.instances);indexedGroupHardwareInstances+=call.instances;}
                        ++indexedGroupBatchDraws;indexedGroupLogicalInstances+=b.instances.size();++indexedBatchDraws;
                    }else{
                        for(const auto& call:nadoc_vr::view_groups::draws(b.vertices.size(),b.instances.size()))if(call.instances){glUniform1i(glGetUniformLocation(program,"uGroupFirstInstance"),call.firstInstance);glDrawArraysInstanced(GL_TRIANGLES,0,call.vertices,call.instances);groupedHardwareInstances+=call.instances;}
                        ++groupedBatchDraws;groupedLogicalInstances+=b.instances.size();
                    }
                }else{
                    glBindBuffer(GL_ARRAY_BUFFER,b.instanceBuffer);
                    for(GLuint a=3;a<=7;++a){glEnableVertexAttribArray(a);glVertexAttribDivisor(a,1);glVertexAttribPointer(a,4,GL_FLOAT,GL_FALSE,sizeof(Instance),(void*)(uintptr_t)((a-3)*sizeof(glm::vec4)));}
                    if(indexed){glDrawElementsInstanced(GL_TRIANGLES,GLsizei(b.indices.size()),GL_UNSIGNED_INT,nullptr,GLsizei(b.instances.size()));++indexedBatchDraws;if(shadow)++indexedShadowBatchDraws;}
                    else glDrawArraysInstanced(GL_TRIANGLES,0,b.vertices.size(),b.instances.size());
                    ++legacyBatchDraws;
                }
            }
            for(GLuint a=3;a<=7;++a){glVertexAttribDivisor(a,0);glDisableVertexAttribArray(a);}
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,0);glBindVertexArray(0);glUseProgram(0);glDisable(GL_BLEND);
        }
        if(shadow){glUseProgram(program);glUniform1i(glGetUniformLocation(program,"shadowPass"),0);glUseProgram(0);return;}
        const float scale=glm::length(glm::vec3(model[0]));std::vector<V> billboards;billboards.reserve(sprites.size()*6);
        for(const auto& s:sprites){const auto p=glm::vec3(model*glm::vec4(s.p,1));const auto a=camera*glm::vec3(s.size.x*scale,0,0),b=camera*glm::vec3(0,s.size.y*scale,0);
            const auto bottom=p-a*s.center.x-b*s.center.y;
            quad(billboards,{{bottom+b,bottom,bottom+a+b,bottom+a}},s.uv,s.color);}
        draw(vp,billboards,GL_TRIANGLES);
    }
};
