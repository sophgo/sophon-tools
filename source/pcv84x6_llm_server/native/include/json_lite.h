// Minimal JSON reader, enough for tokenizer.json.
//
// tokenizer.json is the only JSON this service parses at inference time, and it
// has a fixed shape (objects, arrays, strings, numbers, bool, null). A pull
// parser over the raw bytes keeps it small: no DOM, no allocations beyond the
// strings we keep. Numbers are only ever read as integers (ids) or into a
// double for the odd float field.

#pragma once

#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

namespace cv84x6 {
namespace json {

struct Value;

// Objects keep insertion order: a tokenizer's "added_tokens" order decides
// which duplicate id wins, so the order must be preserved, not just the set.
using Member = std::pair<std::string, Value>;

class Value {
 public:
  enum class Type { Null, Bool, Number, String, Array, Object };

  Value() = default;

  Type type() const { return type_; }
  bool is_null() const { return type_ == Type::Null; }
  bool is_string() const { return type_ == Type::String; }
  bool is_array() const { return type_ == Type::Array; }
  bool is_object() const { return type_ == Type::Object; }

  const std::string& str() const { return str_; }
  double num() const { return num_; }
  long long integer() const { return static_cast<long long>(num_); }
  bool boolean() const { return num_ != 0.0; }

  const std::vector<Value>& array() const { return array_; }
  const std::vector<Member>& members() const { return members_; }

  // Object lookup by key. Returns nullptr when absent or not an object.
  const Value* get(const std::string& key) const {
    for (const auto& m : members_) {
      if (m.first == key) return &m.second;
    }
    return nullptr;
  }

  // Convenience readers that fall back on a default rather than throwing, since
  // tokenizer.json from different model conversions omits different fields.
  std::string get_string(const std::string& key, const std::string& fallback = {}) const {
    const Value* v = get(key);
    return (v && v->is_string()) ? v->str_ : fallback;
  }
  long long get_int(const std::string& key, long long fallback = 0) const {
    const Value* v = get(key);
    return (v && v->type_ == Type::Number) ? v->integer() : fallback;
  }
  bool get_bool(const std::string& key, bool fallback = false) const {
    const Value* v = get(key);
    return (v && v->type_ == Type::Bool) ? v->boolean() : fallback;
  }
  const Value* get_array(const std::string& key) const {
    const Value* v = get(key);
    return (v && v->is_array()) ? v : nullptr;
  }

  static Value make_string(std::string s) {
    Value v; v.type_ = Type::String; v.str_ = std::move(s); return v;
  }
  static Value make_number(double d) {
    Value v; v.type_ = Type::Number; v.num_ = d; return v;
  }

 private:
  friend class Parser;
  Type type_ = Type::Null;
  double num_ = 0.0;
  std::string str_;
  std::vector<Value> array_;
  std::vector<Member> members_;
};

class Parser {
 public:
  Parser(const char* data, size_t size) : p_(data), end_(data + size) {}

  // Parses one value. On failure returns false and sets error().
  bool parse(Value* out) {
    skip_ws();
    if (!parse_value(out)) return false;
    skip_ws();
    return true;
  }

  const std::string& error() const { return error_; }

 private:
  void skip_ws() {
    while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r')) ++p_;
  }

  bool fail(const char* msg) {
    if (error_.empty()) error_ = msg;
    return false;
  }

  bool parse_value(Value* out) {
    if (p_ >= end_) return fail("unexpected end of input");
    switch (*p_) {
      case '{': return parse_object(out);
      case '[': return parse_array(out);
      case '"': {
        std::string s;
        if (!parse_string(&s)) return false;
        out->type_ = Value::Type::String;
        out->str_ = std::move(s);
        return true;
      }
      case 't':
        if (end_ - p_ < 4 || std::string(p_, 4) != "true") return fail("bad literal");
        p_ += 4; out->type_ = Value::Type::Bool; out->num_ = 1.0; return true;
      case 'f':
        if (end_ - p_ < 5 || std::string(p_, 5) != "false") return fail("bad literal");
        p_ += 5; out->type_ = Value::Type::Bool; out->num_ = 0.0; return true;
      case 'n':
        if (end_ - p_ < 4 || std::string(p_, 4) != "null") return fail("bad literal");
        p_ += 4; out->type_ = Value::Type::Null; return true;
      default: return parse_number(out);
    }
  }

  bool parse_object(Value* out) {
    ++p_;  // '{'
    out->type_ = Value::Type::Object;
    skip_ws();
    if (p_ < end_ && *p_ == '}') { ++p_; return true; }
    while (true) {
      skip_ws();
      if (p_ >= end_ || *p_ != '"') return fail("expected object key");
      std::string key;
      if (!parse_string(&key)) return false;
      skip_ws();
      if (p_ >= end_ || *p_ != ':') return fail("expected ':'");
      ++p_;
      skip_ws();
      Value v;
      if (!parse_value(&v)) return false;
      out->members_.emplace_back(std::move(key), std::move(v));
      skip_ws();
      if (p_ >= end_) return fail("unterminated object");
      if (*p_ == ',') { ++p_; continue; }
      if (*p_ == '}') { ++p_; return true; }
      return fail("expected ',' or '}'");
    }
  }

  bool parse_array(Value* out) {
    ++p_;  // '['
    out->type_ = Value::Type::Array;
    skip_ws();
    if (p_ < end_ && *p_ == ']') { ++p_; return true; }
    while (true) {
      skip_ws();
      Value v;
      if (!parse_value(&v)) return false;
      out->array_.push_back(std::move(v));
      skip_ws();
      if (p_ >= end_) return fail("unterminated array");
      if (*p_ == ',') { ++p_; continue; }
      if (*p_ == ']') { ++p_; return true; }
      return fail("expected ',' or ']'");
    }
  }

  // Decodes one \uXXXX (with surrogate pairs) into UTF-8.
  bool parse_hex4(unsigned* out) {
    if (end_ - p_ < 4) return fail("short \\u escape");
    unsigned v = 0;
    for (int i = 0; i < 4; ++i) {
      char c = *p_++;
      v <<= 4;
      if (c >= '0' && c <= '9') v |= unsigned(c - '0');
      else if (c >= 'a' && c <= 'f') v |= unsigned(c - 'a' + 10);
      else if (c >= 'A' && c <= 'F') v |= unsigned(c - 'A' + 10);
      else return fail("bad hex digit in \\u escape");
    }
    *out = v;
    return true;
  }

  static void append_utf8(std::string* s, unsigned cp) {
    if (cp < 0x80) {
      s->push_back(char(cp));
    } else if (cp < 0x800) {
      s->push_back(char(0xC0 | (cp >> 6)));
      s->push_back(char(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
      s->push_back(char(0xE0 | (cp >> 12)));
      s->push_back(char(0x80 | ((cp >> 6) & 0x3F)));
      s->push_back(char(0x80 | (cp & 0x3F)));
    } else {
      s->push_back(char(0xF0 | (cp >> 18)));
      s->push_back(char(0x80 | ((cp >> 12) & 0x3F)));
      s->push_back(char(0x80 | ((cp >> 6) & 0x3F)));
      s->push_back(char(0x80 | (cp & 0x3F)));
    }
  }

  bool parse_string(std::string* out) {
    ++p_;  // '"'
    out->clear();
    while (true) {
      if (p_ >= end_) return fail("unterminated string");
      unsigned char c = static_cast<unsigned char>(*p_);
      if (c == '"') { ++p_; return true; }
      if (c == '\\') {
        ++p_;
        if (p_ >= end_) return fail("unterminated escape");
        char e = *p_++;
        switch (e) {
          case '"': out->push_back('"'); break;
          case '\\': out->push_back('\\'); break;
          case '/': out->push_back('/'); break;
          case 'b': out->push_back('\b'); break;
          case 'f': out->push_back('\f'); break;
          case 'n': out->push_back('\n'); break;
          case 'r': out->push_back('\r'); break;
          case 't': out->push_back('\t'); break;
          case 'u': {
            unsigned cp = 0;
            if (!parse_hex4(&cp)) return false;
            if (cp >= 0xD800 && cp <= 0xDBFF) {
              // High surrogate: pair it with the following low surrogate.
              if (end_ - p_ >= 2 && p_[0] == '\\' && p_[1] == 'u') {
                p_ += 2;
                unsigned lo = 0;
                if (!parse_hex4(&lo)) return false;
                if (lo >= 0xDC00 && lo <= 0xDFFF) {
                  cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                } else {
                  append_utf8(out, cp);  // unpaired: emit the high one as-is
                  cp = lo;
                }
              }
            }
            append_utf8(out, cp);
            break;
          }
          default: return fail("unknown escape");
        }
        continue;
      }
      // Raw byte: tokenizer.json is UTF-8, so copy bytes through unchanged.
      out->push_back(char(c));
      ++p_;
    }
  }

  bool parse_number(Value* out) {
    const char* start = p_;
    if (p_ < end_ && (*p_ == '-' || *p_ == '+')) ++p_;
    bool any = false;
    while (p_ < end_ && ((*p_ >= '0' && *p_ <= '9') || *p_ == '.' || *p_ == 'e' ||
                         *p_ == 'E' || *p_ == '-' || *p_ == '+')) {
      ++p_;
      any = true;
    }
    if (!any) return fail("expected a value");
    std::string tmp(start, p_);
    out->type_ = Value::Type::Number;
    out->num_ = std::strtod(tmp.c_str(), nullptr);
    return true;
  }

  const char* p_;
  const char* end_;
  std::string error_;
};

// Parses a whole buffer. Returns false and fills `error` on malformed input.
inline bool parse(const std::string& text, Value* out, std::string* error) {
  Parser p(text.data(), text.size());
  if (!p.parse(out)) {
    if (error) *error = p.error();
    return false;
  }
  return true;
}

}  // namespace json
}  // namespace cv84x6
