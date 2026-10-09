#pragma once
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace nadoc_vr {
// Host-independent list state. Selection and row actions survive viewport changes.
struct ScrollableSet {
    struct Item {std::string label,detail;int value=0;bool enabled=true,pinned=false;};
    std::vector<Item> items;
    int offset=0,capacity=3,selected=-1;
    int maximum() const {return std::max(0,int(items.size())-capacity);}
    void scroll(int delta){offset=std::clamp(offset+delta,0,maximum());}
    void seek(float fraction){offset=int(std::round(std::clamp(fraction,0.F,1.F)*maximum()));}
    int index(int slot) const {const int i=offset+slot;return slot>=0 && slot<capacity && i<int(items.size())?i:-1;}
};
}
