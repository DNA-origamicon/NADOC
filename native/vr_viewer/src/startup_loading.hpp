#pragma once

// CPU-only scene parsing runs independently of OpenXR's frame submission thread.
// Progress is atomic on disk; a ready record is published only after the scene.
class StartupLoading {
 public:
    std::string statusPath, scenePath, phase="loading", detail="Starting VR";
    int percent=2;
    bool active=false, anchored=false, uploadPending=false;
    std::future<SceneData> parsed;
    std::optional<SceneData> candidate;
    nadoc_vr::MenuPlacement placement;
    MenuPanelSurface surface;
    double completedAt=-1;
    void begin(std::string scene,std::string status) {
        scenePath=std::move(scene);statusPath=std::move(status);active=true;
    }
    void poll() {
        if(!active || phase=="error" || completedAt>=0 || candidate)return;
        if(parsed.valid()) {
            if(parsed.wait_for(std::chrono::seconds(0))==std::future_status::ready) {
                try {candidate=parsed.get();percent=92;detail="Preparing GPU buffers and selection";uploadPending=true;}
                catch(const std::exception& e){phase="error";detail=e.what();}
            }
            return;
        }
        std::ifstream input(statusPath);std::string next;int value;
        if(!(input>>next>>value))return;
        std::string message;std::getline(input,message);std::getline(input,message);
        if(next!="loading" && next!="ready" && next!="error")return;
        phase=next;percent=std::clamp(value,0,100);detail=message;
        if(phase=="ready") {
            detail="Reading and validating scene";
            parsed=std::async(std::launch::async,[path=scenePath]{return loadScene(path);});
        }
    }
    void render(const glm::mat4& vp,const XrPosef& head,bool representation=false,bool integrity=false) {
        if(!active)return;
        if(!anchored) {
            const glm::quat q(head.orientation.w,head.orientation.x,head.orientation.y,head.orientation.z);
            glm::vec3 forward=q*glm::vec3(0,0,-1);forward.y=0;
            if(glm::length(forward)<.01F)return;
            forward=glm::normalize(forward);
            placement.openDocked(glm::vec3(head.position.x,head.position.y,head.position.z)+forward*1.25F,
                glm::quatLookAt(forward,glm::vec3(0,1,0)));
            while(placement.scale()<1.14F)(void)placement.adjustScale(1);
            anchored=true;
        }
        std::vector<Vertex> lines,fills;
        auto text=[&](std::string label,float y,glm::vec3 color,float scale=.0028F) {
            if(label.size()>58)label=label.substr(0,55)+"...";
            for(size_t i=0;i<label.size();++i) {
                auto rows=nadoc_vr::glyph(static_cast<char>(std::toupper(static_cast<unsigned char>(label[i]))));
                for(size_t r=0;r<rows.size();++r)for(int c=0;c<5;++c)if(rows[r]&(1U<<(4-c))) {
                    const float x=-.49F+(i*6+c)*scale, py=y-r*scale;
                    lines.push_back({{x,py,.002F},color,1});
                    lines.push_back({{x+scale*.82F,py,.002F},color,1});
                }
            }
        };
        auto rect=[&](float x,float y,float w,float h,glm::vec3 color) {
            for(auto p:std::array<glm::vec2,6>{{{x,y},{x+w,y},{x+w,y+h},{x,y},{x+w,y+h},{x,y+h}}})
                fills.push_back({{p.x,p.y,0},color,1});
        };
        rect(-.53F,-.38F,1.06F,.76F,{.025F,.04F,.065F});
        text(integrity?"DNA POSITIONING CHECK FAILED":phase=="error"?"NADOC VR - LOADING FAILED":(representation?"NADOC VR - LOADING VIEW":"NADOC VR - LOADING PART"),.33F,{1,1,1},.004F);
        text(detail,.265F,phase=="error"?glm::vec3(1,.5F,.4F):glm::vec3(.7F,.85F,1));
        rect(-.49F,.19F,.98F,.026F,{.15F,.19F,.24F});
        rect(-.49F,.19F,.98F*percent/100,.026F,{.25F,.8F,.65F});
        text(std::to_string(percent)+"% - COMPLETED PREPARATION STAGES",.165F,{.8F,.85F,.9F});
        const std::array<std::pair<int,const char*>,8> stages={{{5,"VR runtime and document"},{15,"Nucleotide geometry"},{40,"Full display geometry"},{50,"Selection metadata"},{65,"Full scene export"},{85,"Snapshot validation and compression"},{92,"Native scene parsing and validation"},{100,"GPU buffers, selection and first part frame"}}};
        const std::array<std::pair<int,const char*>,4> representationStages={{{75,"Exporting representation"},{96,"Reading and preparing geometry"},{99,"Uploading display buffers"},{100,"Activating completed representation"}}};
        float y=.115F;
        if(representation)for(const auto& [end,label]:representationStages){
            text(std::string(percent>=end?"DONE  ":"WAIT  ")+label,y,percent>=end?glm::vec3(.4F,.85F,.65F):glm::vec3(.7F));y-=.055F;
        }
        else
        for(const auto& [end,label]:stages) {
            text(std::string(percent>=end?"DONE  ":"WAIT  ")+label,y,percent>=end?glm::vec3(.4F,.85F,.65F):glm::vec3(.7F));y-=.041F;
        }
        text(integrity?"CLOSE VR. REVIEW THE DNA POSITION REPORT IN NADOC.":phase=="error"?"CLOSE VR AND RETRY FROM NADOC":"HEADSET TRACKING REMAINS ACTIVE",-.335F,{.75F,.8F,.85F},.0026F);
        const nadoc_vr::MenuPanelBounds bounds{{-.53F,-.38F},{.53F,.38F}};
        surface.update(lines,bounds,false,fills);
        surface.render(vp,placement,bounds,.002F,false);
    }
};
