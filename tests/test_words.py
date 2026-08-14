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

import json

import pytest

from utils.caption import SRTCaption
from utils.srt import SRTEditor


PAYLOAD = {
    "version": 1,
    "words": [
        {"t": "Hej", "s": 0.0, "e": 0.5, "c": 0.99},
        {"t": "på", "s": 0.6, "e": 0.8, "c": 0.15},
        {"t": "dig", "s": 1.0, "e": 1.4, "c": 0.95},
        {"t": "idag", "s": 3.0, "e": 3.6, "c": 0.70},
    ],
}

TEXT = "Hej på dig idag"


@pytest.fixture
def editor():
    """
    An editor with the UI side effects of editing stubbed out.
    """

    editor = SRTEditor("job-uuid", "srt", "file.srt")
    editor.refresh_display = lambda *args, **kwargs: None
    editor.update_words_per_minute = lambda *args, **kwargs: None
    editor.save_state_for_undo = lambda *args, **kwargs: None
    editor.mark_as_changed = lambda *args, **kwargs: None

    return editor


def caption(text: str = TEXT) -> SRTCaption:
    return SRTCaption(1, "00:00:00,000", "00:00:04,000", text)


class TestLoadWords:
    """
    Parsing of the word timing payload.
    """

    def test_loads_payload(self, editor):
        editor.load_words(PAYLOAD)

        assert [word["t"] for word in editor.words] == ["Hej", "på", "dig", "idag"]
        assert editor.has_confidence is True

    def test_loads_json_string(self, editor):
        editor.load_words(json.dumps(PAYLOAD))

        assert len(editor.words) == 4

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "",
            "not json",
            [1, 2, 3],
            {"words": "not a list"},
            {"version": 99, "words": [{"t": "Hej", "s": 0.0, "e": 0.5}]},
            {"version": 1, "words": [{"t": "Hej"}]},
            {"version": 1, "words": [{"s": 0.0, "e": 0.5}]},
        ],
    )
    def test_rejects_unusable_payload(self, editor, payload):
        editor.load_words(payload)

        assert editor.words == []
        assert editor.has_confidence is False

    def test_timings_without_confidence(self, editor):
        editor.load_words({"version": 1, "words": [{"t": "Hej", "s": 0.0, "e": 0.5}]})

        assert len(editor.words) == 1
        assert editor.has_confidence is False
        assert editor.caption_confidence(caption()) is None

    def test_words_are_sorted_by_start_time(self, editor):
        editor.load_words(
            {
                "version": 1,
                "words": [
                    {"t": "b", "s": 1.0, "e": 1.5},
                    {"t": "a", "s": 0.0, "e": 0.5},
                ],
            }
        )

        assert [word["t"] for word in editor.words] == ["a", "b"]


class TestWordLookup:
    """
    Mapping words onto captions by time.
    """

    def test_caption_words(self, editor):
        editor.load_words(PAYLOAD)

        assert [word["t"] for word in editor.caption_words(caption())] == [
            "Hej",
            "på",
            "dig",
            "idag",
        ]

    def test_range_excludes_words_outside_it(self, editor):
        editor.load_words(PAYLOAD)

        assert [word["t"] for word in editor.words_in_range(0.0, 1.0)] == ["Hej", "på"]

    def test_range_is_empty_without_word_data(self, editor):
        assert editor.words_in_range(0.0, 10.0) == []

    def test_caption_confidence_is_the_average(self, editor):
        editor.load_words(PAYLOAD)

        expected = (0.99 + 0.15 + 0.95 + 0.70) / 4

        assert editor.caption_confidence(caption()) == pytest.approx(expected)


class TestSplitAtCursor:
    """
    Splitting a caption where the caret sits.
    """

    def test_splits_text_at_the_cursor(self, editor):
        editor.load_words(PAYLOAD)
        target = caption()
        editor.captions = [target]

        editor.split_caption(target, cursor_position=len("Hej på "), text=TEXT)

        assert [c.text for c in editor.captions] == ["Hej på", "dig idag"]

    def test_uses_the_silence_between_words(self, editor):
        editor.load_words(PAYLOAD)
        target = caption()
        editor.captions = [target]

        editor.split_caption(target, cursor_position=len("Hej på "), text=TEXT)

        first, second = editor.captions

        # "på" ends at 0.8 and "dig" starts at 1.0.
        assert first.get_end_seconds() == pytest.approx(0.9)
        assert first.end_time == second.start_time
        assert second.get_end_seconds() == pytest.approx(4.0)

    def test_keeps_uncommitted_edits(self, editor):
        editor.load_words(PAYLOAD)
        target = caption()
        editor.captions = [target]

        editor.split_caption(target, cursor_position=8, text="Hej PAA dig idag")

        assert [c.text for c in editor.captions] == ["Hej PAA", "dig idag"]

    @pytest.mark.parametrize("position", [0, len(TEXT), 99, -3, None])
    def test_never_produces_an_empty_caption(self, editor, position):
        editor.load_words(PAYLOAD)
        target = caption()
        editor.captions = [target]

        editor.split_caption(target, cursor_position=position, text=TEXT)

        assert all(c.text.strip() for c in editor.captions)

    def test_falls_back_to_proportional_without_word_data(self, editor):
        target = caption()
        editor.captions = [target]

        editor.split_caption(target, cursor_position=len("Hej på "), text=TEXT)

        first = editor.captions[0]

        assert 0.0 < first.get_end_seconds() < 4.0


class TestSplitWithoutCursor:
    """
    The pre-existing split behaviour, which results without word timings and
    callers that pass no caret position still rely on.
    """

    def test_single_line_is_halved(self, editor):
        target = caption()
        editor.captions = [target]

        editor.split_caption(target)

        first, second = editor.captions

        assert (first.text, second.text) == ("Hej på", "dig idag")
        assert first.get_end_seconds() == pytest.approx(2.0)

    def test_multi_line_splits_on_the_line_break(self, editor):
        target = caption("line one\nline two")
        editor.captions = [target]

        editor.split_caption(target)

        assert [c.text for c in editor.captions] == ["line one", "line two"]
        assert editor.captions[0].get_end_seconds() == pytest.approx(2.0)


class TestConfidenceDisplay:
    """
    Confidence markup shown when the toggle is on.
    """

    def test_marks_only_uncertain_words(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_confidence_html(caption())

        assert 'class="confidence-word confidence-low"' in html
        assert 'class="confidence-word confidence-medium"' in html
        assert "confidence-high" not in html

    def test_score_rides_on_a_data_attribute(self, editor):
        """
        The score must not go in title=: a native tooltip cannot be coloured.
        """

        editor.load_words(PAYLOAD)

        html = editor.get_confidence_html(caption())

        assert "title=" not in html
        assert 'data-confidence="Low"' in html
        assert 'data-confidence="Medium"' in html
        assert 'aria-label="Confidence: Low"' in html

    def test_no_raw_score_is_shown(self, editor):
        """
        The score is not a calibrated probability, so it is never surfaced as
        a number anywhere in the caption markup.
        """

        editor.load_words(PAYLOAD)

        html = editor.get_confidence_html(caption())

        assert "%" not in html
        assert "0.15" not in html and "0.7" not in html

    def test_no_markup_when_every_word_is_confident(self, editor):
        editor.load_words(
            {"version": 1, "words": [{"t": "Hej", "s": 0.0, "e": 0.5, "c": 0.99}]}
        )

        assert editor.get_confidence_html(caption("Hej")) is None

    def test_no_markup_without_confidence_scores(self, editor):
        editor.load_words({"version": 1, "words": [{"t": "Hej", "s": 0.0, "e": 0.5}]})

        assert editor.get_confidence_html(caption("Hej")) is None

    def test_escapes_caption_text(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_confidence_html(caption("<b>Hej</b> på dig idag"))

        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_keeps_line_breaks(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_confidence_html(caption("Hej på\ndig idag"))

        assert "<br>" in html

    @pytest.mark.parametrize(
        "score,expected",
        [
            (None, ""),
            (0.10, "confidence-low"),
            (0.50, "confidence-medium"),
            (0.90, "confidence-high"),
        ],
    )
    def test_confidence_class(self, score, expected):
        assert SRTEditor.confidence_class(score) == expected

    @pytest.mark.parametrize(
        "score,expected",
        [(None, ""), (0.10, "low"), (0.50, "medium"), (0.90, "high")],
    )
    def test_confidence_level(self, score, expected):
        assert SRTEditor.confidence_level(score) == expected

    @pytest.mark.parametrize(
        "score,expected",
        [(None, ""), (0.10, "Low"), (0.50, "Medium"), (0.90, "High")],
    )
    def test_confidence_label(self, score, expected):
        assert SRTEditor.confidence_label(score) == expected

    def test_label_follows_the_configured_thresholds(self, monkeypatch):
        """
        The bands are settings, so the label must move with them rather than
        being pinned to the defaults.
        """

        from utils import srt as srt_module

        monkeypatch.setattr(srt_module.settings, "CONFIDENCE_MEDIUM", 0.95)

        assert SRTEditor.confidence_label(0.90) == "Medium"

    def test_chip_and_word_classes_do_not_collide(self):
        """
        The chip must not pick up the inline word markup's underline, so the
        two must never share a class name.
        """

        for score in (0.10, 0.50, 0.90):
            word_class = SRTEditor.confidence_class(score)
            chip_class = f"confidence-chip-{SRTEditor.confidence_level(score)}"

            assert word_class != chip_class
