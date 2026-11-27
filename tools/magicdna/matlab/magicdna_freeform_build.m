function magicdna_freeform_build(sourceDirectory, recipeFile, outputDirectory)
% Replay public MagicDNA sketch, sweep, assembly and routing operations.
% Requires source patches from prepare_matlab and prepare_freeform. Hidden
% Handle Graphics objects are retained; no desktop clicks or modal input.
assert(~exist(outputDirectory,'dir'),'Output must be new'); mkdir(outputDirectory);
diary(fullfile(outputDirectory,'matlab.log'));
cleanup=onCleanup(@()finish());
recipe=jsondecode(fileread(recipeFile));
copyfile(recipeFile,fullfile(outputDirectory,'recipe.json'));
cd(sourceDirectory);addpath(genpath(sourceDirectory));
magicdna_batch_graphics(); rng(recipe.seed,'twister');
history={};
record('rng',struct('seed',recipe.seed,'algorithm','twister'));
assert(license('test','Curve_Fitting_Toolbox')==1,'Curve Fitting Toolbox unavailable');
assert(all(isfinite(fnval(cscvn(recipe.points_nm'),0))));
f=main();
setappdata(f,'MagicDNABatchOptions',recipe);
step=findall(f,'Tag','ss_STEP'); step.Parent.SelectedTab=step;
setappdata(step,'MagicDNABatchOptions',recipe);
button=operation(step,'FFCurve(');
info=functions(button.Callback); context=info.workspace{1};
FFCurve(button,[],context.allGraphics,step,context.allbtn,recipe);
record('Sketch -> Export open spline',struct('points_nm',recipe.points_nm,'closed',false));
% FFCurve already invokes its native Finish operation before returning.
record('Finish line model (automatic in FFCurve)',struct());
table=findall(step,'Tag','STEPtable'); assert(numel(table)==1);
for k=1:size(table.Data,1)-1
    editcell(table,k,2,recipe.segment_length_bp);
    if strcmp(recipe.lattice,'HONEYCOMB')
        editcell(table,k,3,'6HB');
    else
        editcell(table,k,3,'3'); editcell(table,k,4,'6');
    end
end
record('Set cross-section and length table',struct('data',{table.Data}));
figure(f);axes(findall(step,'Tag','SS','Type','axes'));
invoke(operation(step,'saveTable('));
assembly=findall(f,'Tag','ss_Assembly');model=assembly.UserData.HyperBundle;
assert(numel(model.containBundle)>1,'Curve was not sliced');
counts=cellfun(@(b)numel(b.Zbase1),model.containBundle);
assert(all(counts==recipe.helix_count),'Cross-section changed');
ffc=step.UserData.FFC;
record('Sweep -> accept native slicing -> Assembly',struct('bundles',numel(counts),'helix_counts',counts));
figure(f);invoke(operation(assembly,'SortDist('));
record('FindXover',struct('adjacency',model.BundleAdjM));
figure(f);invoke(operation(assembly,'ConnectFC('));
record('ssDNA -> accept native defaults',model.ssOption);
figure(f);invoke(findall(f,'Tag','ScafAgain'));
record('GetScaffoldRouting',model.ScafOption);
figure(f);invoke(context.allbtn.MechStapleAgain);
record('GetStapleRouting',struct('type',model.StapOption.type,'halfXover',model.StapOption.halfXover,'clearance_bp',recipe.staple_clearance_bp));
assert(~isempty(model.ScafRouting) && ~isempty(model.StapList3));
figure(f);model.SaveT_wTarget([],[],fullfile(outputDirectory,'design'));
record('SaveT_wTarget',struct('file','design.mat'));
% Retain the upstream free-form sketch/slicing output separately from the
% native Assembly file, whose format does not persist the sketch tab.
freeform=struct('points_nm',recipe.points_nm,'scaled_points',ffc.PointOnScaleCurve, ...
    'frames',ffc.PTN_Vec_onCurve,'bundle',ffc.Bundlett,'cylinders',ffc.Cylinderstt);
save(fullfile(outputDirectory,'freeform.mat'),'freeform');
model.ExportJSON('routing',outputDirectory);
record('ExportJSON',struct('files',{{'routingHC.json','routingSQ.json'}}));
report=struct('status','created','bundle_count',numel(counts),'helix_count_per_bundle',counts, ...
    'scaffolds',numel(model.ScafRouting),'staples',numel(model.StapList3), ...
    'curve_points',ffc.PointOnScaleCurve,'frames',ffc.PTN_Vec_onCurve);
report.bundle_geometry=cellfun(@(b)struct('z1',b.Zbase1,'z2',b.Zbase2, ...
    'xy',b.CylInplanePosition,'transform',b.TransformMatrix2,'axes',b.CylinderXYZGlobal),model.containBundle,'UniformOutput',false);
writejson('report.json',report);
process=history;save(fullfile(outputDirectory,'design.mat'),'process','recipe','-append');
figure(f);assembly.Parent.SelectedTab=assembly;drawnow;
ax=findall(f,'Tag','AssemblyMain');view(ax,3);axis(ax,'equal');
print(f,fullfile(outputDirectory,'review.png'),'-dpng','-r100');
fprintf('MAGICDNA_FREEFORM_BUILD_PASS %s\n',recipe.lattice);

    function record(command,parameters)
        history{end+1}=struct('index',numel(history)+1,'command',command,'parameters',logvalue(parameters));
        writejson('process.json',history);
        fprintf('STAGE_PASS %s\n',command);
    end
    function writejson(name,value)
        encoded=jsonencode(value);
        fid=fopen(fullfile(outputDirectory,name),'w');assert(fid>=0);
        closer=onCleanup(@()fclose(fid));fwrite(fid,encoded,'char');
    end
end
function invoke(button)
assert(numel(button)==1,'Expected exactly one operation control');
cb=button.Callback;
if iscell(cb),feval(cb{1},button,[],cb{2:end});else,feval(cb,button,[]);end
end
function finish()
close all force;set(0,'DefaultFigureCreateFcn','');diary off;
end

function button=operation(root,token)
controls=findall(root,'Type','uicontrol'); button=[];
for k=1:numel(controls)
 cb=controls(k).Callback;if iscell(cb),cb=cb{1};end
 if isa(cb,'function_handle') && contains(func2str(cb),token),button=[button;controls(k)];end
end
assert(numel(button)==1,['Missing/ambiguous operation: ' token]);
end

function result=logvalue(value)
% Exclude transient GUI handles, retaining all numeric authoring parameters.
if isstruct(value)
 result=value; fields=fieldnames(value);
 for k=1:numel(value),for j=1:numel(fields)
  result(k).(fields{j})=logvalue(value(k).(fields{j}));
 end,end
elseif iscell(value)
 result=cellfun(@logvalue,value,'UniformOutput',false);
elseif isobject(value) || isa(value,'function_handle')
 result=struct('transient_ui_class',class(value));
else
 result=value;
end
end

function editcell(table,row,column,value)
table.Data{row,column}=value;
event=struct('EventName','CellEdit','Indices',[row,column],'EditData',value);
feval(table.CellEditCallback,table,event);
end
