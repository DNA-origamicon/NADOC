#pragma once
#include "controller_prompt.hpp"
#include <fstream>
#include <iomanip>

namespace nadoc_vr {
// The heartbeat withdraws orphaned decisions if the browser disappears.
class BrowserPrompt {
 public:
    int version=0,heartbeat=0,answeredVersion=0,answerVersion=0;
    uint64_t sequence=0;
    std::string answer;
    double received=0;
    bool detailAllowed=true,open=false;
    template<class Show,class Publish>
    void poll(const std::string& path,ControllerPrompt& prompts,double now,Show show,Publish publish) {
        if(path.empty())return;
        std::ifstream in(path+".prompt");
        std::string magic,title,message;int v=0,h=0,n=0,allowed=1;
        if(in>>magic>>v>>h>>n>>allowed>>std::quoted(title)>>std::quoted(message);
           in && magic=="NADOC_PROMPT_1" && v>0 && h>0 && n>=0 && n<=4 && (allowed==0 || allowed==1) && title.size()<=256 && message.size()<=16384) {
            ControllerPrompt::Request request{title,message,{}, {},"browser"};
            bool valid=true;
            for(int i=0;i<n;++i) {
                ControllerPrompt::Option o;
                if(!(in>>std::quoted(o.id)>>std::quoted(o.label)) || o.id.size()!=1 || o.id[0]<'0' || o.id[0]>'3' || o.label.empty() || o.label.size()>96){valid=false;break;}
                for(const auto& previous:request.options)if(previous.id==o.id)valid=false;
                request.options.push_back(std::move(o));
            }
            std::string extra;if(in>>extra)valid=false;
            if(valid && (h!=heartbeat || v!=version)) {
                heartbeat=h;received=now;detailAllowed=allowed;
                if(v!=version) {
                    prompts.withdraw("browser");version=v;open=n>0;
                    if(n && v!=answeredVersion) {
                        request.complete=[this,v,publish](const std::string& id){
                            if(v!=version)return;
                            open=false;answer=id;answerVersion=answeredVersion=v;++sequence;publish();
                        };
                        show(std::move(request));
                    }
                }
            }
        }
        if(open && now-received>5) {
            prompts.withdraw("browser");open=false;
            answer="dismiss";answerVersion=answeredVersion=version;++sequence;publish();
        }
    }
};
}
