#pragma once
#include "solid_ui.hpp"
#include "simulation_viz_gallery.hpp"

// Isolated design study: no simulation bridge, document, or job mutations.
// Accepted compact split; A/B compares scalar legend placement and treatment.
class SimulationGallery {
 public:
    using JobState=simulation_study::State;
    using Control=simulation_study::StudyControl;
    static constexpr bool horizontal=true;
    bool detailed=false;
    simulation_study::TrajectoryGallery trajectoryUi;
    simulation_study::ColourScaleGallery mapper;
    float dragOffset=0;
    int engine=0,job=-1,page=0,hover=-1,armed=-1,owner=-1;
    std::array<std::array<JobState,6>,6> states{};
    // Keep this study in desktop engine_capabilities.js ENGINE_KEYS order.
    static constexpr std::array<const char*,6> engines{"CANDO","SNUPI","MRDNA","OXDNA","NAMD","EXP"};
    static constexpr std::array<const char*,6> jobs{"R1 ALPINE","R2 ALPINE","R3 LOCAL","R4 ALPINE","R5 ALPINE","R6 LOCAL"};
    static constexpr std::array<const char*,6> status{"","64%","120 NS","80 NS","QUEUED","FAILED"};
    static constexpr std::array<const char*,6> dates{"OCT 12 08:15","OCT 12 09:40","OCT 11 16:20","OCT 11 10:05","OCT 12 10:30","OCT 10 14:50"};
    static constexpr std::array<const char*,6> stages{"RELAXATION","PRODUCTION","PRODUCTION","PRODUCTION","RELAXATION","PRODUCTION"};
    static void checkmark(SolidUi& ui,float x,float y,float z) {
        const glm::vec3 green(.42F,.86F,.65F);
        ui.triangle({x,y,z},{x+.010F,y-.010F,z},{x+.010F,y-.002F,z},green);
        ui.triangle({x+.010F,y-.010F,z},{x+.028F,y+.014F,z},{x+.024F,y+.019F,z},green);
        ui.triangle({x+.010F,y-.010F,z},{x+.024F,y+.019F,z},{x+.010F,y-.002F,z},green);
    }
    void reset(){const bool style=detailed;*this=SimulationGallery{};detailed=style;}
    bool available() const {return job>=0 && job<4;}
    static float jobY(int row) {return .075F-row*.102F;}
    bool scalar() const {return available() && simulation_study::scalarMode(states[engine][job].mode);}
    auto& scale(){return states[engine][job].scales[states[engine][job].mode];}
    const auto& scale() const {return states[engine][job].scales[states[engine][job].mode];}
    bool trajectoryMode() const {return available() && simulation_study::TrajectoryGallery::isMode(states[engine][job].mode);}
    auto& trajectory(){return states[engine][job].trajectories[states[engine][job].mode==9?1:0];}
    const auto& trajectory() const {return states[engine][job].trajectories[states[engine][job].mode==9?1:0];}
    bool escape(){if(trajectoryUi.popup){trajectoryUi.close();owner=armed=-1;return true;}if(!mapper.prompt.active())return false;mapper.close();return true;}
    bool numericPopup() const {return trajectoryUi.popup==1;}
    void digit(int n){if(numericPopup())trajectoryUi.digit(n);}
    void eraseDigit(){if(numericPopup())trajectoryUi.backspace();}
    void applyNumber(){if(numericPopup())trajectoryUi.apply(trajectory());}
    void focusLost(){mapper.close();trajectoryUi.close();owner=armed=-1;if(trajectoryMode())trajectory().playing=false;}
    void desktopPad(bool pressed){mapper.pad=pressed;}
    static constexpr float tabBase=.276F,tabStep=.20F;
    // Hit rectangles stay inside both tab silhouettes; decorative shoulders do not
    // steal neighboring targets. Active tabs rise upward, keeping the baseline fixed.
    Control engineControl(int index) const {
        return {10+index,-.60F+index*tabStep+.015F,tabBase+.005F,.17F,
                engine==index?.088F:.062F,engines[index],engine==index};
    }
    std::vector<glm::vec3> tabOutline(int index,float z) const {
        const float x=-.60F+index*tabStep,w=.20F,y=tabBase;
        const float top=y+(engine==index?.103F:.077F);
        std::vector<glm::vec3> points{{x-.016F,y,z}};
        const auto curve=[&](glm::vec2 control,glm::vec2 end){
            const glm::vec2 start(points.back());
            for(int n=1;n<=10;++n){const float t=n/10.F;const auto p=(1-t)*(1-t)*start+2*(1-t)*t*control+t*t*end;points.push_back({p,z});}
        };
        curve({x+.012F,y},{x+.012F,y+.023F});
        points.push_back({x+.012F,top-.022F,z});
        curve({x+.012F,top},{x+.035F,top});
        points.push_back({x+w-.035F,top,z});
        curve({x+w-.012F,top},{x+w-.012F,top-.022F});
        points.push_back({x+w-.012F,y+.023F,z});
        curve({x+w-.012F,y},{x+w+.016F,y});
        return points;
    }
    void tab(SolidUi& ui,int index,glm::vec3 face,float z) const {
        const auto outline=tabOutline(index,z);
        const glm::vec3 center(-.50F+index*tabStep,tabBase+.028F,z);
        for(size_t i=0;i<outline.size();++i)ui.triangle(center,outline[i],outline[(i+1)%outline.size()],face);
        const glm::vec3 edge=engine==index?glm::vec3(.40F,.67F,.76F):glm::vec3(.19F,.25F,.32F);
        // Open lower edge joins the active tab to the panel, like a browser tab.
        for(size_t i=0;i+1<outline.size();++i){auto a=outline[i],b=outline[i+1];
            auto aa=a,bb=b;aa.y-=.002F;bb.y-=.002F;a.z=b.z=aa.z=bb.z=z+.001F;
            ui.triangle(a,aa,bb,edge);ui.triangle(a,bb,b,edge);}
        const std::string label=engines[index];const float scale=.0035F;
        ui.text(label,center.x-label.size()*6*scale*.5F,tabBase+(engine==index?.064F:.050F),scale,
                engine==index?glm::vec3(.94F,.98F,1.F):glm::vec3(.55F,.63F,.72F),z+.003F);
    }
    void enginePanel(SolidUi& ui) const {
        const glm::vec3 face=glm::vec3(.085F,.13F,.17F);
        ui.rounded(-.635F,-.548F,1.27F,.823F,.016F,{.018F,.027F,.039F},.0005F);
        // Recessed inactive tabs first; the panel and active tab form one surface.
        for(int i=5;i>=0;--i)if(i!=engine)tab(ui,i,hover==10+i?glm::vec3(.12F,.18F,.24F):glm::vec3(.055F,.078F,.105F),.001F);
        ui.rounded(-.63F,-.54F,1.26F,.817F,.014F,{.23F,.34F,.40F},.001F);
        ui.rounded(-.627F,-.537F,1.254F,.811F,.012F,face,.002F);
        tab(ui,engine,face,.004F);
        // Cover the panel's top seam only at the selected tab's mouth.
        ui.rect(-.60F+engine*tabStep-.012F,.265F,.224F,.016F,face,.004F);
    }
    std::vector<simulation_study::Field> visibleFields() const {
        std::vector<simulation_study::Field> result;
        if(!available() || (trajectoryMode() && states[engine][job].group==0))return result;
        const auto& s=states[engine][job];
        for(const auto& f:simulation_study::fields(engine,s))if(f.group==s.group && !(f.id>=19 && f.id<=22) && !(f.id>=34 && f.id<=36) && f.id!=38)result.push_back(f);
        return result;
    }
    int pageSize() const {return scalar() && horizontal && states[engine][job].group==0?3:6;}
    std::vector<Control> controls() const {
        std::vector<Control> c{{0,-.61F,.438F,.43F,.072F,"A  FLAT SCRUBBER",!detailed},
            {1,-.16F,.438F,.43F,.072F,"B  RAISED SCRUBBER",detailed},
            {2,.43F,.438F,.18F,.072F,"RESET"}};
        for(int i=0;i<6;++i)c.push_back(engineControl(i));
        if(job<0){
            for(int row=0;row<(engine==5?1:3);++row){int index=page*3+row;
                c.push_back({20+index,-.60F,jobY(row),1.20F,.09F,engine==5?"SESSION PREDICTION":jobs[index]});}
            if(engine!=5){c.push_back({30,-.60F,-.515F,.16F,.065F,"PREV",false,page>0});
                c.push_back({31,-.42F,-.515F,.16F,.065F,"NEXT",false,page<1});}
            return c;
        }
        c.push_back({32,-.60F,.174F,.23F,.065F,"< JOBS"});
        if(!available())return c;
        const auto& s=states[engine][job];const auto modes=simulation_study::modes(engine);
        for(size_t i=0;i<modes.size();++i){const auto& m=modes[i];
            const bool enabled=!(engine==3 && job==0 && (m.id==2 || m.id==6));
            c.push_back({60+m.id,-.60F,.021F-i*.06095F,.529F,.05405F,m.label,s.mode==m.id,enabled});
        }
        const float x=-.05F,w=.65F;
        const auto fields=simulation_study::fields(engine,s);
        const std::array<const char*,3> groups{"OPTIONS","SCOPE","OVERLAYS"};
        for(int g=0;g<3;++g){bool exists=g==0;for(const auto& f:fields)exists|=f.group==g;
            if(exists)c.push_back({81+g,x+g*(w+.009F)/3,.024F,(w-.018F)/3,.043F,groups[g],s.group==g});}
        auto fs=visibleFields();const int start=s.optionPage*pageSize();
        const bool legend=scalar() && s.group==0;
        const float fieldWidth=legend && !horizontal?.438F:w;
        for(int i=start;i<std::min(start+pageSize(),int(fs.size()));++i){const auto& f=fs[i];
            c.push_back({100+f.id,x,(legend && horizontal?-.264F:-.039F)-(i-start)*.055F,fieldWidth,.047F,
                f.label+": "+f.choices[s.values[f.id]%f.choices.size()],
                f.choices.size()==2 && s.values[f.id]==1,f.choices.size()>1 || f.id==1 || f.id==12 || f.id==14 || f.id==15 || f.id==29});}
        if(fs.size()>size_t(pageSize())){
            c.push_back({84,x,-.424F,.16F,.043F,"PREV",false,s.optionPage>0});
            c.push_back({85,x+fieldWidth-.16F,-.424F,.16F,.043F,"MORE >",false,start+pageSize()<int(fs.size())});}
        if(legend){
            for(int id:{200,201}){auto b=mapper.bar(horizontal,scale(),id);c.push_back({id,b.x,b.y,b.z,b.w,id==200?"MIN":"MAX"});}
            c.push_back({203,horizontal?-.034F:.424F,horizontal?-.19F:-.391F,horizontal?.415F:.166F,horizontal?.043F:.030F,simulation_study::paletteNames[scale().palette]});
            c.push_back({204,horizontal?.398F:.424F,horizontal?-.19F:-.423F,horizontal?.186F:.166F,horizontal?.043F:.030F,"RESET RANGE"});
        }
        if(trajectoryMode()){
            if(s.group==0){
                auto extra=trajectoryUi.controls(trajectory(),detailed);
                if(trajectoryUi.popup){auto background=trajectoryUi;background.popup=0;
                    auto base=background.controls(trajectory(),detailed);c.insert(c.end(),base.begin(),base.end());}
                c.insert(c.end(),extra.begin(),extra.end());
            }
        }else{
            c.push_back({90,-.60F,-.516F,.24F,.05F,s.load==0?"SAMPLE: READY":s.load<3?"SAMPLE: LOAD":"SAMPLE: ERROR"});
            if(s.load>0)c.push_back({91,.25F,-.516F,.16F,.05F,s.load==3?"RETRY":"ADVANCE"});
            if(s.load==1 || s.load==2)c.push_back({92,.43F,-.516F,.17F,.05F,"CANCEL"});
        }
        if(mapper.prompt.active())for(int i=0;i<6;++i){const auto p=mapper.wheelCenter+nadoc_vr::PaletteControllerPrompt::direction(i,6)*.14F;
            c.push_back({210+i,p.x-.055F,p.y-.020F,.11F,.04F,simulation_study::paletteNames[i],scale().palette==i});}
        return c;
    }
    std::string modeLabel() const {
        for(const auto& m:simulation_study::modes(engine))if(m.id==states[engine][job].mode)return m.label;
        return "";
    }
    int hit(glm::vec3 p) const {
        if(trajectoryUi.popup){for(const auto& c:controls())if(c.id>=340 && c.enabled && p.x>=c.x && p.x<=c.x+c.w && p.y>=c.y && p.y<=c.y+c.h)return c.id;return -1;}
        // Wide acquisition bars may overlap near a tight colour window. Pick the
        // nearest bound along the scale so either handle remains reachable.
        int nearest=-1;float distance=10;
        for(const auto& c:controls())if((c.id==200 || c.id==201) && p.x>=c.x && p.x<=c.x+c.w && p.y>=c.y && p.y<=c.y+c.h){
            const float d=std::abs(horizontal?p.x-(c.x+c.w/2):p.y-(c.y+c.h/2));
            if(d<distance){distance=d;nearest=c.id;}
        }
        if(nearest>=0)return nearest;
        for(const auto& c:controls())if(c.enabled && p.x>=c.x && p.x<=c.x+c.w && p.y>=c.y && p.y<=c.y+c.h)return c.id;
        return -1;
    }
    void activate(int id){
        if(id>=300 && trajectoryMode()){trajectoryUi.action(trajectory(),id);return;}
        if(trajectoryMode() && (id==32 || (id>=10 && id<16 && engine!=id-10) || (id>=20 && id<26) || (id>=60 && id<=73 && states[engine][job].mode!=id-60))){
            trajectory().playing=false;if(trajectory().phase==1)trajectory().invalidate();
        }
        if(id<100){trajectoryUi.close();}
        if(id<100){mapper.close();owner=armed=-1;}
        if(id==0 || id==1){detailed=id==1;if(job>=0){page=job/3;states[engine][job].optionPage=0;}}
        else if(id==2)reset();
        else if(id==32)job=-1;
        else if(id>=10 && id<16){if(engine!=id-10){engine=id-10;job=-1;page=0;}}
        else if(id>=20 && id<26)job=job==id-20?-1:id-20;
        else if(id==30 || id==31){page=std::clamp(page+(id==30?-1:1),0,1);job=-1;}
        else if(available()){
            auto& s=states[engine][job];
            if(id>=60 && id<=73){s.mode=id-60;s.inspecting=true;s.group=0;s.optionPage=0;s.playing=false;}
            else if(id==80)s.inspecting=false;
            else if(id>=81 && id<=83){s.group=id-81;s.optionPage=0;}
            else if(id==84 || id==85)s.optionPage+=id==84?-1:1;
            else if(id==90){s.load=(s.load+1)%4;s.playing=false;}
            else if(id==91)s.load=s.load==3?1:s.load==1?2:0;
            else if(id==92)s.load=0;
            else if(id==203 && scalar())mapper.open(scale());
            else if(id==204 && scalar()){scale().low=0;scale().high=1;}
            else if(id>=100){for(const auto& f:simulation_study::fields(engine,s))if(f.id==id-100)simulation_study::edit(s,f);}
            auto fs=visibleFields();s.optionPage=std::min(s.optionPage,std::max(0,(int(fs.size())-1)/pageSize()));
        }
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,const std::array<bool,2>& held,
            std::array<std::optional<glm::vec3>,2>& beam,float dt){
        if(trajectoryMode())trajectory().update(dt);
        hover=-1;mapper.handleHover=-1;
        if(mapper.prompt.active()){
            const auto p=placement.rayPanelLocalPoint(hands[1],{-2,-2},{2,2});
            if(clicked[1] && p && glm::length(glm::vec2(*p)-mapper.wheelCenter)<.23F)mapper.mouseGesture=true;
            mapper.tick(dt,mapper.pad || (mapper.mouseGesture && held[1]),p?glm::vec2(*p):glm::vec2(0),hands[1].valid && bool(p));
            if(!held[1])mapper.mouseGesture=false;
            owner=armed=-1;return;
        }
        mapper.clock+=dt;
        for(int h=0;h<2;++h){
            auto p=placement.rayPanelLocalPoint(hands[h],{-2,-2},{2,2});
            int target=hands[h].valid && p?hit(*p):-1;
            if(trajectoryMode())trajectoryUi.wheels.hover=simulation_study::TrajectoryRangeWheels::field(target)?target:-1;
            if(target>=0){hover=target;beam[h]=placement.worldPoint(*p);}
            if(target==200 || target==201)mapper.handleHover=target;
            if(owner==h){
                if(!hands[h].valid || !p){owner=armed=mapper.drag=trajectoryUi.drag=-1;trajectoryUi.wheels.stop();}
                else if(simulation_study::TrajectoryRangeWheels::field(armed) && trajectoryMode()){
                    if(held[h])trajectoryUi.wheels.move(trajectory(),p->y,dt);
                    else {trajectoryUi.wheels.stop();owner=armed=-1;}
                }
                else if(armed==311 && trajectoryMode()){
                    if(held[h])trajectory().seek(trajectoryUi.fraction(detailed,*p));
                    else owner=armed=trajectoryUi.drag=-1;
                }
                else if(armed==200 || armed==201){
                    if(held[h])simulation_study::scaleBound(scale(),armed,mapper.fraction(horizontal,*p)+dragOffset);
                    else owner=armed=mapper.drag=trajectoryUi.drag=-1;
                }else if(!held[h]){const int action=armed;owner=armed=-1;if(target==action)activate(action);}
            }
            if(clicked[h] && target>=0 && owner<0){
                owner=h;armed=target;
                if(simulation_study::TrajectoryRangeWheels::field(target) && trajectoryMode())trajectoryUi.wheels.begin(target,p->y);
                if(target==311 && trajectoryMode()){trajectoryUi.drag=311;trajectory().seek(trajectoryUi.fraction(detailed,*p));}
                if(target==200 || target==201){mapper.drag=target;dragOffset=(target==200?scale().low:scale().high)-mapper.fraction(horizontal,*p);}
            }
        }
    }
    void render(SolidUi& ui) const {
        const glm::vec3 ink(.91F,.95F,.98F),muted(.58F,.68F,.77F),cyan(.38F,.81F,.91F),amber(1.F,.74F,.39F);
        ui.text("SIMULATION JOBS / ROUND 05",-.61F,.598F,.005F,ink);
        ui.text("COMPACT SPLIT / SAMPLE DATA",-.61F,.544F,.0034F,muted);
        ui.text("ENGINE",-.61F,.413F,.004F,cyan);enginePanel(ui);
        if(job<0){
            ui.text("JOBS / "+std::string(engines[engine])+(engine==5?" / SESSION RESULT":" / 6 RUNS"),-.60F,.222F,.004F,cyan);
            ui.text(engine==5?"EXP: CURRENT SESSION ONLY":"SELECT A RUN TO OPEN VISUALIZATIONS",-.60F,.18F,.0032F,muted);
        }else{
            ui.text(engine==5?"SESSION PREDICTION":jobs[job],-.34F,.226F,.0042F,ink);
            ui.text(engine==5?"CURRENT SESSION / FULL REQUIRED":std::string(dates[job])+" / "+stages[job],-.34F,.179F,.0026F,muted);
            if(engine!=5){if(job==0)checkmark(ui,.51F,.205F,.01F);else ui.text(status[job],.40F,.224F,.0033F,job==1?amber:ink);}
            ui.rect(-.60F,.15F,1.20F,.002F,{.22F,.33F,.40F},.005F);
            if(available()){
                const auto& s=states[engine][job];
                ui.text("VISUALIZATIONS",-.60F,.124F,.0036F,cyan);
                ui.rect(-.06F,-.425F,.002F,.51F,{.23F,.34F,.40F},.005F);
                ui.text(modeLabel(),-.05F,.091F,.003F,ink);
                const auto fs=visibleFields();
                if(fs.size()>size_t(pageSize()))ui.text(std::to_string(s.optionPage+1)+" / "+std::to_string((fs.size()+pageSize()-1)/pageSize()),.215F,-.398F,.0026F,muted);
                const bool legend=scalar() && s.group==0;
                if(legend){
                    mapper.draw(ui,horizontal,scale(),s.mode);
                    if(fs.empty()){
                        const float y=horizontal?-.26F:-.048F;
                        ui.text("COLOUR WINDOW",-.032F,y,.003F,cyan);
                        ui.text("POINT AT MIN / MAX",-.032F,y-.038F,.0029F,muted);
                        ui.text("GRAB + DRAG TO ADJUST",-.032F,y-.070F,.0029F,muted);
                        ui.text("SWATCH: SIX MAPS",-.032F,y-.119F,.0029F,muted);
                    }
                }
                if(trajectoryMode() && s.group==0)trajectoryUi.draw(ui,trajectory(),detailed,hover);
                std::string note="";
                if(engine==3 && job==0)note="RMSF / STRAIN: PRODUCTION REQUIRED";
                if(engine==2)note="INTERPOLATED SEGMENTS: LOWER CONFIDENCE";
                if(s.mode==7)note=s.values[11]?(s.values[16]?"SCOPE: 2 ELEMENTS / POPULATIONS 62% + 38%":"SCOPE > ADD SELECTION"):engine==4?"FREE PRODUCTION / ENM RAMP EXCLUDED":"SAMPLE POPULATIONS: 62% + 38%";
                if(s.mode==10)note="GEOMETRIC SCORE / NOT REACTION PROBABILITY";
                if(engine==3 && s.values[39])note="FINE DETAIL / REBUILDS EACH FRAME";
                if(!trajectoryMode() && (!legend || (mapper.handleHover<0 && mapper.drag<0)))ui.text(note,-.60F,-.449F,.0025F,muted);
                if(!trajectoryMode()){
                ui.text(s.load==0?"READY / SAMPLE":s.load==1?"DOWNLOADING 35%":s.load==2?"DECODE + APPLY 72%":"LOAD FAILED",-.335F,-.477F,.0026F,s.load==3?amber:cyan);
                ui.rect(-.335F,-.506F,.55F,.01F,{.18F,.25F,.3F},.009F);
                ui.rect(-.335F,-.506F,.55F*(s.load==0?1.F:s.load==1?.35F:s.load==2?.72F:0.F),.01F,cyan,.01F);
                }else if(s.group!=0)ui.text(trajectory().phase==2?"TRAJECTORY READY / OPTIONS FOR PLAYBACK":"TRAJECTORY / OPEN OPTIONS TO LOAD",-.60F,-.477F,.0028F,cyan);
            }else{
                ui.text(job==4?"WAITING FOR RESULTS":"NO VIEWABLE RESULT",-.60F,.045F,.004F,amber);
                ui.text(job==4?"VISUALIZATIONS APPEAR WHEN READY.":"RUN ENDED BEFORE THE FIRST FRAME.",-.60F,-.03F,.0032F,muted);
            }
        }
        for(const auto& c:controls()){
            if((c.id>=10 && c.id<16) || c.id==200 || c.id==201 || (c.id>=210 && c.id<=215) || simulation_study::TrajectoryRangeWheels::field(c.id) || c.id==311 || c.id>=340)continue;
            const bool isJob=c.id>=20 && c.id<26,isMode=c.id>=60 && c.id<=73;
            auto face=!c.enabled?glm::vec3(.065F,.078F,.09F):c.selected?glm::vec3(.09F,.29F,.33F):hover==c.id?glm::vec3(.20F,.29F,.36F):glm::vec3(.105F,.15F,.20F);
            const bool transport=c.id>=300 && c.id<=310;
            const float z=armed==c.id?.009F:transport && detailed?.030F:.014F;
            if(transport && !detailed)ui.rounded(c.x,c.y,c.w,c.h,.004F,face,z);
            else ui.bevel(c.x,c.y,c.w,c.h,.007F,.004F,z,.003F,face);
            const float scale=std::min(isJob?.0038F:isMode?.00368F:.0032F,(c.w-.025F)/std::max(1.F,float(c.label.size())*6));
            ui.text(c.label,c.x+.013F,c.y+c.h-(isJob?.018F:(c.h-7*scale)/2),scale,c.enabled?ink:muted*.65F,z+.003F);
            if(c.id==203)mapper.ramp(ui,this->scale().palette,c.x+.013F,c.y+.003F,c.w-.026F,.004F,true,z+.004F);
            if(isJob){int index=c.id-20;
                ui.text(engine==5?"CURRENT SESSION":dates[index],c.x+.018F,c.y+.032F,.0028F,muted,z+.003F);
                if(engine!=5){if(index==0)checkmark(ui,c.x+.32F,c.y+.024F,z+.003F);else ui.text(status[index],c.x+.32F,c.y+.032F,.0028F,index==1||index>=4?amber:ink,z+.003F);
                    ui.text(stages[index],c.x+.61F,c.y+.055F,.0029F,muted,z+.003F);}
                ui.text("OPEN >",c.x+c.w-.14F,c.y+.053F,.003F,cyan,z+.003F);
            }
        }
        if(job<0 && engine!=5)ui.text(std::string(page==0?"1-3":"4-6")+" / 6 JOBS",-.20F,-.473F,.0033F,muted);
        ui.text(detailed?"B / RAISED RAIL / SIDE PLAY BUTTON":"A / FLAT SCRUBBER / INLINE TRANSPORT",-.61F,-.572F,.0033F,cyan);
        ui.text("SET RANGE > LOAD > PLAY / CLICK FRAME TO ENTER",-.61F,-.61F,.0029F,muted);
        if(mapper.prompt.active())mapper.drawPicker(ui,scale().palette,horizontal);
        if(trajectoryUi.popup && trajectoryMode()){
            trajectoryUi.drawPopup(ui,trajectory());
            for(const auto& c:trajectoryUi.controls(trajectory(),detailed)){
                const auto face=!c.enabled?glm::vec3(.075F,.09F,.11F):hover==c.id?glm::vec3(.22F,.35F,.42F):c.id==352 || c.id==362?glm::vec3(.10F,.31F,.35F):glm::vec3(.14F,.21F,.28F);
                ui.bevel(c.x,c.y,c.w,c.h,.007F,.063F,.073F,.003F,face);
                const float size=std::min(.0035F,(c.w-.035F)/std::max(1.F,float(c.label.size())*6));
                ui.text(c.label,c.x+.014F,c.y+c.h-(c.h-7*size)/2,size,c.enabled?ink:muted,.077F);
            }
        }
    }
    std::string observation(const nadoc_vr::MenuPlacement& placement) const {
        std::ostringstream out;out<<"{\"layout\":\""<<(detailed?"B":"A")<<"\",\"engine\":"<<engine<<",\"job\":"<<job<<",\"page\":"<<page<<",\"trajectory_popup\":"<<trajectoryUi.popup<<",\"numeric_field\":"<<trajectoryUi.field<<",\"digits\":\""<<trajectoryUi.digits<<"\",\"hover\":"<<hover<<",\"handle_hover\":"<<mapper.handleHover<<",\"drag\":"<<mapper.drag<<",\"picker\":"<<(mapper.prompt.active()?"true":"false")<<",\"pulses\":"<<mapper.pulses<<",\"wheel_hover\":"<<(mapper.prompt.hovered()?int(*mapper.prompt.hovered()):-1)<<",\"controls\":[";
        bool first=true;for(const auto& c:controls()){
            if(!first)out<<',';
            first=false;const auto p=placement.worldPoint({c.x+c.w/2,c.y+c.h/2,0});
            out<<"{\"id\":"<<c.id<<",\"width\":"<<c.w<<",\"height\":"<<c.h<<",\"label\":\""<<c.label<<"\",\"enabled\":"<<(c.enabled?"true":"false")<<",\"selected\":"<<(c.selected?"true":"false")<<",\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";
        }
        out<<"],\"job_states\":[";first=true;for(const auto& es:states)for(const auto& s:es){if(!first)out<<',';first=false;
            out<<"{\"mode\":"<<s.mode<<",\"group\":"<<s.group<<",\"option_page\":"<<s.optionPage<<",\"load\":"<<s.load<<",\"frame\":"<<s.frame<<",\"playing\":"<<(s.playing?"true":"false")<<",\"values\":[";
            for(size_t i=0;i<s.values.size();++i){if(i)out<<',';out<<s.values[i];}out<<"],\"scales\":[";for(size_t i=0;i<s.scales.size();++i){if(i)out<<',';const auto& v=s.scales[i];out<<"{\"low\":"<<v.low<<",\"high\":"<<v.high<<",\"palette\":"<<v.palette<<"}";}out<<"],\"trajectories\":[";for(size_t i=0;i<s.trajectories.size();++i){if(i)out<<',';const auto& t=s.trajectories[i];out<<"{\"first\":"<<t.first<<",\"last\":"<<t.last<<",\"interval\":"<<t.interval<<",\"count\":"<<t.count()<<",\"phase\":"<<t.phase<<",\"index\":"<<t.index<<",\"source_frame\":"<<t.sourceFrame()<<",\"progress\":"<<t.progress<<",\"playing\":"<<(t.playing?"true":"false")<<"}";}out<<"]}";
        }out<<"]}";return out.str();
    }
};
