# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from collections import OrderedDict
from pathlib import Path
import glyphsLib
import logging
import openstep_plist
import os
import sys


logger = logging.getLogger(__name__)


class Parser:
    """Parses Python dictionaries from Glyphs files."""

    def __init__(self, current_type=OrderedDict, format_version=2):
        self.current_type = current_type
        self.format_version = format_version

    def parse(self, d):
        try:
            if isinstance(d, str):
                d = self._fl7_format_clean(d)
                d = openstep_plist.loads(d, use_numbers=True)
            elif isinstance(d, bytes):
                d = self._fl7_format_clean(d)
                d = openstep_plist.loads(d.decode(), use_numbers=True)
            result = self._parse(d)
        except openstep_plist.parser.ParseError as e:
            raise ValueError("Failed to parse file") from e
        return result

    def _fl7_format_clean(self, d):
        """FontLab 7 glyphs source format exports include a final closing semicolon.
        This method removes the semicolon before passing the string to the parser."""
        # see https://github.com/googlefonts/fontmake/issues/806
        if isinstance(d, str):
            d = d.rstrip(";\n")
        elif isinstance(d, bytes):
            d = d.rstrip(b";\n")
        return d

    def _parse(self, d, new_type=None):
        self.current_type = new_type or self.current_type
        if isinstance(d, list):
            return self._parse_list(d, new_type)
        if isinstance(d, (dict, OrderedDict)):
            return self._parse_dict(d, new_type)
        return d

    def _parse_list(self, d, new_type=None):
        self.current_type = new_type or self.current_type
        return [self._parse(x, new_type) for x in d]

    def parse_into_object(self, res, value):
        processed_value = self._process_codepage_ranges(value)
        return self._parse_dict_into_object(res, processed_value)

    def _parse_dict(self, text, new_type=None):
        """Parse a dictionary from source text starting at i."""
        old_current_type = self.current_type
        new_type = new_type or self.current_type
        if new_type is None:
            # customparameter.value needs to be set from the found value
            new_type = dict
        elif type(new_type) == list:
            new_type = new_type[0]
        res = new_type()
        self._parse_dict_into_object(res, text)
        self.current_type = old_current_type
        return res

    def _parse_dict_into_object(self, res, d):
        for name in d.keys():
            sane_name = name.replace(".", "__")
            if hasattr(res, f"_parse_{sane_name}_dict"):
                getattr(res, f"_parse_{sane_name}_dict")(self, d[name])
            elif isinstance(res, (dict, OrderedDict)):
                result = self._parse(d[name])
                try:
                    res[name] = result
                except (TypeError, KeyError):  # hmmm...
                    res = {}  # ugly, this fixes nested dicts in customparameters
                    res[name] = result
            else:
                res[name] = d[name]

    def _process_codepage_ranges(self, value):
        codepages = None
        for param in value.get("customParameters", []):
            if param["name"] == "codePageRanges" or param["name"] == "openTypeOS2CodePageRanges":
                codepages = param["value"]
                break
        
        if codepages is None:
            return value
        
        supported_codepages = []
        unsupported_bits = []
        
        CODEPAGE_RANGES = glyphsLib.builder.constants.CODEPAGE_RANGES
        CODEPAGE_RANGES_KEYS = [str(key) for key in CODEPAGE_RANGES.keys()]
        
        for page in codepages:
            if str(page) in CODEPAGE_RANGES_KEYS:
                supported_codepages.append(int(page))
            else:
                unsupported_bits.append(self._convert_bits(page))
    
        result = value.copy()
        new_params = []
        
        for param in result["customParameters"]:
            if param["name"] != "codePageRanges" and param["name"] != "openTypeOS2CodePageRanges":
                new_params.append(param)
    
        if supported_codepages:
            new_params.append({
                "name": "codePageRanges",
                "value": supported_codepages
            })
    
        if unsupported_bits:
            new_params.append({
                "name": "codePageRangesUnsupportedBits",
                "value": unsupported_bits
            })
         
        result["customParameters"] = new_params
        return result

    def _convert_bits(self, value):
        if isinstance(value, int):
            return value
    
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            elif value.startswith('bit '):
                number_str = value[4:]
                try:
                    return int(number_str)
                except ValueError:
                    raise ValueError(f"'{value}' is not in correct format. A number must follow after 'bit '.")
            else:
                raise ValueError(f"'{value}'is neither a number nor 'bit ' format.")
        
        raise TypeError(f"Unsupported type: {type(value)}")


def load_glyphspackage(package_dir):
    package = Path(package_dir)
    infofile = package / "fontinfo.plist"
    orderfile = package / "order.plist"
    uistatefile = package / "UIState.plist"

    glyphorder = []
    if orderfile.exists():
        with open(orderfile, "r", encoding="utf-8") as order_fh:
            glyphorder = openstep_plist.load(order_fh)

    with open(infofile, "r", encoding="utf-8") as info_fh:
        data = openstep_plist.load(info_fh, use_numbers=True)

    if uistatefile.exists():
        with open(uistatefile, "r", encoding="utf-8") as uistate_fh:
            uistate = openstep_plist.load(uistate_fh, use_numbers=True)
            if "displayStrings" in uistate and "DisplayStrings" not in uistate:
                uistate["DisplayStrings"] = uistate.pop("displayStrings")
            data.update(uistate)

    data["glyphs"] = []
    for glyphfile in (package / "glyphs").glob("*.glyph"):
        with open(glyphfile, "r") as fh:
            glyph = openstep_plist.load(fh, use_numbers=True)
        data["glyphs"].append(glyph)
    # Sort according to glyphorder

    def sort_key(glyph):
        glyphname = glyph["glyphname"]
        if glyphname in glyphorder:
            return (0, glyphorder.index(glyphname))
        else:
            return (1, glyphname)

    data["glyphs"] = list(sorted(data["glyphs"], key=sort_key))

    return data


def load(file_or_path, font=None):
    """Read a .glyphs file. 'file_or_path' should be a (readable) file
    object, a file name, or in the case of a .glyphspackage file, a
    directory name. 'font' is an existing object to parse into, or None.
    Return a 'font' or a GSFont object.
    """
    logger.info("Parsing .glyphs file")
    if font is None:
        font = glyphsLib.classes.GSFont()
    p = Parser(current_type=font.__class__)
    if hasattr(file_or_path, "read"):
        data = openstep_plist.load(file_or_path, use_numbers=True)
    elif os.path.isdir(file_or_path):
        data = load_glyphspackage(file_or_path)
    else:
        fp = open(file_or_path, "r", encoding="utf-8")
        data = openstep_plist.load(fp, use_numbers=True)
    p.parse_into_object(font, data)
    return font


def loads(s):
    """Read a .glyphs file from a (unicode) str object, or from
    a UTF-8 encoded bytes object.
    Return a GSFont object.
    """
    p = Parser(current_type=glyphsLib.classes.GSFont)
    logger.info("Parsing .glyphs file")
    res = glyphsLib.classes.GSFont()
    p.parse_into_object(res, openstep_plist.loads(s, use_numbers=True))
    return res


def main(args=None):
    """Roundtrip the .glyphs file given as an argument."""
    for arg in args:
        glyphsLib.dump(load(arg), sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1:])
