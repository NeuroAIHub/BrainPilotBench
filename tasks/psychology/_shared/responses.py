"""Parse marked human responses and construct leak-free sequential prefixes.

Markers are literal ``<<`` and ``>>``. Spans use Python's half-open character
offsets in the original string. Response text is preserved exactly; a response
containing only whitespace is considered empty and rejected.
"""

from dataclasses import dataclass
from typing import Iterator


class TranscriptFormatError(ValueError):
    """A transcript has malformed or empty response markers."""


@dataclass(frozen=True)
class ResponseSpan:
    """One response and its half-open offsets in the original transcript."""

    response_id: int
    raw: str
    marker_start: int
    content_start: int
    content_end: int
    marker_end: int


@dataclass(frozen=True)
class ParsedTranscript:
    """A validated transcript retained by the trusted controller.

    Do not hand this object to a model: it contains all answers. Send only the
    string returned by ``prefix_for`` for the current response.
    """

    raw: str
    responses: tuple[ResponseSpan, ...]

    def prefix_for(self, response_id: int) -> str:
        """Return text through the current ``<<``, before its answer.

        Earlier responses and their intervening feedback remain in the prefix.
        The current answer, its closing marker, and all later text are absent.
        """

        if type(response_id) is not int or not 0 <= response_id < len(self.responses):
            raise IndexError(f"unknown response_id: {response_id!r}")
        return self.raw[: self.responses[response_id].content_start]

    def iter_prefixes(self) -> Iterator[tuple[int, str]]:
        """Yield ``(response_id, current_prefix)`` in transcript order."""

        for span in self.responses:
            yield span.response_id, self.prefix_for(span.response_id)


def parse_transcript(raw: str) -> ParsedTranscript:
    """Parse all response markers; reject stray, nested, unclosed or empty ones.

    Ordinary text before, between and after responses is left untouched. A
    transcript with no markers parses successfully but cannot be scored.
    """

    if type(raw) is not str:
        raise TypeError("transcript must be a string")

    responses: list[ResponseSpan] = []
    cursor = 0
    while cursor < len(raw):
        opening = raw.find("<<", cursor)
        closing = raw.find(">>", cursor)

        if closing != -1 and (opening == -1 or closing < opening):
            raise TranscriptFormatError(f"closing marker without opening at offset {closing}")
        if opening == -1:
            break

        content_start = opening + 2
        closing = raw.find(">>", content_start)
        nested = raw.find("<<", content_start)
        if closing == -1:
            raise TranscriptFormatError(f"unclosed response marker at offset {opening}")
        if nested != -1 and nested < closing:
            raise TranscriptFormatError(f"nested response marker at offset {nested}")

        answer = raw[content_start:closing]
        if not answer.strip():
            raise TranscriptFormatError(f"empty response at offset {opening}")
        responses.append(
            ResponseSpan(
                response_id=len(responses),
                raw=answer,
                marker_start=opening,
                content_start=content_start,
                content_end=closing,
                marker_end=closing + 2,
            )
        )
        cursor = closing + 2

    return ParsedTranscript(raw=raw, responses=tuple(responses))
