// Tokenizer conformance check against tests/tokenizer_golden.json.
//
// The golden file is produced by the Python `tokenizers` package
// (tools/gen_tokenizer_golden.py). The C++ tokenizer exists to replace that
// package on the board, so any drift here is a correctness bug, not a style
// difference: run this on the board and on x86 before shipping.
//
//   tok_check <tokenizer.json> <golden.json>
//
// Exits non-zero on the first mismatch and prints the offending case.

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "json_lite.h"
#include "tokenizer.h"

namespace {

std::string read_file(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

std::string escape(const std::string& s) {
  std::string out;
  for (unsigned char c : s) {
    switch (c) {
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      case '\\': out += "\\\\"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof(buf), "\\x%02x", c);
          out += buf;
        } else {
          out.push_back(static_cast<char>(c));
        }
    }
  }
  return out;
}

std::string join_ids(const std::vector<int32_t>& ids) {
  std::string s;
  for (size_t i = 0; i < ids.size(); ++i) {
    if (i) s += ",";
    s += std::to_string(ids[i]);
  }
  return s;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <tokenizer.json> <golden.json>\n", argv[0]);
    return 2;
  }

  std::string err;
  auto tok = cv84x6::Tokenizer::from_file(argv[1], &err);
  if (!tok) {
    std::fprintf(stderr, "load failed: %s\n", err.c_str());
    return 1;
  }

  cv84x6::json::Value golden;
  const std::string text = read_file(argv[2]);
  if (!cv84x6::json::parse(text, &golden, &err)) {
    std::fprintf(stderr, "golden parse failed: %s\n", err.c_str());
    return 1;
  }

  int failures = 0;
  int checked = 0;
  const cv84x6::json::Value* cases = golden.get_array("cases");
  if (cases == nullptr) {
    std::fprintf(stderr, "golden has no cases\n");
    return 1;
  }
  for (const auto& c : cases->array()) {
    const std::string input = c.get_string("text");
    const cv84x6::json::Value* want = c.get_array("ids");
    if (want == nullptr) continue;

    std::vector<int32_t> expected;
    expected.reserve(want->array().size());
    for (const auto& v : want->array()) {
      expected.push_back(static_cast<int32_t>(v.integer()));
    }

    const std::vector<int32_t> got = tok->encode(input);
    ++checked;
    if (got != expected) {
      ++failures;
      std::fprintf(stderr,
                   "ENCODE MISMATCH  text=%s\n  want=[%s]\n  got =[%s]\n",
                   escape(input).c_str(), join_ids(expected).c_str(),
                   join_ids(got).c_str());
      if (failures >= 10) {
        std::fprintf(stderr, "... stopping after 10 failures\n");
        break;
      }
      continue;
    }

    // decode() is checked on the ids we just produced, so an encode bug cannot
    // hide behind a decode bug.
    const std::string want_skip = c.get_string("decoded_skip_special");
    const std::string got_skip = tok->decode(got, true);
    if (got_skip != want_skip) {
      ++failures;
      std::fprintf(stderr,
                   "DECODE(skip) MISMATCH  text=%s\n  want=%s\n  got =%s\n",
                   escape(input).c_str(), escape(want_skip).c_str(),
                   escape(got_skip).c_str());
      if (failures >= 10) break;
    }
    const std::string want_keep = c.get_string("decoded_keep_special");
    const std::string got_keep = tok->decode(got, false);
    if (got_keep != want_keep) {
      ++failures;
      std::fprintf(stderr,
                   "DECODE(keep) MISMATCH  text=%s\n  want=%s\n  got =%s\n",
                   escape(input).c_str(), escape(want_keep).c_str(),
                   escape(got_keep).c_str());
      if (failures >= 10) break;
    }
  }

  // Special-token ids: a shifted vocab would break the stop set and the vision
  // markers without necessarily breaking any of the text cases.
  const cv84x6::json::Value* specials = golden.get("specials");
  if (specials != nullptr && specials->is_object()) {
    for (const auto& m : specials->members()) {
      const int32_t want = static_cast<int32_t>(m.second.integer());
      const int32_t got = tok->token_to_id(m.first);
      ++checked;
      if (got != want) {
        ++failures;
        std::fprintf(stderr, "SPECIAL MISMATCH  %s want=%d got=%d\n",
                     m.first.c_str(), want, got);
      }
    }
  }

  if (failures == 0) {
    std::printf("tokenizer: %d checks passed (vocab %zu)\n", checked, tok->vocab_size());
    return 0;
  }
  std::fprintf(stderr, "tokenizer: %d of %d checks FAILED\n", failures, checked);
  return 1;
}
