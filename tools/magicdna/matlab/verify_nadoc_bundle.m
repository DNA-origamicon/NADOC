function report = verify_nadoc_bundle(sourceFile, lattice, outputDirectory)
% Regression for native parser -> bundle -> routing compiler -> caDNAno export.
% Input must first pass `python -m tools.magicdna validate`.
assert(~exist(outputDirectory,'dir'), 'Use a new output directory');
[model, parsed, report] = nadoc_magicdna_bundle(sourceFile, lattice);
model.ExportJSON('verified', outputDirectory);
suffix='HC'; if strcmp(lattice,'SQUARE'), suffix='SQ'; end
returned=loadjson(fullfile(outputDirectory,['verified' suffix '.json']));
original=parsed.Odat;
assert(numel(original.vstrands)==numel(returned.vstrands), 'Helix inventory changed');
for k=1:numel(original.vstrands)
    a=original.vstrands{k}; found=false;
    for j=1:numel(returned.vstrands)
        b=returned.vstrands{j};
        if b.num==a.num, found=true; break; end
    end
    assert(found && a.row==b.row && a.col==b.col, 'Helix identity changed');
    for field={'scaf','stap','loop','skip'}
        key=field{1}; x=a.(key); y=b.(key);
        if strcmp(key,'loop') || strcmp(key,'skip'), x=x(:); y=y(:); end
        width=max(size(x,1),size(y,1));
        empty=0; if strcmp(key,'scaf') || strcmp(key,'stap'), empty=-1; end
        x(end+1:width,:)=empty; y(end+1:width,:)=empty;
        assert(isequal(x,y), ['Native round trip changed ' key ' routing/indels']);
    end
end
report.exact_directed_graph_match=true;
fprintf('MAGICDNA_NATIVE_GRAPH_MATCH %s\n',lattice);
end
