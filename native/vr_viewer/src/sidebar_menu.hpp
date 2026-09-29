#pragma once
#include "sidebar_catalog.hpp"
#include "menu_layout.hpp"
#include "stroke_font.hpp"
#include "menu_focus.hpp"
#include "ui_style.hpp"
#include "menu_grip_frame.hpp"
#include "sidebar_scroll.hpp"
#include <functional>
#include <optional>
#include <set>

namespace nadoc_vr {
// Local metres before the user's panel scale. One geometry source for drawing,
// controller hits, layout tests and ScryWrite discovery.
inline constexpr MenuPanelBounds kSidebarBounds{{-.515F,-.735F},{.515F,.735F}};
inline constexpr size_t kSidebarPageRows = 8;
struct SidebarControl {
    std::string id, label, section, action;
    MenuPanelBounds bounds;
    bool enabled = true, active = false, vertical = false;
    std::string icon{};
    std::optional<MenuPanelBounds> drawingBounds{}, viewport{};
};
class SidebarMenu {
 public:
    explicit SidebarMenu(int hand=0): hand(hand) { for(size_t i=0;i<kSidebarTabs.size();++i) if(kSidebarTabs[i].hand==hand) tabs.push_back(i); offsets.resize(tabs.size()); if(hand==1) selected=1; }
    std::function<bool()> dynamic = []{return false;};
    std::function<std::vector<SidebarControl>(bool)> dynamicControls;
    std::function<MenuPanelBounds()> dynamicBounds;
    std::function<size_t()> dynamicTotal, dynamicOffset;
    std::function<void(glm::vec2)> dynamicNavigate;
    std::function<void(int)> dynamicScroll;
    std::function<void(glm::vec2,int)> dynamicScrollAt;
    std::function<void(const std::string&,float)> dynamicScrollTo;
    std::function<MenuPanelBounds(const std::string&)> dynamicThumb;
    bool dynamicActive() const { return !customTab && tab().key=="dynamics" && dynamic(); }
    static bool isScrollbar(const std::string& id) { return id=="scrollbar" || id.starts_with("sim:scroll:"); }
    void scrollControl(const std::string& id,float y) { if(dynamicActive()) dynamicScrollTo(id,y);else scrollTo(y); }
    int hand;
    bool open=false;
    size_t selected=0;
    std::optional<SidebarTab> customTab;
    std::vector<size_t> tabs, offsets;
    std::set<std::string> collapsed;
    MenuPlacement placement;
    GripFrameState gripState=GripFrameState::idle;
    std::array<bool,2> gripNearby{};
    std::string hovered;
    MenuFocus focus;
    std::string pressed;
    double pressedUntil=0;
    MenuLayoutAudit audit;
    std::function<std::string(const std::string&,const std::string&)> label = [](const auto&,const auto& fallback){return fallback;};
    std::function<bool(const std::string&)> available = [](const auto&){return true;};
    std::function<std::optional<std::pair<float,std::string>>(const std::string&)> loadingProgress=[](const auto&){return std::optional<std::pair<float,std::string>>{};};
    std::function<bool(const std::string&)> isActive = [](const auto&){return false;};
    const SidebarTab& tab() const { return customTab ? *customTab : kSidebarTabs.at(tabs.at(selected)); }
    size_t offset() const { return dynamicActive()?dynamicOffset():offsets.at(selected); }
    std::vector<const SidebarRow*> visibleRows() const {
        std::vector<const SidebarRow*> rows;
        for(const auto& row:tab().rows) {
            if(std::none_of(row.parents.begin(),row.parents.end(),[&](const auto& id){return collapsed.contains(id);})) rows.push_back(&row);
        }
        return rows;
    }
    size_t total() const { if(dynamicActive())return dynamicTotal();return visibleRows().size()-(customTab?3:0); }
    size_t pageRows() const { if(customTab && (tab().key=="bend" || tab().key=="twist"))return total();return dynamicActive()?7:customTab?5:kSidebarPageRows; }
    MenuPanelBounds bounds() const {
        if(dynamicActive()) return dynamicBounds();
        auto b=kSidebarBounds;
        if(customTab && (tab().key=="bend" || tab().key=="twist")) {b.minimum.y=-.60F;return b;}
        if(customTab) b.minimum.y=.463F-float((customTab?3:0)+std::min(pageRows(),total())-1)*.12F-.11F;
        return b;
    }
    bool canScroll(int direction) const { return direction<0 ? offset()>0 : offset()+pageRows()<total(); }
    void toggleSection(const std::string& id) {
        auto rows=visibleRows();
        if(std::none_of(rows.begin(),rows.end(),[&](const auto* r){return r->id==id && r->action.starts_with("section:");})) return;
        rowScroll={};
        if(!collapsed.erase(id)) collapsed.insert(id);
        rows=visibleRows();
        auto title=std::find_if(rows.begin(),rows.end(),[&](const auto* r){return r->id==id;});
        // Keep the toggled title visible, even when collapsing the last page.
        offsets[selected]=size_t(title-rows.begin())/kSidebarPageRows*kSidebarPageRows;
        if(focus.active) focus.id=id;
        hovered.clear();
    }
    void scroll(int direction) {
        if(dynamicActive()){dynamicScroll(direction);return;}
        rowScroll={};
        if(direction<0) offsets[selected] = offset()>pageRows() ? offset()-pageRows() : 0;
        else if(canScroll(1)) offsets[selected]+=pageRows();
    }
    MenuPanelBounds scrollBounds() const {
        const float cx=hand==0?.058F:-.058F;
        const float top=customTab?.157F:.517F;
        return hand==0 ? MenuPanelBounds{{cx-.327F,-.431F},{cx-.265F,top}}
                       : MenuPanelBounds{{cx+.265F,-.431F},{cx+.327F,top}};
    }
    MenuPanelBounds scrollThumb() const {
        auto b=scrollBounds();
        const float height=b.maximum.y-b.minimum.y;
        const float thumb=std::max(.085F,height*std::min(1.F,float(pageRows())/std::max(size_t(1),total())));
        const size_t last=total()>pageRows()?total()-pageRows():0;
        const float top=b.maximum.y-(height-thumb)*(last?std::clamp(rowScroll.value(float(offset()),animationClock())/last,0.F,1.F):0);
        return {{b.minimum.x+.008F,top-thumb},{b.maximum.x-.008F,top}};
    }
    void scrollTo(float y) {
        auto b=scrollBounds(),thumb=scrollThumb();
        const float half=(thumb.maximum.y-thumb.minimum.y)*.5F;
        const float travel=b.maximum.y-b.minimum.y-2*half;
        if(travel<=0) return;
        const float fraction=std::clamp((b.maximum.y-half-y)/travel,0.F,1.F);
        rowScroll={};
        offsets[selected]=size_t(std::round(fraction*((total()-1)/pageRows())))*pageRows();
    }
    // Keep the row height while crossing the full-height scrollbar.
    SidebarScroll rowScroll;
    std::function<double()> animationClock=SidebarScroll::now;
    void scrollRow(int direction) {
        const size_t old=offset();
        if(direction<0 && old>0) --offsets[selected];
        else if(direction>0 && canScroll(1)) ++offsets[selected];
        rowScroll.move(float(old),float(offset()),animationClock());
    }
    float navigationY=0;
    void navigate(glm::vec2 axis) {
        if(dynamicActive()){dynamicNavigate(axis);return;}
        const auto items=controls(false);
        auto current=std::find_if(items.begin(),items.end(),[&](const auto& c){return c.id==focus.id;});
        if(current==items.end()) return;
        const auto center=[](const auto& c){return (c.bounds.minimum+c.bounds.maximum)*.5F;};
        const auto column=[&](const auto& c) {
            if(c.vertical) return hand==0?0:2;
            if(c.id=="scrollbar") return 1;
            return hand==0?2:0;
        };
        const bool horizontal=std::abs(axis.x)>std::abs(axis.y);
        if(current->id=="scrollbar" && !horizontal) {
            scrollRow(axis.y>0?-1:1);
            return;
        }
        if(!horizontal && total()>pageRows()) {
            const auto rows=visibleRows();
            const auto row=std::find_if(rows.begin(),rows.end(),[&](const auto* r){return r->id==focus.id;});
            if(row!=rows.end()) {
                const auto index=std::ptrdiff_t(row-rows.begin())+(axis.y>0?-1:1);
                const size_t fixed=customTab?3:0;
                if(index>=0 && index<std::ptrdiff_t(rows.size())) {
                    focus.id=rows[size_t(index)]->id;
                    if(size_t(index)>=fixed) {
                        if(size_t(index)<offset()+fixed) scrollRow(-1);
                        else if(size_t(index)>=offset()+fixed+pageRows()) scrollRow(1);
                    }
                    return;
                }
            }
        }
        auto origin=center(*current);
        if(current->id=="scrollbar") origin.y=navigationY;
        else navigationY=origin.y;
        const int direction=horizontal?(axis.x>0?1:-1):(axis.y>0?1:-1);
        const SidebarControl* best=nullptr;
        float score=1e9F;
        for(const auto& c:items) {
            if(c.id==current->id) continue;
            const auto target=center(c);
            const int delta=column(c)-column(*current);
            float distance;
            if(horizontal) {
                // Neighboring columns take priority over controls farther away.
                // Within content, only a control on the same row is lateral.
                if(delta==0) {
                    if(std::abs(target.y-origin.y)>.025F || direction*(target.x-origin.x)<=.001F) continue;
                    distance=std::abs(target.x-origin.x);
                } else {
                    if(direction*delta<=0) continue;
                    distance=10.F*std::abs(delta)+(c.id=="scrollbar"?0.F:std::abs(target.y-origin.y));
                }
            } else {
                if(delta!=0 || direction*(target.y-origin.y)<=.025F) continue;
                // Do not jump to another button column at its bottom.
                if(std::min(c.bounds.maximum.x,current->bounds.maximum.x)-
                   std::max(c.bounds.minimum.x,current->bounds.minimum.x)<=.001F) continue;
                distance=std::abs(target.y-origin.y)+.01F*std::abs(target.x-origin.x);
            }
            if(distance<score) {score=distance;best=&c;}
        }
        if(best) focus.id=best->id;
    }
    std::vector<SidebarControl> controls(bool animated=true) const {
        auto out=layoutControls(animated);
        for(auto& c:out) if(c.viewport) {
            c.drawingBounds=c.bounds;
            c.bounds=clipSidebarBounds(c.bounds,*c.viewport);
        }
        std::erase_if(out,[](const auto& c){return c.bounds.maximum.x<=c.bounds.minimum.x || c.bounds.maximum.y<=c.bounds.minimum.y;});
        return out;
    }
    std::vector<SidebarControl> layoutControls(bool animated) const {
        std::vector<SidebarControl> out;
        const float tx=hand==0 ? -.397F : .397F;
        const float cx=hand==0 ? .058F : -.058F;
        for(size_t i=0;!customTab && i<tabs.size();++i) {
            float y=.558F-static_cast<float>(i)*.177F;
            const auto& t=kSidebarTabs[tabs[i]];
            out.push_back({"tab:"+t.key,t.label,"","tab:"+std::to_string(i),{{tx-.05F,y-.087F},{tx+.05F,y+.087F}},true,i==selected,true});
        }
        if(dynamicActive()) {
            const auto extra=dynamicControls(animated);out.insert(out.end(),extra.begin(),extra.end());
            out.push_back({"close","Close","","close",{{-.269F,-.657F},{.046F,-.585F}}});
            out.push_back({"dock","Dock / Follow","","dock",{{.07F,-.657F},{.385F,-.585F}}});
            return out;
        }
        if(customTab && (tab().key=="bend" || tab().key=="twist")) {
            // Keep every bend input visible; paired coarse adjustments share a row.
            auto add=[&](const std::string& id,float y,int column=0,float height=.09F) {
                const auto& rows=tab().rows;
                const auto r=std::find_if(rows.begin(),rows.end(),[&](const auto& row){return row.id==tab().key+":"+id;});
                if(r==rows.end())return;
                const float left=cx-.327F,right=cx+.327F,middle=(left+right)*.5F;
                const MenuPanelBounds box{{column==2?middle+.006F:left,y-height*.5F},
                                          {column==1?middle-.006F:right,y+height*.5F}};
                out.push_back({r->id,label(r->action,r->label),column?"":r->section,r->action,box,available(r->action),isActive(r->action)});
            };
            add("back",.463F);add("confirm",.36F,1,.08F);add("cancel",.36F,2,.08F);
            add("plane1",.26F,1);add("plane2",.26F,2);
            if(tab().key=="twist") {
                add("amount",.15F);add("less",.055F,1,.07F);add("more",.055F,2,.07F);
                add("units",-.05F);add("reverse",-.15F,1);add("zero",-.15F,2);
                add("target",-.26F);add("undo",-.37F,1);add("recenter",-.37F,2);return out;
            }
            add("angle",.15F);add("direction",.04F);
            add("direction-less",-.055F,1,.07F);add("direction-more",-.055F,2,.07F);
            add("radius",-.15F);add("radius-less",-.245F,1,.07F);add("radius-more",-.245F,2,.07F);
            add("target",-.35F);add("undo",-.46F,1,.08F);add("recenter",-.46F,2,.08F);
            return out;
        }
        const auto rows=visibleRows();
        std::vector<const SidebarRow*> page;
        if(customTab) page.insert(page.end(),rows.begin(),rows.begin()+3);
        const size_t fixed=customTab?3:0;
        const float position=animated?rowScroll.value(float(offset()),animationClock()):float(offset());
        const size_t start=size_t(std::floor(position))+fixed;
        const size_t end=std::min(size_t(std::ceil(position))+fixed+pageRows(),rows.size());
        for(size_t i=start;i<end;++i)page.push_back(rows[i]);
        for(size_t i=0;i<page.size();++i) {
            const auto& row=*page[i];
            const bool header=row.action.starts_with("section:");
            float y=.463F-static_cast<float>(i)*.12F;
            if(i>=fixed)y+=(position-std::floor(position))*.12F;
            out.push_back({row.id,label(row.action,row.id=="section:visualization:template:view-volumes"?"View Volumes":row.id=="section:properties:dimensions-heading"?"Dimensions":header?(collapsed.contains(row.id)?"+ ":"- ")+row.label:row.label),row.id=="section:visualization:template:view-volumes"?"MANAGE SAVED VOLUMES":row.id=="section:properties:dimensions-heading"?"MEASURE WITH CONTROLLERS":header?(collapsed.contains(row.id)?"EXPAND CARD":"COLLAPSE CARD"):row.section,row.action,{{cx-(hand==0?.247F:.327F),y-.054F},{cx+(hand==0?.327F:.247F),y+.054F}},(row.id=="dimensions-record" || row.id=="dimensions-clear") || header || (!row.action.empty() && available(row.action)), !header && available(row.action) && isActive(row.action)});
            auto& control=out.back();
            control.bounds.minimum.x+=.022F*float(row.parents.size());
            if(i>=fixed) {
                const MenuPanelBounds viewport{{-.5F,.463F-float(fixed+pageRows()-1)*.12F-.054F},{.5F,.463F-float(fixed)*.12F+.054F}};
                control.viewport=viewport;
            }
        }
        if(customTab) {
            std::vector<SidebarControl> extra;
            for(auto& c:out) if(c.id=="extrude:less-period" || c.id=="extrude:less") {
                auto plus=c;const float middle=(c.bounds.minimum.x+c.bounds.maximum.x)*.5F;
                c.bounds.maximum.x=middle-.006F;plus.bounds.minimum.x=middle+.006F;
                plus.id=plus.action=c.id=="extrude:less"?"extrude:more":"extrude:more-period";
                plus.label="+"+c.label.substr(1);
                extra.push_back(plus);
            }
            for(auto& c:out) if(c.action.starts_with("dimension:select:")) {
                const auto id=c.action.substr(17);
                const float right=c.bounds.maximum.x;
                c.bounds.maximum.x-=.208F;
                extra.push_back({"dimension:visibility:"+id,c.section=="eye"?"Hide dimension":"Show dimension","","dimension:visibility:"+id,{{right-.2F,c.bounds.minimum.y},{right-.104F,c.bounds.maximum.y}},true,false,false,c.section});
                extra.push_back({"dimension:delete:"+id,"Delete dimension","","dimension:delete:"+id,{{right-.096F,c.bounds.minimum.y},{right,c.bounds.maximum.y}},true,false,false,"x"});
                c.section.clear();
            }
            for(auto& c:out) if(c.action.starts_with("volume:entry:")) {
                const auto id=c.action.substr(13);const float right=c.bounds.maximum.x;
                c.bounds.maximum.x-=.30F;c.enabled=false;
                extra.push_back({"volume:outline:"+id,"Show / hide box","","volume:outline:"+id,{{right-.294F,c.bounds.minimum.y},{right-.202F,c.bounds.maximum.y}},true,false,false,c.section.starts_with("eye:")?"eye":"eye-off"});
                extra.push_back({"volume:enabled:"+id,c.section.ends_with(":on")?"On":"Off","","volume:enabled:"+id,{{right-.196F,c.bounds.minimum.y},{right-.104F,c.bounds.maximum.y}},true,c.section.ends_with(":on")});
                extra.push_back({"volume:delete:"+id,"Delete volume","","volume:delete:"+id,{{right-.098F,c.bounds.minimum.y},{right,c.bounds.maximum.y}},true,false,false,"x"});
                c.section.clear();
            }
            out.insert(out.end(),extra.begin(),extra.end());
            if(total()<=pageRows()) return out;
        }
        out.push_back({"scrollbar","Scroll content","","",scrollBounds(),total()>pageRows()});
        if(customTab) return out;
        out.push_back({"close","Close","","close",{{cx-.327F,-.657F},{cx-.012F,-.585F}}});
        out.push_back({"dock","Dock / Follow","","dock",{{cx+.012F,-.657F},{cx+.327F,-.585F}}});
        return out;
    }
    std::optional<SidebarControl> hit(const HandPose& pose) const {
        auto b=bounds();
        auto p=placement.rayPanelLocalPoint(pose,b.minimum,b.maximum);
        if(!open || !p) return std::nullopt;
        for(const auto& c:controls()) if(p->x>=c.bounds.minimum.x && p->x<=c.bounds.maximum.x && p->y>=c.bounds.minimum.y && p->y<=c.bounds.maximum.y) return c;
        return std::nullopt;
    }
    // Unsupported actions are blocked here, before any production action adapter.
    std::string activate(const SidebarControl& c) {
        if(!c.enabled) return {};
        if(c.action.starts_with("tab:")) { rowScroll={}; selected=static_cast<size_t>(std::stoul(c.action.substr(4))); return {}; }
        if(c.id=="section:properties:dimensions-heading") return "dimension:toggle";
        if(c.id=="section:visualization:template:view-volumes") return "volume:toggle";
        if(c.id=="dimensions-record") return "dimension:new";
        if(c.id=="dimensions-clear") return "dimension:clear";
        if(c.action.starts_with("section:")) { toggleSection(c.id); return {}; }
        if(c.action=="close") { open=false; return {}; }
        return c.action;
    }
    static std::vector<std::string> wrap(const std::string& value,size_t width) {
        std::vector<std::string> result;
        std::istringstream words(value); std::string word,line;
        while(words>>word) {
            while(word.size()>width) { if(!line.empty()) {result.push_back(line);line.clear();} result.push_back(word.substr(0,width));word.erase(0,width); }
            if(!line.empty() && line.size()+1+word.size()>width) {result.push_back(line);line.clear();}
            if(!line.empty()) line+=' ';
            line+=word;
        }
        if(!line.empty()) result.push_back(line);
        return result;
    }
    // Callbacks consume local-space line segments and filled rectangles.
    template<class Line,class Fill> void draw(Line rawLine,Fill rawFill) {
        std::optional<MenuPanelBounds> clip;
        auto line=[&](glm::vec3 a,glm::vec3 b,glm::vec3 color) {
            if(!clip || clipSidebarLine(a,b,*clip))rawLine(a,b,color);
        };
        auto fill=[&](MenuPanelBounds b,glm::vec3 color) {
            if(clip)b=clipSidebarBounds(b,*clip);
            if(b.maximum.x>b.minimum.x && b.maximum.y>b.minimum.y)rawFill(b,color);
        };
        audit.reset(bounds());
        fill(bounds(),ui_style::panel);
        auto text=[&](const std::string& id,const std::string& value,glm::vec2 at,float scale,glm::vec3 color,const MenuPanelBounds& box,bool vertical=false) {
            std::string label=value;
            std::transform(label.begin(),label.end(),label.begin(),[](unsigned char c){return static_cast<char>(std::toupper(c));});
            const float width=strokeTextWidth(label.size(),scale);
            MenuPanelBounds bounds=vertical
                ? (hand==0 ? MenuPanelBounds{{at.x,at.y},{at.x+6*scale,at.y+width}}
                           : MenuPanelBounds{{at.x-6*scale,at.y-width},{at.x,at.y}})
                : strokeTextLayoutBounds(label,at.x,at.y,scale);
            if(!menuLayoutContains(box,bounds)) audit.addControl("overflow:"+id,bounds,bounds);
            if(!vertical) audit.addText(id,label,at.x,at.y,scale,box);
            for(size_t i=0;i<label.size();++i) {
                auto shape=nadoc_vr::glyph(label[i]);
                for(size_t r=0;r<shape.size();++r) for(int col=0;col<5;++col) if(shape[r]&(1U<<(4-col))) {
                    float x=(static_cast<float>(i)*6+col)*scale, y=-static_cast<float>(r)*scale;
                    glm::vec2 a=vertical ? at+(hand==0?glm::vec2(-y,x):glm::vec2(y,-x)) : at+glm::vec2(x,y);
                    glm::vec2 b=vertical ? a+glm::vec2(0,(hand==0?1.F:-1.F)*scale*.82F) : a+glm::vec2(scale*.82F,0);
                    line(glm::vec3(a,.002F),glm::vec3(b,.002F),color);
                }
            }
        };
        drawGripFrame(bounds(),gripState,line,fill,.04F);
        const std::string gripHint=gripState==GripFrameState::resizing?"RESIZING - RELEASE GRIPS TO SET":
            gripState==GripFrameState::moving?"MOVING - SECOND GRIP RESIZES":
            "GRIP BORDER TO MOVE / TWO GRIPS TO RESIZE";
        text("grip-hint",gripHint,{-strokeTextWidth(gripHint.size(),.0028F)*.5F,.721F},.0028F,
            ui_style::text,{{-.42F,.690F},{.42F,.733F}});
        const float cx=hand==0?.058F:-.058F;
        const MenuPanelBounds title{{cx-.327F,.545F},{cx+.327F,.659F}};
        if(!dynamicActive()) { text("title",tab().label,{cx-.31F,.634F},.004F,{1,1,1},title);
        text("page",std::to_string(total()?offset()+1:0)+"-"+std::to_string(std::min(offset()+pageRows(),total()))+" / "+std::to_string(total())+(customTab && tab().key=="dimensions"?"   TRIGGER: PIN / RECALL":"   GRAY = UNAVAILABLE"),{cx-.31F,.584F},.0023F,{.71F,.76F,.81F},title);
        if(focus.active) text("input-mode",focus.id=="scrollbar"?"PAD UP/DOWN: SCROLL  LEFT/RIGHT: EXIT":"PAD: MOVE / TRIGGER: SELECT",{cx-.31F,.560F},.002F,ui_style::focus,title);
        }
        for(const auto& c:controls()) {
            clip=c.viewport;
            const bool hover=c.id==hovered;
            glm::vec3 bg=c.active?ui_style::selected : c.id==pressed?ui_style::pressed : hover&&c.enabled?ui_style::hover:ui_style::surface;
            if(c.action.starts_with("section:") && c.id!=pressed && !hover) bg=ui_style::hover;
            glm::vec3 fg=c.enabled?ui_style::text:ui_style::disabledText;
            const auto& b=c.drawingBounds?*c.drawingBounds:c.bounds;
            const bool scrollbar=isScrollbar(c.id);
            const glm::vec3 accent=ui_style::buttonAccent(c.id);
            if(!scrollbar) bg=glm::mix(glm::vec3(.075F),accent,c.active?.10F:c.enabled?(hover?.075F:.045F):.02F);
            const glm::vec3 border=c.active?ui_style::selectedBorder:c.enabled?glm::mix(ui_style::border,accent,.25F):ui_style::disabledBorder;
            ui_style::rounded(b,bg,border,line,fill);
            if((focus.active && c.id==focus.id) || (hover && c.enabled)) {
                const glm::vec2 lo=b.minimum+glm::vec2(ui_style::focusInset);
                const glm::vec2 hi=b.maximum-glm::vec2(ui_style::focusInset);
                const auto color=focus.active && c.id==focus.id?ui_style::focus:ui_style::selectedBorder;
                ui_style::rounded({lo,hi},bg,color,line,[](MenuPanelBounds,glm::vec3){},ui_style::cornerRadius-.004F,.003F);
            }
            if(!clip || menuLayoutContains(*clip,b)) audit.addControl(c.id,b,b,!c.icon.empty()?glm::vec2(.09F,.065F):scrollbar?glm::vec2(.06F,.15F):c.vertical?glm::vec2(.09F,.15F):glm::vec2(.15F,.065F));
            if(scrollbar) {
                const auto thumb=dynamicActive()?dynamicThumb(c.id):scrollThumb();
                const auto color=c.enabled?ui_style::disabledText:glm::vec3(.55F);
                ui_style::rounded(thumb,color,color,line,fill,.018F,.001F);
                continue;
            }
            if(!c.icon.empty()) {
                const auto center=(b.minimum+b.maximum)*.5F;
                auto stroke=[&](glm::vec2 a,glm::vec2 d){line(glm::vec3(center+a*.003F,.004F),glm::vec3(center+d*.003F,.004F),fg);};
                if(c.icon=="x") {stroke({-6,-6},{6,6});stroke({-6,6},{6,-6});}
                else {
                    // Desktop eye silhouette and pupil, with slash when hidden.
                    for(int i=0;i<24;++i) {
                        float a=float(i)*6.2831853F/24,beta=float(i+1)*6.2831853F/24;
                        stroke({10*std::cos(a),6*std::sin(a)},{10*std::cos(beta),6*std::sin(beta)});
                        stroke({3*std::cos(a),3*std::sin(a)},{3*std::cos(beta),3*std::sin(beta)});
                    }
                    if(c.icon=="eye-off")stroke({-10,10},{10,-10});
                }
                continue;
            }
            if(c.vertical) {
                float s=std::min(.0033F,(b.maximum.y-b.minimum.y-.018F)/std::max(1.F,static_cast<float>(c.label.size()*6-1)));
                text(c.id,c.label,{(b.minimum.x+b.maximum.x)*.5F+(hand==0?-3:3)*s,(b.minimum.y+b.maximum.y+(hand==0?-1:1)*strokeTextWidth(c.label.size(),s))*.5F},s,fg,b,true);
            } else {
                if(const auto progress=loadingProgress(c.action)) {
                    const float scale=.0028F;
                    text(c.id+":label",c.label,{b.minimum.x+.012F,b.maximum.y-.020F},scale,fg,b);
                    text(c.id+":progress",progress->second,{b.minimum.x+.012F,b.minimum.y+.032F},.0022F,{.55F,.85F,.75F},b);
                    fill({{b.minimum.x+.012F,b.minimum.y+.009F},{b.maximum.x-.012F,b.minimum.y+.017F}},{.12F,.16F,.19F});
                    fill({{b.minimum.x+.012F,b.minimum.y+.009F},{b.minimum.x+.012F+(b.maximum.x-b.minimum.x-.024F)*progress->first,b.minimum.y+.017F}},{.25F,.8F,.6F});
                    continue;
                }
                auto lines=wrap(c.label,32);
                // Fit long desktop descriptions without silently truncating them.
                size_t longest=1;for(const auto& value:lines) longest=std::max(longest,value.size());
                float s=std::min({.0032F,(b.maximum.x-b.minimum.x-.024F)/float(longest*6-1),.056F/std::max(7.F,static_cast<float>(lines.size()*9))});
                float y=(customTab || dynamicActive()) && c.section.empty()?(b.minimum.y+b.maximum.y)*.5F+(float(lines.size()*9)-3)*s*.5F:b.maximum.y-.020F;
                if(!c.section.empty()) {
                    auto section=wrap(c.section,39);
                    text(c.id+":section",section.front(),{b.minimum.x+.012F,y},.0022F,{.55F,.60F,.66F},b);
                    y-=.024F;
                }
                for(const auto& value:lines) {text(c.id+":label",value,{b.minimum.x+.012F,y},s,fg,b);y-=9*s;}
            }
        }
    }
};
}
