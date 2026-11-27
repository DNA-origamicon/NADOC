function [model, parsed, report] = nadoc_magicdna_bundle(sourceFile, lattice)
% Import a validated single-bundle routing file into native MagicDNA objects.
% Call the Python converter's validation first. This function does not save a
% molecular document. The NADOC package retains the complete upstream process.
% Source indices remain unchanged; default SQ deletion patterns are disabled.
parsed = jsonObject(sourceFile, true); % no random sequence assignment
data = parsed.Odat;
n = numel(data.vstrands);
assert((strcmp(lattice,'HONEYCOMB') && n==6) || (strcmp(lattice,'SQUARE') && n==18));
assert(numel(parsed.ScafR_AllBase)==1, 'Exactly one linear scaffold is required');
numbers=zeros(n,1); cells=zeros(n,2); low=zeros(1,n); high=low;
for k=1:n
    h=data.vstrands{k}; numbers(k)=h.num; cells(k,:)=[h.col,h.row];
    occupied=any(h.scaf~=-1,2) | any(h.stap~=-1,2);
    indices=find(occupied)-1;
    assert(~isempty(indices)); low(k)=min(indices); high(k)=max(indices);
end
assert(all(mod(numbers,2)==mod(sum(cells,2),2)), 'Source polarity mismatch');
assert(min(low)>=1, 'MagicDNA native compiler requires occupied base indices >= 1');
if strcmp(lattice,'HONEYCOMB')
    xy=[sqrt(3)*cells(:,1), 3*cells(:,2)+mod(sum(cells,2),2)];
else
    xy=2*cells;
end
% Native constructor reserves 21 bases near its origin. Supply a translated
% extent to satisfy that constructor, then explicitly restore source indices.
% This is an input-index translation only, not a change to the source routing.
offset=21*max(0,ceil((21-min(low))/21));
if strcmp(lattice,'HONEYCOMB')
    bundle=BundleCylinderHC(1,[],low+offset,high+offset,xy);
else
    bundle=BundleCylinderSQ(1,[],low+offset,high+offset,xy);
end
assert(numel(bundle.Zbase1)==n, 'Native bundle constructor discarded cylinders');
bundle.Zbase1=low; bundle.Zbase2=high;
bundle.AGroupGoUp=mod(numbers(1),2)==0;
for k=1:n
    assert(~xor(ismember(k,bundle.AGroup),bundle.AGroupGoUp)==(mod(numbers(k),2)==0), ...
        'Native bundle polarity does not match source');
end
bundle.Default_skipPattern1=[]; bundle.Default_skipPattern2=[];
bundle.skipPosition=zeros(0,4); bundle.InsertPosition=zeros(0,4);
for k=1:n
    for bp=reshape(find(data.vstrands{k}.skip==-1)-1,1,[])
        bundle.skipPosition(end+1,:)=[1,k,k,bp];
    end
    for bp=reshape(find(data.vstrands{k}.loop==1)-1,1,[])
        bundle.InsertPosition(end+1,:)=[1,k,k,bp];
    end
end
model=hyperbundle(1,bundle);
% Explicit C1/C2/C3/C4/C5 correspondence for one nonoverlapping bundle.
model.RelateTable=[ones(n,1),(1:n)',(1:n)',numbers,(1:n)',cells];
model.RelateTableOrr=model.RelateTable; model.RelateVec=numbers';
model.CustomSkipAndInsertion=true; model.UserWantOH='No';
scaf=parsed.ScafCornerRep(); stap=parsed.StapCornerRep();
model.ScafRouting=cell(size(scaf)); model.StapList3=cell(size(stap));
for k=1:numel(scaf)
    [found,index]=ismember(scaf{k}(:,1),numbers); assert(all(found));
    model.ScafRouting{k}=[ones(size(index)),index,scaf{k}(:,2)];
end
for k=1:numel(stap)
    [found,index]=ismember(stap{k}(:,1),numbers); assert(all(found));
    model.StapList3{k}=[index,stap{k}(:,2)];
end
model.ConvertScafG(); model.ConvertScafSQ(); model.ConvertScafHC();
model.ConvertStap('Square'); model.ConvertStap('Honeycomb');
report=struct('helices',n,'scaffolds',numel(scaf),'staples',numel(stap), ...
    'constructor_index_translation',offset,'source_indices_restored',true, ...
    'geometry','MagicDNA native geometry; not atom-coordinate equivalence to NADOC', ...
    'sequences','Unassigned in MagicDNA; original sequences remain in NADOC sidecar');
end
