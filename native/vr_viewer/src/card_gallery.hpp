#pragma once
#include "solid_ui.hpp"

// Six independent disclosure studies, sharing release-to-activate semantics.
class CardGallery {
 public:
    struct Card {bool open=false;float reveal=0;int selected=-1,hover=-1,owner=-1,target=-1,clicks=0;};
    std::array<Card,6> cards{};
    bool disabled=false,demo=false;float clock=0;
    static constexpr std::array<const char*,6> names{"RAISED CARD","OUTLINE CARD","DISCLOSURE LIST","ACCORDION","TREE LIST","INSPECTOR GROUP"};
    static glm::vec3 center(size_t i){return {-.51F+float(i%3)*.51F,.255F-float(i/3)*.43F,.024F};}
    static glm::vec3 target(size_t i,int row=0){auto p=center(i);p.y+=row==0?.025F:row==1?-.065F:-.13F;return p;}
    void reset(){cards={};disabled=demo=false;clock=0;}
    void toggleDemo(){bool next=!demo;reset();demo=next;}
    int hit(size_t i,glm::vec3 p) const {
        const auto c=center(i);if(std::abs(p.x-c.x)>.21F)return -1;
        for(int row=0;row<3;++row)if((row==0 || (cards[i].open && cards[i].reveal>.98F)) && std::abs(p.y-target(i,row).y)<(row==0?.036F:.026F))return row;
        return -1;
    }
    void activate(size_t i,int row){
        auto& c=cards[i];++c.clicks;
        if(row==0)c.open=!c.open;
        else {c.selected=c.selected==row?-1:row;}
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
                const std::array<bool,2>& clicked,const std::array<bool,2>& held,float dt,
                std::array<std::optional<glm::vec3>,2>& beam) {
        clock+=dt;
        if(demo)for(auto& c:cards){c.open=int(clock/1.5F)%3!=0;c.selected=int(clock/1.5F)%3==2?1:-1;}
        for(auto& c:cards)c.hover=-1;
        for(size_t h=0;h<2;++h){
            int index=-1,row=-1;
            if(hands[h].valid){
                const auto origin=placement.localPoint(hands[h].position);
                const auto d=placement.localPoint(hands[h].position+hands[h].orientation*glm::vec3(0,0,-1))-origin;
                if(std::abs(d.z)>1e-7F){const float t=(.024F-origin.z)/d.z;const auto p=origin+t*d;
                    if(t>0)for(size_t i=0;i<6;++i)if((row=hit(i,p))>=0){index=int(i);cards[i].hover=row;beam[h]=placement.worldPoint(p);break;}
                }
            }
            for(size_t i=0;i<6;++i){auto& c=cards[i];if(c.owner!=int(h))continue;
                if(disabled || !hands[h].valid){c.owner=c.target=-1;continue;}
                if(!held[h]){if(index==int(i) && row==c.target)activate(i,row);c.owner=c.target=-1;}
            }
            if(clicked[h] && index>=0 && !disabled && cards[index].owner<0){demo=false;cards[index].owner=int(h);cards[index].target=row;}
        }
        for(auto& c:cards)c.reveal+=(float(c.open)-c.reveal)*(1-std::exp(-dt*18));
    }
    void render(SolidUi& ui) const {
        const glm::vec3 ink(.89F,.93F,.98F),muted(.53F,.64F,.75F),accent(.42F,.77F,1.F);
        ui.text("CARDS + LISTS / COMPONENT GALLERY",-.73F,.595F,.0057F,ink);
        ui.text("OPEN A HEADER. SELECT A ROW. CLOSE TO COMPARE.",-.73F,.52F,.0038F,muted);
        for(size_t i=0;i<6;++i){const auto p=center(i);const auto& c=cards[i];const float x=p.x-.22F;
            ui.text(std::to_string(i+1)+" / "+names[i],x,p.y+.17F,.0039F,ink);
            const char* hint=i==0?"ELEVATION + SUMMARY":i==1?"BORDER + SUMMARY":i==2?"FLAT / FULL ROW TARGET":i==3?"ONE DETAIL AT A TIME":i==4?"INDENTED CHILDREN":"PROPERTY SECTIONS";
            ui.text(hint,x,p.y+.116F,.0027F,muted);
            const float bottom=p.y-.018F-.16F*c.reveal,height=.08F+.16F*c.reveal;
            if(i<2){
                if(i==0)ui.bevel(x,bottom,.44F,height,.015F,.003F,.016F,.006F,{.15F,.20F,.27F});
                else {ui.rounded(x,bottom,.44F,height,.014F,accent*.65F,.01F);ui.rounded(x+.003F,bottom+.003F,.434F,height-.006F,.011F,{.045F,.065F,.09F},.012F);}
            }else ui.rect(x,bottom,.44F,height,{.06F,.085F,.115F},.01F);
            const bool focus=c.hover==0 || (c.owner>=0 && c.target==0);
            ui.rounded(x+.006F,p.y-.011F,.428F,.072F,i==5?.002F:.009F,disabled?glm::vec3(.11F):focus?glm::vec3(.23F,.34F,.44F):glm::vec3(.18F,.25F,.33F),.020F);
            ui.text(c.open?"-":"+",x+.018F,p.y+.039F,.0043F,disabled?muted:accent,.026F);
            ui.text(i==4?"CLUSTER 01":i==5?"APPEARANCE":"STRUCTURE",x+.056F,p.y+.039F,.004F,disabled?muted:ink,.026F);
            ui.text(c.open?"2":"2 ITEMS",x+.325F,p.y+.033F,.0025F,muted,.026F);
            if(c.reveal>.98F)for(int row=1;row<=2;++row){const auto pos=target(i,row);const bool chosen=c.selected==row;
                const float indent=i==4?.036F:.01F;
                const auto bg=disabled?glm::vec3(.085F):chosen?glm::vec3(.12F,.42F,.34F):c.hover==row?glm::vec3(.20F,.30F,.40F):glm::vec3(.095F,.13F,.17F);
                if(i==2){
                    if(chosen || c.hover==row)ui.rect(x+indent,pos.y-.026F,.43F-indent,.052F,bg,.021F);
                    ui.rect(x+.01F,pos.y-.028F,.42F,.0015F,muted*.4F,.022F);
                }else ui.rounded(x+indent,pos.y-.026F,.43F-indent,.052F,i==5?.001F:.005F,bg,.021F);
                if(i==5)ui.rect(x+.275F,pos.y-.021F,.139F,.042F,{.035F,.052F,.072F},.023F);
                if(i==4){ui.rect(x+.016F,pos.y,.015F,.002F,muted,.023F);ui.rect(x+.016F,pos.y,.002F,.065F,muted,.023F);}
                const char* label=i==5?(row==1?"COLOR":"OPACITY"):i==3?(row==1?"GEOMETRY":"MATERIAL"):(row==1?"HELIX A":"HELIX B");
                ui.text(label,x+indent+.012F,pos.y+(i==3 && chosen?.019F:.010F),.0032F,disabled?muted:ink,.026F);
                std::string value=i==5?(row==1?"BLUE":"100%"):chosen?"ON":"OFF";
                // Accordion reserves detail space inside the selected section.
                if(i==3){value=chosen?"-":"+";
                    if(chosen)ui.text(row==1?"LENGTH 24 BP":"COLOR BLUE",x+indent+.02F,pos.y-.007F,.0025F,muted,.026F);
                }
                ui.text(value,x+.30F,pos.y+.009F,.0029F,chosen?accent:muted,.026F);
            }
        }
    }
    std::string observation(const nadoc_vr::MenuPlacement& placement) const {
        std::ostringstream out;out<<'[';
        for(size_t i=0;i<6;++i){if(i)out<<',';const auto& c=cards[i];auto p=placement.worldPoint(target(i));
            out<<"{\"style\":\""<<names[i]<<"\",\"open\":"<<(c.open?"true":"false")<<",\"hovered\":"<<(c.hover>=0?"true":"false")<<",\"hovered_row\":"<<c.hover<<",\"selected\":"<<c.selected<<",\"clicks\":"<<c.clicks<<",\"state\":\""<<(disabled?"DISABLED":c.owner>=0?"PRESSED":c.open?"OPEN":"CLOSED")<<"\",\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"],\"children\":[";
            for(int row=1;row<=2;++row){if(row>1)out<<',';p=placement.worldPoint(target(i,row));out<<"["<<p.x<<','<<p.y<<','<<p.z<<']';}out<<"]}";
        }out<<']';return out.str();
    }
};
