"""Tokenisation and BM25 for the knowledge base.

Deliberately **not** the model's tokenizer. BM25 is the stage that has to work
when no model is loaded at all -- that is the whole point of the fallback in the
degradation design -- and reaching for ``tokenizers``/``tokenizer.json`` would
make keyword search depend on the embedding model being present. So this is a
small, fixed, dependency-free scheme:

* a run of CJK characters becomes overlapping **bigrams** (a single-character run
  stays one token), because Chinese has no spaces and a unigram index retrieves
  on single characters that carry almost no meaning;
* a run of Latin letters/digits becomes one **lowercased word**;
* everything else is a separator.

No stemming and no stop words: a demo whose ranking an operator is inspecting
must be explainable by reading the text, and every removed word is one more
thing they cannot see. The cost is a slightly noisier ranking than a tuned
English pipeline, which is the right trade for this app.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

#: One token: a run of CJK ideographs, or a run of Latin letters/digits.
#: ``unicodedata`` is not used for classification below 0x2E80 because Python's
#: own ``str.isalpha`` already covers accented Latin; the CJK ranges are listed
#: explicitly since their exact boundaries decide the bigrams.
_TOKEN = re.compile(
    r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]+"
    r"|[0-9a-zA-Z]+"
)

#: BM25's own constants, per the design.
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    """The index terms of ``text``, in order, with repeats kept for term frequency.

    Order matters only for the query path (which never uses frequencies), but
    keeping it makes a test failure readable.
    """
    out: list[str] = []
    for match in _TOKEN.finditer(unicodedata.normalize("NFKC", text or "")):
        run = match.group(0)
        if run[0].isascii():
            out.append(run.lower())
        elif len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


@dataclass
class Bm25Index:
    """An in-memory BM25 index over one knowledge base's chunks.

    Rebuilt from ``chunks.jsonl`` whenever the chunk set changes. The cost is one
    pass over the texts (a library at the 20000-chunk cap is ~8 MB of text, tens
    of milliseconds), which is cheaper and far less error-prone than maintaining
    an incremental structure across the several ways chunks change (upload,
    retry, delete, reindex).
    """

    chunk_ids: list[str] = field(default_factory=list)
    #: Per-document term frequencies, aligned with ``chunk_ids``.
    term_freqs: list[dict[str, int]] = field(default_factory=list)
    #: Length of each chunk in tokens, same alignment.
    lengths: list[int] = field(default_factory=list)
    #: Inverse document frequency, computed once at build time.
    idf: dict[str, float] = field(default_factory=dict)
    avg_length: float = 0.0

    @classmethod
    def build(cls, chunks: list[dict]) -> "Bm25Index":
        index = cls()
        df: dict[str, int] = {}
        for chunk in chunks:
            terms = tokenize(chunk.get("text") or "")
            counts: dict[str, int] = {}
            for term in terms:
                counts[term] = counts.get(term, 0) + 1
            index.chunk_ids.append(chunk.get("id") or "")
            index.term_freqs.append(counts)
            index.lengths.append(len(terms))
            for term in counts:
                df[term] = df.get(term, 0) + 1
        total = len(index.chunk_ids)
        index.avg_length = (sum(index.lengths) / total) if total else 0.0
        # Lucene's IDF, with the +0.5 smoothing that keeps a term appearing in
        # every document from scoring zero (and thus from being silently
        # unrankable rather than merely uninformative).
        index.idf = {
            term: math.log(1.0 + (total - n + 0.5) / (n + 0.5))
            for term, n in df.items()
        }
        return index

    def __len__(self) -> int:
        return len(self.chunk_ids)

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """The top ``limit`` ``(chunk_id, score)`` pairs, best first.

        Only documents that share at least one term with the query are scored: a
        zero-scoring document is indistinguishable from an absent one, and
        returning it would fill the result list with noise that then has to be
        filtered by every caller.
        """
        terms = tokenize(query)
        if not terms or not self.chunk_ids:
            return []
        # Distinct terms only: a repeated query term must not multiply its own
        # weight, which would make "盘点 盘点" rank differently from "盘点".
        unique = list(dict.fromkeys(terms))
        scores: dict[int, float] = {}
        avg = self.avg_length or 1.0
        for term in unique:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, counts in enumerate(self.term_freqs):
                tf = counts.get(term)
                if not tf:
                    continue
                norm = K1 * (1.0 - B + B * (self.lengths[i] / avg))
                scores[i] = scores.get(i, 0.0) + idf * (tf * (K1 + 1.0)) / (tf + norm)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(self.chunk_ids[i], score) for i, score in ranked[:limit]]
