// Flat C ABI over the engine, for the python worker to drive through ctypes.
//
// The C++ classes are the real implementation; this file adds nothing but a
// stable surface a ctypes binding can call. Everything here takes/returns PODs
// and never throws across the boundary -- errors come back as NULL / negative
// codes plus a last_error string.

#include "asr_engine.h"
#include "aux_engine.h"
#include "llm_engine.h"
#include "net_engine.h"
#include "tokenizer.h"
#include "vision.h"
#include "vl_engine.h"

#include <algorithm>
#include <cstring>
#include <new>
#include <string>
#include <vector>

namespace {

thread_local std::string g_last_error;

void set_error(const char** err, const std::string& msg) {
  g_last_error = msg;
  if (err) *err = g_last_error.c_str();
}

}  // namespace

extern "C" {

void* llm_engine_load(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::Engine();
  if (!e) {
    set_error(err, "out of memory allocating Engine");
    return nullptr;
  }
  if (!e->load(model_path, dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void llm_engine_free(void* eng) { delete static_cast<cv84x6::Engine*>(eng); }

#define ENGINE_GETTER(name, expr) \
  int llm_engine_##name(void* eng) { return static_cast<cv84x6::Engine*>(eng)->expr; }
ENGINE_GETTER(num_layers, num_layers())
ENGINE_GETTER(context_length, context_length())
ENGINE_GETTER(max_input_length, max_input_length())
ENGINE_GETTER(hidden_size, hidden_size())
ENGINE_GETTER(has_vision, has_vision() ? 1 : 0)
ENGINE_GETTER(vit_max_patches, vit_max_patches())
ENGINE_GETTER(vit_dims, vit_dims())
ENGINE_GETTER(supports_history, supports_history() ? 1 : 0)
ENGINE_GETTER(fault, fault() ? 1 : 0)
#undef ENGINE_GETTER

unsigned long long llm_engine_session_state_bytes(void* eng) {
  return static_cast<cv84x6::Engine*>(eng)->session_state_bytes();
}

unsigned long long llm_engine_kv_bytes_per_token(void* eng) {
  return static_cast<cv84x6::Engine*>(eng)->kv_bytes_per_token();
}

unsigned long long llm_engine_linear_state_bytes(void* eng) {
  return static_cast<cv84x6::Engine*>(eng)->linear_state_bytes();
}

int llm_engine_park_granule(void* eng) {
  return static_cast<cv84x6::Engine*>(eng)->park_granule();
}

// Embedding table size, so the engine can reject out-of-range token ids before
// it hands them to the embedding graph (see Engine::set_vocab_size). The
// bmodel does not carry it -- lm_head fuses argmax, so the vocabulary never
// appears in a shape -- and the tokenizer that does know it lives behind its
// own opaque handle, so the caller tells us. 0 disables the check.
void llm_engine_set_vocab_size(void* eng, int n) {
  static_cast<cv84x6::Engine*>(eng)->set_vocab_size(n);
}

int llm_engine_vocab_size(void* eng) {
  return static_cast<cv84x6::Engine*>(eng)->vocab_size();
}

void* llm_session_new(void* eng, const char** err) {
  auto* e = static_cast<cv84x6::Engine*>(eng);
  auto s = e->new_session();
  if (!s) {
    set_error(err, e->last_error());
    return nullptr;
  }
  return s.release();
}

void llm_session_free(void* sess) { delete static_cast<cv84x6::Session*>(sess); }

int llm_session_token_len(void* sess) {
  return static_cast<cv84x6::Session*>(sess)->token_len();
}

namespace {
int prefill_common(bool append, void* eng, void* sess, const int* tokens, int n,
                   const int* pos3, int n_images, const int* offsets,
                   const int* patches, const float* const* pixels,
                   const int* const* pos_ids, const int* const* pos_idx,
                   const float* const* pos_weight, const char** err) {
  std::vector<cv84x6::VitImage> imgs(n_images > 0 ? n_images : 0);
  for (int i = 0; i < n_images; i++) {
    imgs[i].offset = offsets[i];
    imgs[i].patches = patches[i];
    imgs[i].pixels = pixels[i];
    imgs[i].pos_ids = pos_ids[i];
    imgs[i].pos_idx = pos_idx[i];
    imgs[i].pos_weight = pos_weight[i];
  }
  auto* s = static_cast<cv84x6::Session*>(sess);
  const bool ok = append ? s->extend(tokens, n, pos3, imgs.data(), n_images)
                         : s->prefill(tokens, n, pos3, imgs.data(), n_images);
  if (!ok) {
    set_error(err, static_cast<cv84x6::Engine*>(eng)->last_error());
    return -1;
  }
  return 0;
}
}  // namespace

// Prefill (fresh) / extend (append after the session's state). `pos3` is
// [3, n] int32 absolute positions, or NULL for plain text. Images are given as
// parallel arrays of length n_images, offsets relative to these n tokens.
// Returns 0 on success, -1 on failure; the next token comes from
// llm_session_decode().
int llm_session_prefill(void* eng, void* sess, const int* tokens, int n,
                        const int* pos3, int n_images, const int* offsets,
                        const int* patches, const float* const* pixels,
                        const int* const* pos_ids, const int* const* pos_idx,
                        const float* const* pos_weight, const char** err) {
  return prefill_common(false, eng, sess, tokens, n, pos3, n_images, offsets, patches,
                        pixels, pos_ids, pos_idx, pos_weight, err);
}

int llm_session_extend(void* eng, void* sess, const int* tokens, int n,
                       const int* pos3, int n_images, const int* offsets,
                       const int* patches, const float* const* pixels,
                       const int* const* pos_ids, const int* const* pos_idx,
                       const float* const* pos_weight, const char** err) {
  return prefill_common(true, eng, sess, tokens, n, pos3, n_images, offsets, patches,
                        pixels, pos_ids, pos_idx, pos_weight, err);
}

// -- snapshots (prefix cache) ------------------------------------------------
void* llm_session_snapshot(void* eng, void* sess, const char** err) {
  void* h = static_cast<cv84x6::Session*>(sess)->snapshot();
  if (!h) set_error(err, static_cast<cv84x6::Engine*>(eng)->last_error());
  return h;
}

int llm_session_restore(void* eng, void* sess, void* snap, const char** err) {
  if (!static_cast<cv84x6::Session*>(sess)->restore(snap)) {
    set_error(err, static_cast<cv84x6::Engine*>(eng)->last_error());
    return -1;
  }
  return 0;
}

void llm_snapshot_free(void* snap) { cv84x6::Engine::free_snapshot(snap); }

unsigned long long llm_snapshot_bytes(void* snap) {
  return cv84x6::Engine::snapshot_bytes(snap);
}

void llm_session_set_exact_tail(void* sess, int rows) {
  static_cast<cv84x6::Session*>(sess)->set_exact_tail(rows);
}

int llm_session_debug_rows(void* sess, uint16_t* out, int n) {
  return static_cast<cv84x6::Session*>(sess)->debug_rows(out, n);
}

int llm_session_last_hidden(void* sess, uint16_t* out, int n) {
  return static_cast<cv84x6::Session*>(sess)->last_hidden(out, n);
}

// Returns the next token id (>= 0) or -1 on failure.
int llm_session_decode(void* eng, void* sess, const char** err) {
  const int id = static_cast<cv84x6::Session*>(sess)->decode();
  if (id < 0) set_error(err, static_cast<cv84x6::Engine*>(eng)->last_error());
  return id;
}

const char* llm_last_error() { return g_last_error.c_str(); }

// -- tokenizer --------------------------------------------------------------
//
// The tokenizer lives in this library so the worker needs no Python at all.
// Handles are opaque to the caller. Calls take a caller-provided int32 buffer;
// when it is too small they return the needed count and write nothing, which is
// how a caller sizes a prompt without a second round trip.
void* llm_tokenizer_load(const char* tokenizer_json, const char** err) {
  std::string e;
  auto tok = cv84x6::Tokenizer::from_file(tokenizer_json, &e);
  if (!tok) {
    set_error(err, e);
    return nullptr;
  }
  return tok.release();
}

void llm_tokenizer_free(void* tok) { delete static_cast<cv84x6::Tokenizer*>(tok); }

// Returns the number of ids the text encodes to; writes up to `cap` of them
// into `out` (when `out` is non-null). Negative on error.
int llm_tokenizer_encode(void* tok, const char* text, int* out, int cap,
                         const char** err) {
  if (tok == nullptr) {
    set_error(err, "null tokenizer");
    return -1;
  }
  const std::vector<int32_t> ids =
      static_cast<cv84x6::Tokenizer*>(tok)->encode(text ? text : "");
  if (out != nullptr) {
    const int n = std::min<int>(cap, static_cast<int>(ids.size()));
    for (int i = 0; i < n; ++i) out[i] = ids[static_cast<size_t>(i)];
  }
  return static_cast<int>(ids.size());
}

// Decodes ids into `out` (NUL-terminated) and returns the byte length the text
// needs, excluding the terminator; writes up to cap-1 bytes.
int llm_tokenizer_decode(void* tok, const int* ids, int n, char* out, int cap,
                         int skip_special, const char** err) {
  if (tok == nullptr) {
    set_error(err, "null tokenizer");
    return -1;
  }
  std::vector<int32_t> v(static_cast<size_t>(n));
  for (int i = 0; i < n; ++i) v[static_cast<size_t>(i)] = ids[i];
  const std::string text =
      static_cast<cv84x6::Tokenizer*>(tok)->decode(v, skip_special != 0);
  if (out != nullptr && cap > 0) {
    const size_t k = std::min<size_t>(static_cast<size_t>(cap - 1), text.size());
    std::memcpy(out, text.data(), k);
    out[k] = '\0';
  }
  return static_cast<int>(text.size());
}

// Id of one literal token string, or -1.
int llm_tokenizer_token_to_id(void* tok, const char* token) {
  if (tok == nullptr) return -1;
  return static_cast<cv84x6::Tokenizer*>(tok)->token_to_id(token ? token : "");
}

int llm_tokenizer_vocab_size(void* tok) {
  return tok == nullptr ? 0 : static_cast<int>(static_cast<cv84x6::Tokenizer*>(tok)->vocab_size());
}

// -- vision ----------------------------------------------------------------
//
// Image decoding and preprocessing are pure host software, and doing them here
// keeps torch/transformers/pillow/qwen_vl_utils off the board. The calls mirror
// what app/engine/native.py used to do in Python.

// Decodes a JPEG/PNG held in `data` and returns its dimensions through `wh`
// ({width, height}). Returns 0 on success, -1 on failure (see *err).
int llm_image_info(const unsigned char* data, int len, int* wh, const char** err) {
  std::string e;
  cv84x6::Image img;
  const std::string bytes(reinterpret_cast<const char*>(data), static_cast<size_t>(len));
  if (!cv84x6::decode_image(bytes, &img, &e)) {
    set_error(err, e);
    return -1;
  }
  wh[0] = img.width;
  wh[1] = img.height;
  return 0;
}

// Preprocesses one image into the vit's input layout.
//
// Output is written through `out`:
//   out[0..2]  grid {t, h, w}
//   out[3]     patches  = t*h*w
//   out[4]     width    = elements per patch row (the vit's input width)
// `pixels` receives `patches * width` floats. Pass pixels = nullptr to query the
// sizes first; the return value is the element count, or -1 on error.
int llm_image_preprocess(const unsigned char* data, int len, int max_patches,
                         int patch_size, int spatial_merge, int temporal_patch_size,
                         long long min_pixels, long long max_pixels,
                         int* out, float* pixels, const char** err) {
  cv84x6::VisionConfig cfg;
  cfg.patch_size = patch_size;
  cfg.spatial_merge = spatial_merge;
  cfg.temporal_patch_size = temporal_patch_size;
  cfg.grid_per_side = 48;
  cfg.max_patches = max_patches;
  cfg.min_pixels = min_pixels;
  cfg.max_pixels = max_pixels;

  std::string e;
  cv84x6::VisionInput vi;
  const std::string bytes(reinterpret_cast<const char*>(data), static_cast<size_t>(len));
  if (!cv84x6::preprocess_image(bytes, cfg, &vi, &e)) {
    set_error(err, e);
    return -1;
  }
  const int width = static_cast<int>(vi.pixels.size() / std::max(1, vi.patches()));
  if (out != nullptr) {
    out[0] = vi.grid_t;
    out[1] = vi.grid_h;
    out[2] = vi.grid_w;
    out[3] = vi.patches();
    out[4] = width;
  }
  if (pixels != nullptr) {
    std::memcpy(pixels, vi.pixels.data(), vi.pixels.size() * sizeof(float));
  }
  return static_cast<int>(vi.pixels.size());
}

// ViT position tables for one image. `pos_ids` is patches*2 ints, `pos_idx`
// patches*4 ints and `pos_weight` patches*4 floats.
void llm_vision_pos_tables(int grid_t, int grid_h, int grid_w, int grid_per_side,
                           int* pos_ids, int* pos_idx, float* pos_weight) {
  std::vector<int32_t> ids, idx;
  std::vector<float> w;
  cv84x6::vision_rot_pos(grid_t, grid_h, grid_w, &ids);
  cv84x6::vision_pos_embed_interpolate(grid_t, grid_h, grid_w, grid_per_side, &idx, &w);
  if (pos_ids) std::memcpy(pos_ids, ids.data(), ids.size() * sizeof(int32_t));
  if (pos_idx) std::memcpy(pos_idx, idx.data(), idx.size() * sizeof(int32_t));
  if (pos_weight) std::memcpy(pos_weight, w.data(), w.size() * sizeof(float));
}

// M-RoPE positions for a prompt with `n_images` images. `grids` is n_images*3
// ints {t, h, w} in patch units. `pos3` receives 3*n ints, [3, n] row-major.
// Returns 0 on success.
int llm_vision_rope(const int* ids, int n, const int* grids, int n_images,
                    int vision_start_id, int image_pad_id, int spatial_merge,
                    int* pos3, const char** err) {
  if (n < 0 || n_images < 0 || (n_images > 0 && grids == nullptr)) {
    set_error(err, "llm_vision_rope: bad arguments");
    return -1;
  }
  std::vector<int32_t> tokens(static_cast<size_t>(n));
  for (int i = 0; i < n; ++i) tokens[static_cast<size_t>(i)] = ids[i];
  std::vector<std::vector<int>> g;
  g.reserve(static_cast<size_t>(n_images));
  for (int i = 0; i < n_images; ++i) {
    g.push_back({grids[3 * i], grids[3 * i + 1], grids[3 * i + 2]});
  }
  std::vector<int32_t> p;
  cv84x6::vision_rope_index(tokens, g, vision_start_id, image_pad_id, spatial_merge, &p);
  if (pos3 != nullptr) std::memcpy(pos3, p.data(), p.size() * sizeof(int32_t));
  return 0;
}

// -- auxiliary models (embedding / rerank) ---------------------------------
//
// Same conventions as the chat engine above: opaque handle, bool-ish int return,
// errors through `err`. Neither engine has sessions or KV state -- one call is
// one forward -- so there is no request/session split here.

void* cv_embed_create(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::EmbedEngine();
  if (!e) {
    set_error(err, "out of memory allocating EmbedEngine");
    return nullptr;
  }
  if (!e->load(model_path ? model_path : "", dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void cv_embed_destroy(void* h) { delete static_cast<cv84x6::EmbedEngine*>(h); }

// Writes `seq_len` and `hidden_size` through the two out parameters.
void cv_embed_info(void* h, int* seqlen, int* hidden) {
  auto* e = static_cast<cv84x6::EmbedEngine*>(h);
  if (!e) return;
  if (seqlen) *seqlen = e->seq_len();
  if (hidden) *hidden = e->hidden_size();
}

// Fills `out` with `dim` floats (last-token pooled, truncated, L2-normalised,
// exactly as the reference pipeline does). Returns 0 on success, -1 on failure.
int cv_embed_forward(void* h, const int* ids, int n, int dim, float* out,
                     const char** err) {
  auto* e = static_cast<cv84x6::EmbedEngine*>(h);
  if (!e) {
    set_error(err, "null embed engine");
    return -1;
  }
  if (!out) {
    set_error(err, "cv_embed_forward: null output");
    return -1;
  }
  if (!e->forward(reinterpret_cast<const int32_t*>(ids), n, dim, out)) {
    set_error(err, e->last_error());
    return -1;
  }
  return 0;
}

void* cv_rerank_create(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::RerankEngine();
  if (!e) {
    set_error(err, "out of memory allocating RerankEngine");
    return nullptr;
  }
  if (!e->load(model_path ? model_path : "", dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void cv_rerank_destroy(void* h) { delete static_cast<cv84x6::RerankEngine*>(h); }

void cv_rerank_info(void* h, int* seqlen, int* hidden) {
  auto* e = static_cast<cv84x6::RerankEngine*>(h);
  if (!e) return;
  if (seqlen) *seqlen = e->seq_len();
  if (hidden) *hidden = e->hidden_size();
}

// All three arrays are `seq_len` long (the tokenizer padded them); `*out`
// receives the raw logit. Returns 0 on success, -1 on failure.
int cv_rerank_forward(void* h, const int* input_ids, const int* position_ids,
                      const int* attention_mask, float* out, const char** err) {
  auto* e = static_cast<cv84x6::RerankEngine*>(h);
  if (!e) {
    set_error(err, "null rerank engine");
    return -1;
  }
  if (!out) {
    set_error(err, "cv_rerank_forward: null output");
    return -1;
  }
  if (!e->forward(reinterpret_cast<const int32_t*>(input_ids),
                  reinterpret_cast<const int32_t*>(position_ids),
                  reinterpret_cast<const int32_t*>(attention_mask), out)) {
    set_error(err, e->last_error());
    return -1;
  }
  return 0;
}

// -- ASR (Qwen3-ASR) -------------------------------------------------------
//
// The one auxiliary engine with state: it owns a KV cache, so the caller drives
// a request as clear -> forward_audio -> forward_first -> forward_next*. Every
// entry point takes the same opaque handle and reports failure as -1 plus
// `err`, exactly like the chat engine's session calls.
//
// ``cv_asr_info`` writes five numbers through out parameters, which is one
// static block rather than a struct: the caller sizes its prompt from them, and
// a struct would be a second definition of the same facts to keep in step
// across the ABI.

void* cv_asr_create(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::AsrEngine();
  if (!e) {
    set_error(err, "out of memory allocating AsrEngine");
    return nullptr;
  }
  if (!e->load(model_path ? model_path : "", dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void cv_asr_destroy(void* h) { delete static_cast<cv84x6::AsrEngine*>(h); }

// Writes ``SEQLEN``, ``MAX_INPUT_LENGTH``, ``AUDIO_LENGTH``, ``HIDDEN_SIZE`` and
// the audio tokens one tower call emits (13). Any pointer may be NULL.
void cv_asr_info(void* h, int* seqlen, int* max_input, int* audio_length,
                 int* hidden, int* tokens_per_chunk) {
  auto* e = static_cast<cv84x6::AsrEngine*>(h);
  if (!e) return;
  if (seqlen) *seqlen = e->seq_len();
  if (max_input) *max_input = e->max_input_length();
  if (audio_length) *audio_length = e->audio_length();
  if (hidden) *hidden = e->hidden_size();
  if (tokens_per_chunk) *tokens_per_chunk = e->tokens_per_chunk();
}

// The vocabulary size and the stop token, from the tokenizer that owns them.
// The bmodel carries neither, so the caller tells us; 0 / -1 disable the checks.
void cv_asr_set_vocab(void* h, int vocab_size, int im_end_id) {
  if (!h) return;
  static_cast<cv84x6::AsrEngine*>(h)->set_vocab(vocab_size, im_end_id);
}

int cv_asr_im_end(void* h) {
  auto* e = static_cast<cv84x6::AsrEngine*>(h);
  return e ? e->im_end_id() : -1;
}

// ``feats`` is ``n_chunks * 128 * AUDIO_LENGTH`` floats, chunk-major (the
// reference's reshape(128, -1, AUDIO_LENGTH).transpose(0, 1)); ``offsets[i]``
// is the prompt position the i-th chunk's tokens occupy.
int cv_asr_forward_audio(void* h, const float* feats, int n_chunks,
                         const int* offsets, const char** err) {
  auto* e = static_cast<cv84x6::AsrEngine*>(h);
  if (!e) {
    set_error(err, "null asr engine");
    return -1;
  }
  if (!e->forward_audio(feats, n_chunks,
                        reinterpret_cast<const int32_t*>(offsets))) {
    set_error(err, e->last_error());
    return -1;
  }
  return 0;
}

// Returns the first generated token (>= 0) or -1 on failure.
int cv_asr_forward_first(void* h, const int* ids, int n, const char** err) {
  auto* e = static_cast<cv84x6::AsrEngine*>(h);
  if (!e) {
    set_error(err, "null asr engine");
    return -1;
  }
  const int token = e->forward_first(reinterpret_cast<const int32_t*>(ids), n);
  if (token < 0) set_error(err, e->last_error());
  return token;
}

// Returns the next token (>= 0) or -1 on failure.
int cv_asr_forward_next(void* h, const char** err) {
  auto* e = static_cast<cv84x6::AsrEngine*>(h);
  if (!e) {
    set_error(err, "null asr engine");
    return -1;
  }
  const int token = e->forward_next();
  if (token < 0) set_error(err, e->last_error());
  return token;
}

void cv_asr_clear(void* h) {
  if (!h) return;
  static_cast<cv84x6::AsrEngine*>(h)->clear();
}

// -- generic single-graph networks (OCR: PP-OCRv6 det and rec) --------------
//
// Deliberately shape-agnostic, unlike the three engines above: a caller reads
// the tensor sizes out of the loaded bmodel and passes flat float32 arrays.
// Every tensor crossing this boundary is float32 whatever the graph's internal
// width is -- net_engine.cpp owns that conversion -- so the Python side never
// has to know whether a build is f16, bf16 or quantised.

void* cv_net_create(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::NetEngine();
  if (!e) {
    set_error(err, "out of memory allocating NetEngine");
    return nullptr;
  }
  if (!e->load(model_path ? model_path : "", dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void cv_net_destroy(void* h) { delete static_cast<cv84x6::NetEngine*>(h); }

// Writes the counts through the out parameters (either may be NULL), the stage
// count, and -- for each tensor -- its rank into `ranks` and the first
// `dims_cap` dims into `dims`, laid out as ranks[i] values one after another.
// Returns 0 on success. The caller sizes `ranks` input_num + output_num long
// and `dims` (input_num + output_num) * dims_cap long, which is why the two
// numbers are reported before anything is written.
int cv_net_info(void* h, int* num_inputs, int* num_outputs, int* num_stages,
                int* ranks, int dims_cap, int* dims) {
  auto* e = static_cast<cv84x6::NetEngine*>(h);
  if (!e) {
    return -1;
  }
  const int ni = e->num_inputs();
  const int no = e->num_outputs();
  if (num_inputs) *num_inputs = ni;
  if (num_outputs) *num_outputs = no;
  if (num_stages) *num_stages = e->num_stages();
  if (ranks == nullptr || dims == nullptr) return 0;
  if (dims_cap <= 0) return 0;
  for (int i = 0; i < ni + no; i++) {
    const int idx = i < ni ? i : i - ni;
    const int rank = i < ni ? e->input_dims(idx, dims + i * dims_cap, dims_cap)
                            : e->output_dims(idx, dims + i * dims_cap, dims_cap);
    ranks[i] = rank;
  }
  return 0;
}

// Element counts, so the caller allocates without re-deriving the shapes.
// `which` is 0 for inputs and 1 for outputs; index -1 means "all of them", in
// which case the counts are summed (enough to size one flat buffer).
long long cv_net_elements(void* h, int which, int index) {
  auto* e = static_cast<cv84x6::NetEngine*>(h);
  if (!e) return -1;
  const int n = which == 0 ? e->num_inputs() : e->num_outputs();
  if (index >= 0) {
    if (index >= n) return -1;
    return which == 0 ? e->input_elements(index) : e->output_elements(index);
  }
  long long total = 0;
  for (int i = 0; i < n; i++) {
    const long long k = which == 0 ? e->input_elements(i) : e->output_elements(i);
    if (k < 0) return -1;
    total += k;
  }
  return total;
}

// The graph's own dtype for one tensor, as a bm_data_type_t value (bmdef.h:
// 0 = f32, 1 = f16, 8 = bf16, ...). Reported for diagnostics only -- the
// pointers below are always float32.
int cv_net_dtype(void* h, int which, int index) {
  auto* e = static_cast<cv84x6::NetEngine*>(h);
  if (!e) return -1;
  return which == 0 ? e->input_dtype(index) : e->output_dtype(index);
}

// `in` has `num_inputs` float32 arrays and `out` has `num_outputs`, each of the
// element count cv_net_elements reported for it. Returns 0 on success.
int cv_net_run(void* h, int stage, const float* const* in, float* const* out,
               const char** err) {
  auto* e = static_cast<cv84x6::NetEngine*>(h);
  if (!e) {
    set_error(err, "null network engine");
    return -1;
  }
  if (!e->run(stage, in, out)) {
    set_error(err, e->last_error());
    return -1;
  }
  return 0;
}

// -- PaddleOCR-VL (ocr_vl) --------------------------------------------------
//
// A chat-shaped model whose tokenizer and image preprocessing are the worker's
// job (they need the model's own chat template and a fixed vit stage), so this
// side is only the NPU: one prompt in, then one token per call. The KV cache is
// allocated with the weights and reused, which is the whole point of a resident
// worker -- MYS-2660 measured the prototype spending ~7 s of each element's
// ~8 s reloading the 2.27 GB bmodel.

void* cv_vl_create(const char* model_path, int dev_id, const char** err) {
  auto* e = new (std::nothrow) cv84x6::VlEngine();
  if (!e) {
    set_error(err, "out of memory allocating VlEngine");
    return nullptr;
  }
  if (!e->load(model_path ? model_path : "", dev_id)) {
    set_error(err, e->last_error());
    delete e;
    return nullptr;
  }
  return e;
}

void cv_vl_destroy(void* h) { delete static_cast<cv84x6::VlEngine*>(h); }

// ``*image_tokens`` is the vit row count divided by the spatial merge, i.e. the
// number of prompt rows one image occupies at the bmodel's fixed vit stage.
void cv_vl_info(void* h, int* seqlen, int* layers, int* hidden, int* image_tokens,
                int* vit_patches, unsigned long long* kv_bytes_per_layer) {
  auto* e = static_cast<cv84x6::VlEngine*>(h);
  if (!e) return;
  if (seqlen) *seqlen = e->seq_len();
  if (layers) *layers = e->num_layers();
  if (hidden) *hidden = e->hidden_size();
  if (image_tokens) *image_tokens = e->image_tokens();
  if (vit_patches) *vit_patches = e->vit_patches();
  if (kv_bytes_per_layer) {
    *kv_bytes_per_layer = static_cast<unsigned long long>(e->kv_bytes_per_layer());
  }
}

// ``patches`` is grid_h*grid_w*3*14*14 floats, patch-major and already
// normalised; ``ids`` is the prompt with ``head_len`` text tokens before the
// image block and grid_h/2 * grid_w/2 placeholder rows there.
int cv_vl_prefill(void* h, const int* ids, int n_ids, int head_len, int grid_h,
                  int grid_w, const float* patches, const char** err) {
  auto* e = static_cast<cv84x6::VlEngine*>(h);
  if (!e) {
    set_error(err, "null vl engine");
    return -1;
  }
  if (!ids || !patches) {
    set_error(err, "cv_vl_prefill: null input");
    return -1;
  }
  if (!e->prefill(reinterpret_cast<const int32_t*>(ids), n_ids, head_len, grid_h,
                  grid_w, patches)) {
    set_error(err, e->last_error());
    return -1;
  }
  return 0;
}

// The next token id, or -1 on failure (see cv_vl_last_error).
int cv_vl_step(void* h, const char** err) {
  auto* e = static_cast<cv84x6::VlEngine*>(h);
  if (!e) {
    set_error(err, "null vl engine");
    return -1;
  }
  const int32_t tok = e->step();
  if (tok < 0) {
    set_error(err, e->last_error());
    return -1;
  }
  return static_cast<int>(tok);
}

// Stage timings of the last request, in milliseconds, plus its token counts.
// Any pointer may be NULL.
void cv_vl_timings(void* h, double* vit_ms, double* embed_ms, double* prefill_ms,
                   double* decode_ms, double* lm_ms, int* prompt_tokens,
                   int* image_tokens, int* decode_steps) {
  auto* e = static_cast<cv84x6::VlEngine*>(h);
  if (!e) return;
  const cv84x6::VlTimings tm = e->timings();
  if (vit_ms) *vit_ms = tm.vit_ms;
  if (embed_ms) *embed_ms = tm.embed_ms;
  if (prefill_ms) *prefill_ms = tm.prefill_ms;
  if (decode_ms) *decode_ms = tm.decode_ms;
  if (lm_ms) *lm_ms = tm.lm_ms;
  if (prompt_tokens) *prompt_tokens = tm.prompt_tokens;
  if (image_tokens) *image_tokens = tm.image_tokens;
  if (decode_steps) *decode_steps = tm.decode_steps;
}

}  // extern "C"
