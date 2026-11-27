"""Add optional noninteractive I/O to the authors' free-form MagicDNA source.

Also corrects the scaffold compiler's crossover predecessor index. No geometry
algorithms are changed. Every replacement is exact and fail-closed.
"""

import argparse
import hashlib
import json
from pathlib import Path


def patch_source(root):
    root = Path(root)
    patches = {
        "class/jsonObject.m": [
            (
                "function obj=jsonObject()",
                "function obj=jsonObject(sourceFile, routingOnly)",
            ),
            (
                "            [obj.filename,obj.filepath,FilterIndex]= uigetfile({'*.json','JSONfile' },'Select the json file');",
                "            if nargin < 2, routingOnly = false; end\n"
                "            if nargin < 1\n"
                "                [obj.filename,obj.filepath,FilterIndex]= uigetfile({'*.json','JSONfile' },'Select the json file');\n"
                "            else\n"
                "                [folder, stem, ext] = fileparts(sourceFile);\n"
                "                obj.filename = [stem ext]; obj.filepath = [folder filesep];\n"
                "            end",
            ),
            (
                "                    obj.getSeq ;\n            obj.getSegment;\n            obj.getSegment2;",
                "            if ~routingOnly\n                obj.getSeq;\n                obj.getSegment;\n                obj.getSegment2;\n            end",
            ),
        ],
        "class/hyperbundle.m": [
            (
                "                        Z0=Seq(i1,2) ;\n"
                "                        DCellList{CylinderIndex}(Z0,:)=[C0,Z0,C1,ZNext]    ;\n"
                "                        C0=CylinderIndex;",
                "                        % Preserve the previous nucleotide until its link is written.\n"
                "                        DCellList{CylinderIndex}(Seq(i1,2),:)=[C0,Z0,C1,ZNext];\n"
                "                        Z0=Seq(i1,2);\n"
                "                        C0=CylinderIndex;",
            ),
            (
                "function obj=ExportJSON(obj)",
                "function obj=ExportJSON(obj, outputName, outputDirectory)",
            ),
            (
                "            answer = inputdlg(prompt,dlg_title,num_lines,defaultans);\n            \n            if strcmp(answer,'No')",
                "            if nargin < 2\n                answer = inputdlg(prompt,dlg_title,num_lines,defaultans);\n"
                "            else\n                answer = {outputName};\n            end\n"
                "            if nargin < 3, outputDirectory = fullfile(pwd, 'cadnano_jsonfile'); end\n"
                "            \n            if strcmp(answer,'No')",
            ),
            (
                "                        Hex =t_json.Data{Colorstap(color_j),5} ;",
                "                        if isempty(t_json) || isempty(t_json.Data)\n"
                "                            Hex = dec2hex(ColorChoice(1+mod(color_j-1,numel(ColorChoice))));\n"
                "                        else\n                            Hex =t_json.Data{Colorstap(color_j),5} ;\n                        end",
            ),
            (
                "                JsonFolder=[ pwd filesep 'cadnano_jsonfile' filesep];",
                "                if ~exist(outputDirectory, 'dir'), mkdir(outputDirectory); end\n"
                "                JsonFolder=[outputDirectory filesep];\n"
                "                if nargin >= 2 && exist([JsonFolder file_name], 'file')\n"
                "                    error('MagicDNA:OutputExists', 'Refusing to overwrite output');\n                end",
            ),
        ],
    }
    report = {}
    prepared = []
    for relative, replacements in patches.items():
        path = root / relative
        before = path.read_bytes()
        text = before.decode().replace("\r\n", "\n")
        # Upgrade the first patch revision without nesting its color fallback.
        if relative == "class/hyperbundle.m":
            text = text.replace(
                "                        if isempty(t_json)\n",
                "                        if isempty(t_json) || isempty(t_json.Data)\n",
            )
        for old, new in replacements:
            if new in text:
                continue
            expected = (
                2 if old.startswith("                        Z0=Seq(i1,2)") else 1
            )
            if text.count(old) != expected:
                raise ValueError(
                    f"Unrecognized source anchor in {relative}: {old[:70]}"
                )
            text = text.replace(old, new)
        after = (
            text.replace("\n", "\r\n").encode() if b"\r\n" in before else text.encode()
        )
        report[relative] = {
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
        }
        prepared.append((path, after))
    for path, after in prepared:
        path.write_bytes(after)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    print(json.dumps(patch_source(p.parse_args().source), indent=2))
