// Production VR table. Desktop browser rendering and document operations stay browser-owned.
inline constexpr MenuPanelBounds kFileTableBounds{{-.96F,-.68F},{.96F,.735F}};
inline bool fileTableEntry(const std::string& id){return id.starts_with("routing:file-entry-");}
inline size_t fileTableCount(const SidebarTab& tab){return std::count_if(tab.rows.begin(),tab.rows.end(),[](const auto& r){return fileTableEntry(r.id);});}
inline std::vector<SidebarControl> fileTableControls(const SidebarTab& tab,size_t offset,
        const std::function<bool(const std::string&)>& available) {
    std::vector<SidebarControl> out;size_t row=0,button=0;
    const std::array<std::string,5> commands{"file-new","file-assembly","file-open","file-save","file-close"};
    auto add=[&](const SidebarRow& r,MenuPanelBounds b){out.push_back({r.id,r.label,r.section,r.action,b,!r.action.empty()&&available(r.action)});};
    for(const auto& r:tab.rows){
        if(fileTableEntry(r.id)){
            const size_t index=row++;if(index<offset||index>=offset+6)continue;
            const float top=.24F-float(index-offset)*.10F;
            add(r,{{-.43F,top-.085F},{.78F,top}});
        }else if(r.id=="routing-help")add(r,{{-.43F,.405F},{.78F,.525F}});
        else if(r.id=="routing:file-keyboard")add(r,{{-.43F,-.48F},{.78F,-.39F}});
        else if(r.id=="routing:info-error")add(r,{{-.43F,-.60F},{.78F,-.51F}});
        else if(!r.action.empty()){
            const auto command=std::find(commands.begin(),commands.end(),r.id.substr(r.id.starts_with("routing:")?8:0));
            const size_t index=command==commands.end()?5+button++:size_t(command-commands.begin());
            const float top=.39F-float(index)*.12F;
            add(r,{{-.86F,top-.095F},{-.49F,top}});
        }
    }
    if(row>6)out.push_back({"scrollbar","Scroll files","","",{{.81F,-.345F},{.88F,.24F}},true});
    return out;
}
inline std::array<std::string,4> fileTableCells(const SidebarControl& c){
    std::array<std::string,4> cells{c.label,"--","--","--"};
    std::istringstream in(c.section);for(size_t i=1;i<4;++i)if(!std::getline(in,cells[i],'|'))cells[i]="--";
    return cells;
}
template<class Text> void drawFileTableCells(const std::string& id,const std::array<std::string,4>& cells,
        float bottom,float top,glm::vec3 color,Text text){
    constexpr std::array<float,5> columns{-.415F,.125F,.30F,.60F,.765F};
    for(size_t i=0;i<4;++i){
        const MenuPanelBounds box{{columns[i]+.006F,bottom+.009F},{columns[i+1]-.012F,top-.009F}};
        text(id+":col"+std::to_string(i),cells[i],{box.minimum.x,(bottom+top)*.5F+.009F},i==0?.0036F:.0028F,color,box);
    }
}
