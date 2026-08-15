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
import re

import pytest

from utils.caption import SRTCaption
from utils.srt import DEFAULT_REVIEW_SENSITIVITY, SRTEditor


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
        assert editor.flagged_word_count() == 0

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

    def test_caption_words_carry_their_scores(self, editor):
        editor.load_words(PAYLOAD)

        assert [word["c"] for word in editor.caption_words(caption())] == [
            0.99,
            0.15,
            0.95,
            0.70,
        ]


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


class TestReviewMarking:
    """
    Marking of words worth reviewing, and the flagged counter.
    """

    def test_low_sensitivity_flags_only_the_least_confident(self, editor):
        editor.load_words(PAYLOAD)
        editor.captions = [caption()]

        assert editor.review_sensitivity == "low"
        # Only "på" at 0.15 sits below the low threshold of 0.25.
        assert editor.flagged_word_count() == 1

    def test_raising_sensitivity_flags_strictly_more(self, editor):
        editor.load_words(PAYLOAD)
        editor.captions = [caption()]

        counts = []

        for sensitivity in ("low", "medium", "high"):
            editor.set_review_sensitivity(sensitivity)
            counts.append(editor.flagged_word_count())

        assert counts == sorted(counts), counts
        assert counts[0] < counts[-1], "high must flag more than low"

    def test_unknown_sensitivity_is_ignored(self, editor):
        editor.load_words(PAYLOAD)

        editor.set_review_sensitivity("nonsense")

        assert editor.review_sensitivity == "low"

    def test_marks_flagged_words_only(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_review_html(caption())

        # "på" (0.15) is flagged at low sensitivity; the rest are not.
        assert html.count('class="review-word"') == 1
        assert ">på<" in html

    def test_every_marking_is_identical(self, editor):
        """
        The score is not precise enough to grade flagged words against each
        other, so they must all look and read the same.
        """

        editor.load_words(PAYLOAD)
        editor.set_review_sensitivity("high")

        html = editor.get_review_html(caption())
        markings = re.findall(r'<span class="([^"]*)"', html)

        assert len(markings) > 1
        assert set(markings) == {"review-word"}
        assert html.count("This word may need review") == 2 * len(markings)

    def test_no_marking_when_nothing_is_flagged(self, editor):
        editor.load_words(
            {"version": 1, "words": [{"t": "Hej", "s": 0.0, "e": 0.5, "c": 0.99}]}
        )

        assert editor.get_review_html(caption("Hej")) is None

    def test_no_marking_without_confidence_scores(self, editor):
        editor.load_words({"version": 1, "words": [{"t": "Hej", "s": 0.0, "e": 0.5}]})

        assert editor.get_review_html(caption("Hej")) is None
        assert editor.flagged_word_count() == 0

    def test_shared_tooltip_carries_no_score(self, editor):
        """
        One message for every flagged word, and never a raw number.
        """

        editor.load_words(PAYLOAD)

        html = editor.get_review_html(caption())

        assert "title=" not in html
        assert 'data-review="This word may need review"' in html
        assert 'aria-label="This word may need review"' in html
        assert "%" not in html
        assert "0.15" not in html

    def test_escapes_caption_text(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_review_html(caption("Hej på <b>dig</b> idag"))

        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_keeps_line_breaks(self, editor):
        editor.load_words(PAYLOAD)

        html = editor.get_review_html(caption("Hej på\ndig idag"))

        assert "<br>" in html

    def test_counter_reports_zero_while_switched_off(self, editor):
        editor.load_words(PAYLOAD)

        class Label:
            text = None

            def set_text(self, value):
                self.text = value

        editor.captions = [caption()]
        label = Label()
        editor.set_flagged_count_element(label)

        assert label.text == "0 flagged", "off by default, so nothing is flagged"

        editor.set_show_uncertain_words(True)

        assert label.text == "1 flagged"

        editor.set_show_uncertain_words(False)

        assert label.text == "0 flagged"

    def test_counter_follows_sensitivity(self, editor):
        editor.load_words(PAYLOAD)

        class Label:
            text = None

            def set_text(self, value):
                self.text = value

        editor.captions = [caption()]
        label = Label()
        editor.set_flagged_count_element(label)
        editor.set_show_uncertain_words(True)
        editor.set_review_sensitivity("high")

        assert label.text == f"{editor.flagged_word_count()} flagged"


class TestPersistedReviewState:
    """
    Review preferences survive a reload via app.storage.user.
    """

    def test_restores_both_preferences(self, editor):
        editor.restore_review_state(True, "high")

        assert editor.show_uncertain_words is True
        assert editor.review_sensitivity == "high"

    @pytest.mark.parametrize("stored", ["", None, "HIGH", "medium ", 3, "nonsense"])
    def test_unrecognised_sensitivity_falls_back_to_the_default(self, editor, stored):
        """
        A value left by an older editor must not silently flag nothing.
        """

        editor.restore_review_state(True, stored)

        assert editor.review_sensitivity == DEFAULT_REVIEW_SENSITIVITY

    @pytest.mark.parametrize("stored", [None, "", 0, "no"])
    def test_show_flag_is_coerced(self, editor, stored):
        editor.restore_review_state(stored, "low")

        assert editor.show_uncertain_words is bool(stored)

    def test_restoring_does_not_touch_the_caption_list(self, editor):
        """
        Runs before the first render, so it must not refresh anything.
        """

        def explode(*args, **kwargs):
            raise AssertionError("restore must not refresh the display")

        editor.refresh_display = explode

        editor.restore_review_state(True, "high")

    def test_restored_state_drives_the_markup(self, editor):
        editor.load_words(PAYLOAD)
        editor.captions = [caption()]
        editor.restore_review_state(True, "high")

        html = editor.get_review_html(caption())

        assert html is not None
        assert html.count('class="review-word"') == editor.flagged_word_count()


class TestMarkingSurvivesEditing:
    """
    The marking must describe the text on screen, not the text the model
    originally produced. Both cases here were reported as bugs.
    """

    def marked(self, editor, text):
        """Words actually marked in a caption, in order."""
        html = editor.get_review_html(caption(text))

        return re.findall(r'aria-label="[^"]*">([^<]*)</span>', html or "")

    def test_editing_a_flagged_word_clears_its_score(self, editor):
        """
        "på" is flagged; replacing it must not leave the flag on whatever the
        user typed instead -- that score described a different word.
        """

        editor.load_words(PAYLOAD)

        assert self.marked(editor, TEXT) == ["på"]
        assert self.marked(editor, "Hej två dig idag") == []

    def test_inserting_a_word_does_not_shift_the_marking(self, editor):
        """
        Inserting a word must not push the flag onto its neighbour.
        """

        editor.load_words(PAYLOAD)

        # "på" stays flagged; the inserted word takes no flag of its own.
        assert self.marked(editor, "Hej på nytt dig idag") == ["på"]
        assert self.marked(editor, "helt Hej på dig idag") == ["på"]

    def test_deleting_a_word_keeps_the_rest_aligned(self, editor):
        editor.load_words(PAYLOAD)

        assert self.marked(editor, "Hej på idag") == ["på"]

    def test_recasing_and_punctuation_keep_the_score(self, editor):
        """
        Only the word itself decides the match, so tidying punctuation or
        capitalisation must not silently drop a flag.
        """

        editor.load_words(PAYLOAD)

        assert self.marked(editor, "Hej På, dig idag") == ["På,"]

    def test_rewriting_the_caption_entirely_flags_nothing(self, editor):
        editor.load_words(PAYLOAD)

        assert self.marked(editor, "helt annan text här") == []

    def test_count_drops_when_a_flagged_word_is_fixed(self, editor):
        editor.load_words(PAYLOAD)
        editor.captions = [caption(TEXT)]

        assert editor.flagged_word_count() == 1

        editor.captions = [caption("Hej två dig idag")]

        assert editor.flagged_word_count() == 0

    def test_repeated_words_stay_aligned(self, editor):
        """
        SequenceMatcher's autojunk heuristic drops frequently repeated
        elements; it must stay off or repeated words lose their scores.
        """

        editor.load_words(
            {
                "version": 1,
                "words": [
                    {"t": "ja", "s": i * 0.01, "e": i * 0.01 + 0.005, "c": 0.10}
                    for i in range(300)
                ],
            }
        )

        text = " ".join(["ja"] * 300)
        words = editor.aligned_words(caption(text))

        assert all(word and word["c"] == 0.10 for word in words), (
            "alignment dropped words"
        )


class TestPersistedAutoscroll:
    """
    Autoscroll survives a reload, like the review preferences.
    """

    @pytest.mark.parametrize("stored", [True, False])
    def test_restores_the_stored_value(self, editor, stored):
        editor.set_autoscroll(stored)

        assert editor.autoscroll is stored

    @pytest.mark.parametrize("stored", [None, "", 0, 1, "yes"])
    def test_coerces_whatever_was_stored(self, editor, stored):
        """
        The value arrives straight from storage, so it may be any JSON type.
        """

        editor.set_autoscroll(stored)

        assert editor.autoscroll is bool(stored)


class TestReviewBackdrop:
    """
    The highlight layer painted behind an open caption text area.
    """

    def test_mirrors_the_text_exactly(self, editor):
        """
        The layer has to hold the same characters as the text area, or the
        highlight boxes drift off their words.
        """

        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True

        html = editor.review_backdrop_html(caption(), TEXT)
        stripped = re.sub(r"<[^>]+>", "", html)

        assert stripped == TEXT

    def test_marks_the_flagged_word(self, editor):
        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True

        assert 'class="review-word"' in editor.review_backdrop_html(caption(), TEXT)

    def test_returns_markup_even_with_nothing_flagged(self, editor):
        """
        get_review_html returns None when nothing is marked; the layer cannot,
        or it would stop mirroring the text area.
        """

        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True

        assert editor.review_backdrop_html(caption(), "helt annan text") != ""
        assert editor.get_review_html(caption(), "helt annan text") is None

    def test_returns_markup_with_the_toggle_off(self, editor):
        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = False

        html = editor.review_backdrop_html(caption(), TEXT)

        assert "review-word" not in html
        assert re.sub(r"<[^>]+>", "", html) == TEXT

    def test_tracks_uncommitted_text(self, editor):
        """
        Typing repaints the layer from the live value, before the caption has
        been updated.
        """

        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True
        target = caption()

        assert "review-word" in editor.review_backdrop_html(target, TEXT)
        # Same caption object, but the word has been typed over.
        assert "review-word" not in editor.review_backdrop_html(
            target, "Hej TVÅ dig idag"
        )

    def test_escapes_the_text(self, editor):
        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True

        html = editor.review_backdrop_html(caption(), "Hej <b>på</b> dig")

        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_trailing_newline_keeps_a_line_box(self, editor):
        """
        A text area shows an empty last line for a trailing newline; without
        this the layer is one line short and every box below shifts up.
        """

        editor.load_words(PAYLOAD)
        editor.show_uncertain_words = True

        assert editor.review_backdrop_html(caption(), "Hej\n").endswith("<br>")
