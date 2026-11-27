function magicdna_freeform_reopen(sourceDirectory, buildDirectory, outputDirectory)
% Fresh MATLAB process: exercise native LoadT and export, checking saved state.
assert(~exist(outputDirectory,'dir'),'Output must be new');mkdir(outputDirectory);
diary(fullfile(outputDirectory,'matlab.log')); cleanup=onCleanup(@()finish());
cd(sourceDirectory);addpath(genpath(sourceDirectory));magicdna_batch_graphics();
f=main();
original=load(fullfile(buildDirectory,'design.mat'),'S','process','recipe');
assert(isfield(original,'process') && ~isempty(original.process),'AGENT_PROCESS_REQUIRED');
assert(isequaln(original.process,jsondecode(fileread(fullfile(buildDirectory,'process.json')))) || ...
    strcmp(jsonencode(original.process),fileread(fullfile(buildDirectory,'process.json'))),'Saved process differs');
beforeTolerance=cellfun(@(b)b.Tol,original.S.containBundle);
beforeGeometry=geometry(original.S.containBundle);
model=hyperbundle(1,original.S.containBundle{1});
figure(f);model.LoadT([],[],fullfile(buildDirectory,'design.mat'));
fields={'ScafRouting','StapList3','ScafdigitHC','ScafdigitSQ','DigitStapHC','DigitStapSQ', ...
    'BundleAdjM','RelateTable','SavePremPair','CustomSkipAndInsertion'};
for k=1:numel(fields)
 key=fields{k};assert(isequaln(original.S.(key),model.(key)),['Native reopen changed ' key]);
end
afterTolerance=cellfun(@(b)b.Tol,model.containBundle);
assert(isequal(beforeTolerance,afterTolerance),'Native reopen changed saved tolerance');
assert(strcmp(beforeGeometry,geometry(model.containBundle)),'Native reopen changed geometry');
figure(f);model.ExportJSON('routing',outputDirectory);
report=struct('status','reopened','geometry_exact',true,'routing_exact',true, ...
 'saved_tolerance',beforeTolerance,'reopened_tolerance',afterTolerance, ...
 'tolerance_preserved',isequal(beforeTolerance,afterTolerance),'process_verified',true);
fid=fopen(fullfile(outputDirectory,'report.json'),'w');assert(fid>=0);
fwrite(fid,jsonencode(report),'char');fclose(fid);
fprintf('MAGICDNA_FREEFORM_REOPEN_PASS\n');
end
function finish()
close all force;set(0,'DefaultFigureCreateFcn','');diary off;
end

function result=geometry(bundles)
result=jsonencode(cellfun(@(b)struct('z1',b.Zbase1,'z2',b.Zbase2, ...
 'xy',b.CylInplanePosition,'transform',b.TransformMatrix2,'axes',b.CylinderXYZGlobal, ...
 'skip',b.skipPosition,'insert',b.InsertPosition),bundles,'UniformOutput',false));
end
