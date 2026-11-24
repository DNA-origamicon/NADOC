#pragma once
#include "solid_ui.hpp"

// UI-only sample data. No document creation, saving or filesystem operations.
class FileGallery {
 public:
    static constexpr std::array<const char*,6> names{"ESSENTIAL","FOLDER TILES","COMPACT LIST","DETAIL TABLE","FOLDER TREE","SPLIT INSPECTOR"};
    static constexpr std::array<const char*,6> hints{"ACTIONS FIRST / RECENT ON REQUEST","LARGE TARGETS / NAME AND TYPE","SIX NAMES / LITTLE METADATA","NAME / TYPE / MODIFIED / SIZE","EXPAND FOLDERS IN PLACE","BROWSE AND INSPECT TOGETHER"};
    struct Control {int id;float x,y,w,h;std::string label;bool enabled=true;};
    int variant=0, selected=-1, hover=-1, owner=-1, pressed=-1, clicks=0;
    bool opened=false, expanded=false, folder=false, disabled=false,demo=false;
    float clock=0;
    std::string status="SELECT A STYLE ABOVE";
    static constexpr std::array<const char*,6> files{"Corner.nadoc","Frame.nadoc","Hinge.nadoc","Panel.nadoc","Ring.nadoc","Tile.nadoc"};
    void reset(){*this=FileGallery{};}
    void choose(int v){variant=v;selected=-1;opened=expanded=folder=false;owner=pressed=-1;status=hints[v];}
    void toggleDemo(){demo=!demo;clock=0;}
    std::vector<Control> controls() const {
        std::vector<Control> c;
        for(int i=0;i<6;++i)c.push_back({i,-.73F+i*.245F,.43F,.228F,.07F,std::to_string(i+1)+" "+(i==0?"MINIMAL":i==1?"TILES":i==2?"LIST":i==3?"TABLE":i==4?"TREE":"SPLIT")});
        const char* actions[]={"NEW PART","NEW ASSEMBLY","OPEN","SAVE AS","CLOSE SESSION"};
        for(int i=0;i<5;++i)c.push_back({10+i,-.73F,.265F-i*.125F,.32F,.095F,actions[i],i!=1&&!disabled});
        if(variant==0&&!opened){c.push_back({20,-.32F,.18F,.97F,.16F,"SHOW RECENT FILES",!disabled});return c;}
        c.push_back({21,-.33F,.305F,.97F,.065F,folder?"< WORKSPACE / DESIGNS":"WORKSPACE / DESIGNS >",!disabled});
        if(variant==4){c.push_back({22,-.33F,.20F,.97F,.08F,expanded?"- DESIGNS":"+ DESIGNS",!disabled});if(!expanded)return c;}
        const int count=variant==0?2:variant==1?4:variant==4?4:6;
        for(int i=0;i<count;++i){
            float x=-.33F,y=.19F-i*.09F,w=.97F,h=.075F;
            if(variant==0){y=.13F-i*.17F;h=.14F;}
            if(variant==1){x+=i%2*.50F;y=.04F-i/2*.245F;w=.47F;h=.215F;}
            if(variant==3){y=.15F-i*.083F;h=.072F;}
            if(variant==4){x+=.06F;y=.09F-i*.105F;w-=.06F;h=.085F;}
            if(variant==5)w=.45F;
            c.push_back({30+i,x,y,w,h,files[i],!disabled});
        }
        return c;
    }
    int hit(glm::vec3 p)const{for(const auto& c:controls())if(p.x>=c.x&&p.x<=c.x+c.w&&p.y>=c.y&&p.y<=c.y+c.h)return c.id;return -1;}
    glm::vec3 target(int id)const{for(const auto& c:controls())if(c.id==id)return {c.x+c.w*.5F,c.y+c.h*.5F,.028F};return {};}
    void activate(int id){
        for(const auto& c:controls())if(c.id==id&&!c.enabled)return;
        ++clicks;if(id<6){choose(id);return;}
        if(id==20||id==12){opened=true;status="CHOOSE A SAMPLE FILE";}
        else if(id==21){folder=!folder;selected=-1;status=folder?"DESIGNS FOLDER":"WORKSPACE";}
        else if(id==22){expanded=!expanded;status=expanded?"FOLDER EXPANDED":"FOLDER COLLAPSED";}
        else if(id>=30){selected=id-30;status=std::string("SELECTED: ")+files[selected];}
        else status=id==10?"NEW PART SELECTED":id==13?"SAVE AS SELECTED":"CLOSE SESSION SELECTED";
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
                const std::array<bool,2>& clicked,const std::array<bool,2>& held,float dt,
                std::array<std::optional<glm::vec3>,2>& beam){
        if(demo){clock+=dt;if(clock>4){clock=0;choose((variant+1)%6);opened=expanded=true;}}
        hover=-1;
        for(int h=0;h<2;++h){const auto p=placement.rayPanelLocalPoint(hands[h],{-.79F,-.67F},{.79F,.65F});const int id=p?hit(*p):-1;
            if(id>=0){hover=id;beam[h]=placement.worldPoint(*p);}
            if(owner==h&&(!held[h]||!hands[h].valid)){if(hands[h].valid&&id==pressed)activate(id);owner=pressed=-1;}
            if(clicked[h]&&id>=0&&owner<0){demo=false;owner=h;pressed=id;}
        }
    }
    void render(SolidUi& ui)const{
        const glm::vec3 ink(.9F,.94F,1),muted(.55F,.66F,.77F),accent(.35F,.76F,1),gold(.95F,.70F,.30F);
        ui.text("FILE MENUS / "+std::to_string(variant+1)+" OF 6 / "+names[variant],-.73F,.595F,.0049F,ink);
        ui.text(hints[variant],-.73F,.535F,.0033F,muted);
        ui.text("FILE",-.73F,.39F,.0038F,muted);
        for(const auto& c:controls()){
            const bool focus=hover==c.id,chosen=c.id==variant||c.id==selected+30;
            const auto tint=!c.enabled?glm::vec3(.24F,.29F,.34F):chosen?glm::vec3(.15F,.38F,.48F):glm::vec3(.12F,.20F,.28F);
            const auto edge=focus?gold:chosen?accent:glm::vec3(.30F,.43F,.55F);
            if(variant==1&&c.id>=30){ // tabbed manila folder silhouette
                ui.rounded(c.x,c.y+c.h-.025F,c.w*.42F,.045F,.008F,gold*.65F,.012F);
                ui.bevel(c.x,c.y,c.w,c.h-.015F,.014F,.006F,.021F,.008F,focus?gold*.6F:tint);
            }else if(variant==0||variant==5){ui.raisedSlate(c.x,c.y,c.w,c.h,pressed==c.id?.012F:.023F,tint,edge);}
            else {ui.rounded(c.x,c.y,c.w,c.h,.009F,edge,.012F);ui.rounded(c.x+.003F,c.y+.003F,c.w-.006F,c.h-.006F,.007F,tint,.014F);}
            const float scale=c.id<6?.0028F:c.id>=30?.0031F:.0034F;
            ui.text(c.label,c.x+.015F,c.y+c.h*.60F,scale,c.enabled?ink:muted,.030F);
            if(c.id>=30&&(variant==0||variant==1))ui.text("PART / LOCAL",c.x+.015F,c.y+.03F,.0026F,muted,.030F);
            if(c.id>=30&&variant==3)ui.text("PART   TODAY   24 KB",c.x+.41F,c.y+.043F,.0028F,muted,.030F);
        }
        if(variant==3)ui.text("NAME                 TYPE   MODIFIED   SIZE",-.31F,.255F,.0028F,muted);
        if(variant==5){ui.rounded(.15F,-.30F,.50F,.57F,.015F,{.075F,.12F,.17F},.014F);
            ui.text("FILE DETAILS",.18F,.23F,.0037F,accent,.030F);
            ui.text(selected<0?"SELECT A FILE":files[selected],.18F,.13F,.0035F,ink,.030F);
            ui.text("TYPE       PART",.18F,.035F,.0029F,muted,.030F);
            ui.text("MODIFIED   TODAY",.18F,-.035F,.0029F,muted,.030F);
            ui.text("SIZE       24 KB",.18F,-.105F,.0029F,muted,.030F);
            ui.text("LOCATION   LOCAL",.18F,-.175F,.0029F,muted,.030F);
        }
        ui.text(status,-.73F,-.44F,.0034F,accent);
        ui.text("INTERACTIVE STYLE STUDY / SAMPLE FILES / NO DISK CHANGES",-.73F,-.495F,.0028F,muted);
    }
    std::string observation(const nadoc_vr::MenuPlacement& p)const{
        std::ostringstream out;out<<"{\"component\":\"files\",\"active\":true,\"variant\":"<<variant<<",\"selected\":"<<selected<<",\"expanded\":"<<(expanded?"true":"false")<<",\"clicks\":"<<clicks<<",\"orientation_xyzw\":["<<p.orientation().x<<','<<p.orientation().y<<','<<p.orientation().z<<','<<p.orientation().w<<"],\"controls\":[";
        bool first=true;for(const auto& c:controls()){if(!first)out<<',';first=false;const auto v=p.worldPoint(target(c.id));
            out<<"{\"id\":"<<c.id<<",\"enabled\":"<<(c.enabled?"true":"false")<<",\"hovered\":"<<(hover==c.id?"true":"false")<<",\"position\":["<<v.x<<','<<v.y<<','<<v.z<<"]}";}
        out<<"]}";return out.str();
    }
};
