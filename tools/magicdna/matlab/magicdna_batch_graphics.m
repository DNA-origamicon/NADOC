function magicdna_batch_graphics()
% Native code calls figure(f), which otherwise overrides DefaultFigureVisible.
% Keep graphics objects/current-figure semantics, but never expose input windows.
set(0,'DefaultFigureVisible','off','DefaultFigureCreateFcn',@protect);
end
function protect(f,~)
set(f,'Visible','off','WindowKeyPressFcn',[],'KeyPressFcn',[]);
listeners={addlistener(f,'Visible','PostSet',@(~,~)hide(f)), ...
 addlistener(f,'WindowKeyPressFcn','PostSet',@(~,~)clearinput(f,'WindowKeyPressFcn')), ...
 addlistener(f,'KeyPressFcn','PostSet',@(~,~)clearinput(f,'KeyPressFcn'))};
setappdata(f,'MagicDNABatchGraphicsListeners',listeners);
end
function hide(f)
if isvalid(f) && strcmp(f.Visible,'on'),f.Visible='off';end
end
function clearinput(f,key)
if isvalid(f) && ~isempty(f.(key)),f.(key)=[];end
end
