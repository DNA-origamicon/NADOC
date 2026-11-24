#pragma once
#include "solid_ui.hpp"
#include "keyboard_slate.hpp"

// Desktop-only studies. Geometry comes from the production text keyboard;
// style selection and sample typing never change documents or VR preferences.
class KeyboardGallery {
 public:
    static constexpr std::array<const char*,4> names{"FLAT / QUIET","BEVEL / SLATE","SOFT / CAPSULE","MECHANICAL / DETAIL"};
    static constexpr std::array<const char*,4> hints{"8 MM FACE / MINIMAL LEGENDS","26 MM FACE / CHAMFERED SIDES","50 MM FACE / ROUNDED KEYCAPS","75 MM FACE / SOCKETS AND HOME MARKS"};
    struct Control {int id;float x,y,w,h;std::string key;};
    int variant=0,hover=-1,pressed=-1,owner=-1;
    bool upper=false,symbols=false,disabled=false;
    std::string value,status="CLICK KEYS TO TYPE / SAMPLE TEXT ONLY";
    void reset(){*this=KeyboardGallery{};}
    std::vector<Control> controls()const {
        std::vector<Control> result;
        for(int i=0;i<4;++i)result.push_back({i,-.8625F+i*.438F,.555F,.42F,.065F,std::to_string(i+1)+" "+names[i]});
        result.push_back({4,-.8545F,.255F,.42F,.09F,"CLEAR"});
        result.push_back({5,-.40F,.255F,.57F,.09F,disabled?"ENABLE KEYS":"DISABLE KEYS"});
        result.push_back({6,.205F,.255F,.65F,.09F,"RESET SAMPLE"});
        int i=10;
        for(const auto& key:nadoc_vr::textKeyboardKeys()){
            const auto b=nadoc_vr::textKeyBounds(key);
            result.push_back({i++,b.minimum.x,b.minimum.y,b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y,key.key});
        }
        return result;
    }
    std::string label(const std::string& key)const{
        if(key=="shift")return "SHIFT";
        if(key=="delete")return "BACKSPACE";
        if(key=="space")return "SPACE";
        if(key=="symbols")return symbols?"ABC":"#+=";
        if(key=="dot")return symbols?"+":upper?">":".";
        if(key=="dash")return symbols?"`":upper?"_":"-";
        if(key=="underscore")return symbols?"~":"_";
        const std::string digits="1234567890";
        if(upper&&!symbols&&key.size()==1&&digits.find(key)!=std::string::npos)return std::string("!@#$%^&*()").substr(digits.find(key),1);
        if(symbols && key.size()==1){
            const std::string letters="qwertyuiopasdfghjklzxcvbnm",punctuation="!@#$%^&*()[]{}<>/\\|:;\"'?,=";
            const auto i=letters.find(key);if(i!=std::string::npos)return punctuation.substr(i,1);
        }
        if(upper && key.size()==1)return std::string(1,char(std::toupper(key[0])));
        return key;
    }
    float depth(int id)const{if(id>=10&&variant==1&&disabled)return keyboard_slate::restDepth;return id<10?.014F:std::array<float,4>{.008F,.026F,.050F,.075F}[variant]-(pressed==id?(variant==0?.002F:.006F):0.F);}
    glm::vec3 target(int id)const{for(const auto& c:controls())if(c.id==id)return {c.x+c.w*.5F,c.y+c.h*.5F,depth(id)};return {};}
    void activate(int id){
        if(id<4){variant=id;status=hints[id];return;}
        if(id==5){disabled=!disabled;return;}
        if(id==4||id==6){value.clear();if(id==6){upper=symbols=disabled=false;}return;}
        if(disabled)return;
        for(const auto& c:controls())if(c.id==id){
            if(c.key=="shift")upper=!upper;
            else if(c.key=="symbols")symbols=!symbols;
            else if(c.key=="delete"){if(!value.empty())value.pop_back();}
            else if(value.size()<80)value+=c.key=="space"?" ":label(c.key);
        }
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,const std::array<bool,2>& held){
        hover=-1;
        for(int h=0;h<2;++h){
            int hit=-1;
            for(const auto& c:controls()){
                auto face=placement;face.openDocked(placement.worldPoint({0,0,depth(c.id)}),placement.orientation());
                auto p=face.rayPanelLocalPoint(hands[h],{c.x,c.y},{c.x+c.w,c.y+c.h});
                if(p){hit=c.id;break;}
            }
            if(hit>=0)hover=hit;
            if(owner==h&&(!held[h]||!hands[h].valid)){if(hands[h].valid&&hit==pressed)activate(hit);owner=pressed=-1;}
            if(clicked[h]&&hit>=0&&owner<0){owner=h;pressed=hit;}
        }
    }
    void render(SolidUi& ui)const{
        const glm::vec3 ink(.9F,.94F,1),muted(.55F,.66F,.77F),cyan(.35F,.76F,1),gold(.95F,.70F,.30F);
        ui.rect(-.945F,-.67F,1.89F,1.405F,{.035F,.048F,.067F},0);
        ui.text("TEXT KEYBOARD / FOUR DESKTOP STUDIES",-.86F,.685F,.0044F,ink);
        ui.rounded(-.86F,.385F,1.72F,.13F,.012F,{.06F,.09F,.13F},.006F);
        const auto preview=value.empty()?"CLICK KEYS TO ENTER TEXT":value.substr(value.size()>55?value.size()-55:0);
        ui.text(preview+"_",-.835F,.465F,.0047F,ink,.012F);
        ui.text(status,-.86F,-.595F,.003F,muted);
        for(const auto& c:controls()){
            const bool key=c.id>=10,enabled=!key||!disabled,focus=c.id==hover;
            const bool selected=c.id==variant||(c.key=="shift"&&upper)||(c.key=="symbols"&&symbols);
            const auto face=!enabled?glm::vec3(.16F,.19F,.23F):selected?glm::vec3(.13F,.36F,.44F):glm::vec3(.16F,.24F,.33F);
            const auto edge=focus?gold:selected?cyan:glm::vec3(.35F,.46F,.58F);
            const float z=depth(c.id);
            if(!key||variant==0){ui.rounded(c.x,c.y,c.w,c.h,.009F,edge,z-.002F);ui.rounded(c.x+.003F,c.y+.003F,c.w-.006F,c.h-.006F,.007F,face,z);}
            else if(variant==1){keyboard_slate::key(ui,c.x,c.y,c.w,c.h,label(c.key),enabled,focus,selected,pressed==c.id?1.F:0.F,c.key=="delete");continue;}
            else if(variant==2){ui.rounded(c.x,c.y,c.w,c.h,.038F,edge,.005F);ui.bevel(c.x+.003F,c.y+.003F,c.w-.006F,c.h-.006F,.035F,.006F,z,.016F,face);}
            else {
                ui.rounded(c.x-.003F,c.y-.003F,c.w+.006F,c.h+.006F,.012F,edge*.6F,.004F);
                ui.bevel(c.x+.004F,c.y+.004F,c.w-.008F,c.h-.008F,.011F,.006F,z,.014F,face);
                ui.rounded(c.x+.022F,c.y+.022F,c.w-.044F,c.h-.044F,.005F,face*1.16F,z+.001F);
                if(c.key=="f"||c.key=="j")ui.rect(c.x+c.w*.38F,c.y+.027F,c.w*.24F,.004F,muted,z+.003F);
                if(c.key.size()==1)ui.text(c.key,c.x+.026F,c.y+c.h-.027F,.002F,muted,z+.003F);
            }
            const auto text=key?label(c.key):c.key;
            const float font=key?(c.key=="delete"?.0028F:.0045F):.0028F;
            ui.text(text,c.x+(c.w-float(text.size()*6-1)*font)*.5F,c.y+c.h*.56F,font,enabled?ink:muted,z+.004F);
        }
    }
    std::string observation(const nadoc_vr::MenuPlacement& placement)const{
        std::ostringstream out;out<<"{\"component\":\"keyboards\",\"variant\":"<<variant<<",\"disabled\":"<<(disabled?"true":"false")<<",\"length\":"<<value.size()<<",\"hover\":"<<hover<<",\"controls\":[";
        bool first=true;for(const auto& c:controls()){if(!first)out<<',';first=false;const auto p=placement.worldPoint(target(c.id));out<<"{\"id\":"<<c.id<<",\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";}return out.str()+"]}";
    }
};
