// Production VR table. Desktop browser rendering and document operations stay browser-owned.
inline constexpr MenuPanelBounds kFileTableBounds{{file_table_style::panel.x,file_table_style::panel.y},{file_table_style::panel.x+file_table_style::panel.w,file_table_style::panel.y+file_table_style::panel.h}};
inline bool fileTableEntry(const std::string& id){return id.starts_with("routing:file-entry-");}
inline size_t fileTableCount(const SidebarTab& tab){return std::count_if(tab.rows.begin(),tab.rows.end(),[](const auto& r){return fileTableEntry(r.id);});}
inline std::vector<SidebarControl> fileTableControls(const SidebarTab& tab,size_t offset,
        const std::function<bool(const std::string&)>& available) {
    std::vector<SidebarControl> out;size_t row=0,button=0;
    const std::array<std::string,5> commands{"file-new","file-assembly","file-open","file-save","file-close"};
    const auto box=[](file_table_style::Rect r){return MenuPanelBounds{{r.x,r.y},{r.x+r.w,r.y+r.h}};};
    auto add=[&](const SidebarRow& r,MenuPanelBounds b){out.push_back({r.id,r.label,r.section,r.action,b,!r.action.empty()&&available(r.action)});out.back().surfaceDepth=file_table_style::faceDepth;};
    for(const auto& r:tab.rows){
        if(fileTableEntry(r.id)){
            const size_t index=row++;if(index<offset||index>=offset+6)continue;
            add(r,box(file_table_style::row(index-offset)));
        }else if(r.id=="routing-help")add(r,box(file_table_style::location));
        else if(r.id=="routing:file-keyboard")add(r,{{-.33F,-.40F},{.64F,-.305F}});
        else if(r.id=="routing:info-error")add(r,{{-.33F,-.53F},{.64F,-.455F}});
        else if(!r.action.empty()){
            const auto command=std::find(commands.begin(),commands.end(),r.id.substr(r.id.starts_with("routing:")?8:0));
            const size_t index=command==commands.end()?5+button++:size_t(command-commands.begin());
            add(r,box(file_table_style::command(index)));
        }
    }
    if(row>6)out.push_back({"scrollbar","Scroll files","","",box(file_table_style::rail),true});
    return out;
}
inline std::array<std::string,4> fileTableCells(const SidebarControl& c){
    std::array<std::string,4> cells{c.label,"--","--","--"};
    std::istringstream in(c.section);for(size_t i=1;i<4;++i)if(!std::getline(in,cells[i],'|'))cells[i]="--";
    return cells;
}
