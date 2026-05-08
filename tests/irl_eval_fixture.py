"""IRL ("in real life") eval fixture.

This corpus mimics what kayo's user actually has in PAM: a working engineer's
mid-month memory state. Bug investigation threads (with corrected diagnoses
that hit SUPERSEDES), code review notes, an architecture RFC + decision,
debugging sessions, personal opinions about tooling, stream-of-consciousness
notes, mentoring context, and a few random items.

Queries are intentionally messy:
- `vague` — under-specified ("the throughput thing", "what was that auth thing")
- `casual` — lowercase / fragment-style
- `typo` — misspelled tokens
- `multihop_2` / `multihop_3` / `multihop_4` — chained reasoning across
  entity / relation / time / preference axes
- `wrong_premise` — false assumption baked into the question
- `demanding` — multi-part questions that require synthesis
- `time_relative` — "last week", "the day before X"
- `out_of_blue` — random topics that happen to be in the corpus
- `partial_id` — PR number or filename mentioned without context
- `negative` — out-of-fixture topics that should return NO_ANSWER
- `colloquial_relationship` — role/relationship questions (manager, mentee,
  reviewer, collaborator) where the corpus expresses the relationship in
  colloquial language (`"1:1 with Anya"`, `"requesting Anya for review"`,
  `"Mentoring assignment: Diego"`) instead of the keyword the user types.
  Each query has zero or near-zero FTS recall on the expected answer today;
  a future hybrid retriever (embeddings + write-time cue rules) is the
  intended unlock. Includes both directions — `"who's my manager"` and the
  reverse-direction `"who reports to me"` (expects empty, since the user
  has no direct reports in this corpus) — to catch retrievers that confuse
  edge direction.
- `paraphrase` — answer note uses different vocabulary than the question
  (`"the lock granularity debate"` for notes about `"global mutex"` /
  `"per-key locks"`). Tests semantic-recall headroom that FTS alone leaves
  on the table.
- `time_vague` — qualitative time references (`"last month"`,
  `"earlier this spring"`, `"around easter time"`) rather than the
  parser-friendly relative times in `time_relative`. Tests whether
  retrieval can connect a fuzzy time framing to the right window of notes.
- `entity_by_role` — note names the person, query asks by role
  (`"the engineer who came from a Java background"` → Diego). Inverse of
  the `colloquial_relationship` shape: the colloquial axis is on the
  description-of-the-person, not the relationship-to-the-user.

Unlike the templated `hard` and `large` suites, every query here is
hand-written and unique. The point is to expose how PAM behaves under
realistic mess, not to measure consistency across many similar shapes.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).parent / "fixtures" / "irl_eval_corpus.json"


@lru_cache(maxsize=1)
def load_irl_eval_fixture() -> dict:
    with CORPUS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


__all__ = ["load_irl_eval_fixture"]
