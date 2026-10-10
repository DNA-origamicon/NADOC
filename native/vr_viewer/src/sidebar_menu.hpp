#pragma once
#include "sidebar_catalog.hpp"
#include "menu_layout.hpp"
#include "stroke_font.hpp"
#include "menu_focus.hpp"
#include "ui_style.hpp"
#include "menu_grip_frame.hpp"
#include "sidebar_scroll.hpp"
#include "extrude_wheels.hpp"
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
#include "sidebar_sets.hpp"
class SidebarMenu {
 public:
    // Native Part sessions must not expose Assembly controls. An assembly host
    // must explicitly opt in with its actual document context.
    explicit SidebarMenu(int hand=0,bool assemblyActive=false): hand(hand) {
        placement.setBorderWidth(ui_style::gripRail);
        for(size_t i=0;i<kSidebarTabs.size();++i) {
            const auto& tab=kSidebarTabs[i];
            if(tab.hand!=hand || (tab.key=="assembly" && !assemblyActive))continue;
            if(tab.key=="properties")selected=tabs.size();
            tabs.push_back(i);
        }
        offsets.resize(tabs.size());
    }
    std::function<bool()> dynamic = []{return false;};
    std::function<std::vector<SidebarControl>(bool)> dynamicControls;
    std::function<MenuPanelBounds()> dynamicBounds;
    std::function<size_t()> dynamicTotal, dynamicOffset;
    std::function<void(glm::vec2)> dynamicNavigate;
    std::function<void(int)> dynamicScroll;
    std::function<void(glm::vec2,int)> dynamicScrollAt;
    std::function<void(const std::string&,float)> dynamicScrollTo;
    std::function<MenuPanelBounds(const std::string&)> dynamicThumb;
    std::function<size_t()> dynamicPage=[]{return size_t(7);};
    std::function<std::string(float,bool)> historyScrub;
    std::function<void()> historyScrubCancel;
    bool dynamicActive() const { return !customTab && (tab().key=="dynamics" || tab().key=="feature-log") && dynamic(); }
    static bool isScrollbar(const std::string& id) { return id=="scrollbar" || id.starts_with("sim:scroll:") || id=="history:scroll"; }
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
    std::function<bool(const std::string&)> spinning=[](const auto&){return false;};
    std::function<bool(const std::string&)> isActive = [](const auto&){return false;};
    const SidebarTab& tab() const { return customTab ? *customTab : kSidebarTabs.at(tabs.at(selected)); }
    size_t offset() const { return dynamicActive()?dynamicOffset():offsets.at(selected); }
    std::vector<const SidebarRow*> visibleRows() const {
        std::vector<const SidebarRow*> rows;
        for(const auto& row:tab().rows) {
            // Both surface presets share the final representation row.
            if(row.id=="menu-view-surface-detail") continue;
            if(std::none_of(row.parents.begin(),row.parents.end(),[&](const auto& id){return collapsed.contains(id);})) rows.push_back(&row);
        }
        return rows;
    }
    bool toolFooter() const {
        return customTab && (tab().key=="extrude" || tab().key=="sweep" || tab().key=="move" || tab().key=="bend" || tab().key=="twist");
    }
    bool sweepPath() const {
        return customTab && tab().key=="sweep" && std::any_of(tab().rows.begin(),tab().rows.end(),[](const auto& r){return r.id=="sweep:free-draw";});
    }
    bool raisedAction(const SidebarControl& c) const {
        return c.id.starts_with("sim:j:") || (toolFooter() && (c.id==tab().key+":back" || c.id==tab().key+":confirm" || c.id=="move:apply"));
    }
    float footerY() const {
        return sweepPath()?-.52F:tab().key=="extrude" || tab().key=="sweep"?-.425F:tab().key=="move"?-.54F:tab().key=="bend"?-.54F:-.51F;
    }
    std::vector<const SidebarRow*> contentRows() const {
        auto rows=visibleRows();
        if(customTab && tab().key=="sweep") {
            const bool path=sweepPath();
            std::erase_if(rows,[&](const auto* r){return path?!r->id.starts_with("sweep:point:"):r->id=="sweep:back" || r->id=="sweep:confirm";});
        }
        if(customTab && tab().key=="extrude") {
            std::erase_if(rows,[](const auto* r){return r->id=="extrude:back" || r->id=="extrude:confirm" || r->id=="extrude:length" || extrudeWheelIndex(r->id).has_value();});
            std::rotate(rows.begin(),rows.begin()+1,rows.end());
        }
        return rows;
    }
    size_t total() const { if(dynamicActive())return dynamicTotal();if(customTab && tab().key=="sweep")return contentRows().size();return visibleRows().size()-(customTab && tab().key=="extrude"?5:toolFooter()?2:customTab?3:0); }
    size_t pageRows() const { if(customTab && tab().key=="sweep")return sweepPath()?2:6;if(customTab && (tab().key=="move" || tab().key=="bend" || tab().key=="twist"))return total();return dynamicActive()?dynamicPage():customTab?5:kSidebarPageRows; }
    MenuPanelBounds bounds() const {
        if(dynamicActive()) return dynamicBounds();
        auto b=kSidebarBounds;
        if(toolFooter()) {b.minimum.y=footerY()-ui_style::footerHalfHeight-ui_style::raisedBottomOverhang-ui_style::gripRail-ui_style::contentPadding;return b;}
        if(customTab) b.minimum.y=.463F-float((customTab?3:0)+std::min(pageRows(),total())-1)*.12F-.054F-ui_style::gripRail-ui_style::contentPadding;
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
        const float cx=toolFooter()?0.F:hand==0?.058F:-.058F;
        if(customTab && tab().key=="sweep")return {{ui_style::toolHalfWidth-.062F,sweepPath()?-.234F:-.191F},{ui_style::toolHalfWidth,sweepPath()?.282F:.517F}};
        if(customTab && tab().key=="extrude")return {{ui_style::toolHalfWidth-.062F,-.339F},{ui_style::toolHalfWidth,.249F}};
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
            const auto rows=contentRows();
            const auto row=std::find_if(rows.begin(),rows.end(),[&](const auto* r){return r->id==(focus.id=="menu-view-surface-detail"?"menu-view-surface":focus.id);});
            if(row!=rows.end()) {
                const auto index=std::ptrdiff_t(row-rows.begin())+(axis.y>0?-1:1);
                const size_t fixed=customTab && tab().key!="extrude" && tab().key!="sweep"?3:0;
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
        if(toolFooter() && tab().key!="move") {
            std::erase_if(out,[&](const auto& c){return raisedAction(c);});
            const float left=-ui_style::toolHalfWidth,right=ui_style::toolHalfWidth,middle=0;
            const float gap=ui_style::raisedColumnGap*.5F;
            // Cancel remains a distinct action; Back retains its existing return behavior.
            if(tab().key!="extrude" && tab().key!="sweep")for(auto& c:out)if(c.id==tab().key+":cancel")
                c.bounds={{left,.418F},{right,.508F}};
            for(auto& c:out)if(c.id==tab().key+":cancel")
                c.bounds.maximum.x=middle-gap;
            for(bool back:{false,true}) {
                const std::string id=tab().key+":"+(back?"back":tab().key=="move"?"apply":"confirm");
                const auto row=std::find_if(tab().rows.begin(),tab().rows.end(),[&](const auto& r){return r.id==id;});
                if(row==tab().rows.end())continue;
                out.push_back({id,back?"BACK":tab().key=="move"?"APPLY":tab().key=="sweep"?row->label:"CONFIRM","",row->action,
                    {{back?left:middle+gap,footerY()-ui_style::footerHalfHeight},{back?middle-gap:right,footerY()+ui_style::footerHalfHeight}},available(row->action)});
            }
        }
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
        const float cx=toolFooter()?0.F:hand==0 ? .058F : -.058F;
        for(size_t i=0;!customTab && i<tabs.size();++i) {
            float y=.558F-static_cast<float>(i)*.189F;
            const auto& t=kSidebarTabs[tabs[i]];
            out.push_back({"tab:"+t.key,t.label,"","tab:"+std::to_string(i),{{tx-.05F,y-.0885F},{tx+.05F,y+.0885F}},true,i==selected,true});
        }
        if(dynamicActive()) {
            const auto extra=dynamicControls(animated);out.insert(out.end(),extra.begin(),extra.end());
            out.push_back({"close","Close","","close",{{-.269F,-.657F},{.046F,-.585F}}});
            out.push_back({"dock","Dock / Follow","","dock",{{.07F,-.657F},{.385F,-.585F}}});
            return out;
        }
        if(customTab && tab().key=="sweep") {
            const float left=-ui_style::toolHalfWidth,right=ui_style::toolHalfWidth-.080F;
            const bool path=sweepPath();
            auto add=[&](const std::string& id,MenuPanelBounds box,const std::string& icon="",bool selected=false) {
                const auto r=std::find_if(tab().rows.begin(),tab().rows.end(),[&](const auto& row){return row.id=="sweep:"+id;});
                if(r==tab().rows.end())return;
                const bool value=id.ends_with(":value") || id=="smoothing" || id=="bp-info";
                out.push_back({r->id,r->label,r->section,r->action,box,!value && available(r->action),selected || isActive(r->action),false,icon});
            };
            if(path) {
                add("free-draw",{{left,.420F},{ui_style::toolHalfWidth,.510F}});
                add("add-point",{{left,.306F},{-.006F,.394F}});
                add("delete-point",{{.006F,.306F},{ui_style::toolHalfWidth,.394F}});
                add("smoothing-less",{{left,-.341F},{-.207F,-.263F}});
                add("smoothing",{{-.195F,-.341F},{.195F,-.263F}});
                add("smoothing-more",{{.207F,-.341F},{ui_style::toolHalfWidth,-.263F}});
                add("bp-info",{{left,-.437F},{ui_style::toolHalfWidth,-.359F}});
            }
            const auto rows=contentRows();
            const float position=animated?rowScroll.value(float(offset()),animationClock()):float(offset());
            const size_t start=size_t(std::floor(position)),end=std::min(size_t(std::ceil(position))+pageRows(),rows.size());
            const MenuPanelBounds viewport{{left,path?-.234F:-.191F},{right,path?.282F:.517F}};
            for(size_t index=start;index<end;++index) {
                const auto& row=*rows[index];const size_t before=out.size();
                if(path) {
                    const auto id=row.id.substr(12);
                    const float railLeft=left+.030F;
                    const float top=.282F-(float(index)-position)*.258F;
                    const bool selected=row.section=="SELECTED";
                    add("point:"+id,{{railLeft,top-.065F},{right-.21F,top}},"",selected);
                    out.back().section.clear();
                    add("direction:"+id,{{right-.198F,top-.065F},{right,top}});
                    const float width=(right-left-.024F)/3.F;
                    for(int axis=0;axis<3;++axis) {
                        const float x=left+float(axis)*(width+.012F),y=top-.077F;
                        const auto prefix="axis:"+id+":"+std::to_string(axis);
                        add(prefix+":value",{{x,y-.142F},{x+width-.086F,y}},"",selected);
                        add(prefix+":1",{{x+width-.074F,y-.065F},{x+width,y}},"up");
                        add(prefix+":-1",{{x+width-.074F,y-.142F},{x+width,y-.077F}},"down");
                    }
                } else {
                    const float y=.463F-(float(index)-position)*.12F;
                    add(row.id.substr(6),{{left,y-.054F},{right,y+.054F}});
                }
                for(size_t i=before;i<out.size();++i)out[i].viewport=viewport;
            }
            if(total()>pageRows())out.push_back({"scrollbar","Scroll points","","",scrollBounds(),true});
            return out;
        }
        if(customTab && tab().key=="move") {
            auto add=[&](const char* id,float y,float left,float right,float height=.09F,const char* icon="") {
                const auto r=std::find_if(tab().rows.begin(),tab().rows.end(),[&](const auto& row){return row.id==std::string("move:")+id;});
                if(r==tab().rows.end())return;
                out.push_back({r->id,r->label,r->section,r->action,{{left,y-height*.5F},{right,y+height*.5F}},available(r->action),isActive(r->action),false,icon});
            };
            const float left=-ui_style::toolHalfWidth,right=ui_style::toolHalfWidth;
            add("back",.463F,left,right);
            add("selection",.333F,left,right,.12F);
            add("snap",.197F,left,right,.12F);
            for(int i=0;i<6;++i) {
                const float x=i<3?left:.012F,y=.060F-float(i%3)*.16F;
                const auto id=std::to_string(i);
                add((id+"-wheel").c_str(),y,x,x+.102F,.11F);
                add((id+":value").c_str(),y+.028F,x+.114F,x+.363F,.066F);
                add((id+":less").c_str(),y-.05F,x+.114F,x+.232F,.065F,"down");
                add((id+":more").c_str(),y-.05F,x+.244F,x+.363F,.065F,"up");
            }
            add("undo",-.405F,left,-.135F,.075F);
            add("redo",-.405F,-.12F,.12F,.075F);
            add("recenter",-.405F,.135F,right,.075F);
            add("cancel",-.54F,left,-.018F,.108F);
            add("apply",-.54F,.018F,right,.108F);
            return out;
        }
        if(customTab && (tab().key=="bend" || tab().key=="twist")) {
            // Keep every bend input visible; paired coarse adjustments share a row.
            auto add=[&](const std::string& id,float y,int column=0,float height=.09F) {
                const auto& rows=tab().rows;
                const auto r=std::find_if(rows.begin(),rows.end(),[&](const auto& row){return row.id==tab().key+":"+id;});
                if(r==rows.end())return;
                const float extent=ui_style::toolHalfWidth;
                const float left=cx-extent,right=cx+extent,middle=(left+right)*.5F;
                const MenuPanelBounds box{{column==2?middle+.006F:left,y-height*.5F},
                                          {column==1?middle-.006F:right,y+height*.5F}};
                out.push_back({r->id,label(r->action,r->label),column?"":r->section,r->action,box,available(r->action),isActive(r->action)});
            };
            add("back",.463F);add("confirm",.36F,1,.08F);add("cancel",.36F,2,.08F);
            add("plane1",.34F,1);add("plane2",.34F,2);
            if(tab().key=="bend")for(auto& c:out)if(c.id=="bend:plane1" || c.id=="bend:plane2") {
                c.action="";c.enabled=false;
            }
            if(tab().key=="twist") {
                add("amount",.15F);add("less",.055F,1,.07F);add("more",.055F,2,.07F);
                add("units",-.05F);add("reverse",-.152F,1);add("zero",-.152F,2);
                add("target",-.26F);add("undo",-.37F,1);add("recenter",-.37F,2);return out;
            }
            const bool dropdown=std::any_of(tab().rows.begin(),tab().rows.end(),[](const auto& r){return r.id.starts_with("bend:cluster-");});
            add("cluster",.23F,dropdown?0:1);
            if(dropdown) {
                int i=0;
                for(const auto& r:tab().rows)if(r.id.starts_with("bend:cluster-"))add(r.id.substr(5),.12F-.11F*i++);
                add("clusters-prev",-.32F,1);add("clusters-next",-.32F,2);
                return out;
            }
            add("manual",.23F,2);
            // Dedicated wheel hit areas to the LEFT of readouts. Angle and
            // curvature share a row; number fields never initiate a drag.
            auto wheelField=[&](const std::string& id,float y,int column) {
                add(id,y,column,.17F);
                auto& field=out.back();const float left=field.bounds.minimum.x;
                field.bounds.minimum.x+=.114F;
                auto wheel=field;
                wheel.id="bend:"+id+"-wheel";wheel.action=wheel.id;wheel.label="";wheel.section="";
                wheel.bounds.minimum.x=left;wheel.bounds.maximum.x=left+.102F;
                out.push_back(wheel);
            };
            wheelField("angle",.075F,1);wheelField("radius",.075F,2);
            wheelField("direction",-.115F,0);
            add("direction-less",-.253F,1,.07F);add("direction-more",-.253F,2,.07F);
            add("radius-less",-.335F,1,.07F);add("radius-more",-.335F,2,.07F);
            add("undo",-.417F,1,.07F);add("recenter",-.417F,2,.07F);
            return out;
        }
        const auto rows=contentRows();
        const bool extrude=customTab && tab().key=="extrude";
        if(extrude)for(const auto& row:tab().rows) {
            const auto wheel=extrudeWheelIndex(row.id);
            if(row.id=="extrude:length")
                out.push_back({row.id,row.label,row.section,"",{{-ui_style::toolHalfWidth,.261F},{-.025F,.517F}},false});
            else if(wheel)
                out.push_back({row.id,row.label,row.section,row.action,kExtrudeWheelBounds[*wheel],available(row.action)});
        }
        const float firstRowY=extrude?.195F:.463F;
        std::vector<const SidebarRow*> page;
        if(customTab && !extrude) page.insert(page.end(),rows.begin(),rows.begin()+3);
        const size_t fixed=customTab && tab().key!="extrude"?3:0;
        const float position=animated?rowScroll.value(float(offset()),animationClock()):float(offset());
        const size_t start=size_t(std::floor(position))+fixed;
        const size_t end=std::min(size_t(std::ceil(position))+fixed+pageRows(),rows.size());
        for(size_t i=start;i<end;++i)page.push_back(rows[i]);
        for(size_t i=0;i<page.size();++i) {
            const auto& row=*page[i];
            const bool header=row.action.starts_with("section:");
            float y=firstRowY-static_cast<float>(i)*.12F;
            if(i>=fixed)y+=(position-std::floor(position))*.12F;
            out.push_back({row.id,label(row.action,row.id=="section:visualization:template:view-volumes"?"View Volumes":row.id=="section:properties:dimensions-heading"?"Dimensions":header?(collapsed.contains(row.id)?"+ ":"- ")+row.label:row.label),row.id=="section:visualization:template:view-volumes"?"MANAGE SAVED VOLUMES":row.id=="section:properties:dimensions-heading"?"MEASURE WITH CONTROLLERS":header?(collapsed.contains(row.id)?"EXPAND CARD":"COLLAPSE CARD"):row.section,row.action,{{toolFooter()?-ui_style::toolHalfWidth:cx-(hand==0?.247F:.327F),y-.054F},{toolFooter()?ui_style::toolHalfWidth-.080F:cx+(hand==0?.327F:.247F),y+.054F}},(row.id=="dimensions-record" || row.id=="dimensions-clear") || header || (!row.action.empty() && available(row.action)), !header && available(row.action) && isActive(row.action)});
            auto& control=out.back();
            control.bounds.minimum.x+=.022F*float(row.parents.size());
            if(i>=fixed) {
                const MenuPanelBounds viewport{{-.5F,firstRowY-float(fixed+pageRows()-1)*.12F-.054F},{.5F,firstRowY-float(fixed)*.12F+.054F}};
                control.viewport=viewport;
            }
        }
        const auto quick=std::find_if(out.begin(),out.end(),[](const auto& c){return c.id=="menu-view-surface";});
        if(quick!=out.end()) {
            const auto row=std::find_if(tab().rows.begin(),tab().rows.end(),[](const auto& r){return r.id=="menu-view-surface-detail";});
            if(row!=tab().rows.end()) {
                auto detail=*quick;
                const float middle=(quick->bounds.minimum.x+quick->bounds.maximum.x)*.5F;
                quick->bounds.maximum.x=middle-.006F;
                detail.bounds.minimum.x=middle+.006F;
                detail.id=row->id;detail.label=label(row->action,row->label);detail.action=row->action;
                detail.enabled=available(row->action);detail.active=detail.enabled&&isActive(row->action);
                out.push_back(detail);
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
                c.active=c.label.starts_with("> ");
                const float right=c.bounds.maximum.x;
                c.bounds.maximum.x-=.216F;
                const auto split=c.label.rfind(" / ");
                if(split!=std::string::npos){
                    auto value=c;value.id="dimension:value:"+id;value.label=c.label.substr(split+3);if(value.label=="Waiting for controllers")value.label="UNPLACED";value.section.clear();value.action.clear();value.enabled=false;
                    value.bounds.minimum.x=value.bounds.maximum.x-.15F;
                    c.label=c.label.substr(0,split);c.bounds.maximum.x=value.bounds.minimum.x-.012F;extra.push_back(value);
                }
                extra.push_back({"dimension:visibility:"+id,c.section=="eye"?"Hide dimension":"Show dimension","","dimension:visibility:"+id,{{right-.204F,c.bounds.minimum.y},{right-.108F,c.bounds.maximum.y}},true,false,false,c.section});
                extra.back().viewport=c.viewport;
                extra.push_back({"dimension:delete:"+id,"Delete dimension","","dimension:delete:"+id,{{right-.096F,c.bounds.minimum.y},{right,c.bounds.maximum.y}},true,false,false,"x"});
                extra.back().viewport=c.viewport;
                c.section.clear();
            }
            for(auto& c:out) if(c.action.starts_with("volume:entry:")) {
                const auto id=c.action.substr(13);const float right=c.bounds.maximum.x;
                c.bounds.maximum.x-=.318F;c.enabled=false;
                extra.push_back({"volume:outline:"+id,"Show / hide box","","volume:outline:"+id,{{right-.306F,c.bounds.minimum.y},{right-.214F,c.bounds.maximum.y}},true,false,false,c.section.starts_with("eye:")?"eye":"eye-off"});
                extra.back().viewport=c.viewport;
                extra.push_back({"volume:enabled:"+id,c.section.ends_with(":on")?"On":"Off","","volume:enabled:"+id,{{right-.202F,c.bounds.minimum.y},{right-.108F,c.bounds.maximum.y}},true,c.section.ends_with(":on")});
                extra.back().viewport=c.viewport;
                extra.push_back({"volume:delete:"+id,"Delete volume","","volume:delete:"+id,{{right-.096F,c.bounds.minimum.y},{right,c.bounds.maximum.y}},true,false,false,"x"});
                extra.back().viewport=c.viewport;
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
    float controlDepth(const SidebarControl& c) const {
        if(const auto wheel=extrudeWheelIndex(c.id))return extrudeWheelFront(*wheel).z;
        return c.id.starts_with("sim:j:")?.018F:raisedAction(c) ? (pressed==c.id?.026F:.035F) : 0.F;
    }
    std::optional<glm::vec3> raySurfacePoint(const HandPose& pose) const {
        if(!open || !pose.valid)return std::nullopt;
        const auto origin=placement.localPoint(pose.position);
        const auto direction=placement.localPoint(pose.position+pose.orientation*glm::vec3(0,0,-1))-origin;
        if(customTab && tab().key=="extrude")for(size_t i=0;i<kExtrudeWheelIds.size();++i)
            if(const auto hit=thumbwheelHit(extrudeWheelShape(),extrudeWheelCenter(i),placement,pose))return hit;
        if(std::abs(direction.z)>1e-7F)for(const auto& c:controls())if(raisedAction(c)) {
            const float t=(controlDepth(c)-origin.z)/direction.z;
            const auto p=origin+t*direction;
            if(t>0 && p.x>=c.bounds.minimum.x && p.x<=c.bounds.maximum.x &&
               p.y>=c.bounds.minimum.y && p.y<=c.bounds.maximum.y)return p;
        }
        const auto b=bounds();
        return placement.rayPanelLocalPoint(pose,b.minimum,b.maximum);
    }
    std::optional<SidebarControl> hit(const HandPose& pose) const {
        auto p=raySurfacePoint(pose);
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
            audit.addTextBounds(id,label,bounds,scale,box,kMinimumMenuTextScale,clip);
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
        auto boundedText=[&](const std::string& id,const std::string& value,glm::vec2 at,float scale,
                             glm::vec3 color,const MenuPanelBounds& box) {
            const auto fitted=boundedMenuStrokeText(value,box.maximum.x-at.x,scale);
            text(id,fitted.text,at,fitted.scale,color,box);
        };
        auto textBlock=[&](const std::string& id,const std::string& value,const MenuPanelBounds& box,
                           glm::vec3 color,float maximumScale=.0032F) {
            const float width=box.maximum.x-box.minimum.x,height=box.maximum.y-box.minimum.y;
            float scale=maximumScale;
            std::vector<std::string> lines;
            for(;;) {
                const size_t columns=size_t(std::max(1.F,std::floor((width/scale+1.F)/6.F)));
                lines=wrap(value,columns);
                if((float(lines.size()*9)-3)*scale<=height+kMenuLayoutEpsilon || scale<=kMinimumMenuTextScale)break;
                scale=std::max(kMinimumMenuTextScale,scale-.0002F);
            }
            const size_t maximumLines=size_t(std::max(0.F,std::floor((height/scale+3.F)/9.F)));
            if(!maximumLines)return;
            if(lines.size()>maximumLines) {
                lines.resize(maximumLines);
                lines.back()=boundedMenuStrokeText(lines.back()+" ...",width,scale,scale).text;
            }
            float y=(box.minimum.y+box.maximum.y+(float(lines.size()*9)-3)*scale)*.5F;
            for(const auto& value:lines){text(id,value,{box.minimum.x,y},scale,color,box);y-=9*scale;}
        };
        drawGripFrame(bounds(),gripState,line,fill,ui_style::gripRail);
        const std::string gripHint=gripState==GripFrameState::resizing?"RESIZING - RELEASE TO SET":
            gripState==GripFrameState::moving?"MOVING - RELEASE TO SET":
            "BORDER: HOLD TO MOVE / DOUBLE TO RESIZE";
        text("grip-hint",gripHint,{-strokeTextWidth(gripHint.size(),.0028F)*.5F,.721F},.0028F,
            ui_style::text,{{-.42F,.690F},{.42F,.733F}});
        const float cx=toolFooter()?0.F:hand==0?.058F:-.058F;
        const float titleHalf=toolFooter()?ui_style::toolHalfWidth:.327F;
        const MenuPanelBounds title{{cx-titleHalf,.545F},{cx+titleHalf,.659F}};
        if(!dynamicActive()) { text("title",tab().label,{cx-titleHalf+.017F,.634F},.004F,{1,1,1},title);
        const auto statusRow=std::find_if(tab().rows.begin(),tab().rows.end(),[&](const auto& r){return r.id==tab().key+":back";});
        if(toolFooter() && statusRow!=tab().rows.end())
            boundedText("tool-status",statusRow->section,{cx-titleHalf+.017F,.584F},.0023F,ui_style::text,
                {title.minimum+glm::vec2(.012F,0),title.maximum-glm::vec2(.012F,0)});
        else text("page",std::to_string(total()?offset()+1:0)+"-"+std::to_string(std::min(offset()+pageRows(),total()))+" / "+std::to_string(total())+(customTab && tab().key=="dimensions"?"   TRIGGER: PIN / RECALL":"   GRAY = UNAVAILABLE"),{cx-titleHalf+.017F,.584F},.0023F,{.71F,.76F,.81F},title);
        if(focus.active) text("input-mode",focus.id=="scrollbar"?"PAD UP/DOWN: SCROLL  LEFT/RIGHT: EXIT":"PAD: MOVE / TRIGGER: SELECT",{cx-titleHalf+.017F,.560F},.002F,ui_style::focus,title);
        }
        if(sweepPath())text("sweep:set-count","POINTS "+std::to_string(total()?offset()+1:0)+"-"+std::to_string(std::min(offset()+pageRows(),total()))+" / "+std::to_string(total()),
            {-ui_style::toolHalfWidth,.301F},.002F,{.53F,.74F,.72F},{{-ui_style::toolHalfWidth,.283F},{ui_style::toolHalfWidth,.305F}});
        const auto listControls=controls();
        drawSidebarSets(listControls,line,fill);
        for(const auto& c:listControls) {
            clip=c.viewport;
            audit.addSpacing(c.id,raisedAction(c)&&!c.id.starts_with("sim:j:")?ui_style::raisedEnvelope(c.bounds):c.bounds,
                ui_style::gripRail+ui_style::contentPadding,ui_style::controlGap);
            if(raisedAction(c)) {
                audit.addControl(c.id,c.bounds,c.bounds);
                continue; // Raised geometry and lettering are drawn by SidebarRuntime.
            }
            if(c.id=="history:scrub") {
                audit.addControl(c.id,c.bounds,c.bounds,{.06F,.15F});
                ui_style::rounded(c.bounds,{.03F,.055F,.065F},{.22F,.42F,.45F},line,fill);
                if(c.drawingBounds)ui_style::rounded(*c.drawingBounds,{.38F,.85F,.68F},{.55F,.95F,.8F},line,fill,.01F,.001F);
                continue;
            }
            const bool hover=c.id==hovered;
            glm::vec3 bg=c.active?ui_style::selected : c.id==pressed?ui_style::pressed : hover&&c.enabled?ui_style::hover:ui_style::surface;
            if(c.action.starts_with("section:") && c.id!=pressed && !hover) bg=ui_style::hover;
            glm::vec3 fg=c.enabled?ui_style::text:ui_style::disabledText;
            const auto& b=c.drawingBounds?*c.drawingBounds:c.bounds;
            const bool scrollbar=isScrollbar(c.id);
            const glm::vec3 accent=c.id.starts_with("dimension:")?glm::vec3(.42F,.77F,1.F):
                c.id.starts_with("history:delete:")?glm::vec3(1.F,.4F,.4F):c.id.starts_with("history:revert:")?glm::vec3(1.F,.75F,.35F):
                c.id.starts_with("history:") || c.id.starts_with("sweep:point:") || c.id.starts_with("sweep:axis:")?glm::vec3(.38F,.85F,.68F):ui_style::buttonAccent(c.id);
            if(!scrollbar) bg=glm::mix(glm::vec3(.075F),accent,c.active?.10F:c.enabled?(hover?.075F:.045F):.02F);
            const glm::vec3 border=c.active?ui_style::selectedBorder:c.enabled?glm::mix(ui_style::border,accent,.25F):ui_style::disabledBorder;
            if(c.id=="bend:plane1" || c.id=="bend:plane2")fg=ui_style::text;
            else {
                if(c.id.starts_with("sim:j:")){
                    fill({b.minimum+glm::vec2(.005F,-.004F),b.maximum+glm::vec2(.005F,-.004F)},{.018F,.026F,.039F});
                    bg=glm::mix(bg,glm::vec3(.16F,.21F,.29F),.55F);
                }
                ui_style::rounded(b,bg,border,line,fill,c.id.starts_with("dimension:select:") || c.id.starts_with("dimension:value:")?.002F:ui_style::cornerRadius);
                if(c.id.starts_with("sim:j:"))fill({b.minimum+glm::vec2(.003F,.006F),{b.minimum.x+.008F,b.maximum.y-.006F}},c.active?glm::vec3(.38F,.85F,.68F):glm::vec3(.64F,.46F,.83F));
            }
            if((focus.active && c.id==focus.id) || (hover && c.enabled)) {
                const glm::vec2 lo=b.minimum+glm::vec2(ui_style::focusInset);
                const glm::vec2 hi=b.maximum-glm::vec2(ui_style::focusInset);
                const auto color=focus.active && c.id==focus.id?ui_style::focus:ui_style::selectedBorder;
                ui_style::rounded({lo,hi},bg,color,line,[](MenuPanelBounds,glm::vec3){},ui_style::cornerRadius-.004F,.003F);
            }
            if(!clip || menuLayoutContains(*clip,b)) audit.addControl(c.id,b,b,c.id.starts_with("dimension:value:")?glm::vec2(.14F,.065F):c.id.starts_with("sweep:axis:")?glm::vec2(.07F,.065F):c.id.ends_with("-wheel")?glm::vec2(.05F,.065F):(!c.icon.empty() || c.id.starts_with("volume:enabled:"))?glm::vec2(.09F,.065F):scrollbar?glm::vec2(.06F,.15F):c.vertical?glm::vec2(.09F,.15F):glm::vec2(.15F,.065F));
            if(scrollbar) {
                const auto thumb=dynamicActive()?dynamicThumb(c.id):scrollThumb();
                const auto color=c.enabled?ui_style::disabledText:glm::vec3(.55F);
                ui_style::rounded(thumb,color,color,line,fill,.018F,.001F);
                continue;
            }
            if(extrudeWheelIndex(c.id)) {
                const float scale=.0028F;
                text(c.id+":label",c.label,{(b.minimum.x+b.maximum.x-strokeTextWidth(c.label.size(),scale))*.5F,b.maximum.y-.010F},scale,fg,b);
                continue;
            }
            if(c.id=="extrude:length") {
                text(c.id+":section","LENGTH",{b.minimum.x+.020F,b.maximum.y-.040F},.0028F,ui_style::text,b);
                const float scale=std::min(.006F,(b.maximum.x-b.minimum.x-.040F)/std::max(1.F,float(c.label.size()*6-1)));
                text(c.id+":value",c.label,{b.minimum.x+.020F,.383F},scale,ui_style::text,b);
                continue;
            }
            if(!c.icon.empty()) {
                auto center=(b.minimum+b.maximum)*.5F;
                auto stroke=[&](glm::vec2 a,glm::vec2 d){line(glm::vec3(center+a*.003F,.004F),glm::vec3(center+d*.003F,.004F),fg);};
                if(c.icon=="base" || c.icon=="domain" || c.icon=="cluster") {
                    center.y+=.018F;
                    auto bead=[&](glm::vec2 p){for(int j=0;j<12;++j){float a=j*6.2831853F/12,b=(j+1)*6.2831853F/12;stroke(p+glm::vec2(std::cos(a),std::sin(a))*2.8F,p+glm::vec2(std::cos(b),std::sin(b))*2.8F);}};
                    if(c.icon=="base")bead({0,0});
                    else if(c.icon=="domain") {stroke({-8,-2},{0,3});stroke({0,3},{8,-2});bead({-8,-2});bead({0,3});bead({8,-2});}
                    else for(int x=-1;x<=1;++x){stroke({x*8.F,-6},{x*8.F,6});bead({x*8.F,-6});bead({x*8.F,6});}
                    const float scale=.0028F;
                    text(c.id+":label",c.label,{center.x-strokeTextWidth(c.label.size(),scale)*.5F,b.minimum.y+.028F},scale,fg,b);
                }
                else if(c.icon=="edit"){stroke({-6,-6},{5,5});stroke({-3,-7},{7,3});stroke({5,5},{7,3});stroke({-6,-6},{-3,-7});}
                else if(c.icon=="revert"){stroke({5,-5},{5,4});stroke({5,4},{-6,4});stroke({-6,4},{-2,8});stroke({-6,4},{-2,0});}
                else if(c.icon=="x") {stroke({-6,-6},{6,6});stroke({-6,6},{6,-6});}
                else if(c.icon=="up" || c.icon=="down") {
                    const float sign=c.icon=="up"?1.F:-1.F;
                    stroke({-5,-3*sign},{0,3*sign});stroke({0,3*sign},{5,-3*sign});
                }
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
                const auto fitted=boundedMenuStrokeText(c.label,b.maximum.y-b.minimum.y-.010F,.0033F);
                const float s=fitted.scale;
                text(c.id,fitted.text,{(b.minimum.x+b.maximum.x)*.5F+(hand==0?-3:3)*s,(b.minimum.y+b.maximum.y+(hand==0?-1:1)*strokeTextWidth(fitted.text.size(),s))*.5F},s,fg,
                    {b.minimum+glm::vec2(.005F),b.maximum-glm::vec2(.005F)},true);
            } else {
                const bool sweepValue=c.id.starts_with("sweep:axis:") && c.id.ends_with(":value");
                const float padding=sweepValue?.010F:.012F;
                const MenuPanelBounds content{b.minimum+glm::vec2(padding),b.maximum-glm::vec2(padding)};
                if(const auto progress=loadingProgress(c.action)) {
                    textBlock(c.id+":label",c.label,{{content.minimum.x,content.minimum.y+.040F},content.maximum},fg,.0028F);
                    boundedText(c.id+":progress",progress->second,{content.minimum.x,content.minimum.y+.032F},.0022F,{.55F,.85F,.75F},content);
                    const MenuPanelBounds track{{content.minimum.x,content.minimum.y+.002F},{content.maximum.x,content.minimum.y+.010F}};
                    if(!clip || menuLayoutContains(*clip,track))audit.addFeature(c.id+":progress-bar",track);
                    fill(track,{.12F,.16F,.19F});
                    fill({track.minimum,{track.minimum.x+(track.maximum.x-track.minimum.x)*std::clamp(progress->first,0.F,1.F),track.maximum.y}},{.25F,.8F,.6F});
                    continue;
                }
                auto body=content;
                if(!c.section.empty()) {
                    boundedText(c.id+":section",c.section,{content.minimum.x,content.maximum.y},.0022F,{.55F,.60F,.66F},content);
                    body.maximum.y-=.022F;
                }
                float maximumScale=.0032F;
                if(sweepValue) {
                    // Keep the number intact on one line below its axis label.
                    const auto separator=c.label.find(' ');
                    const auto digits=separator==std::string::npos?c.label.size():c.label.size()-separator-1;
                    maximumScale=std::clamp((body.maximum.x-body.minimum.x)/strokeTextWidth(digits,1.F),kMinimumMenuTextScale,maximumScale);
                }
                textBlock(c.id+":label",c.label,body,fg,maximumScale);
            }
        }
        audit.finish();
    }
};
}
