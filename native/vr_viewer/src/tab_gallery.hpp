#pragma once
#include "solid_ui.hpp"

// Desktop evaluation only. No bindings to production menus or documents.
class TabGallery {
 public:
    static constexpr std::array<const char*,4> labels{"VIEW","TRAJECTORY CONTROL","COLOUR MAPPING","SIMULATION OPTIONS"};
    struct Row {
        int selected=0,hover=-1,armed=-1;
        std::array<float,4> time{},growth{};
    };
    std::array<Row,2> rows{};
    struct Bounds {float x,y,w,h;};
    void reset(){rows={};}
    static float textWidth(int i,float scale){return (std::string(labels[i]).size()*6-1)*scale;}
    Bounds bounds(int row,int i) const {
        float x=-.72F;
        for(int n=0;n<i;++n)x+=width(row,n)+.016F;
        return {x,row==0?.28F:-.20F,width(row,i),row==0?.09F:.065F+rows[row].growth[i]*.025F};
    }
    float width(int row,int i) const {
        return row==0?.348F:.17F+rows[row].growth[i]*(std::max(.17F,textWidth(i,.0045F)+.04F)-.17F);
    }
    float overflow(int row,int i) const {return std::max(0.F,textWidth(i,row==0?.006F:.0033F+rows[row].growth[i]*.0012F)-(width(row,i)-.04F));}
    float offset(int i) const {
        const float distance=overflow(0,i),travel=distance/.085F;
        if(distance<=0)return 0;
        const float t=std::fmod(rows[0].time[i],2*travel+1.6F);
        if(t<.8F)return 0;
        if(t<.8F+travel)return (t-.8F)*.085F;
        if(t<1.6F+travel)return distance;
        return std::max(0.F,distance-(t-1.6F-travel)*.085F);
    }
    static bool inside(glm::vec3 p,Bounds b){return p.x>=b.x && p.x<=b.x+b.w && p.y>=b.y && p.y<=b.y+b.h;}
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
                const std::array<bool,2>& clicked,const std::array<bool,2>& pressed,float dt) {
        const auto p=placement.rayPanelLocalPoint(hands[1],{-2,-2},{2,2});
        for(int r=0;r<2;++r){auto& row=rows[r];int hit=-1;
            if(p){
                // Keep ownership while the expanding surface remains under the pointer.
                if(row.hover>=0 && inside(*p,bounds(r,row.hover)))hit=row.hover;
                else for(int i=0;i<4;++i)if(inside(*p,bounds(r,i)))hit=i;
            }
            row.hover=hit;
            if(clicked[1])row.armed=hit;
            if(!hands[1].valid)row.armed=-1;
            if(!pressed[1] && row.armed>=0){if(hit==row.armed)row.selected=hit;row.armed=-1;}
            for(int i=0;i<4;++i){const bool active=hit==i || row.selected==i;
                row.time[i]=active?row.time[i]+dt:0;
                const float target=active?1.F:0.F;
                row.growth[i]+=std::clamp(target-row.growth[i],-dt*5,dt*5);
            }
        }
    }
    // Clip each bitmap cell in local space, so fading also works in the angled view.
    static void label(SolidUi& ui,int i,Bounds b,float scale,float offset,glm::vec3 face) {
        const float left=b.x+.02F,right=b.x+b.w-.02F;
        const float full=textWidth(i,scale),x=left+(full<right-left?(right-left-full)*.5F:0)-offset;
        const float y=b.y+b.h*.5F+2.5F*scale;
        const bool fadeLeft=offset>.001F,fadeRight=full-offset>right-left+.001F;
        const std::string text=labels[i];
        for(size_t n=0;n<text.size();++n){const auto glyph=nadoc_vr::glyph(text[n]);
            for(size_t row=0;row<glyph.size();++row)for(int col=0;col<5;++col)if(glyph[row]&(1U<<(4-col))){
                const float a=std::max(left,x+(n*6+col)*scale),end=std::min(right,x+(n*6+col+.82F)*scale);
                if(end<=a)continue;
                float opacity=1;
                if(fadeLeft)opacity=std::min(opacity,(a-left)/.035F);
                if(fadeRight)opacity=std::min(opacity,(right-end)/.035F);
                ui.rect(a,y-row*scale,end-a,scale*.82F,glm::mix(face,glm::vec3(.94F,.97F,1.F),std::clamp(opacity,0.F,1.F)),.019F);
            }
        }
    }
    void render(SolidUi& ui) const {
        const glm::vec3 text(.90F,.94F,1.F),muted(.55F,.66F,.77F),accent(.43F,.79F,.94F);
        ui.text("LONG LABELS / TAB STUDIES",-.72F,.57F,.006F,text);
        ui.text("HOVER TO READ / CLICK TO KEEP SELECTED / R RESET",-.72F,.49F,.0035F,muted);
        for(int r=0;r<2;++r){const float top=r==0?.42F:-.06F;
            ui.text(r==0?"A  FIXED TABS + SCROLLING LABELS":"B  COMPACT TABS + EXPANSION",-.72F,top,.0043F,accent);
            const float bottom=r==0?.11F:-.37F;
            ui.rounded(-.73F,bottom,1.46F,.17F,.012F,{.065F,.095F,.13F},.003F);
            ui.text(std::string("SELECTED: ")+labels[rows[r].selected],-.69F,bottom+.09F,.0035F,text);
            for(int i=0;i<4;++i){const auto b=bounds(r,i);const bool selected=rows[r].selected==i,hover=rows[r].hover==i;
                const auto face=selected?glm::vec3(.14F,.29F,.36F):hover?glm::vec3(.17F,.23F,.30F):glm::vec3(.085F,.12F,.17F);
                ui.rounded(b.x,b.y,b.w,b.h,.009F,face,.012F);
                if(selected)ui.rect(b.x+.01F,b.y,b.w-.02F,.004F,accent,.016F);
                if(hover)ui.rect(b.x+.01F,b.y+b.h-.003F,b.w-.02F,.003F,text,.016F);
                label(ui,i,b,r==0?.006F:.0033F+rows[r].growth[i]*.0012F,r==0?offset(i):0,face);
            }
            ui.text(r==0?"LARGER TYPE. FADED EDGES. PAUSES AT BOTH ENDS.":"SMALL AT REST. HOVERED AND SELECTED TABS GROW.",-.70F,bottom-.04F,.0032F,muted);
        }
        ui.text("SAME LABELS / INDEPENDENT SELECTION / DESKTOP ONLY",-.72F,-.52F,.0034F,muted);
    }
    std::string observation() const {
        std::ostringstream out;out<<"{\"component\":\"tabs\",\"rows\":[";
        for(int r=0;r<2;++r){if(r)out<<',';out<<"{\"selected\":"<<rows[r].selected<<",\"hover\":"<<rows[r].hover<<",\"tabs\":[";
            for(int i=0;i<4;++i){if(i)out<<',';auto b=bounds(r,i);out<<"{\"label\":\""<<labels[i]<<"\",\"x\":"<<b.x<<",\"y\":"<<b.y<<",\"width\":"<<b.w<<",\"height\":"<<b.h<<",\"offset\":"<<(r==0?offset(i):0)<<",\"overflow\":"<<overflow(r,i)<<'}';}out<<"]}";
        }out<<"]}";return out.str();
    }
};
