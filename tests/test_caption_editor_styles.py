# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
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

"""
The highlight layer sits behind the caption text area and has to line up with
it character for character. That is a property of the stylesheet, so it is
guarded here: the failure mode is a silent visual one that no behavioural test
would catch.
"""

import re

import pytest

from utils.styles import default_styles


def rules():
    """Every rule in the stylesheet, as (selectors, declarations)."""

    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", default_styles):
        selectors = [
            re.sub(r"^.*\*/\s*", "", part.strip(), flags=re.S)
            for part in match.group(1).split(",")
            if part.strip()
        ]
        yield selectors, match.group(2)


def effective(selector: str) -> dict:
    """
    Properties a selector ends up with, after later rules of equal weight have
    overridden earlier ones. Several rules name the same selector, so reading
    only the first would misjudge what the browser applies.
    """

    applied = {}
    found = False

    for selectors, declarations in rules():
        if selector not in selectors:
            continue
        found = True
        for declaration in declarations.split(";"):
            if ":" not in declaration:
                continue
            prop, _, value = declaration.partition(":")
            applied[prop.strip()] = value.strip()

    assert found, f"no rule for {selector!r}"

    return applied


class TestSharedTextMetrics:
    """
    Anything that decides where a character lands must be set on both layers
    by the same rule, never inherited.
    """

    @pytest.mark.parametrize(
        "prop",
        ["font-size", "line-height", "letter-spacing", "padding",
         "white-space", "overflow-wrap"],
    )
    def test_metric_is_shared_by_both_layers(self, prop):
        shared = re.search(
            r"\.caption-highlights,\s*\.caption-editor \.caption-entry "
            r"\.q-field__native \{([^}]*)\}",
            default_styles,
        )

        assert shared, "the two layers no longer share one metrics rule"
        assert prop in shared.group(1), f"{prop} is not shared, so it can drift"


class TestMarkedWordsAreLayoutNeutral:
    """
    A marked word in the layer may only paint. Anything that takes up space
    widens it and pushes the rest of the line out of step with the text area;
    anything that gives it a colour draws the word a second time under the one
    the reader is typing.
    """

    def test_read_view_styling_is_neutralised(self):
        applied = effective(".caption-highlights .review-word")

        assert applied["color"] == "transparent"
        assert applied["padding"] == "0"
        assert applied["border"] == "0"

    def test_flag_paints_with_background_and_shadow_only(self):
        """
        Background and inset shadow are the only visible properties that cost
        no space.
        """

        applied = effective(".caption-highlights .review-word")

        assert applied["background-color"] == "var(--color-review-bg)"
        assert applied["box-shadow"].startswith("inset")
        # Whatever else it sets must not take up space.
        assert applied["padding"] == "0"
        assert applied["border"] == "0"
        assert "font-size" not in applied
        assert "margin" not in applied

    def test_layer_hides_its_text(self):
        assert effective(".caption-highlights")["color"] == "transparent"

    def test_no_tooltip_behind_the_text_area(self):
        assert effective(".caption-highlights .review-word::after")["content"] == "none"
