"""Expose existing MagicDNA free-form GUI operations to explicit batch inputs.

No spline, slicing, cylinder, or routing algorithms are replaced. Exact source
anchors fail closed; each modal path still invokes its normal OK callback.
"""

import argparse
import hashlib
import json
from pathlib import Path


def patch_source(root):
    patches = {
        "class/hyperbundle.m": [
            (
                "            OldData = 0 ;\n            for k=1: length( obj.containBundle )\n                if  obj.containBundle{k}.Tol ~=15\n                    fprintf('The Tol is %i when saving this data \\n' , obj.containBundle{k}.Tol);\n                    OldData =1 ;\n                end\n                \n                obj.containBundle{k}.Tol = 15 ;   % debug 02132019\n            end\n            \n            if OldData==1\n%                 obj.TakeSeveralV3=cell(size( obj.TakeSeveralV3))  ;  % assign as empty to prevent wrong FB index\n                fprintf(' OldData is true............. \\n' ) ;\n                fprintf(' Please search forced-connection again \\n' ) ;\n            end\n            \n",
                "            % Preserve the serialized connection tolerance on native reload.\n            \n",
            ),
            (
                "function obj=LoadT(obj,src,evn)",
                "function obj=LoadT(obj,src,evn,sourceFile)",
            ),
            (
                "            uiopen([AssemFolder '*.mat']);",
                "            if nargin < 4\n                uiopen([AssemFolder '*.mat']);\n            else\n                load(sourceFile,'S','SavepH2','SaveOHTable');\n            end",
            ),
        ],
        "functions/QueryStapleClr.m": [
            (
                "uiwait(NewFig)",
                "if isappdata(MagicDNAfH,'MagicDNABatchOptions')\n"
                "    batch=getappdata(MagicDNAfH,'MagicDNABatchOptions');\n"
                "    assert(ismember(batch.staple_clearance_bp,[2:10,15]));\n"
                "    t.Data(:)={num2str(batch.staple_clearance_bp)};\n"
                "    Export(btn_OK,[],t,NewFig);\n"
                "else\n    uiwait(NewFig)\nend",
            ),
        ],
        "functions/FFCurve.m": [
            (
                "function FFCurve(src,evn,allGraphics,ss_STEP,allbtn)",
                "function FFCurve(src,evn,allGraphics,ss_STEP,allbtn,varargin)",
            ),
            (
                "readPoints_2(allbtn.StartPoints,[],allGraphics,ss_STEP) ;",
                "readPoints_2(allbtn.StartPoints,[],allGraphics,ss_STEP,varargin{:}) ;",
            ),
        ],
        "functions/readPoints_2.m": [
            (
                "nargin\n",
                "nargin\n% Explicit batch equivalent of Sketch -> Export open spline.\n"
                "if nargin == 5 && isstruct(varargin{1})\n"
                "    recipe=varargin{1};\n"
                "    FFC=freeformcurve(2,recipe.points_nm,ss_STEP);\n"
                "    FFC.ExportXYZ(src,[],false);\n"
                "    return\nend\n",
            ),
        ],
        "class/freeformcurve.m": [
            (
                "function ExportXYZ(obj,src,evn)",
                "function ExportXYZ(obj,src,evn,closed)",
            ),
            (
                "            NewFig = dialog('units','pixels', 'position',[300 300 400 500],...",
                "            if nargin < 4\n            NewFig = dialog('units','pixels', 'position',[300 300 400 500],...",
            ),
            (
                "            uiwait(NewFig) ;",
                "            uiwait(NewFig) ;\n            else\n"
                "                assert(isscalar(closed) && ~closed, 'Batch supports open splines');\n"
                "                src.UserData.ConnectDataInTable={ '1', false };\n"
                "            end",
            ),
        ],
        "functions/GUI_ContinuousSlicing.m": [
            (
                "uiwait(d);",
                "if isappdata(FFC.ss_STEP,'MagicDNABatchOptions')\n"
                "    batch=getappdata(FFC.ss_STEP,'MagicDNABatchOptions');\n"
                "    assert(batch.accept_native_slicing, 'Explicit slicing acceptance required');\n"
                "    Exportresult(btn1,[],nCylinder,Cyl_h,sH,sH_alljoint,PTN_vec_onSpline,Fine_tarr,FFC);\n"
                "else\n    uiwait(d);\nend",
            ),
        ],
        "functions/GUIAsignSSInfo3.m": [
            (
                "d=gcf; sBundle=src.Value ;",
                "d=ancestor(src,'figure'); sBundle=src.Value ;",
            ),
            ("        delete(gcf)", "        delete(ancestor(src,'figure'))"),
            (
                "uiwait(d);",
                "if isappdata(ancestor(fH,'figure'),'MagicDNABatchOptions')\n"
                "    batch=getappdata(ancestor(fH,'figure'),'MagicDNABatchOptions');\n"
                "    assert(batch.accept_native_ss_defaults, 'Explicit ssDNA defaults acceptance required');\n"
                "    Exportresult(btn1,[],t,popup1,ppH);\n"
                "else\n    uiwait(d);\nend",
            ),
        ],
    }
    pending, report = [], {}
    for relative, pairs in patches.items():
        path = Path(root) / relative
        before = path.read_bytes()
        code = before.decode().replace("\r\n", "\n")
        for old, new in pairs:
            if new in code:
                continue
            if code.count(old) != 1:
                raise ValueError(
                    f"Unexpected anchor count {code.count(old)} in {relative}: {old[:70]}"
                )
            code = code.replace(old, new)
        after = (
            code.replace("\n", "\r\n").encode() if b"\r\n" in before else code.encode()
        )
        pending.append((path, after))
        report[relative] = {
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
        }
    for path, data in pending:
        path.write_bytes(data)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    print(json.dumps(patch_source(parser.parse_args().source), indent=2))
