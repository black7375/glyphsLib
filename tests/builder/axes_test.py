#
# Copyright 2016 Google Inc. All Rights Reserved.
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

from copy import deepcopy
import os.path

import pytest

from fontTools import designspaceLib
from glyphsLib import to_glyphs, to_designspace, to_ufos
from glyphsLib.classes import GSFont, GSFontMaster, GSAxis, GSInstance
from glyphsLib.builder.axes import _is_subset_of_default_axes, get_regular_master

"""
Goal: check how files with custom axes are roundtripped.
"""


@pytest.mark.parametrize(
    "axes",
    [
        [("wght", "Weight alone")],
        [("wdth", "Width alone")],
        [("XXXX", "Custom alone")],
        [("wght", "Weight (with width)"), ("wdth", "Width (with weight)")],
        [
            ("wght", "Weight (1/3 default)"),
            ("wdth", "Width (2/3 default)"),
            ("XXXX", "Custom (3/3 default)"),
        ],
        [("ABCD", "First custom"), ("EFGH", "Second custom")],
        [
            ("ABCD", "First custom"),
            ("EFGH", "Second custom"),
            ("IJKL", "Third custom"),
            ("MNOP", "Fourth custom"),
        ],
        [("opsz", "First custom"), ("wght", "Second custom")],
        # Test that standard axis definitions don't generate an Axes custom parameter.
        [("wght", "Weight"), ("wdth", "Width")],
        [("wdth", "Width"), ("wght", "Weight")],
    ],
)
def test_weight_width_custom(axes, ufo_module):
    """Test that having axes in any order or quantity does not confuse
    glyphsLib, even when the weight or width are not in the default positions.
    """
    doc = _make_designspace_with_axes(axes, ufo_module)

    font = to_glyphs(doc)

    if _is_subset_of_default_axes([GSAxis(name=n, tag=t) for t, n in axes]):
        assert font.customParameters["Axes"] is None
    else:
        assert font.customParameters["Axes"] == [
            {"Tag": tag, "Name": name} for tag, name in axes
        ]

    doc = to_designspace(font, ufo_module=ufo_module)

    assert len(doc.axes) == len(axes)
    for doc_axis, (tag, name) in zip(doc.axes, axes):
        assert doc_axis.tag == tag
        assert doc_axis.name == name


def _make_designspace_with_axes(axes, ufo_module):
    doc = designspaceLib.DesignSpaceDocument()

    # Add a "Regular" source
    regular = doc.newSourceDescriptor()
    regular.font = ufo_module.Font()
    regular.location = {name: 0 for _, name in axes}
    doc.addSource(regular)

    for tag, name in axes:
        axis = doc.newAxisDescriptor()
        axis.tag = tag
        axis.name = name
        axis.minimum = 0
        axis.default = 0
        axis.maximum = 100
        doc.addAxis(axis)

        extreme = doc.newSourceDescriptor()
        extreme.font = ufo_module.Font()
        extreme.location = {name_: 0 if name_ != name else 100 for _, name_ in axes}
        doc.addSource(extreme)

    return doc


def test_masters_have_user_locations(ufo_module):
    """Test the new axis definition with custom parameters.
    See https://github.com/googlefonts/glyphsLib/issues/280.

    For tests about the previous system with weight/width/custom,
    see `tests/builder/interpolation_test.py`.
    """
    # Get a font with two masters
    font = to_glyphs([ufo_module.Font(), ufo_module.Font()])
    font.customParameters["Axes"] = [{"Tag": "opsz", "Name": "Optical"}]
    # There is only one axis, so the design location is stored in the weight
    font.masters[0].weightValue = 0
    # The user location is stored as a custom parameter
    font.masters[0].customParameters["Axis Location"] = [
        {"Axis": "Optical", "Location": 13}
    ]
    font.masters[1].weightValue = 1000
    font.masters[1].customParameters["Axis Location"] = [
        {"Axis": "Optical", "Location": 100}
    ]

    doc = to_designspace(font, ufo_module=ufo_module)
    assert len(doc.axes) == 1
    assert doc.axes[0].map == [(13, 0), (100, 1000)]
    assert len(doc.sources) == 2
    assert doc.sources[0].location == {"Optical": 0}
    assert doc.sources[1].location == {"Optical": 1000}

    font = to_glyphs(doc)
    assert font.customParameters["Axes"] == [{"Tag": "opsz", "Name": "Optical"}]
    assert font.masters[0].weightValue == 0
    assert font.masters[0].customParameters["Axis Location"] == [
        {"Axis": "Optical", "Location": 13}
    ]
    assert font.masters[1].weightValue == 1000
    assert font.masters[1].customParameters["Axis Location"] == [
        {"Axis": "Optical", "Location": 100}
    ]


def test_masters_have_user_locations_string(ufo_module):
    """Test that stringified Axis Locations are converted.

    Some versions of Glyph store a string instead of an int.
    """
    font = to_glyphs([ufo_module.Font(), ufo_module.Font()])
    font.customParameters["Axes"] = [{"Tag": "opsz", "Name": "Optical"}]
    font.masters[0].weightValue = 0
    font.masters[0].customParameters["Axis Location"] = [
        {"Axis": "Optical", "Location": 13}
    ]
    font.masters[1].weightValue = 1000
    font.masters[1].customParameters["Axis Location"] = [
        {"Axis": "Optical", "Location": "100"}
    ]

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].map == [(13, 0), (100, 1000)]

    font = to_glyphs(doc)
    assert font.masters[0].customParameters["Axis Location"] == [
        {"Axis": "Optical", "Location": 13}
    ]
    assert font.masters[1].customParameters["Axis Location"] == [
        {"Axis": "Optical", "Location": 100}
    ]


def test_master_user_location_goes_into_os2_classes(ufo_module):
    font = to_glyphs([ufo_module.Font(), ufo_module.Font()])
    font.customParameters["Axes"] = [
        {"Tag": "wght", "Name": "Weight"},
        {"Tag": "wdth", "Name": "Width"},
    ]
    font.masters[0].weightValue = 0
    font.masters[0].widthValue = 1000
    # This master will be Light Expanded
    # as per https://docs.microsoft.com/en-gb/typography/opentype/spec/os2#uswidthclass
    font.masters[0].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 300},
        {"Axis": "Width", "Location": 125},
    ]
    font.masters[1].weightValue = 1000
    font.masters[1].widthValue = 0
    # This master is Black Ultra-condensed but not quite
    font.masters[1].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 920},  # instead of 900
        {"Axis": "Width", "Location": 55},  # instead of 50
    ]

    light, black = to_ufos(font)

    assert light.info.openTypeOS2WeightClass == 300
    assert light.info.openTypeOS2WidthClass == 7

    assert black.info.openTypeOS2WeightClass == 920
    assert black.info.openTypeOS2WidthClass == 1


def test_mapping_is_same_regardless_of_axes_custom_parameter(ufo_module):
    # https://github.com/googlefonts/glyphsLib/issues/409
    # https://github.com/googlefonts/glyphsLib/issues/411

    # First, try without the custom param
    font = to_glyphs([ufo_module.Font(), ufo_module.Font(), ufo_module.Font()])
    font.masters[0].name = "ExtraLight"
    font.masters[0].weightValue = 200
    font.masters[1].name = "Regular"
    font.masters[1].weightValue = 400
    font.masters[2].name = "Bold"
    font.masters[2].weightValue = 700

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].minimum == 200
    assert doc.axes[0].maximum == 700
    assert doc.axes[0].map == []

    # Now with the custom parameter. Should produce the same results
    font.customParameters["Axes"] = [{"Name": "Weight", "Tag": "wght"}]

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].minimum == 200
    assert doc.axes[0].maximum == 700
    assert doc.axes[0].map == []


def test_mapping_using_axis_location_custom_parameter_on_instances(ufo_module):
    # https://github.com/googlefonts/glyphsLib/issues/714
    # https://github.com/googlefonts/glyphsLib/pull/810

    font = to_glyphs(
        [ufo_module.Font(), ufo_module.Font(), ufo_module.Font(), ufo_module.Font()]
    )

    origin_id = "95FB0C11-C828-4064-8966-34220AA4D426"
    font.customParameters["Axes"] = [
        {"Name": "Weight", "Tag": "wght"},
        {"Name": "Width", "Tag": "wdth"},
    ]

    # Add masters

    font.masters[0].name = "Regular"
    font.masters[0].id = origin_id
    font.masters[0].weightValue = 72
    font.masters[0].widthValue = 448
    font.masters[0].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[1].name = "Bold"
    font.masters[1].weightValue = 112
    font.masters[1].widthValue = 448
    font.masters[1].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 700},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[2].name = "Thin"
    font.masters[2].weightValue = 48
    font.masters[2].widthValue = 448
    font.masters[2].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 200},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[3].name = "Cd Regular"
    font.masters[3].weightValue = 72
    font.masters[3].widthValue = 224
    font.masters[3].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 50},
    ]

    font.customParameters["Variable Font Origin"] = origin_id

    # Add some instances with mappings

    font.instances = [
        GSInstance(),
        GSInstance(),
        GSInstance(),
        GSInstance(),
        GSInstance(),
        GSInstance(),
    ]

    font.instances[0].name = "Thin"
    font.instances[0].weightValue = 48
    font.instances[0].widthValue = 448
    font.instances[0].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 200},
        {"Axis": "Width", "Location": 100},
    ]
    font.instances[1].name = "Light"
    font.instances[1].weightValue = 62
    font.instances[1].widthValue = 448
    font.instances[1].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 300},
        {"Axis": "Width", "Location": 100},
    ]
    font.instances[2].name = "Regular"
    font.instances[2].weightValue = 72
    font.instances[2].widthValue = 448
    font.instances[2].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 100},
    ]
    font.instances[3].name = "Medium"
    font.instances[3].weightValue = 92
    font.instances[3].widthValue = 448
    font.instances[3].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 600},
        {"Axis": "Width", "Location": 100},
    ]
    font.instances[4].name = "Cd Regular"
    font.instances[4].weightValue = 72
    font.instances[4].widthValue = 224
    font.instances[4].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 50},
    ]
    font.instances[5].name = "SCd Regular"
    font.instances[5].weightValue = 72
    font.instances[5].widthValue = 384
    font.instances[5].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 60},
    ]

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].minimum == 200
    assert doc.axes[0].default == 400
    assert doc.axes[0].maximum == 700
    assert doc.axes[0].map == [(200, 48), (300, 62), (400, 72), (600, 92), (700, 112)]

    assert doc.axes[1].minimum == 50
    assert doc.axes[1].default == 100
    assert doc.axes[1].maximum == 100
    assert doc.axes[1].map == [(50, 224), (60, 384), (100, 448)]


def test_mapping_using_axis_location_cp_on_masters_none(ufo_module):
    # https://github.com/googlefonts/glyphsLib/issues/714
    # https://github.com/googlefonts/glyphsLib/pull/810

    # When masters have no or disabled Axis Location CP, the ones on the
    # instances should still be evaluated.

    font = to_glyphs(
        [ufo_module.Font(), ufo_module.Font(), ufo_module.Font(), ufo_module.Font()]
    )

    font.customParameters["Axes"] = [
        {"Name": "Weight", "Tag": "wght"},
        {"Name": "Width", "Tag": "wdth"},
    ]

    # Add masters

    font.masters[0].name = "Regular"
    font.masters[0].weightValue = 72
    font.masters[0].widthValue = 448

    font.masters[1].name = "Bold"
    font.masters[1].weightValue = 112
    font.masters[1].widthValue = 448

    font.masters[2].name = "Thin"
    font.masters[2].weightValue = 48
    font.masters[2].widthValue = 448

    font.masters[3].name = "Cd Regular"
    font.masters[3].weightValue = 72
    font.masters[3].widthValue = 224

    font.instances = [GSInstance(), GSInstance(), GSInstance()]

    font.instances[0].name = "Regular"
    font.instances[0].weightValue = 72
    font.instances[0].widthValue = 448
    font.instances[0].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 100},
    ]
    font.instances[1].name = "SCd Regular"
    font.instances[1].weightValue = 72
    font.instances[1].widthValue = 384
    font.instances[1].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 60},
    ]
    font.instances[2].name = "Cd Regular"
    font.instances[2].weightValue = 72
    font.instances[2].widthValue = 224
    font.instances[2].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 50},
    ]

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].minimum == 400
    assert doc.axes[0].default == 400
    assert doc.axes[0].maximum == 400
    assert doc.axes[0].map == [(400, 72)]

    assert doc.axes[1].minimum == 50
    assert doc.axes[1].default == 100
    assert doc.axes[1].maximum == 100
    assert doc.axes[1].map == [(50, 224), (60, 384), (100, 448)]


def test_mapping_using_axis_location_cp_on_instances_none(ufo_module):
    # https://github.com/googlefonts/glyphsLib/issues/714
    # https://github.com/googlefonts/glyphsLib/pull/810

    # When all masters have Axis Location CP, non-"Axis Location" instance
    # mappings should be ignored.

    font = to_glyphs(
        [ufo_module.Font(), ufo_module.Font(), ufo_module.Font(), ufo_module.Font()]
    )

    font.customParameters["Axes"] = [
        {"Name": "Weight", "Tag": "wght"},
        {"Name": "Width", "Tag": "wdth"},
    ]

    # Add masters

    font.masters[0].name = "Regular"
    font.masters[0].weightValue = 72
    font.masters[0].widthValue = 448
    font.masters[0].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[1].name = "Bold"
    font.masters[1].weightValue = 112
    font.masters[1].widthValue = 448
    font.masters[1].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 700},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[2].name = "Thin"
    font.masters[2].weightValue = 48
    font.masters[2].widthValue = 448
    font.masters[2].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 200},
        {"Axis": "Width", "Location": 100},
    ]
    font.masters[3].name = "Cd Regular"
    font.masters[3].weightValue = 72
    font.masters[3].widthValue = 224
    font.masters[3].customParameters["Axis Location"] = [
        {"Axis": "Weight", "Location": 400},
        {"Axis": "Width", "Location": 50},
    ]

    font.instances = [GSInstance()]

    font.instances[0].name = "SCd Regular"
    font.instances[0].weightValue = 72
    font.instances[0].widthValue = 384

    doc = to_designspace(font, ufo_module=ufo_module)
    assert doc.axes[0].minimum == 200
    assert doc.axes[0].default == 400
    assert doc.axes[0].maximum == 700
    assert doc.axes[0].map == [(200, 48), (400, 72), (700, 112)]

    assert doc.axes[1].minimum == 50
    assert doc.axes[1].default == 100
    assert doc.axes[1].maximum == 100
    assert doc.axes[1].map == [(50, 224), (100, 448)]


def test_custom_parameter_vfo_current():
    """Tests get_regular_master when 'Variable Font Origin' custom parameter name
    is used with master set to 'Regular Text'.  This is the current default
    custom parameter name in the Glyphs editor / glyphs source file specification."""
    source_path = os.path.join("tests", "data", "CustomParameterVFO.glyphs")
    font = GSFont(source_path)
    assert font.customParameters["Variation Font Origin"] is None
    test_id = font.customParameters["Variable Font Origin"]
    assert test_id == "ACC63F3E-1323-486A-94AF-B18797A154CE"
    matched = False
    for master in font.masters:
        if master.id == test_id:
            assert master.name == "Regular Text"
            matched = True
    assert matched is True
    default_master = get_regular_master(font)
    assert default_master.name == "Regular Text"


def test_custom_parameter_vfo_old_name():
    """Tests get_regular_master when 'Variation Font Origin' custom parameter name
    is used with master set to 'Regular Text'.  This custom parameter name is not
    used in current releases of the Glyphs editor / glyphs source file specification."""
    source_path = os.path.join("tests", "data", "CustomParameterVFO.glyphs")
    font = GSFont(source_path)

    # mock up source for this test with a source file from another test
    del font.customParameters["Variable Font Origin"]
    font.customParameters["Variation Font Origin"] = "Regular Text"
    assert font.customParameters["Variable Font Origin"] is None
    # start tests
    test_name = font.customParameters["Variation Font Origin"]
    matched = False
    for master in font.masters:
        if master.name == test_name:
            matched = True
    assert matched is True
    default_master = get_regular_master(font)
    assert default_master.name == "Regular Text"


def test_custom_parameter_vfo_not_set():
    """Tests default behavior of get_regular_master when Variable Font Origin custom
    parameter is not set"""
    source_path = os.path.join("tests", "data", "CustomParameterVFO.glyphs")
    font = GSFont(source_path)

    # mock up source for this test with a source file from another test
    del font.customParameters["Variable Font Origin"]
    del font.customParameters["Variation Font Origin"]
    assert font.customParameters["Variable Font Origin"] is None
    assert font.customParameters["Variation Font Origin"] is None
    default_master = get_regular_master(font)
    assert default_master.name == "Regular Text"


def test_wheres_ma_axis(datadir):
    font1 = GSFont(datadir.join("AxesWdth.glyphs"))
    doc1 = to_designspace(font1)
    assert [a.tag for a in doc1.axes] == ["wdth"]


def test_wheres_ma_axis2(datadir):
    font2 = GSFont(datadir.join("AxesWdthWght.glyphs"))
    doc2 = to_designspace(font2)
    assert [a.tag for a in doc2.axes] == ["wdth", "wght"]


def test_single_master_default_weight_400(ufo_module):
    font = GSFont()
    master = GSFontMaster()
    master.weightValue = 400
    font.masters.append(master)

    doc = to_designspace(font, ufo_module=ufo_module)

    assert len(doc.axes) == 1
    assert doc.axes[0].name == "Weight"
    assert doc.axes[0].minimum == 400
    assert doc.axes[0].default == 400
    assert doc.axes[0].maximum == 400
    assert len(doc.sources) == 1
    assert doc.sources[0].location["Weight"] == 400

    font2 = to_glyphs(doc)

    assert len(font2.masters) == 1
    assert font2.masters[0].weightValue == 400


def test_axis_mapping(ufo_module):
    font = to_glyphs(
        [ufo_module.Font(), ufo_module.Font(), ufo_module.Font(), ufo_module.Font()]
    )
    font.masters[0].weightValue = 0
    font.masters[0].widthValue = 100
    font.masters[1].weightValue = 1000
    font.masters[1].widthValue = 100

    font.masters[2].weightValue = 0
    font.masters[2].widthValue = 75
    font.masters[3].weightValue = 1000
    font.masters[3].widthValue = 75

    wght_mapping = [(100, 0), (400, 350), (900, 1000)]
    wdth_mapping = [(75, 75), (100, 100)]

    axis_mappings = {
        "wght": {str(float(k)): v for k, v in wght_mapping},
        "wdth": {str(float(k)): v for k, v in wdth_mapping},
    }

    font.customParameters["Axis Mappings"] = axis_mappings
    # When we convert to a designspace, the wdth mapping is removed because
    # it isn't needed.
    doc = to_designspace(font, ufo_module=ufo_module)

    assert doc.axes[0].name == "Weight"
    assert doc.axes[0].minimum == 100
    assert doc.axes[0].default == 100
    assert doc.axes[0].maximum == 900
    assert doc.axes[0].map == wght_mapping

    assert doc.axes[1].name == "Width"
    assert doc.axes[1].minimum == 75
    assert doc.axes[0].default == 100
    assert doc.axes[1].maximum == 100
    assert doc.axes[1].map != wdth_mapping
    assert doc.axes[1].map == []

    font = to_glyphs(doc)
    assert font.customParameters["Axis Mappings"] == axis_mappings


def test_axis_with_no_mapping_does_not_error_in_roundtrip(ufo_module):
    """Tests that a custom axis without a mapping and without sources on its
    extremes does not generate an error during roundtrip. Also tests that
    during a to_glyphs, to_designspace roundtrip the min and max axis
    information is not lost.
    """
    doc = designspaceLib.DesignSpaceDocument()

    # Add a "Regular" source
    regular = doc.newSourceDescriptor()
    regular.font = ufo_module.Font()
    regular.location = {"Style": 0}
    doc.addSource(regular)

    axis = doc.newAxisDescriptor()
    axis.tag = "styl"
    axis.name = "Style"
    doc.addAxis(axis)

    # This axis spans a range of 0 to 1 but only has a source at {"Style": 0}
    # and no explicit mapping. The point of this test is to see if the min and
    # max are still the same after round tripping.
    doc.axes[0].minimum = 0
    doc.axes[0].maximum = 1
    doc.axes[0].default = 0
    doc.axes[0].map = []

    doc2 = deepcopy(doc)
    font = to_glyphs(doc2)
    doc_rt = to_designspace(font)

    assert doc_rt.axes[0].serialize() == doc.axes[0].serialize()


def test_axis_with_no_mapping_does_not_error_in_roundtrip_with_2_axes(ufo_module):
    """Tests that a designspace with 2 axis, one with a mapping and one
    without a mapping, roundtrips correctly without error. The axis without a
    mapping should generate an identity mapping on the fly so that the
    Glyphs.app customParameter field does not lose min/max infromation about
    the axis.
    """
    doc = _make_designspace_with_axes(
        [("wght", "Weight with mapping"), ("wdth", "Width without mapping")], ufo_module
    )
    # Add mapping to weight axis
    doc.axes[0].map = [(0, 0), (50, 350), (100, 1000)]

    doc2 = deepcopy(doc)
    font = to_glyphs(doc2)
    doc_rt = to_designspace(font)

    assert doc_rt.axes[0].serialize() == doc.axes[0].serialize()
    assert doc_rt.axes[1].serialize() == doc.axes[1].serialize()


def test_variable_instance(ufo_module):
    """Glyphs 3 introduced a "variable" instance which is a special instance
    that holds various VF settings. We export it to Design Space variable-font.
    """
    source_path = os.path.join("tests", "data", "VariableInstance.glyphs")
    font = GSFont(source_path)
    assert len(font.instances) == 28  # Including the VF setting
    doc = to_designspace(font)

    assert doc.axes[0].map[2] == (400, 80)
    assert doc.axes[0].default == 400
    assert len(doc.instances) == 27  # The VF setting should not be in the DS

    assert len(doc.variableFonts) == 1

    varfont = doc.variableFonts[0]
    assert varfont.name == "Variable Foo Bar"
    assert varfont.filename == "Cairo-VariableFooBarVF"
    assert len(varfont.axisSubsets) == len(doc.axes)
    assert "public.fontInfo" in varfont.lib

    info = varfont.lib["public.fontInfo"]
    assert len(info.get("openTypeNameRecords")) == 1
    assert info["openTypeNameRecords"][0].string == "Variable"
    assert info["openTypeNameRecords"][0].nameID == 1
    assert info["openTypeNameRecords"][0].platformID == 1
    assert info["openTypeNameRecords"][0].languageID == 0
    assert info["openTypeNameRecords"][0].encodingID == 0
    assert info.get("openTypeNamePreferredFamilyName") == "Cairo Variable"


def test_virtual_masters_extend_min_max_for_unmapped_axis(ufo_module, datadir):
    # https://github.com/googlefonts/glyphsLib/issues/859
    font = GSFont(datadir.join("IntermediateLayer.glyphs"))
    assert ["Cap Height", "Weight"] == [a.name for a in font.axes]

    assert "Axis Mappings" not in font.customParameters
    for master in font.masters:
        assert "Axis Location" not in master.customParameters
        # all non-virtual masters are at the default Cap Height location
        assert master.axes[0] == 700

    virtual_masters = [
        cp.value for cp in font.customParameters if cp.name == "Virtual Master"
    ]
    assert virtual_masters[0] == [
        {"Axis": "Cap Height", "Location": 600},
        {"Axis": "Weight", "Location": 400},
    ]
    assert virtual_masters[1] == [
        {"Axis": "Cap Height", "Location": 800},
        {"Axis": "Weight", "Location": 400},
    ]

    ds = to_designspace(font, ufo_module=ufo_module)

    # the min/max for this axis are taken from the virtual masters
    assert ds.axes[0].name == "Cap Height"
    assert ds.axes[0].minimum == 600
    assert ds.axes[0].default == 700
    assert ds.axes[0].maximum == 800
    assert not ds.axes[0].map

    assert ds.axes[1].name == "Weight"
    assert ds.axes[1].minimum == 400
    assert ds.axes[1].default == 400
    assert ds.axes[1].maximum == 900
    assert not ds.axes[1].map

    font2 = to_glyphs(ds)

    assert [
        cp.value for cp in font2.customParameters if cp.name == "Virtual Master"
    ] == virtual_masters
