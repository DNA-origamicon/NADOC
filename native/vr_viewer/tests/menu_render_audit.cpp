// Deterministic pixels from production menu renderers. No OpenXR session or desktop capture.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#ifndef NADOC_MENU_AUDIT_SOURCE
#define NADOC_MENU_AUDIT_SOURCE "../src/main.cpp"
#endif
#include NADOC_MENU_AUDIT_SOURCE
#undef main

namespace {
struct LiveViewerTest {
    static constexpr int width=1200,height=1200;
    static void run(const std::filesystem::path& directory,const std::string& texture,GLuint framebuffer) {
        Viewer v(SceneData{},(directory/"events.json").string());
        SceneData data;data.available.fill(true);
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        v.sidebarMenus_.initialize();v.menuPanelSurface_.initialize();
        v.latticePanelSurface_.initialize();v.desktopFrameSurface_.initialize();
        v.startup_.surface.initialize();
        std::ofstream manifest(directory/"states.jsonl");
        size_t captured=0,failures=0;
        auto quote=[](const std::string& text){return '"'+nadoc_vr::scrywrite::visualJson(text)+'"';};
        auto background=[&] {
            glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);glDrawBuffer(GL_COLOR_ATTACHMENT0);glReadBuffer(GL_COLOR_ATTACHMENT0);
            glViewport(0,0,width,height);glDisable(GL_SCISSOR_TEST);
            glClearColor(.012F,.018F,.027F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            glEnable(GL_SCISSOR_TEST);
            for(int x=0;x<width;x+=40){glScissor(x,0,20,height);glClearColor(.026F,.035F,.048F,1);glClear(GL_COLOR_BUFFER_BIT);}
            glDisable(GL_SCISSOR_TEST);
        };
        auto pixels=[] {std::vector<uint8_t> rgb(width*height*3);glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());return rgb;};
        bool firstUpdateFramebuffer=true,resizedFramebuffer=true;
        {
            MenuPanelSurface fresh;fresh.initialize();background();
            const std::vector<Vertex> ink{{{-.1F,0,0},{1,1,1},1},{{.1F,0,0},{1,1,1},1}};
            fresh.update(ink,{{-.2F,-.3F},{.2F,.3F}},true);
            GLint draw=0,read=0;glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&draw);glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&read);
            firstUpdateFramebuffer=GLuint(draw)==framebuffer&&GLuint(read)==framebuffer;
            background();fresh.update(ink,{{-.7F,-.3F},{.7F,.3F}},true);
            glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&draw);glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&read);
            resizedFramebuffer=GLuint(draw)==framebuffer&&GLuint(read)==framebuffer;
            fresh.shutdown();
            if(!firstUpdateFramebuffer || !resizedFramebuffer)++failures;
        }
        auto capture=[&](const std::string& name,nadoc_vr::MenuPanelBounds bounds,
                         auto draw,const nadoc_vr::MenuLayoutAudit* audit=nullptr,
                         const std::vector<std::pair<std::string,nadoc_vr::MenuPanelBounds>>& inkRegions={}) {
            const auto center=(bounds.minimum+bounds.maximum)*.5F;
            const float half=std::max(bounds.maximum.x-bounds.minimum.x,bounds.maximum.y-bounds.minimum.y)*.5F+.055F;
            const auto vp=glm::ortho(center.x-half,center.x+half,center.y-half,center.y+half,.01F,10.F)*
                glm::lookAt(glm::vec3(0,0,2),glm::vec3(0),glm::vec3(0,1,0));
            // Cache allocation may restore framebuffer zero. Warm it before
            // binding the audit destination, just as production updates before eyes.
            draw(vp);background();const auto plain=pixels();v.menuGlass_.capture();draw(vp);glFinish();
            GLint actual=0;glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&actual);
            if(GLuint(actual)!=framebuffer)throw std::runtime_error("renderer changed audit framebuffer: "+name);
            const auto rgb=pixels();size_t changed=0,ink=0,neutral=0;
            for(size_t p=0;p<rgb.size();p+=3){const bool foreground=std::abs(int(rgb[p])-plain[p])+std::abs(int(rgb[p+1])-plain[p+1])+std::abs(int(rgb[p+2])-plain[p+2])>20;if(foreground)++changed;if(foreground&&std::max({rgb[p],rgb[p+1],rgb[p+2]})>85)++ink;if(rgb[p]>85&&rgb[p+1]>85&&rgb[p+2]>85)++neutral;}
            bool visible=changed>=1000&&ink>=100;
            std::ostringstream regions;bool firstRegion=true;
            for(const auto& [label,region]:inkRegions) {
                auto project=[&](glm::vec2 p){const auto clip=vp*glm::vec4(p,0,1);return glm::ivec2((clip.x/clip.w+1)*width*.5F,(clip.y/clip.w+1)*height*.5F);};
                const auto a=project(region.minimum),b=project(region.maximum);size_t textInk=0;
                for(int y=std::max(0,a.y);y<std::min(height,b.y);++y)for(int x=std::max(0,a.x);x<std::min(width,b.x);++x){const size_t p=(y*width+x)*3;if(std::min({rgb[p],rgb[p+1],rgb[p+2]})>100)++textInk;}
                visible=visible&&textInk>=100;
                if(!firstRegion)regions<<',';firstRegion=false;
                regions<<"{\"label\":"<<quote(label)<<",\"bright_text_pixels\":"<<textInk<<",\"minimum\":100}";
            }
            if(!visible || (audit&&!audit->valid()))++failures;
            const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,width,height);
            std::ofstream file(directory/(name+".png"),std::ios::binary);file.write(reinterpret_cast<const char*>(png.data()),png.size());
            manifest<<"{\"name\":"<<quote(name)<<",\"image\":"<<quote(name+".png")<<",\"width\":"<<width<<",\"height\":"<<height
                <<",\"changed_pixels\":"<<changed<<",\"ink_pixels\":"<<ink<<",\"neutral_pixels\":"<<neutral<<",\"pixels_visible\":"<<(visible?"true":"false")<<",\"pixels_per_local_m\":"<<width/(2*half)<<",\"text_regions\":["<<regions.str()<<']'
                <<",\"layout\":"<<quote(audit?audit->status():"not-instrumented")<<",\"layout_detail\":"<<quote(audit?audit->summary():"")<<",\"texts\":[";
            if(audit){bool first=true;for(const auto& text:audit->texts()){if(!first)manifest<<',';first=false;manifest<<"{\"owner\":"<<quote(text.owner)<<",\"text\":"<<quote(text.text)<<",\"scale\":"<<text.scale<<'}';}}
            manifest<<"]}\n";manifest.flush();++captured;
        };
        auto resetMenus=[&](bool assembly=false) {
            v.sidebarMenus_.menus={nadoc_vr::SidebarMenu(0,assembly),nadoc_vr::SidebarMenu(1,assembly)};
            for(auto& menu:v.sidebarMenus_.menus){menu.placement.openDocked({0,0,0},{1,0,0,0});menu.placement.setScale(1);}
            v.solidWheels_.vertices.clear();
            v.extrudePanel_.active=false;v.bendPanel_.active=false;
        };
        auto sidebar=[&](const std::string& name,int hand) {
            auto& menu=v.sidebarMenus_.menus[hand];menu.open=true;v.sidebarMenus_.menus[1-hand].open=false;
            v.solidWheels_.vertices.clear();v.controllerGuides_.clear();
            if(menu.tab().key=="extrude") {
                v.extrudePanel_.active=true;v.toolShell_.activate(nadoc_vr::ToolMode::extrude,"end");
                (void)v.toolConfig_.bind(nadoc_vr::ToolMode::extrude,"end:1","end",{"owner:1"});
                v.appendThumbwheelGuides();
                if(v.solidWheels_.vertices.empty())throw std::runtime_error("extrude fixture omitted production wheels");
            } else v.extrudePanel_.active=false;
            if(menu.tab().key=="bend" || menu.tab().key=="twist")
                v.drawBend([&](auto a,auto b,auto color){v.controllerGuides_.push_back({a,color,1});v.controllerGuides_.push_back({b,color,1});});
            v.sidebarMenus_.draw();
            capture(name,menu.bounds(),[&](const auto& vp){v.solidWheels_.render(vp);v.sidebarMenus_.render(vp);v.glScene_->renderGuides(vp,v.controllerGuides_);},&menu.audit);
        };
        auto pages=[&](const std::string& name,int hand) {
            auto& menu=v.sidebarMenus_.menus[hand];menu.offsets[menu.selected]=0;
            for(size_t page=0;;++page){sidebar(name+"-page-"+std::to_string(page+1),hand);if(!menu.canScroll(1))break;menu.scroll(1);if(page>150)throw std::runtime_error("scroll did not advance");}
        };
        for(bool assembly:{false,true})for(int hand:{0,1}) {
            resetMenus(assembly);auto& menu=v.sidebarMenus_.menus[hand];
            for(menu.selected=0;menu.selected<menu.tabs.size();++menu.selected) {
                const std::string name=std::string(assembly?"assembly-":"part-")+(hand?"right-":"left-")+menu.tab().key;
                menu.collapsed.clear();pages(name+"-expanded",hand);
                for(const auto& row:menu.tab().rows)if(row.action.starts_with("section:"))menu.collapsed.insert(row.id);
                if(!menu.collapsed.empty())pages(name+"-collapsed",hand);
            }
        }
        // Explicit state styling and scrolling midpoint, separate from all-page coverage.
        resetMenus();auto& styled=v.sidebarMenus_.menus[1];
        for(int state=0;state<4;++state) {
            styled.available=[state](const auto&){return state!=0;};styled.isActive=[state](const auto&){return state==1;};
            const auto controls=styled.controls();styled.hovered=state==2?controls.back().id:"";styled.focus.reset();
            if(state==3)styled.focus.begin(controls.back().id,"");
            sidebar("sidebar-style-"+std::to_string(state),1);
        }
        resetMenus();
        for(bool enabled:{false,true}) {
            auto& menus=v.sidebarMenus_.menus;menus[1].available=[enabled](const auto&){return enabled;};
            nadoc_vr::ExtrudePanel extrude;extrude.enter(menus);
            extrude.refresh(menus,999999,1,"EXTRUDE FROM XY","BOTH",true,12345,false,false,"READY TO EXTRUDE - LONG STATUS DETAIL FOR FORMATTING AUDIT");
            pages(std::string("tool-extrude-")+(enabled?"ready":"disabled"),1);extrude.exit(menus);
            nadoc_vr::MovePanel move;move.enter(menus);move.refresh(menus,"nucleotide","READY - A LONG TARGET SELECTION STATUS FOR FORMATTING");
            pages(std::string("tool-move-")+(enabled?"ready":"disabled"),1);move.exit(menus);
            for(bool twist:{false,true}) {
                nadoc_vr::BendPanel bend;bend.twist=twist;bend.enter(menus);
                nadoc_vr::ToolConfigurationDraft config;(void)config.bind(twist?nadoc_vr::ToolMode::twist:nadoc_vr::ToolMode::bend,"cluster:1","cluster",{"owner:1"});
                (void)config.setPlaneBp("a",0);(void)config.setPlaneBp("b",999999);
                bend.clusterLabel="Long selected cluster label with multiple descriptive words";
                for(int i=0;i<13;++i)bend.clusters.push_back("Cluster "+std::to_string(i)+" with a long descriptive name");
                for(bool expanded:{false,true})for(int page:expanded?std::vector<int>{0,4,8,12}:std::vector<int>{0}) {
                    bend.clustersOpen=expanded;bend.clusterPage=page;
                    bend.refresh(menus,config,"READY - LONG EXECUTION STATUS / CHOOSE TWO PLANES");
                    v.bendPanel_=bend;v.toolConfig_=config;
                    sidebar(std::string(twist?"tool-twist-":"tool-bend-")+(enabled?"ready-":"disabled-")+(expanded?"expanded-":"collapsed-")+std::to_string(page),1);
                }
                bend.exit(menus);
            }
        }
        resetMenus();
        nadoc_vr::DimensionPanel dimensions;dimensions.action("dimension:toggle",v.sidebarMenus_.menus,.01F);
        for(int count:{0,1,17}) {
            dimensions.tool.entries.clear();for(int i=0;i<count;++i){dimensions.tool.create();dimensions.tool.entries.back().name="Dimension "+std::to_string(i)+" with a long measurement name";}
            dimensions.refresh(v.sidebarMenus_.menus,.01F);pages("tool-dimensions-"+std::to_string(count),1);
        }
        dimensions.exit(v.sidebarMenus_.menus);
        nadoc_vr::ViewVolumePanel volumes;volumes.active=volumes.connected=true;
        for(int count:{0,1,17}) {
            volumes.entries.clear();for(int i=0;i<count;++i){nadoc_vr::ViewVolumePanel::Entry e;e.id=std::to_string(i);e.name="Saved volume "+std::to_string(i)+" with a long descriptive name";volumes.entries.push_back(e);}
            volumes.refresh(v.sidebarMenus_.menus);pages("tool-view-volumes-"+std::to_string(count),1);
        }
        resetMenus();
        nadoc_vr::SimulationPanel simulation;auto& simMenu=v.sidebarMenus_.menus[0];simMenu.selected=1;simulation.bind(simMenu);simulation.version=1;
        simulation.engines={{"e:cando","CanDo","",true,true},{"e:snupi","SNUPI","",true,false}};
        for(bool selected:{false,true})for(int count:{0,1,20})for(bool pending:{false,true}) {
            simulation.selected=selected;simulation.sequence=pending?2:0;simulation.acknowledged=0;simulation.jobs.clear();simulation.views.clear();
            for(int i=0;i<count;++i){simulation.jobs.push_back({"j:"+std::to_string(i),"Long completed simulation job "+std::to_string(i),"Long job status with archived detail",true,i==1});simulation.views.push_back({"v:"+std::to_string(i),"Predicted shape "+std::to_string(i)+" long detail","Result detail",true,i==1});}
            for(size_t offset:count>7?std::vector<size_t>{0,7,13}:std::vector<size_t>{0}) {
                simulation.jobOffset=simulation.viewOffset=offset;
                sidebar("simulation-"+std::to_string(count)+(selected?"-selected":"-engines")+(pending?"-pending":"-ready")+"-offset-"+std::to_string(offset),0);
            }
        }
        resetMenus();
        v.normalizationScale_=.026F;
        v.activateAuthoringTool(0);
        v.latticePlacement_.openDocked({0,0,0},{1,0,0,0});
        v.latticePlacement_.setScale(1);
        v.sidebarMenus_.menus[1].placement.openDocked({0,0,0},{1,0,0,0});
        v.sidebarMenus_.menus[1].placement.setScale(1);
        v.extrudePlane_.plane="XY";
        std::istringstream latticeContext("XY 0 0 0 1 0 0 0 1 0 0 0 1 8 0 0 0 1 0 2 0 3 0 4 0 5 0 6 0 7");
        v.latticeContext_.read(latticeContext);
        for(bool square:{false,true}) {
            v.latticeSquare_=square;v.extrudePlane_.lattice=square?"SQUARE":"HONEYCOMB";v.centerLatticePainting(true);
            (void)v.extrudeLatticeDraft_.setSelected({1,3},true);(void)v.extrudeLatticeDraft_.setSelected({2,3},true);
            v.latticeOpen_=true;v.appendLatticeGuides();
            capture(square?"lattice-square-occupied-selected":"lattice-honeycomb-occupied-selected",Viewer::kLatticePanelBounds,[&](const auto& vp){v.latticePanelSurface_.render(vp,v.latticePlacement_,Viewer::kLatticePanelBounds);},&v.latticeLayoutAudit_);
            v.refreshExtrudePanel();pages(square?"tool-extrude-square-wheels":"tool-extrude-honeycomb-wheels",1);
        }
        v.latticeOpen_=false;resetMenus();
        v.menuOpen_=true;v.menuPlacement_.openDocked({0,0,0},{1,0,0,0});v.menuPlacement_.setScale(1);
        auto legacy=[&](const std::string& name,Viewer::MenuPage page) {
            v.menuPage_=page;v.controllerGuides_.clear();v.appendMenuGuides();
            v.menuLocalGuides_=v.controllerGuides_;
            for(auto& guide:v.menuLocalGuides_)guide.position=v.menuPlacement_.localPoint(guide.position);
            v.menuPanelSurface_.update(v.menuLocalGuides_,v.menuPanelBounds(),page==Viewer::MenuPage::desktop,
                frostedButtonFills<Vertex>(v.menuPlacement_,v.witnessMenuEntries(),page==Viewer::MenuPage::desktop));
            capture("legacy-"+name,v.menuPanelBounds(),[&](const auto& vp){v.renderMenuSurface(vp);},&v.menuLayoutAudit_);
        };
        legacy("options",Viewer::MenuPage::options);
        nadoc_vr::VisualizationSnapshot visualization;visualization.mode="simulation_displacement_heatmap";v.glScene_->setVisualization(visualization);
        legacy("options-live",Viewer::MenuPage::options);
        for(size_t mode=0;mode<5;++mode) {
            v.toolShell_.activate(static_cast<nadoc_vr::ToolMode>(mode),"cluster");
            (void)v.toolConfig_.bind(static_cast<nadoc_vr::ToolMode>(mode),mode==2?"end:1":"cluster:1",mode==2?"end":"cluster",{"owner:1"});
            (void)v.toolConfig_.setPlaneBp("a",-999999);(void)v.toolConfig_.setPlaneBp("b",999999);
            v.planePickStatus_="PLANE A/B SELECTED - A LONG VALIDATION STATUS DETAIL FROM THE MODEL";
            legacy("tools-mode-"+std::to_string(mode),Viewer::MenuPage::tools);
            if(mode>=2)legacy("config-"+std::string(nadoc_vr::toolModeName(v.toolConfig_.mode())),Viewer::MenuPage::tool_config);
        }
        for(bool available:{false,true}){v.jobsSnapshotAvailable_=available;legacy(available?"jobs-empty":"jobs-unavailable",Viewer::MenuPage::jobs);}
        v.jobsSnapshotTotal_=999;v.jobsSnapshotAvailable_=true;
        for(int i=0;i<13;++i){nadoc_vr::JobSnapshotRow row;row.depth=i%8;row.engine=i%2?"snupi":"cando";row.label="Extremely long simulation result name for nested construction "+std::to_string(i);row.jobId="audit-job-0123456789012345678901234567890123456789-"+std::to_string(i);row.status="complete";row.statusText="Very long completed status detail with many descriptive words to exercise clipping";row.progressPermille=999;row.viewable=row.stale=row.archived=true;v.jobs_.push_back(row);}
        v.desktopActiveJobEngine_=v.jobs_[0].engine;v.desktopActiveJobId_=v.jobs_[0].jobId;
        for(size_t page=0;page<3;++page){v.jobPage_=page;legacy("jobs-long-page-"+std::to_string(page+1),Viewer::MenuPage::jobs);}
        v.selectedJobIndex_=0;legacy("job-detail-active-archived-stale",Viewer::MenuPage::job_detail);
        v.selectedJobIndex_=1;v.jobs_[1].viewable=false;legacy("job-detail-pending",Viewer::MenuPage::job_detail);
        legacy("trajectory-unavailable",Viewer::MenuPage::trajectory);
        v.trajectoryState_.active=v.trajectoryState_.playing=v.trajectoryState_.loop=v.trajectoryState_.live=true;
        v.trajectoryState_.frameCount=4294967295U;v.trajectoryState_.frameIndex=4294967294U;v.trajectoryState_.speed=8;v.trajectoryState_.stride=100000;
        legacy("trajectory-extreme",Viewer::MenuPage::trajectory);
        legacy("desktop-default-aspect",Viewer::MenuPage::desktop);v.menuOpen_=false;
        // New desktop panel captures chrome only: never reads unrelated desktop pixels.
        v.desktopPanel_.open=true;v.desktopPanel_.placement.openDocked({0,0,0},{1,0,0,0});
        for(float scale:{.75F,1.F})for(float aspect:{.75F,1.F,16.F/9.F,32.F/9.F}) {
            v.desktopPanel_.aspect=aspect;v.desktopPanel_.placement.setScale(scale);v.updateDesktopFrame();
            const auto content=v.desktopPanel_.content(),close=v.desktopPanel_.closeBounds();
            auto region=[&](glm::vec2 a,glm::vec2 b){return nadoc_vr::MenuPanelBounds{a*scale,b*scale};};
            const std::vector<std::pair<std::string,nadoc_vr::MenuPanelBounds>> regions{
                {"desktop-title",region({content.minimum.x,close.maximum.y-.055F},{content.minimum.x+.30F,close.maximum.y})},
                {"desktop-help",region({content.minimum.x+.36F,close.maximum.y-.055F},{close.minimum.x-.025F,close.maximum.y})},
                {"desktop-close",region({close.minimum.x+.025F,close.minimum.y+.008F},{close.maximum.x-.025F,close.maximum.y-.01F})}};
            capture("desktop-chrome-aspect-"+std::to_string(aspect)+"-scale-"+std::to_string(scale),v.desktopPanel_.chromeBounds(),[&](const auto& vp){v.desktopFrameSurface_.render(vp,v.desktopPanel_.placement,v.desktopPanel_.chromeBounds(),.008F);},nullptr,regions);
        }
        v.desktopPanel_.open=false;
        nadoc_vr::HandPose hand;hand.valid=true;hand.orientation=glm::angleAxis(nadoc_vr::RadialToolMenu::kBackwardTiltRadians,glm::vec3(1,0,0));
        v.radialToolMenu_.open(hand,{});
        for(int hover=-1;hover<4;++hover) {
            const float angle=hover*glm::half_pi<float>();(void)v.radialToolMenu_.update(hover<0?glm::vec3(0):glm::vec3(std::cos(angle)*.1F,std::sin(angle)*.1F,0));
            v.controllerGuides_.clear();v.appendRadialToolGuides();
            capture("radial-hover-"+std::to_string(hover),{{-.18F,-.18F},{.18F,.18F}},[&](const auto& vp){v.glScene_->renderGuides(vp,v.controllerGuides_);});
        }
        v.radialToolMenu_.close();
        v.componentGallery_.active=v.componentGallery_.posed=true;v.componentGallery_.placement.openDocked({0,0,0},{1,0,0,0});
        v.componentGallery_.placement.setScale(1);
        for(int mode=0;mode<3;++mode)for(int state=0;state<5;++state) {
            auto& gallery=v.componentGallery_;gallery.reset();gallery.buttonMode=mode==1;gallery.cardMode=mode==2;
            for(auto& wheel:gallery.wheels){wheel.hovered=state==1;wheel.value=state==2?0:state==3?wheel.maximum:wheel.maximum/2;}
            gallery.buttonStyles.disabled=gallery.cardStyles.disabled=state==4;
            for(auto& button:gallery.buttonStyles.buttons){button.hovered=state==1;button.hand=state==2?0:-1;button.press=state==2?1:0;button.selected=state==3;}
            for(auto& card:gallery.cardStyles.cards){card.open=state!=0;card.reveal=state==0?0:1;card.hover=state==1?0:-1;card.selected=state==3?2:-1;}
            capture(std::string("gallery-")+(mode==0?"wheels":mode==1?"buttons":"cards")+"-state-"+std::to_string(state),{{-.81F,-.68F},{.81F,.67F}},[&](const auto& vp){gallery.render(vp);});
        }
        v.componentGallery_.active=false;
        v.startup_.active=v.startup_.anchored=true;v.startup_.placement.openDocked({0,0,0},{1,0,0,0});
        v.startup_.placement.setScale(1);
        for(bool representation:{false,true})for(int percent:{2,92,100,-1}) {
            v.startup_.percent=std::max(percent,0);v.startup_.phase=percent<0?"error":"loading";
            v.startup_.detail="Long preparation or failure detail that exceeds the full status display width for this audit";
            capture(std::string("startup-")+(representation?"representation-":"part-")+std::to_string(percent),{{-.53F,-.38F},{.53F,.38F}},[&](const auto& vp){v.startup_.render(vp,XrPosef{},representation);});
        }
        v.startup_.active=false;
        // Inspect the native composite, including its frame around the canvas.
        // The fallback lets a retained older source snapshot demonstrate the bug.
        const auto viewToolsBounds=[]<class T>(const T& tool) {
            if constexpr(requires{tool.panelBounds();})return tool.panelBounds();
            else return nadoc_vr::MenuPanelBounds{{-T::half,-T::half},{T::half,T::half}};
        }(v.viewTools_);
        bool viewToolsFrameClear=true,viewToolsIconHits=true;
        constexpr float contentHalf=VRViewTools::half;
        auto overlapsContent=[&](glm::vec2 lo,glm::vec2 hi){return hi.x>=-contentHalf && lo.x<=contentHalf && hi.y>=-contentHalf && lo.y<=contentHalf;};
        nadoc_vr::drawGripFrame(viewToolsBounds,nadoc_vr::GripFrameState::idle,
            [&](glm::vec3 a,glm::vec3 b,glm::vec3){if(overlapsContent(glm::min(glm::vec2(a),glm::vec2(b)),glm::max(glm::vec2(a),glm::vec2(b))))viewToolsFrameClear=false;},
            [&](nadoc_vr::MenuPanelBounds b,glm::vec3){if(overlapsContent(b.minimum,b.maximum))viewToolsFrameClear=false;});
        v.viewTools_.open=true;v.viewTools_.placement.openDocked({0,0,0},{1,0,0,0});v.viewTools_.placement.setScale(1);v.viewTools_.syncPose();
        for(size_t i=0;i<VRViewTools::keys.size();++i) {
            const auto uv=VRViewTools::cell(i);nadoc_vr::HandPose ray;ray.valid=true;ray.position=v.viewTools_.world(uv)+glm::vec3(0,0,.3F);ray.orientation={1,0,0,0};
            const auto hit=v.viewTools_.hit(ray);
            if(!hit || glm::length(*hit-uv)>1e-5F)viewToolsIconHits=false;
            std::array<bool,2> blocked{};v.viewTools_.input({ray,nadoc_vr::HandPose{}},{},blocked,[](size_t){});
            if(v.viewTools_.hover[0]!=int(i))viewToolsIconHits=false;
        }
        v.viewTools_.open=false;
        if(!viewToolsFrameClear || !viewToolsIconHits)++failures;
        if(!texture.empty()) {
            std::vector<std::filesystem::path> streams;
            if(std::filesystem::is_directory(texture)){for(const auto& entry:std::filesystem::directory_iterator(texture))if(entry.path().extension()==".bin")streams.push_back(entry.path());std::sort(streams.begin(),streams.end());}
            else streams.push_back(texture);
            if(streams.empty())throw std::runtime_error("no production viewtools fixtures");
            v.viewTools_.initialize();
            for(const auto& stream:streams) {
                const auto fixture=directory/"atlas-event";std::filesystem::copy_file(stream,fixture.string()+".viewtools",std::filesystem::copy_options::overwrite_existing);
                v.viewTools_.frames=14;v.viewTools_.version=0;
                if(!v.viewTools_.poll(fixture.string(),{},1,{}))throw std::runtime_error("invalid production viewtools fixture");
                v.viewTools_.open=true;v.viewTools_.placement.openDocked({0,0,0},{1,0,0,0});v.viewTools_.placement.setScale(1);v.viewTools_.syncPose();
                for(int hover=-1;hover<8;++hover){v.viewTools_.hover={hover,-1};capture("view-tools-"+stream.stem().string()+"-hover-"+std::to_string(hover),viewToolsBounds,[&](const auto& vp){v.viewTools_.renderPanel(vp);});}
                std::filesystem::remove(fixture.string()+".viewtools");
            }
        }
        // Identical background with a real panel moved fully offscreen is a
        // negative control for the foreground pixel count (including frost).
        background();const auto plain=pixels();v.menuGlass_.capture();
        nadoc_vr::MenuPlacement offscreen;offscreen.openDocked({50,0,0},{1,0,0,0});
        const auto vp=glm::ortho(-1.F,1.F,-1.F,1.F,.01F,10.F)*glm::lookAt(glm::vec3(0,0,2),glm::vec3(0),glm::vec3(0,1,0));
        v.menuPanelSurface_.render(vp,offscreen,v.menuPanelBounds());glFinish();
        if(pixels()!=plain)throw std::runtime_error("offscreen negative rendered foreground");
        const auto negativePng=nadoc_vr::scrywrite::encodeActorEyePng(plain,width,height);
        std::ofstream negative(directory/"negative-offscreen.png",std::ios::binary);negative.write(reinterpret_cast<const char*>(negativePng.data()),negativePng.size());
        std::ofstream completion(directory/"render-complete.json");
        completion<<"{\"complete\":true,\"rendered_states\":"<<captured<<",\"failures\":"<<failures<<",\"renderer_exit_code\":"<<(failures?1:0)<<",\"first_update_framebuffer_passed\":"<<(firstUpdateFramebuffer?"true":"false")<<",\"resize_framebuffer_passed\":"<<(resizedFramebuffer?"true":"false")<<",\"viewtools_frame_clearance_passed\":"<<(viewToolsFrameClear?"true":"false")<<",\"viewtools_icon_hits_passed\":"<<(viewToolsIconHits?"true":"false")<<",\"offscreen_negative_passed\":true,\"viewtools_stream\":"<<(texture.empty()?"false":"true")<<"}\n";
        completion.close();
        std::cout<<"Rendered "<<captured<<" production menu states into "<<directory<<'\n';
        if(failures)throw std::runtime_error(std::to_string(failures)+" menu states failed; retained all images and audit records");
    }
};
}
int main(int argc,char** argv) {
    if(argc<2 || argc>3){std::cerr<<"usage: menu-render-audit OUTPUT [PRODUCTION_VIEWTOOLS_STREAM]\n";return 2;}
    const auto output=std::filesystem::absolute(argv[1]);std::filesystem::create_directories(output);
    std::filesystem::permissions(output,std::filesystem::perms::owner_all,std::filesystem::perm_options::replace);
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(LiveViewerTest::width,LiveViewerTest::height,"Menu formatting audit",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);
    // Hidden X11 windows may still be constrained to the monitor height.
    // A dedicated framebuffer keeps the promised observation dimensions exact.
    GLuint framebuffer=0,color=0,depth=0;
    glGenFramebuffers(1,&framebuffer);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
    glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,LiveViewerTest::width,LiveViewerTest::height,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    glGenRenderbuffers(1,&depth);glBindRenderbuffer(GL_RENDERBUFFER,depth);
    glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH24_STENCIL8,LiveViewerTest::width,LiveViewerTest::height);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,GL_RENDERBUFFER,depth);
    glDrawBuffer(GL_COLOR_ATTACHMENT0);glReadBuffer(GL_COLOR_ATTACHMENT0);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw std::runtime_error("audit framebuffer incomplete");
    try{LiveViewerTest::run(output,argc>2?argv[2]:"",framebuffer);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';glfwDestroyWindow(window);glfwTerminate();return 1;}
    glDeleteRenderbuffers(1,&depth);glDeleteTextures(1,&color);glDeleteFramebuffers(1,&framebuffer);
    glfwDestroyWindow(window);glfwTerminate();return 0;
}
