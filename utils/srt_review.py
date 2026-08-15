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
Word level review: which words the model was unsure of, and which of those
the reader has since confirmed.

Mixed into SRTEditor rather than kept as a separate object, so that call
sites stay `editor.get_review_html(...)`. Everything here reads the editor's
own captions and word list.
"""

import bisect
import json
import re

from difflib import SequenceMatcher
from html import escape as html_escape
from typing import List, Optional

from utils.caption import SRTCaption
from utils.settings import get_settings

settings = get_settings()

# Word timing payload version this editor understands. A wire format constant,
# deliberately not a setting: anything with a different version is treated as
# absent rather than guessed at.
WORDS_FORMAT_VERSION = 1

# How far up the confidence range each sensitivity flags. Words are marked
# identically whichever setting is in force -- the setting decides how many
# are marked, not how alarming any one of them looks. The raw score is never
# surfaced: it is not a calibrated probability, so a number would read as odds
# it cannot back up, and its absolute value shifts between models.
REVIEW_SENSITIVITIES = ("low", "medium", "high")
DEFAULT_REVIEW_SENSITIVITY = "low"

REVIEW_TOOLTIP = "This word may need review"
ACCEPTED_TOOLTIP = "Marked correct \u2014 click to flag it again"

# Where the review preferences live in app.storage.user, so a reload does not
# reset them. Plain values: they are display preferences, not secrets, so they
# do not go through storage_encrypt the way tokens and passwords do.
REVIEW_SHOW_KEY = "srt_show_uncertain_words"
REVIEW_SENSITIVITY_KEY = "srt_review_sensitivity"
AUTOSCROLL_KEY = "srt_autoscroll"


def accepted_words_key(uuid: str) -> str:
    """
    Storage key for the words marked correct in one job.

    Per job rather than global: a word index only means anything against the
    transcription it came from.
    """

    return f"srt_accepted_words_{uuid}"


class ReviewMixin:
    """
    Word level confidence, review marking and the flagged-word counter.
    """

    def load_words(self, payload) -> None:
        """
        Load the per-word timing payload returned by the backend.

        Anything unrecognised is discarded silently: word data is an optional
        enhancement, and an editor that cannot read it must still open the
        transcription normally.
        """

        self.words = []
        self._word_midpoints = []
        self.has_confidence = False

        if not payload:
            return

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                return

        if not isinstance(payload, dict):
            return

        if payload.get("version") != WORDS_FORMAT_VERSION:
            return

        words = payload.get("words")

        if not isinstance(words, list):
            return

        loaded = []

        for word in words:
            if not isinstance(word, dict):
                continue

            text = word.get("t")
            start = word.get("s")
            end = word.get("e")

            if not text or start is None or end is None:
                continue

            try:
                entry = {"t": str(text), "s": float(start), "e": float(end)}
            except (TypeError, ValueError):
                continue

            confidence = word.get("c")

            if confidence is not None:
                try:
                    entry["c"] = float(confidence)
                    self.has_confidence = True
                except (TypeError, ValueError):
                    pass

            loaded.append(entry)

        loaded.sort(key=lambda word: word["s"])

        # Stable identity for each word, used to remember which ones have been
        # marked correct. Position in the caption cannot serve: it shifts the
        # moment a word is inserted.
        for position, word in enumerate(loaded):
            word["i"] = position

        self.words = loaded
        self._word_midpoints = [(word["s"] + word["e"]) / 2 for word in loaded]


    def words_in_range(self, start: float, end: float) -> List[dict]:
        """
        Words spoken inside a time range, matched on their midpoint so a word
        straddling a caption boundary belongs to exactly one caption.
        """

        if not self.words or end < start:
            return []

        first = bisect.bisect_left(self._word_midpoints, start)
        last = bisect.bisect_right(self._word_midpoints, end)

        return self.words[first:last]


    def caption_words(self, caption: SRTCaption) -> List[dict]:
        """
        Words belonging to a caption.
        """

        if not caption:
            return []

        return self.words_in_range(
            caption.get_start_seconds(), caption.get_end_seconds()
        )


    def review_threshold(self) -> float:
        """
        Confidence below which a word is flagged, for the current sensitivity.
        """

        return {
            "low": settings.REVIEW_SENSITIVITY_LOW,
            "medium": settings.REVIEW_SENSITIVITY_MEDIUM,
            "high": settings.REVIEW_SENSITIVITY_HIGH,
        }.get(self.review_sensitivity, settings.REVIEW_SENSITIVITY_LOW)


    def is_flagged(self, score: Optional[float]) -> bool:
        """
        Whether a word scoring this low is worth a second look.
        """

        return score is not None and score < self.review_threshold()


    def word_needs_review(self, word: Optional[dict]) -> bool:
        """
        Whether a word should carry a flag right now.

        A word the user has marked correct never does, however low it scored:
        they have looked at it, which is more than the model can say.
        """

        if not word or "c" not in word:
            return False

        if word.get("i") in self.accepted_words:
            return False

        return self.is_flagged(word["c"])


    def accept_word(self, identity) -> None:
        """
        Mark a word correct, taking its flag away.
        """

        self.accepted_words.add(identity)
        self.after_accepted_change()


    def restore_word(self, identity) -> None:
        """
        Undo marking a word correct, so it can be flagged again.
        """

        self.accepted_words.discard(identity)
        self.after_accepted_change()


    def toggle_word_accepted(self, identity) -> None:
        """
        Flip whether a word is marked correct.
        """

        if identity in self.accepted_words:
            self.restore_word(identity)
        else:
            self.accept_word(identity)


    def restore_accepted_words(self, identities) -> None:
        """
        Load previously marked words, before the first render.

        Anything that is not a word index is dropped rather than trusted, so
        a malformed value cannot silently unflag the wrong word.
        """

        self.accepted_words = {
            identity for identity in (identities or []) if isinstance(identity, int)
        }


    def after_accepted_change(self) -> None:
        """
        Re-render and hand the new set to whoever is persisting it.
        """

        self.refresh_display(force_full_refresh=True)
        self.update_flagged_count()

        if self.on_accepted_change:
            self.on_accepted_change(sorted(self.accepted_words))


    def handle_word_click(self, event) -> None:
        """
        Toggle the word a click landed on. Only fires for marked words: the
        browser-side handler emits nothing for anything else.
        """

        identity = event.args

        if isinstance(identity, (int, float)):
            self.toggle_word_accepted(int(identity))


    def flagged_word_count(self) -> int:
        """
        How many words are flagged across the whole transcription.

        Counts what is actually marked in the captions rather than scanning
        the raw word list, so the number tracks edits: fixing a flagged word
        takes it off the count.
        """

        return sum(
            1
            for caption in self.captions
            for word in self.aligned_words(caption)
            if self.word_needs_review(word)
        )


    def restore_review_state(self, show, sensitivity) -> None:
        """
        Apply persisted review preferences before the first render.

        Assigns rather than going through the setters, which refresh a caption
        list that does not exist yet. A sensitivity that is not recognised is
        ignored, so a value left behind by an older version of the editor
        falls back to the default instead of flagging nothing.
        """

        self.show_uncertain_words = bool(show)

        if sensitivity in REVIEW_SENSITIVITIES:
            self.review_sensitivity = sensitivity


    def set_show_uncertain_words(self, show: bool) -> None:
        """
        Toggle the review marking on the caption list.
        """

        self.show_uncertain_words = bool(show)
        self.refresh_display(force_full_refresh=True)
        self.update_flagged_count()


    def set_review_sensitivity(self, sensitivity: str) -> None:
        """
        Choose how far up the confidence range to flag words.
        """

        if sensitivity not in REVIEW_SENSITIVITIES:
            return

        self.review_sensitivity = sensitivity

        if self.show_uncertain_words:
            self.refresh_display(force_full_refresh=True)

        self.update_flagged_count()


    def set_flagged_count_element(self, element) -> None:
        """
        Register the label that reports how many words are flagged.
        """

        self.flagged_count_element = element
        self.update_flagged_count()


    def update_flagged_count(self) -> None:
        """
        Refresh the flagged-word counter.
        """

        if self.flagged_count_element is None:
            return

        count = self.flagged_word_count() if self.show_uncertain_words else 0

        self.flagged_count_element.set_text(f"{count} flagged")


    @staticmethod
    def match_key(text: str) -> str:
        """
        Normalised form used to decide whether a token is still the word the
        model transcribed. Case and surrounding punctuation are ignored, so
        recasing a word or adding a comma does not discard its score.
        """

        return re.sub(r"^\W+|\W+$", "", text).casefold()


    def aligned_words(
        self, caption: SRTCaption, text: Optional[str] = None
    ) -> List[Optional[dict]]:
        """
        The transcribed word behind each word of a caption, in order.

        The caption text is aligned against the words the model actually
        transcribed, rather than paired off by position. Position alone breaks
        as soon as the text is edited: replacing a word would keep the entry
        that belonged to the old one, and inserting a word would shift every
        entry after it onto the wrong word.

        A token that no longer matches the word it came from returns None --
        it has no timing or confidence we can honestly attribute to it.

        Pass text to align something other than what the caption currently
        holds, such as the uncommitted value of an open text area.
        """

        source = caption.text if text is None else text
        tokens = [token for token in re.split(r"\s+", source) if token]
        aligned: List[Optional[dict]] = [None] * len(tokens)
        words = self.caption_words(caption)

        if not words or not tokens:
            return aligned

        # autojunk would treat repeated words as noise in long captions and
        # silently drop them from the alignment.
        matcher = SequenceMatcher(
            None,
            [self.match_key(token) for token in tokens],
            [self.match_key(word["t"]) for word in words],
            autojunk=False,
        )

        for tag, token_start, token_end, word_start, _ in matcher.get_opcodes():
            if tag != "equal":
                continue

            for offset in range(token_end - token_start):
                aligned[token_start + offset] = words[word_start + offset]

        return aligned


    def get_review_html(
        self, caption: SRTCaption, text: Optional[str] = None
    ) -> Optional[str]:
        """
        Caption text with the words worth reviewing marked up.

        Words already marked correct are rendered quietly rather than dropped
        entirely, so the mark can be taken back. Returns None when the caption
        has nothing to show either way.
        """

        source = caption.text if text is None else text
        words = self.aligned_words(caption, source)

        if not words:
            return None

        # Keep the separators so line breaks and spacing survive the round trip.
        tokens = re.split(r"(\s+)", source)
        marked = False
        parts = []
        index = 0

        for token in tokens:
            if not token.strip():
                parts.append(html_escape(token).replace("\n", "<br>"))
                continue

            word = words[index] if index < len(words) else None
            index += 1

            if self.word_needs_review(word):
                label, style = REVIEW_TOOLTIP, "review-word"
            elif word is not None and word.get("i") in self.accepted_words:
                label, style = ACCEPTED_TOOLTIP, "review-accepted"
            else:
                parts.append(html_escape(token))
                continue

            marked = True

            # data-word carries the word identity for the click handler. One
            # marking and one message per flagged word: the score behind it is
            # not precise enough to grade them against each other. The text
            # rides on a data attribute rather than title= so the tooltip is a
            # CSS box we can style; aria-label keeps it reachable for screen
            # readers.
            parts.append(
                f'<span class="{style}" data-word="{word.get("i")}" '
                f'data-review="{label}" '
                f'aria-label="{label}">{html_escape(token)}</span>'
            )

        return "".join(parts) if marked else None


    def review_backdrop_html(self, caption: SRTCaption, text: str) -> str:
        """
        Markup for the highlight layer behind an open text area.

        Always returns markup, even with nothing flagged: the layer has to
        mirror the text area character for character or the highlight boxes
        drift off their words.
        """

        markup = None

        if self.show_uncertain_words:
            markup = self.get_review_html(caption, text)

        if markup is None:
            markup = html_escape(text).replace("\n", "<br>")

        # A trailing newline opens no line box, so without this the layer comes
        # up one line short of the text area.
        return f"{markup}<br>" if text.endswith("\n") else markup

    def attach_word_clicks(self, element) -> None:
        """
        Let a click on a marked word toggle whether it is correct.

        The words live inside one block of raw HTML, so the click is handled
        by delegation. The browser-side handler emits nothing unless the click
        landed on a marked word, which keeps ordinary clicks off the wire.
        """

        element.on(
            "click",
            self.handle_word_click,
            js_handler=(
                "(e) => { const word = e.target.closest('[data-word]');"
                " if (word) { emit(Number(word.dataset.word)); } }"
            ),
        )
