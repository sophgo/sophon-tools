// Byte-level BPE tokenizer. See tokenizer.h for why this exists.
//
// The pieces that must match the reference implementation exactly:
//
//  * NFC. The normalizer in tokenizer.json is {"type":"NFC"}: text is
//    decomposed canonically, reordered by combining class, then recomposed.
//    unicode_tables.h carries the data.
//  * The pre-tokenizer regex. It is applied with behavior "Isolated", i.e. the
//    matched text is its own piece and everything between matches is another
//    piece. Writing it as an explicit left-to-right matcher (pretok_match)
//    keeps the semantics obvious; the pattern is the fixed one shipped with
//    Qwen models, not user input.
//  * BPE merge order. tokenizers ranks merges by their position in the file;
//    where two merges tie on rank the leftmost wins, and a merged pair is not
//    reconsidered within the same pass.
//  * added_tokens. Matched literally on the *raw* text before anything else,
//    longest content first, so <|im_end|> is one id and never BPE'd.

#include "tokenizer.h"

#include <algorithm>
#include <climits>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

#include "json_lite.h"
#include "unicode_tables.h"

namespace cv84x6 {
namespace {

// -- Unicode helpers --------------------------------------------------------

bool in_ranges(uint32_t cp, const uni::Range* rs, size_t n) {
  size_t lo = 0, hi = n;
  while (lo < hi) {
    size_t mid = (lo + hi) / 2;
    if (cp < rs[mid].lo) {
      hi = mid;
    } else if (cp > rs[mid].hi) {
      lo = mid + 1;
    } else {
      return true;
    }
  }
  return false;
}

bool is_letter(uint32_t cp) { return in_ranges(cp, uni::kLetters, uni::kLetters_count); }
bool is_mark(uint32_t cp) { return in_ranges(cp, uni::kMarks, uni::kMarks_count); }
bool is_number(uint32_t cp) { return in_ranges(cp, uni::kNumbers, uni::kNumbers_count); }

// \p{L} or \p{M}: the second character class in the Qwen pre-tokenizer regex.
bool is_letter_or_mark(uint32_t cp) { return is_letter(cp) || is_mark(cp); }

// Whitespace as the regex engine sees it: Rust regex's \s is Unicode White_Space.
bool is_space(uint32_t cp) {
  switch (cp) {
    case 0x09: case 0x0A: case 0x0B: case 0x0C: case 0x0D: case 0x20:
    case 0x85: case 0xA0: case 0x1680:
    case 0x2000: case 0x2001: case 0x2002: case 0x2003: case 0x2004:
    case 0x2005: case 0x2006: case 0x2007: case 0x2008: case 0x2009:
    case 0x200A: case 0x2028: case 0x2029: case 0x202F: case 0x205F:
    case 0x3000:
      return true;
    default:
      return false;
  }
}

bool is_cr(uint32_t cp) { return cp == '\r'; }
bool is_lf(uint32_t cp) { return cp == '\n'; }

// -- UTF-8 ----------------------------------------------------------------

// Decodes one code point at index `*i`, advancing it. Invalid bytes decode as
// themselves so the caller never loops forever and byte-level BPE still sees
// every raw byte.
uint32_t utf8_next(const std::string& s, size_t* i) {
  const unsigned char c = static_cast<unsigned char>(s[*i]);
  auto cont = [&](size_t k) -> bool {
    return *i + k < s.size() &&
           (static_cast<unsigned char>(s[*i + k]) & 0xC0) == 0x80;
  };
  if (c < 0x80) {
    ++*i;
    return c;
  }
  if ((c & 0xE0) == 0xC0 && cont(1)) {
    const uint32_t cp = ((c & 0x1Fu) << 6) |
                        (static_cast<unsigned char>(s[*i + 1]) & 0x3Fu);
    *i += 2;
    return cp;
  }
  if ((c & 0xF0) == 0xE0 && cont(1) && cont(2)) {
    const uint32_t cp = ((c & 0x0Fu) << 12) |
                        ((static_cast<unsigned char>(s[*i + 1]) & 0x3Fu) << 6) |
                        (static_cast<unsigned char>(s[*i + 2]) & 0x3Fu);
    *i += 3;
    return cp;
  }
  if ((c & 0xF8) == 0xF0 && cont(1) && cont(2) && cont(3)) {
    const uint32_t cp = ((c & 0x07u) << 18) |
                        ((static_cast<unsigned char>(s[*i + 1]) & 0x3Fu) << 12) |
                        ((static_cast<unsigned char>(s[*i + 2]) & 0x3Fu) << 6) |
                        (static_cast<unsigned char>(s[*i + 3]) & 0x3Fu);
    *i += 4;
    return cp;
  }
  ++*i;
  return c;
}

void utf8_append(std::string* out, uint32_t cp) {
  if (cp < 0x80) {
    out->push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    out->push_back(static_cast<char>(0xC0 | (cp >> 6)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    out->push_back(static_cast<char>(0xE0 | (cp >> 12)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    out->push_back(static_cast<char>(0xF0 | (cp >> 18)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
}

bool is_ascii(const std::string& s) {
  for (char c : s) {
    if (static_cast<unsigned char>(c) >= 0x80) return false;
  }
  return true;
}

// -- Unicode data lookups -------------------------------------------------

uint8_t combining_class(uint32_t cp) {
  size_t lo = 0, hi = uni::kCcc_count;
  while (lo < hi) {
    const size_t mid = (lo + hi) / 2;
    if (uni::kCcc[mid].cp < cp) {
      lo = mid + 1;
    } else if (uni::kCcc[mid].cp > cp) {
      hi = mid;
    } else {
      return uni::kCcc[mid].value;
    }
  }
  return 0;
}

const uni::Decomp* decomposition(uint32_t cp) {
  size_t lo = 0, hi = uni::kDecomp_count;
  while (lo < hi) {
    const size_t mid = (lo + hi) / 2;
    if (uni::kDecomp[mid].cp < cp) {
      lo = mid + 1;
    } else if (uni::kDecomp[mid].cp > cp) {
      hi = mid;
    } else {
      return &uni::kDecomp[mid];
    }
  }
  return nullptr;
}

bool compose_pair(uint32_t a, uint32_t b, uint32_t* out) {
  size_t lo = 0, hi = uni::kCompose_count;
  while (lo < hi) {
    const size_t mid = (lo + hi) / 2;
    const uni::Compose& c = uni::kCompose[mid];
    if (c.first < a || (c.first == a && c.second < b)) {
      lo = mid + 1;
    } else if (c.first > a || (c.first == a && c.second > b)) {
      hi = mid;
    } else {
      *out = c.composite;
      return true;
    }
  }
  return false;
}

// NFC (Unicode 16, section 3.11): decompose fully, canonical-order, recompose.
// unicode_tables.h stores already-recursively-expanded decompositions, so one
// pass expands every character.
std::string nfc(const std::string& text) {
  if (is_ascii(text)) return text;  // already NFC, and the common case

  // 1. Full canonical decomposition.
  std::vector<uint32_t> cps;
  cps.reserve(text.size());
  for (size_t i = 0; i < text.size();) {
    const uint32_t cp = utf8_next(text, &i);
    const uni::Decomp* d = decomposition(cp);
    if (d == nullptr) {
      cps.push_back(cp);
    } else {
      for (uint8_t k = 0; k < d->n; ++k) cps.push_back(d->parts[k]);
    }
  }

  // 2. Canonical ordering: stably sort each run of non-starters by class.
  for (size_t i = 0; i < cps.size();) {
    if (combining_class(cps[i]) == 0) {
      ++i;
      continue;
    }
    size_t j = i;
    while (j < cps.size() && combining_class(cps[j]) != 0) ++j;
    std::stable_sort(cps.begin() + static_cast<long>(i),
                     cps.begin() + static_cast<long>(j),
                     [](uint32_t a, uint32_t b) {
                       return combining_class(a) < combining_class(b);
                     });
    i = j;
  }

  // 3. Canonical composition, honouring the blocking rule.
  std::vector<uint32_t> out;
  out.reserve(cps.size());
  if (cps.empty()) return std::string();
  out.push_back(cps[0]);
  size_t starter = 0;
  bool have_starter = combining_class(cps[0]) == 0;
  uint8_t prev_class = 0;  // class of the last character appended after `starter`
  for (size_t i = 1; i < cps.size(); ++i) {
    const uint32_t cp = cps[i];
    const uint8_t cls = combining_class(cp);
    if (have_starter && (prev_class < cls || prev_class == 0)) {
      uint32_t composite = 0;
      if (compose_pair(out[starter], cp, &composite)) {
        out[starter] = composite;
        continue;
      }
    }
    if (cls == 0) {
      starter = out.size();
      have_starter = true;
      prev_class = 0;
    } else {
      prev_class = cls;
    }
    out.push_back(cp);
  }

  std::string res;
  res.reserve(text.size());
  for (uint32_t cp : out) utf8_append(&res, cp);
  return res;
}

// PaddleOCR-VL-1.5's pre-tokenizer is nothing like Qwen's:
//
//   normalizer      Sequence[ Replace(" ", "▁") ]     (the metaspace)
//   pre_tokenizer   null -- there is no regex at all
//   model           BPE with byte_fallback, over the ▁-marked text
//   decoder         Sequence[ Replace("▁", " "), ByteFallback, Fuse ]
//
// So text is *not* split before BPE; the whole normalised run is one BPE
// input, and a character the vocabulary cannot build is emitted as its
// <0xXX> byte tokens. Both differences change ids, so the flavour is a fact
// read from the file, not a switch an operator picks.
//
// The check below is deliberately narrow: exactly the Qwen normalizer (NFC) or
// exactly this Replace, and any other normalizer is refused. A guessed
// normalizer would change ids silently, which is how a tokenizer bug reaches
// the board.
enum class Flavour { kQwenNfc, kMetaspaceReplace };

// -- The Qwen pre-tokenizer regex -----------------------------------------
//
// (?i:'s|'t|'re|'ve|'m|'ll|'d)
//   | [^\r\n\p{L}\p{M}\p{N}]?[\p{L}\p{M}]+
//   | \p{N}
//   | \ ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*
//   | \s*[\r\n]+
//   | \s+(?!\S)
//   | \s+
//
// `at`/`off` walk a UTF-8 string by code point; the alternations are tried in
// the order the pattern lists them, and the first that matches at the current
// position wins, which is what a backtracking-free regex engine does here.

// True for POSIX-ish whitespace as Rust regex defines \s (Unicode White_Space)
// -- is_space above.

struct Cp {
  uint32_t cp;
  size_t next;  // byte offset just past this code point
};

// Code point at `off`, or {none, off} at end of string.
Cp cp_at(const std::string& s, size_t off) {
  if (off >= s.size()) return Cp{0xFFFFFFFFu, off};
  size_t i = off;
  const uint32_t cp = utf8_next(s, &i);
  return Cp{cp, i};
}

constexpr uint32_t kNone = 0xFFFFFFFFu;

// Case-insensitive ASCII compare at `i`.
bool match_ci(const std::string& s, size_t i, const char* lit) {
  const size_t n = std::strlen(lit);
  if (i + n > s.size()) return false;
  for (size_t k = 0; k < n; ++k) {
    char a = s[i + k];
    char b = lit[k];
    if (a >= 'A' && a <= 'Z') a = static_cast<char>(a - 'A' + 'a');
    if (b >= 'A' && b <= 'Z') b = static_cast<char>(b - 'A' + 'a');
    if (a != b) return false;
  }
  return true;
}

// End offset of a run of code points satisfying `pred`, starting at `off`.
template <typename Pred>
size_t run_end(const std::string& s, size_t off, Pred pred) {
  size_t i = off;
  while (true) {
    const Cp c = cp_at(s, i);
    if (c.cp == kNone || !pred(c.cp)) return i;
    i = c.next;
  }
}

bool pretok_match(const std::string& s, size_t start, size_t* end) {
  // 1. (?i:'s|'t|'re|'ve|'m|'ll|'d)
  if (cp_at(s, start).cp == '\'') {
    // No alternative here is a prefix of another in a way that matters ('l vs
    // 'll, 'r vs 're, 'v vs 've): try the longer first and fall back, which is
    // what a leftmost-first engine ends up doing.
    for (const char* lit : {"'re", "'ve", "'ll"}) {
      if (match_ci(s, start, lit)) {
        *end = start + 3;
        return true;
      }
    }
    for (const char* lit : {"'s", "'t", "'m", "'d"}) {
      if (match_ci(s, start, lit)) {
        *end = start + 2;
        return true;
      }
    }
  }

  // 2. [^\r\n\p{L}\p{M}\p{N}]?[\p{L}\p{M}]+
  {
    const Cp first = cp_at(s, start);
    const bool eligible =
        first.cp != kNone && !is_cr(first.cp) && !is_lf(first.cp) &&
        !is_letter_or_mark(first.cp) && !is_number(first.cp);
    if (eligible) {
      const Cp after = cp_at(s, first.next);
      if (after.cp != kNone && is_letter_or_mark(after.cp)) {
        *end = run_end(s, first.next, is_letter_or_mark);
        return true;
      }
    }
    if (first.cp != kNone && is_letter_or_mark(first.cp)) {
      *end = run_end(s, start, is_letter_or_mark);
      return true;
    }
  }

  // 3. \p{N}  (exactly one number)
  {
    const Cp c = cp_at(s, start);
    if (c.cp != kNone && is_number(c.cp)) {
      *end = c.next;
      return true;
    }
  }

  // 4. \ ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*
  {
    size_t i = start;
    if (cp_at(s, i).cp == ' ') i = cp_at(s, i).next;
    const size_t punct_end = run_end(s, i, [](uint32_t cp) {
      return !is_space(cp) && !is_letter_or_mark(cp) && !is_number(cp);
    });
    if (punct_end > i) {
      *end = run_end(s, punct_end, [](uint32_t cp) { return is_cr(cp) || is_lf(cp); });
      return true;
    }
  }

  // 5. \s*[\r\n]+ : greedy space run, then backtrack to the last CR/LF in it.
  {
    const size_t space_end = run_end(s, start, is_space);
    size_t last_crlf = 0;
    for (size_t k = start; k < space_end;) {
      const Cp c = cp_at(s, k);
      if (is_cr(c.cp) || is_lf(c.cp)) last_crlf = c.next;
      k = c.next;
    }
    if (last_crlf != 0) {
      *end = run_end(s, last_crlf, [](uint32_t cp) { return is_cr(cp) || is_lf(cp); });
      return true;
    }
  }

  // 6. \s+(?!\S) : \s+ greedy, then the lookahead may not see a non-space.
  //    When the whole space run is followed by a non-space the lookahead fails
  //    and the engine backtracks one character at a time; dropping the last
  //    space folds it into the next match, which always begins by consuming
  //    exactly that space (that is why every following piece starts with "Ġ").
  {
    std::vector<size_t> ends;
    for (size_t k = start; k < s.size(); k = cp_at(s, k).next) {
      if (!is_space(cp_at(s, k).cp)) break;
      ends.push_back(cp_at(s, k).next);
    }
    if (!ends.empty()) {
      const size_t after_all = ends.back();
      const Cp after = cp_at(s, after_all);
      if (after.cp == kNone || is_space(after.cp)) {
        *end = after_all;
        return true;
      }
      if (ends.size() >= 2) {
        *end = ends[ends.size() - 2];
        return true;
      }
    }
  }

  // 7. \s+
  {
    const size_t space_end = run_end(s, start, is_space);
    if (space_end > start) {
      *end = space_end;
      return true;
    }
  }

  return false;
}

// -- ByteLevel ------------------------------------------------------------

// The GPT-2 byte-to-code-point map. The 188 printable bytes stand for
// themselves; the remaining 68 are moved up to code points 256.. so that every
// raw byte has a visible, non-control stand-in. Those high stand-ins are real
// code points, not bytes: " " becomes U+0120 ("Ġ"), two UTF-8 bytes. Everything
// downstream works on code points, so the map is by code point in both
// directions.
constexpr int kByteLevelHigh = 256;

struct ByteLevelMap {
  // raw byte -> code point
  uint32_t to_cp[256];
  // code point -> raw byte, or -1. Indexed by code point up to 0x200, which
  // covers the low ASCII/punctuation range and the 68 high stand-ins.
  int32_t to_byte[kByteLevelHigh + 68];

  ByteLevelMap() {
    for (int i = 0; i < kByteLevelHigh + 68; ++i) to_byte[i] = -1;
    int n = 0;
    for (int b = 0; b < 256; ++b) {
      const bool printable = (b >= 0x21 && b <= 0x7E) || (b >= 0xA1 && b <= 0xAC) ||
                             (b >= 0xAE && b <= 0xFF);
      const uint32_t cp = printable ? static_cast<uint32_t>(b)
                                    : static_cast<uint32_t>(kByteLevelHigh + n);
      to_cp[b] = cp;
      if (!printable) ++n;
      to_byte[cp] = b;
    }
  }
};

const ByteLevelMap& byte_level_map() {
  static const ByteLevelMap m;
  return m;
}

// Maps raw bytes to their stand-in code points, UTF-8 encoded. The result is
// the string the vocabulary is keyed by, so a piece is a run of code points,
// each one a potential token on its own.
std::string byte_level_encode(const std::string& raw) {
  const ByteLevelMap& m = byte_level_map();
  std::string out;
  out.reserve(raw.size() + raw.size() / 4);
  for (unsigned char c : raw) utf8_append(&out, m.to_cp[c]);
  return out;
}

int32_t id_of(const std::unordered_map<std::string, int32_t>& m, const std::string& s) {
  const auto it = m.find(s);
  return it == m.end() ? -1 : it->second;
}

}  // namespace

std::unique_ptr<Tokenizer> Tokenizer::from_file(const std::string& path, std::string* err) {
  std::ifstream f(path, std::ios::binary);
  if (!f) {
    if (err) *err = "cannot open " + path;
    return nullptr;
  }
  std::ostringstream ss;
  ss << f.rdbuf();
  return from_json(ss.str(), err);
}

std::unique_ptr<Tokenizer> Tokenizer::from_json(const std::string& json, std::string* err) {
  json::Value root;
  std::string jerr;
  if (!json::parse(json, &root, &jerr)) {
    if (err) *err = "tokenizer.json: " + jerr;
    return nullptr;
  }
  if (!root.is_object()) {
    if (err) *err = "tokenizer.json: root is not an object";
    return nullptr;
  }

  // Two normalizers are understood, one per model family, and nothing else:
  // a guessed normalizer would change ids silently.
  //
  //   {"type":"NFC"}                     Qwen3.5 / Qwen3.6
  //   Replace(" ", "▁")             PaddleOCR-VL (sentencepiece metaspace),
  //                                      written either on its own or wrapped in
  //                                      a one-element Sequence
  //
  // Anything else is refused rather than approximated.
  auto is_metaspace_replace = [](const json::Value* n) -> bool {
    if (n == nullptr || n->get_string("type") != "Replace") return false;
    const json::Value* pattern = n->get("pattern");
    const std::string pattern_str =
        pattern ? pattern->get_string("String") : std::string();
    return pattern_str == " " && n->get_string("content") == "\xE2\x96\x81";
  };

  const json::Value* norm = root.get("normalizer");
  const std::string norm_type = norm ? norm->get_string("type") : "";
  Flavour flavour = Flavour::kQwenNfc;
  if (norm_type == "NFC") {
    flavour = Flavour::kQwenNfc;
  } else if (is_metaspace_replace(norm)) {
    flavour = Flavour::kMetaspaceReplace;
  } else if (norm_type == "Sequence") {
    const json::Value* inner = norm->get_array("normalizers");
    if (inner == nullptr || inner->array().size() != 1 ||
        !is_metaspace_replace(&inner->array()[0])) {
      if (err) *err = "tokenizer.json: unsupported Sequence normalizer";
      return nullptr;
    }
    flavour = Flavour::kMetaspaceReplace;
  } else {
    if (err) *err = "tokenizer.json: unsupported normalizer '" + norm_type + "'";
    return nullptr;
  }

  const json::Value* model = root.get("model");
  if (model == nullptr || !model->is_object()) {
    if (err) *err = "tokenizer.json: no model";
    return nullptr;
  }
  if (model->get_string("type") != "BPE") {
    if (err) *err = "tokenizer.json: unsupported model type '" +
                    model->get_string("type") + "'";
    return nullptr;
  }

  auto tok = std::unique_ptr<Tokenizer>(new Tokenizer());

  const json::Value* vocab = model->get("vocab");
  if (vocab == nullptr || !vocab->is_object()) {
    if (err) *err = "tokenizer.json: no vocab";
    return nullptr;
  }
  int32_t max_id = -1;
  tok->token_to_id_.reserve(vocab->members().size() * 2);
  for (const auto& m : vocab->members()) {
    const int32_t id = static_cast<int32_t>(m.second.integer());
    tok->token_to_id_[m.first] = id;
    if (id > max_id) max_id = id;
  }

  const json::Value* merges = model->get_array("merges");
  if (merges == nullptr) {
    if (err) *err = "tokenizer.json: no merges";
    return nullptr;
  }

  tok->id_to_token_.assign(static_cast<size_t>(max_id) + 1, std::string());
  for (const auto& m : tok->token_to_id_) {
    if (m.second >= 0) tok->id_to_token_[static_cast<size_t>(m.second)] = m.first;
  }

  // merges: ["a b", ...] (older) or [["a","b"], ...] (newer).
  tok->merges_.reserve(merges->array().size() * 2);
  int32_t rank = 0;
  for (const auto& m : merges->array()) {
    std::string left, right;
    if (m.is_string()) {
      const std::string& s = m.str();
      const size_t sp = s.find(' ');
      if (sp == std::string::npos) {
        if (err) *err = "tokenizer.json: malformed merge '" + s + "'";
        return nullptr;
      }
      left = s.substr(0, sp);
      right = s.substr(sp + 1);
    } else if (m.is_array() && m.array().size() == 2) {
      left = m.array()[0].str();
      right = m.array()[1].str();
    } else {
      if (err) *err = "tokenizer.json: malformed merge entry";
      return nullptr;
    }
    const int32_t li = id_of(tok->token_to_id_, left);
    const int32_t ri = id_of(tok->token_to_id_, right);
    if (li < 0 || ri < 0) {
      ++rank;  // a merge whose halves are missing can never fire
      continue;
    }
    const int32_t merged = id_of(tok->token_to_id_, left + right);
    if (merged < 0) {
      ++rank;
      continue;
    }
    tok->merges_[Tokenizer::merge_key(li, ri)] = Merge{merged, rank};
    ++rank;
  }

  // added_tokens: literal matches, longest content first (as the reference
  // sorts them so a longer special token wins over a shorter prefix). They are
  // vocabulary entries too -- token_to_id must resolve "<|im_end|>" even when
  // the vocab object does not list it.
  const json::Value* added = root.get_array("added_tokens");
  if (added != nullptr) {
    for (const auto& a : added->array()) {
      Added t;
      t.content = a.get_string("content");
      t.id = static_cast<int32_t>(a.get_int("id"));
      t.special = a.get_bool("special");
      if (t.content.empty()) continue;
      tok->added_.push_back(std::move(t));
    }
    std::stable_sort(tok->added_.begin(), tok->added_.end(),
                     [](const Added& a, const Added& b) {
                       return a.content.size() > b.content.size();
                     });
    // Grow the id table to fit added tokens, then register their literals.
    for (const auto& a : tok->added_) {
      if (a.special) tok->added_special_.push_back(a.id);
      if (a.id < 0) continue;
      if (static_cast<size_t>(a.id) >= tok->id_to_token_.size()) {
        tok->id_to_token_.resize(static_cast<size_t>(a.id) + 1);
      }
      if (tok->id_to_token_[static_cast<size_t>(a.id)].empty()) {
        tok->id_to_token_[static_cast<size_t>(a.id)] = a.content;
      }
      tok->token_to_id_.emplace(a.content, a.id);
    }
  }

  // Byte fallback: `byte_fallback: true` in the model, and the vocabulary holds
  // one `<0xXX>` literal per byte. Both are indexed now so encoding and
  // decoding are table lookups rather than string formatting per code point.
  tok->flavour_ = flavour;
  tok->byte_fallback_ = model->get_bool("byte_fallback");
  tok->unk_id_ = id_of(tok->token_to_id_, model->get_string("unk_token"));
  if (tok->unk_id_ < 0) tok->unk_id_ = 0;
  for (int b = 0; b < 256; ++b) {
    char lit[8];
    std::snprintf(lit, sizeof(lit), "<0x%02X>", b);
    const int32_t id = id_of(tok->token_to_id_, lit);
    tok->byte_fallback_ids_[b] = id;
    if (id >= 0) tok->byte_token_bytes_[id] = b;
  }
  return tok;
}

void Tokenizer::merge_ids(std::vector<int32_t>* sym) const {
  std::vector<int32_t>& s = *sym;
  while (s.size() > 1) {
    int32_t best_rank = INT32_MAX;
    size_t best_at = 0;
    bool found = false;
    for (size_t i = 0; i + 1 < s.size(); ++i) {
      const auto it = merges_.find(merge_key(s[i], s[i + 1]));
      if (it == merges_.end()) continue;
      if (it->second.rank < best_rank) {
        best_rank = it->second.rank;
        best_at = i;
        found = true;
      }
    }
    if (!found) break;
    s[best_at] = merges_.find(merge_key(s[best_at], s[best_at + 1]))->second.id;
    s.erase(s.begin() + static_cast<long>(best_at) + 1);
  }
}

void Tokenizer::bpe(const std::string& piece, std::vector<int32_t>* out) const {
  // Symbols are whole code points of the byte-level alphabet, which is how the
  // vocabulary is keyed ("Ġhello" is one token, "Ġ" plus "hello" is two).
  std::vector<int32_t> sym;
  sym.reserve(piece.size());
  for (size_t i = 0; i < piece.size();) {
    size_t next = i;
    utf8_next(piece, &next);
    const std::string cp = piece.substr(i, next - i);
    const int32_t id = id_of(token_to_id_, cp);
    i = next;
    if (id < 0) continue;  // not in vocab: nothing sensible to emit for it
    sym.push_back(id);
  }
  merge_ids(&sym);
  out->insert(out->end(), sym.begin(), sym.end());
}

void Tokenizer::bpe_metaspace(const std::string& norm,
                              std::vector<int32_t>* out) const {
  // The whole normalised run is one BPE input: this tokenizer has no
  // pre-tokenizer at all (see Flavour). A code point the vocabulary does not
  // hold is spelled with its own UTF-8 bytes through the byte-fallback table
  // (`<0xE7><0xB0><0xAA>` for one character), which is what makes every input
  // encodable and keeps ids identical to the reference.
  std::vector<int32_t> sym;
  sym.reserve(norm.size());
  for (size_t i = 0; i < norm.size();) {
    size_t next = i;
    utf8_next(norm, &next);
    const std::string cp = norm.substr(i, next - i);
    const int32_t id = id_of(token_to_id_, cp);
    if (id >= 0) {
      sym.push_back(id);
    } else if (byte_fallback_) {
      for (size_t k = 0; k < cp.size(); ++k) {
        const int32_t b = byte_fallback_ids_[static_cast<unsigned char>(cp[k])];
        // A vocabulary that advertises byte_fallback but is missing a byte
        // token cannot encode some input; the reference falls back to unk, and
        // so do we rather than invent an id.
        sym.push_back(b >= 0 ? b : unk_id_);
      }
    }
    // Without byte_fallback an unknown code point is dropped, which is what the
    // reference's BPE does with a character no symbol covers.
    i = next;
  }
  merge_ids(&sym);
  out->insert(out->end(), sym.begin(), sym.end());
}


std::vector<int32_t> Tokenizer::encode(const std::string& text) const {
  std::vector<int32_t> out;
  if (text.empty()) return out;

  // Pass 1: added_tokens first, on the raw text. Spans between them go on to
  // normalization and BPE; a matched added token is emitted as its own id.
  struct Span {
    size_t begin, end;
    int32_t added_id;  // -1 for ordinary text
  };
  std::vector<Span> spans;
  size_t i = 0;
  while (i < text.size()) {
    int32_t hit = -1;
    size_t hit_len = 0;
    for (const auto& a : added_) {
      if (a.content.size() <= text.size() - i &&
          std::memcmp(text.data() + i, a.content.data(), a.content.size()) == 0) {
        hit = a.id;
        hit_len = a.content.size();
        break;  // added_ is sorted longest-first
      }
    }
    if (hit >= 0) {
      spans.push_back(Span{i, i + hit_len, hit});
      i += hit_len;
      continue;
    }
    // Ordinary text runs until the next added token.
    size_t stop = text.size();
    for (const auto& a : added_) {
      const size_t n = a.content.size();
      if (n > text.size() - i) continue;
      for (size_t k = i + 1; k + n <= text.size(); ++k) {
        if (std::memcmp(text.data() + k, a.content.data(), n) == 0) {
          if (k < stop) stop = k;
          break;
        }
      }
    }
    spans.push_back(Span{i, stop, -1});
    i = stop;
  }

  for (const auto& sp : spans) {
    if (sp.added_id >= 0) {
      out.push_back(sp.added_id);
      continue;
    }
    if (flavour_ == Flavour::kMetaspaceReplace) {
      // No NFC, no regex: the normalizer swaps every space for the metaspace
      // marker (U+2581) and the result is one BPE input.
      const std::string& raw = text;
      std::string norm;
      norm.reserve(sp.end - sp.begin);
      for (size_t k = sp.begin; k < sp.end; ++k) {
        if (raw[k] == ' ') {
          norm += "\xE2\x96\x81";  // U+2581
        } else {
          norm.push_back(raw[k]);
        }
      }
      if (!norm.empty()) bpe_metaspace(norm, &out);
      continue;
    }
    const std::string norm = nfc(text.substr(sp.begin, sp.end - sp.begin));
    if (norm.empty()) continue;

    // Pass 2: the pre-tokenizer. Matches are pieces; the gaps between matches
    // are pieces too (Split with behavior Isolated).
    size_t k = 0;
    while (k < norm.size()) {
      size_t end = 0;
      if (pretok_match(norm, k, &end) && end > k) {
        bpe(byte_level_encode(norm.substr(k, end - k)), &out);
        k = end;
      } else {
        // Not reachable for well-formed text (the last alternation matches any
        // space and \p{L}+ covers the rest), but advancing one byte keeps the
        // loop finite if a future pattern leaves a hole.
        const size_t next = cp_at(norm, k).next;
        bpe(byte_level_encode(norm.substr(k, next - k)), &out);
        k = next > k ? next : k + 1;
      }
    }
  }
  return out;
}

std::string Tokenizer::decode(const std::vector<int32_t>& ids, bool skip_special) const {
  const ByteLevelMap& m = byte_level_map();
  std::string bytes;
  for (int32_t id : ids) {
    if (id < 0 || static_cast<size_t>(id) >= id_to_token_.size()) continue;
    if (skip_special && is_special(id)) continue;
    const std::string& tok = id_to_token_[static_cast<size_t>(id)];
    if (flavour_ == Flavour::kMetaspaceReplace) {
      // `Replace("▁", " ")` then ByteFallback then Fuse. ByteFallback is
      // what turns the `<0xE7>` tokens back into the bytes they name -- without
      // it a CJK character the vocabulary lacks would decode to the literal
      // seven characters "<0xE7>" instead of the character.
      const int32_t byte = byte_token_value(id);
      if (byte >= 0) {
        bytes.push_back(static_cast<char>(byte));
        continue;
      }
      for (size_t i = 0; i < tok.size();) {
        size_t next = i;
        const uint32_t cp = utf8_next(tok, &next);
        if (cp == 0x2581u) {
          bytes.push_back(' ');
        } else {
          bytes.append(tok, i, next - i);
        }
        i = next;
      }
      continue;
    }
    // ByteLevel decode: each code point maps back to one raw byte. Code points
    // outside the alphabet (an added token's literal text) pass through as-is.
    for (size_t i = 0; i < tok.size();) {
      size_t next = i;
      const uint32_t cp = utf8_next(tok, &next);
      if (cp < static_cast<uint32_t>(kByteLevelHigh + 68) && m.to_byte[cp] >= 0) {
        bytes.push_back(static_cast<char>(m.to_byte[cp]));
      } else {
        bytes.append(tok, i, next - i);
      }
      i = next;
    }
  }
  return bytes;
}

int32_t Tokenizer::byte_token_value(int32_t id) const {
  const auto it = byte_token_bytes_.find(id);
  return it == byte_token_bytes_.end() ? -1 : it->second;
}

bool Tokenizer::is_special(int32_t id) const {
  return std::find(added_special_.begin(), added_special_.end(), id) !=
         added_special_.end();
}

int32_t Tokenizer::token_to_id(const std::string& token) const {
  return id_of(token_to_id_, token);
}

std::string Tokenizer::id_to_token(int32_t id) const {
  if (id < 0 || static_cast<size_t>(id) >= id_to_token_.size()) return std::string();
  return id_to_token_[static_cast<size_t>(id)];
}

}  // namespace cv84x6
