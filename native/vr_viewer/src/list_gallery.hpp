#pragma once
#include "solid_ui.hpp"
#include "scrollable_set.hpp"

// Six presentations of the same bounded list model. All targets use the same
// geometry as rendering; rows outside the discrete viewport have no hit target.
class ListGallery {
 public:
    struct Sample {
        nadoc_vr::ScrollableSet list;
        int hover=-1,owner=-1,target=-1,item=-1,clicks=0;
    };
    std::array<Sample,6> samples;
    bool disabled=false,demo=false;
    float clock=0;
    static constexpr std::array<const char*,6> names{"INSET TRAY","OUTLINED TABLE","JOB CARDS","SWEEP RAIL","GROUPED SET","PINNED INSPECTOR"};
    static glm::vec3 center(size_t i){return {-.51F+float(i%3)*.51F,.26F-float(i/3)*.46F,.028F};}
    // 0..8: three rows x (select, action A, action B); 9/10: up/down; 11: track.
    static glm::vec3 target(size_t i,int control=0){auto p=center(i);
        if(control<9){p.x+=control%3==0?-.10F:control%3==1?.085F:.15F;p.y+=.027F-float(control/3)*.066F;}
        else if(control==11){p.x+=.204F;p.y-=.04F;}
        else {p.x+=control==9?.11F:.18F;p.y-=.191F;}
        return p;
    }
    ListGallery(){reset();}
    void reset(){disabled=demo=false;clock=0;
        for(size_t i=0;i<samples.size();++i){samples[i]={};auto& list=samples[i].list;
            for(int j=0;j<12;++j){const bool jobs=i==2||i==4;const bool sweep=i==3;
                list.items.push_back({std::string(jobs?"JOB ":sweep?"POINT ":"DIM ")+(j<9?"0":"")+std::to_string(j+1),
                    jobs?(j<6?"RELAX":"PRODUCTION"):sweep?"SWEEP POSITION":"DISTANCE",jobs?15+j*7:20+j*3,true,false});}
        }
    }
    void toggleDemo(){const bool next=!demo;reset();demo=next;}
    int hit(size_t i,glm::vec3 p) const {
        const auto c=center(i);const float x=p.x-c.x,y=p.y-c.y;
        if(x>=.187F && x<=.224F && y>=-.14F && y<=.066F)return 11;
        for(int k=9;k<=10;++k){const auto t=target(i,k);if(std::abs(p.x-t.x)<.029F && std::abs(p.y-t.y)<.024F)return k;}
        if(x<-.215F || x>.179F)return -1;
        for(int slot=0;slot<3;++slot)if(samples[i].list.index(slot)>=0 && std::abs(y-(.027F-slot*.066F))<.028F)
            return slot*3+(x<.052F?0:x<.117F?1:2);
        return -1;
    }
    void activate(size_t i,int control,int item){auto& s=samples[i];
        if(control==9 || control==10){s.list.scroll(control==9?-1:1);++s.clicks;return;}
        if(control<0 || control>=9 || item<0 || item>=int(s.list.items.size()))return;
        auto& row=s.list.items[item];++s.clicks;
        if(control%3==0)s.list.selected=item;
        else if(i==1 || i==3)row.value=std::clamp(row.value+(control%3==1?-1:1),0,999);
        else if(control%3==1)row.enabled=!row.enabled;
        else row.pinned=!row.pinned;
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
                const std::array<bool,2>& clicked,const std::array<bool,2>& held,float dt,
                std::array<std::optional<glm::vec3>,2>& beam){
        clock+=dt;
        if(demo)for(auto& s:samples){s.list.seek((1-std::cos(clock*.7F))*.5F);s.list.selected=s.list.offset;s.list.items[s.list.offset].pinned=int(clock)%2;}
        for(auto& s:samples)s.hover=-1;
        for(size_t h=0;h<2;++h){int index=-1,control=-1;glm::vec3 p{};bool valid=false;
            if(hands[h].valid){const auto o=placement.localPoint(hands[h].position);
                const auto d=placement.localPoint(hands[h].position+hands[h].orientation*glm::vec3(0,0,-1))-o;
                if(std::abs(d.z)>1e-7F){const float t=(.028F-o.z)/d.z;p=o+t*d;valid=t>0;
                    if(valid)for(size_t i=0;i<6;++i)if((control=hit(i,p))>=0){index=int(i);samples[i].hover=control;beam[h]=placement.worldPoint(p);break;}}
            }
            for(size_t i=0;i<6;++i){auto& s=samples[i];if(s.owner!=int(h))continue;
                if(disabled || !valid){s.owner=s.target=s.item=-1;continue;}
                if(s.target==11 && held[h]){s.list.seek((center(i).y+.043F-p.y)/.16F);beam[h]=placement.worldPoint(p);}
                if(!held[h]){if(index==int(i) && control==s.target && (control>=9 || s.list.index(control/3)==s.item))activate(i,control,s.item);s.owner=s.target=s.item=-1;}
            }
            if(clicked[h] && index>=0 && !disabled && samples[index].owner<0){
                for(auto& s:samples)if(s.owner==int(h))s.owner=s.target=s.item=-1;
                auto& s=samples[index];demo=false;s.owner=int(h);s.target=control;s.item=control<9?s.list.index(control/3):-1;
                if(control==11)s.list.seek((center(index).y+.043F-p.y)/.16F);
            }
        }
    }
    void render(SolidUi& ui) const {
        const glm::vec3 ink(.89F,.93F,.98F),muted(.53F,.64F,.75F),accent(.42F,.77F,1.F),green(.38F,.85F,.68F);
        ui.text("SCROLLABLE SETS / COMPONENT GALLERY",-.73F,.595F,.0054F,ink);
        ui.text("SELECT ROW / USE ITS ACTIONS / DRAG RAIL OR USE UP + DOWN",-.73F,.527F,.0036F,muted);
        for(size_t i=0;i<6;++i){const auto p=center(i);const float x=p.x-.225F;const auto& s=samples[i];const auto& list=s.list;
            const glm::vec3 tint=i==2?glm::vec3(.82F,.62F,1.F):i==3?green:accent;
            ui.text(std::to_string(i+1)+" / "+names[i],x,p.y+.184F,.0037F,ink);
            const char* hint=i==0?"VISIBILITY + PIN":i==1?"ALIGNED VALUES / - +":i==2?"RUN STATE + PIN":i==3?"ORDER + POSITION / - +":i==4?"STICKY GROUP / RUN + PIN":"SELECTION STAYS IN VIEW";
            ui.text(hint,x,p.y+.142F,.00265F,muted);
            // Shared enclosing boundary makes membership explicit in every study.
            if(i==0){ui.bevel(x-.005F,p.y-.222F,.47F,.339F,.013F,.003F,.013F,.009F,{.21F,.28F,.35F});ui.rounded(x+.004F,p.y-.213F,.452F,.317F,.006F,{.028F,.044F,.062F},.015F);}
            else {ui.rounded(x-.003F,p.y-.222F,.466F,.339F,.012F,i==1?tint*.65F:glm::vec3(.13F,.19F,.25F),.012F);ui.rounded(x,p.y-.219F,.46F,.333F,.01F,{.052F,.075F,.10F},.014F);}
            ui.rect(x+.009F,p.y+.072F,.439F,.036F,{.15F,.23F,.30F},.018F);
            const std::string header=i==4?(list.offset<6?"RELAX / GROUP 1":"PRODUCTION / GROUP 2"):i==2?"SIMULATION JOBS":i==3?"SWEEP POINTS":"DIMENSIONS";
            ui.text(header,x+.018F,p.y+.098F,.0031F,disabled?muted:tint,.029F);
            ui.text("12",x+.39F,p.y+.098F,.003F,muted,.029F);
            for(int slot=0;slot<3;++slot){const int index=list.index(slot);if(index<0)continue;const auto& row=list.items[index];const auto t=target(i,slot*3);
                const bool selected=list.selected==index;const float left=x+(i==3?.04F:.01F),width=i==3?.36F:.39F;
                const auto bg=disabled?glm::vec3(.095F):selected?glm::vec3(.12F,.32F,.38F):glm::vec3(.10F,.145F,.19F);
                if(i==2)ui.bevel(left,t.y-.028F,width,.056F,.006F,.019F,.024F,.003F,bg);
                else if(i==1){ui.rect(left,t.y-.028F,width,.056F,bg,.022F);ui.rect(left,t.y-.030F,width,.0015F,muted*.45F,.024F);}
                else ui.rounded(left,t.y-.028F,width,.056F,.004F,bg,.022F);
                if(i==3){ui.rect(x+.02F,t.y-.033F,.002F,.066F,tint*.5F,.024F);ui.rounded(x+.012F,t.y-.006F,.018F,.018F,.009F,selected?tint:muted,.026F);}
                if(i==4)ui.rect(left,t.y-.028F,.004F,.056F,index<6?accent:green,.025F);
                if(s.hover/3==slot && s.hover>=0 && s.hover<9 && s.hover%3==0)ui.rect(left,t.y-.028F,.004F,.056F,ink,.027F);
                ui.text(row.label,left+.010F,t.y+.018F,.0031F,disabled?muted:ink,.030F);
                const std::string detail=(i==2||i==4)?(row.enabled?"RUN ":"PAUSED ")+std::to_string(row.value)+"%":std::to_string(row.value)+" NM";
                ui.text(detail,left+.010F,t.y-.006F,.0025F,muted,.030F);
                if(i==2)ui.rect(left+.13F,t.y-.020F,.105F*row.value/100.F,.004F,tint,.030F);
                for(int a=1;a<=2;++a){const int k=slot*3+a;const auto q=target(i,k);const bool on=a==1?row.enabled:row.pinned;
                    const bool numeric=i==1||i==3;
                    ui.rounded(q.x-.027F,q.y-.024F,.054F,.048F,.006F,disabled?glm::vec3(.12F):s.hover==k?glm::vec3(.32F,.43F,.53F):glm::vec3(.19F,.27F,.34F),.027F);
                    const std::string label=numeric?(a==1?"-":"+"):a==2?(on?"PIN":"P"):(i==2||i==4)?(on?"II":">"):(on?"ON":"OFF");
                    ui.text(label,q.x-float(label.size())*.007F,q.y+.009F,.0025F,disabled?muted:on&&!numeric?tint:ink,.031F);
                }
            }
            // A fixed rail and count disclose overflow even at an endpoint.
            ui.rounded(p.x+.19F,p.y-.14F,.028F,.206F,.009F,{.022F,.033F,.048F},.023F);
            const float fraction=list.maximum()?float(list.offset)/list.maximum():0;
            ui.rounded(p.x+.192F,p.y+.043F-fraction*.16F-.023F,.024F,.046F,.006F,disabled?muted:tint,.028F);
            const std::string info=i==5?(list.selected<0?"SELECT TO INSPECT":list.items[list.selected].label+" / "+std::to_string(list.items[list.selected].value)+" NM"):
                i==4?list.items[list.offset].detail:"SELECTED "+(list.selected<0?std::string("NONE"):list.items[list.selected].label);
            ui.text(info,x+.013F,p.y-.148F,.0025F,muted,.030F);
            ui.text(std::to_string(list.offset+1)+"-"+std::to_string(std::min(list.offset+3,int(list.items.size())))+" / 12",x+.014F,p.y-.183F,.003F,ink,.030F);
            for(int k=9;k<=10;++k){const auto q=target(i,k);const bool available=!disabled && (k==9?list.offset>0:list.offset<list.maximum());
                ui.rounded(q.x-.029F,q.y-.024F,.058F,.048F,.005F,s.hover==k&&available?glm::vec3(.3F,.4F,.5F):glm::vec3(.14F,.21F,.28F),.026F);
                ui.text(k==9?"UP":"DN",q.x-.016F,q.y+.009F,.0028F,available?ink:muted*.65F,.030F);}
        }
    }
    std::string observation(const nadoc_vr::MenuPlacement& placement) const {
        std::ostringstream out;out<<'[';
        for(size_t i=0;i<6;++i){if(i)out<<',';const auto& s=samples[i];auto p=placement.worldPoint(target(i));
            out<<"{\"style\":\""<<names[i]<<"\",\"hovered\":"<<(s.hover>=0?"true":"false")<<",\"hovered_control\":"<<s.hover<<",\"offset\":"<<s.list.offset<<",\"selected\":"<<s.list.selected<<",\"clicks\":"<<s.clicks<<",\"state\":\""<<(disabled?"DISABLED":s.owner>=0?"PRESSED":"READY")<<"\",\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"],\"controls\":[";
            for(int k=0;k<12;++k){if(k)out<<',';p=placement.worldPoint(target(i,k));out<<'['<<p.x<<','<<p.y<<','<<p.z<<']';}
            out<<"],\"items\":[";for(size_t j=0;j<s.list.items.size();++j){if(j)out<<',';const auto& r=s.list.items[j];out<<"{\"value\":"<<r.value<<",\"enabled\":"<<(r.enabled?"true":"false")<<",\"pinned\":"<<(r.pinned?"true":"false")<<'}';}out<<"]}";
        }out<<']';return out.str();
    }
};
