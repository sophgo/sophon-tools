/* A stand-in for libcv84x6_llm.so: enough of the C ABI for app/engine/native.py
 * to run its real code paths on a machine with no NPU and no bmodel.
 *
 * It exists for one question a mock cannot answer: does the Python side hand
 * the engine the addresses of the arrays it built, or something else? So the
 * prefill/extend entry points do no arithmetic -- they record every pointer
 * argument, and the test reads the memory back through those pointers and
 * compares it with the arrays and the values it knows it passed. Tokenising
 * and image preprocessing are deterministic fakes with fixed sizes, so the
 * expected values are known without a reference implementation.
 *
 * The struct below is mirrored in tests/test_native_ctypes.py; keep the two in
 * step.
 */
#include <stdint.h>
#include <string.h>

#define VIT_DIMS 1536
#define GRID_T 1
#define GRID_H 4
#define GRID_W 4
#define MAX_IMAGES 8
#define MAX_COPY 512

/* Special tokens, so the Python side can look them up by name. */
#define ID_VISION_START 10
#define ID_VISION_END 12
#define ID_IMAGE_PAD 11
#define ID_IM_START 13
#define ID_IM_END 14
#define ID_ENDOFTEXT 15

struct llm_test_call {
  int is_extend;
  int n;
  int n_images;
  intptr_t tokens;
  intptr_t pos3;
  intptr_t offsets;
  intptr_t patches;
  intptr_t pixels[MAX_IMAGES];
  intptr_t pos_ids[MAX_IMAGES];
  intptr_t pos_idx[MAX_IMAGES];
  intptr_t pos_weight[MAX_IMAGES];
  /* Copies taken during the call. _prefill builds the token, position and
   * per-image metadata arrays as locals, so they are gone once it returns;
   * these are what the engine actually read at the time. */
  int n_tokens;
  int n_pos3;
  int tokens_copy[MAX_COPY];
  int pos3_copy[3 * MAX_COPY];
  int offsets_copy[MAX_IMAGES];
  int patches_copy[MAX_IMAGES];
};

static const char* g_error = 0;
static int g_token_len = 0;
static int g_engine = 0;
static int g_session = 0;
static int g_tokenizer = 0;
static struct llm_test_call g_last;
static int g_calls = 0;

/* -- what the test reads back ---------------------------------------------- */

const struct llm_test_call* llm_test_last(void) { return &g_last; }
int llm_test_calls(void) { return g_calls; }
int llm_test_token_len(void) { return g_token_len; }

void llm_test_reset(void) {
  memset(&g_last, 0, sizeof(g_last));
  g_calls = 0;
  g_token_len = 0;
}

/* Dereference exactly what the engine would: proves the recorded address is
 * the base of a readable buffer with the values the Python side generated. */
int llm_test_read_int(intptr_t p, int i) { return ((const int*)p)[i]; }
float llm_test_read_float(intptr_t p, int i) { return ((const float*)p)[i]; }

/* -- engine ---------------------------------------------------------------- */

const char* llm_last_error(void) { return g_error; }

void* llm_engine_load(const char* model, int dev, const char** err) {
  (void)model; (void)dev; (void)err;
  return &g_engine;
}
void llm_engine_free(void* e) { (void)e; }

int llm_engine_num_layers(void* e) { (void)e; return 40; }
int llm_engine_context_length(void* e) { (void)e; return 4096; }
int llm_engine_max_input_length(void* e) { (void)e; return 2048; }
int llm_engine_hidden_size(void* e) { (void)e; return 2048; }
int llm_engine_has_vision(void* e) { (void)e; return 1; }
int llm_engine_vit_max_patches(void* e) { (void)e; return 2304; }
int llm_engine_vit_dims(void* e) { (void)e; return VIT_DIMS; }
int llm_engine_supports_history(void* e) { (void)e; return 1; }
int llm_engine_fault(void* e) { (void)e; return 0; }

unsigned long long llm_engine_session_state_bytes(void* e) { (void)e; return 32u * 1024u * 1024u; }
unsigned long long llm_engine_kv_bytes_per_token(void* e) { (void)e; return 1024; }
unsigned long long llm_engine_linear_state_bytes(void* e) { (void)e; return 0; }

/* -- tokenizer ------------------------------------------------------------- */

struct special { const char* text; int id; };
static const struct special g_specials[] = {
  {"<|vision_start|>", ID_VISION_START},
  {"<|vision_end|>", ID_VISION_END},
  {"<|image_pad|>", ID_IMAGE_PAD},
  {"<|im_start|>", ID_IM_START},
  {"<|im_end|>", ID_IM_END},
};
#define N_SPECIALS ((int)(sizeof(g_specials) / sizeof(g_specials[0])))

void* llm_tokenizer_load(const char* path, const char** err) {
  (void)path; (void)err;
  return &g_tokenizer;
}
void llm_tokenizer_free(void* h) { (void)h; }

/* One id per byte, except the specials, which are one id each -- so a prompt
 * keeps its <|vision_start|>/<|image_pad|> markers within reach of the test. */
static int encode_into(const char* text, int* out, int cap) {
  int n = 0;
  const char* p = text;
  while (*p) {
    int matched = 0;
    for (int i = 0; i < N_SPECIALS; i++) {
      size_t len = strlen(g_specials[i].text);
      if (strncmp(p, g_specials[i].text, len) == 0) {
        if (out && n < cap) out[n] = g_specials[i].id;
        n++;
        p += len;
        matched = 1;
        break;
      }
    }
    if (matched) continue;
    if (out && n < cap) out[n] = 1000 + (unsigned char)*p;
    n++;
    p++;
  }
  return n;
}

int llm_tokenizer_encode(void* h, const char* text, int* out, int cap, const char** err) {
  (void)h; (void)err;
  return encode_into(text, out, cap);
}

/* Decode: one id per byte, the exact inverse of encode_into, so a prompt
 * round-trips and a test can see that a single id may hold only part of a
 * UTF-8 character. The size-then-fill protocol is the real library's: with
 * out == NULL the caller is asking how many bytes it needs. */
static int decode_into(const int* ids, int n, char* out, int cap, int skip_special) {
  int written = 0;
  for (int i = 0; i < n; i++) {
    const int id = ids[i];
    const char* lit = 0;
    for (int k = 0; k < N_SPECIALS; k++)
      if (g_specials[k].id == id) lit = g_specials[k].text;
    if (!lit) {
      /* A byte id (and any id encode never produces: nothing to add). */
      if (id >= 1000 && id < 1256) {
        if (out && written < cap) out[written] = (char)(id - 1000);
        written++;
      }
      continue;
    }
    if (skip_special) continue;
    for (size_t j = 0; lit[j]; j++) {
      if (out && written < cap) out[written] = lit[j];
      written++;
    }
  }
  return written;
}

int llm_tokenizer_decode(void* h, const int* ids, int n, char* out, int cap,
                         int skip_special, const char** err) {
  (void)h; (void)err;
  if (!out || cap <= 0) return decode_into(ids, n, 0, 0, skip_special);
  return decode_into(ids, n, out, cap, skip_special);
}

int llm_tokenizer_token_to_id(void* h, const char* token) {
  (void)h;
  for (int i = 0; i < N_SPECIALS; i++)
    if (strcmp(token, g_specials[i].text) == 0) return g_specials[i].id;
  if (strcmp(token, "<|endoftext|>") == 0) return ID_ENDOFTEXT;
  return -1;
}

int llm_tokenizer_vocab_size(void* h) { (void)h; return 2000; }

/* The engine's token range check. Recorded so the test can assert the worker
   told the engine the tokenizer's vocabulary size on load. */
int g_vocab_set = -1;
int llm_engine_vocab_size(void* e) { (void)e; return g_vocab_set; }
void llm_engine_set_vocab_size(void* e, int n) { (void)e; g_vocab_set = n; }

/* -- vision ---------------------------------------------------------------- */

int llm_image_preprocess(const char* blob, int blen, int max_patches, int patch,
                         int merge, int temporal, long long min_pixels,
                         long long max_pixels, int* info, float* out,
                         const char** err) {
  (void)blob; (void)blen; (void)max_patches; (void)patch; (void)merge;
  (void)temporal; (void)min_pixels; (void)max_pixels; (void)err;
  if (info) {
    info[0] = GRID_T;
    info[1] = GRID_H;
    info[2] = GRID_W;
  }
  int n = GRID_T * GRID_H * GRID_W * VIT_DIMS;
  if (out)
    for (int i = 0; i < n; i++) out[i] = (float)i * 0.5f;
  return n;
}

void llm_vision_pos_tables(int t, int gh, int gw, int side, int* pos_ids,
                           int* pos_idx, float* pos_weight) {
  (void)side;
  int patches = t * gh * gw;
  for (int i = 0; i < patches; i++) {
    pos_ids[2 * i] = i;
    pos_ids[2 * i + 1] = i + 100;
    for (int j = 0; j < 4; j++) {
      pos_idx[4 * i + j] = 3 * i + j;
      pos_weight[4 * i + j] = (float)(i + j) * 0.25f;
    }
  }
}

int llm_vision_rope(const int* tokens, int n, const int* grids, int n_images,
                    int vision_start, int pad_id, int merge, int* pos3,
                    const char** err) {
  (void)tokens; (void)grids; (void)n_images; (void)vision_start; (void)pad_id;
  (void)merge; (void)err;
  for (int r = 0; r < 3; r++)
    for (int i = 0; i < n; i++) pos3[r * n + i] = 1000 * (r + 1) + i;
  return 0;
}

/* -- sessions -------------------------------------------------------------- */

void* llm_session_new(void* e, const char** err) { (void)e; (void)err; return &g_session; }
void llm_session_free(void* s) { (void)s; }
int llm_session_token_len(void* s) { (void)s; return g_token_len; }

int llm_session_decode(void* e, void* s, const char** err) {
  (void)e; (void)s; (void)err;
  return ID_ENDOFTEXT;
}

void* llm_session_snapshot(void* e, void* s, const char** err) {
  (void)e; (void)s; (void)err;
  return 0;
}
int llm_session_restore(void* e, void* s, void* snap, const char** err) {
  (void)e; (void)s; (void)snap; (void)err;
  return -1;
}
void llm_snapshot_free(void* snap) { (void)snap; }
unsigned long long llm_snapshot_bytes(void* snap) { (void)snap; return 0; }

static void record(int is_extend, const int* tokens, int n, const int* pos3,
                   int n_images, const int* offsets, const int* patches,
                   const float* const* pixels, const int* const* pos_ids,
                   const int* const* pos_idx, const float* const* pos_weight) {
  memset(&g_last, 0, sizeof(g_last));
  g_last.is_extend = is_extend;
  g_last.n = n;
  g_last.n_images = n_images;
  g_last.tokens = (intptr_t)tokens;
  g_last.pos3 = (intptr_t)pos3;
  g_last.offsets = (intptr_t)offsets;
  g_last.patches = (intptr_t)patches;
  int k = n_images < MAX_IMAGES ? n_images : MAX_IMAGES;
  for (int i = 0; i < k; i++) {
    /* These four are arrays *of pointers*; the element is the buffer address
     * the engine reads rows from. Those buffers outlive the call (they belong
     * to the Prompt), so the test can read them back afterwards. */
    g_last.pixels[i] = (intptr_t)pixels[i];
    g_last.pos_ids[i] = (intptr_t)pos_ids[i];
    g_last.pos_idx[i] = (intptr_t)pos_idx[i];
    g_last.pos_weight[i] = (intptr_t)pos_weight[i];
    g_last.offsets_copy[i] = offsets[i];
    g_last.patches_copy[i] = patches[i];
  }
  int nt = n < MAX_COPY ? n : MAX_COPY;
  g_last.n_tokens = nt;
  if (tokens)
    for (int i = 0; i < nt; i++) g_last.tokens_copy[i] = tokens[i];
  if (pos3) {
    int np = 3 * n < 3 * MAX_COPY ? 3 * n : 3 * MAX_COPY;
    g_last.n_pos3 = np;
    for (int i = 0; i < np; i++) g_last.pos3_copy[i] = pos3[i];
  }
  g_calls++;
}

int llm_session_prefill(void* e, void* s, const int* tokens, int n,
                        const int* pos3, int n_images, const int* offsets,
                        const int* patches, const float* const* pixels,
                        const int* const* pos_ids, const int* const* pos_idx,
                        const float* const* pos_weight, const char** err) {
  (void)e; (void)s; (void)err;
  record(0, tokens, n, pos3, n_images, offsets, patches, pixels, pos_ids,
         pos_idx, pos_weight);
  g_token_len = n;
  return 0;
}

int llm_session_extend(void* e, void* s, const int* tokens, int n,
                       const int* pos3, int n_images, const int* offsets,
                       const int* patches, const float* const* pixels,
                       const int* const* pos_ids, const int* const* pos_idx,
                       const float* const* pos_weight, const char** err) {
  (void)e; (void)s; (void)err;
  record(1, tokens, n, pos3, n_images, offsets, patches, pixels, pos_ids,
         pos_idx, pos_weight);
  g_token_len += n;
  return 0;
}

/* -- auxiliary engines (embedding / rerank) --------------------------------
 *
 * Same doctrine as the chat side above: record what the binding handed the
 * engine, so the test can read the memory back through those pointers. The
 * arithmetic is a fixed pattern (element i of the vector is i/1000, the logit is
 * the token sum scaled), which lets the test assert the *conversion* it does
 * on top -- L2 normalisation, sigmoid -- without a bmodel.
 */
#define AUX_HIDDEN 1024
#define AUX_SEQ 2048

static int g_embed_handle = 0;
static int g_rerank_handle = 0;
static struct {
  int n;
  int dim;
  int tokens_copy[MAX_COPY];
  intptr_t out;
} g_embed_call;
static struct {
  intptr_t ids;
  intptr_t pos;
  intptr_t mask;
  int ids_copy[64];
  int pos_copy[64];
  int mask_copy[64];
  intptr_t out;
} g_rerank_call;

const int* llm_test_embed_last(int* n, int* dim) {
  if (n) *n = g_embed_call.n;
  if (dim) *dim = g_embed_call.dim;
  return g_embed_call.tokens_copy;
}
int llm_test_embed_out(int i) { return (int)g_embed_call.out; }
float llm_test_read_out_float(intptr_t p, int i) { return ((const float*)p)[i]; }

const int* llm_test_rerank_last(int* n) {
  if (n) *n = g_rerank_call.ids_copy[0];
  return g_rerank_call.pos_copy;
}
int llm_test_rerank_ids(int i) { return g_rerank_call.ids_copy[i]; }
int llm_test_rerank_pos(int i) { return g_rerank_call.pos_copy[i]; }
int llm_test_rerank_mask(int i) { return g_rerank_call.mask_copy[i]; }

void* cv_embed_create(const char* model, int dev, const char** err) {
  (void)dev;
  if (model == 0 || model[0] == '\0') {
    g_error = "embed: empty model path";
    if (err) *err = g_error;
    return 0;
  }
  return &g_embed_handle;
}

void cv_embed_destroy(void* h) { (void)h; }

void cv_embed_info(void* h, int* seqlen, int* hidden) {
  (void)h;
  if (seqlen) *seqlen = AUX_SEQ;
  if (hidden) *hidden = AUX_HIDDEN;
}

int cv_embed_forward(void* h, const int* ids, int n, int dim, float* out,
                     const char** err) {
  (void)h;
  if (n > AUX_SEQ || n <= 0) {
    g_error = "embed: bad token count";
    if (err) *err = g_error;
    return -1;
  }
  if (dim <= 0 || dim > AUX_HIDDEN) {
    g_error = "embed: bad dim";
    if (err) *err = g_error;
    return -1;
  }
  g_embed_call.n = n;
  g_embed_call.dim = dim;
  g_embed_call.out = (intptr_t)out;
  for (int i = 0; i < n && i < MAX_COPY; i++) g_embed_call.tokens_copy[i] = ids[i];
  /* Not normalised: the binding does that, and this is what pins it there. */
  for (int i = 0; i < dim; i++) out[i] = (float)(i + 1);
  return 0;
}

void* cv_rerank_create(const char* model, int dev, const char** err) {
  (void)dev;
  if (model == 0 || model[0] == '\0') {
    g_error = "rerank: empty model path";
    if (err) *err = g_error;
    return 0;
  }
  return &g_rerank_handle;
}

void cv_rerank_destroy(void* h) { (void)h; }

void cv_rerank_info(void* h, int* seqlen, int* hidden) {
  (void)h;
  if (seqlen) *seqlen = AUX_SEQ;
  if (hidden) *hidden = AUX_HIDDEN;
}

int cv_rerank_forward(void* h, const int* ids, const int* pos, const int* mask,
                      float* out, const char** err) {
  (void)h;
  if (ids == 0 || pos == 0 || mask == 0 || out == 0) {
    g_error = "rerank: null argument";
    if (err) *err = g_error;
    return -1;
  }
  g_rerank_call.ids = (intptr_t)ids;
  g_rerank_call.pos = (intptr_t)pos;
  g_rerank_call.mask = (intptr_t)mask;
  g_rerank_call.out = (intptr_t)out;
  for (int i = 0; i < 64; i++) {
    g_rerank_call.ids_copy[i] = ids[i];
    g_rerank_call.pos_copy[i] = pos[i];
    g_rerank_call.mask_copy[i] = mask[i];
  }
  /* A fixed logit: the API's sigmoid is what a caller sees, and it is applied
   * a layer up (app/api/openai_api.py), not here. */
  *out = 2.0f;
  return 0;
}

/* -- ASR engine ------------------------------------------------------------
 *
 * Same doctrine again: record what the binding handed the engine so the test can
 * read it back. The engine is stateful (clear -> audio -> first -> next*), so the
 * stub keeps a tiny state machine: each forward_next returns ids from a fixed
 * script, which is how "the loop stops on the stop token" and "the decode rule
 * drops the preamble" become checkable without an NPU.
 */
#define ASR_SEQ 1024
#define ASR_MAX_INPUT 512
#define ASR_AUDIO_LEN 100
#define ASR_PER_CHUNK 13
#define ASR_HIDDEN 1024
#define ASR_IM_END 7
/* Features are kept up to one whole chunk plus one sample of the next, which is
 * enough to prove the layout is chunk-major without holding 38 s of audio. */
#define ASR_FEAT_COPY (128 * ASR_AUDIO_LEN + 1)

static int g_asr_handle = 0;
static int g_asr_vocab = 0;
static int g_asr_im_end = -1;
static int g_asr_cleared = 0;
static struct {
  int n_chunks;
  int first_offset;
  int offsets[MAX_COPY];
  float feats[ASR_FEAT_COPY];
  int feat_count;
} g_asr_audio;
static struct {
  int n;
  int tokens[MAX_COPY];
  int calls;
} g_asr_first;
static int g_asr_next_calls = 0;

/* The script forward_next walks. A test sets it through llm_test_asr_script. */
static int g_asr_script[64];
static int g_asr_script_len = 0;
static int g_asr_script_pos = 0;

void llm_test_asr_set_script(const int* tokens, int n) {
  g_asr_script_len = n > 64 ? 64 : n;
  for (int i = 0; i < g_asr_script_len; i++) g_asr_script[i] = tokens[i];
  g_asr_script_pos = 0;
  g_asr_next_calls = 0;
}

int llm_test_asr_cleared(void) { return g_asr_cleared; }
int llm_test_asr_next_calls(void) { return g_asr_next_calls; }
int llm_test_asr_vocab(void) { return g_asr_vocab; }
int llm_test_asr_audio_chunks(void) { return g_asr_audio.n_chunks; }
int llm_test_asr_audio_feat_count(void) { return g_asr_audio.feat_count; }
int llm_test_asr_audio_offset(int i) { return g_asr_audio.offsets[i]; }
float llm_test_asr_audio_feat(int i) { return g_asr_audio.feats[i]; }
int llm_test_asr_first_len(void) { return g_asr_first.n; }
int llm_test_asr_first_token(int i) { return g_asr_first.tokens[i]; }
int llm_test_asr_first_calls(void) { return g_asr_first.calls; }

void llm_test_asr_reset(void) {
  memset(&g_asr_audio, 0, sizeof(g_asr_audio));
  memset(&g_asr_first, 0, sizeof(g_asr_first));
  g_asr_cleared = 0;
  g_asr_next_calls = 0;
  g_asr_script_len = 0;
  g_asr_script_pos = 0;
}

void* cv_asr_create(const char* model, int dev, const char** err) {
  (void)dev;
  if (model == 0 || model[0] == '\0') {
    g_error = "asr: empty model path";
    if (err) *err = g_error;
    return 0;
  }
  return &g_asr_handle;
}

void cv_asr_destroy(void* h) { (void)h; }

void cv_asr_info(void* h, int* seqlen, int* max_input, int* audio_length,
                 int* hidden, int* per_chunk) {
  (void)h;
  if (seqlen) *seqlen = ASR_SEQ;
  if (max_input) *max_input = ASR_MAX_INPUT;
  if (audio_length) *audio_length = ASR_AUDIO_LEN;
  if (hidden) *hidden = ASR_HIDDEN;
  if (per_chunk) *per_chunk = ASR_PER_CHUNK;
}

void cv_asr_set_vocab(void* h, int vocab, int im_end) {
  (void)h;
  g_asr_vocab = vocab;
  g_asr_im_end = im_end;
}

int cv_asr_im_end(void* h) { (void)h; return g_asr_im_end; }

int cv_asr_forward_audio(void* h, const float* feats, int n_chunks,
                         const int* offsets, const char** err) {
  (void)h;
  if (feats == 0 || offsets == 0) {
    g_error = "asr: null audio argument";
    if (err) *err = g_error;
    return -1;
  }
  g_asr_audio.n_chunks = n_chunks;
  g_asr_audio.first_offset = n_chunks > 0 ? offsets[0] : -1;
  for (int i = 0; i < n_chunks && i < MAX_COPY; i++) g_asr_audio.offsets[i] = offsets[i];
  int count = n_chunks * 128 * ASR_AUDIO_LEN;
  g_asr_audio.feat_count = count;
  int keep = count > ASR_FEAT_COPY ? ASR_FEAT_COPY : count;
  for (int i = 0; i < keep; i++) g_asr_audio.feats[i] = feats[i];
  return 0;
}

int cv_asr_forward_first(void* h, const int* ids, int n, const char** err) {
  (void)h;
  if (ids == 0 || n <= 0) {
    g_error = "asr: empty prompt";
    if (err) *err = g_error;
    return -1;
  }
  if (n > ASR_MAX_INPUT) {
    g_error = "asr: prompt longer than MAX_INPUT_LENGTH";
    if (err) *err = g_error;
    return -1;
  }
  g_asr_first.calls++;
  g_asr_first.n = n > MAX_COPY ? MAX_COPY : n;
  for (int i = 0; i < g_asr_first.n; i++) g_asr_first.tokens[i] = ids[i];
  /* The first generated token is the first of the script, as the real engine's
   * prefill returns a token rather than logits. */
  g_asr_script_pos = 0;
  return g_asr_script_len > 0 ? g_asr_script[g_asr_script_pos++] : ASR_IM_END;
}

int cv_asr_forward_next(void* h, const char** err) {
  (void)h;
  (void)err;
  g_asr_next_calls++;
  if (g_asr_script_pos >= g_asr_script_len) return ASR_IM_END;
  return g_asr_script[g_asr_script_pos++];
}

void cv_asr_clear(void* h) { (void)h; g_asr_cleared++; }

/* -- generic single-graph runner (OCR det/rec) ----------------------------
 *
 * Two graphs, shaped like the two the service actually loads: "det"
 * ([1,3,736,736] -> [1,1,736,736]) and "rec1600" ([1,3,48,1600] ->
 * [1,200,18710]). The graph is chosen by the model path, so a test can drive
 * both through the same binding.
 *
 * The forward is a fixed, checkable transform rather than an echo: output[0] is
 * the input's maximum and output[1] its sum, and the rest of the map is a ramp.
 * That is enough to pin (a) which buffer the engine was handed, (b) that it was
 * the right size, and (c) which output array the result landed in -- without
 * the test having to reimplement the model.
 */
#define NET_DET_IN (1 * 3 * 736 * 736)
#define NET_DET_OUT (1 * 1 * 736 * 736)
#define NET_REC_IN (1 * 3 * 48 * 1600)
#define NET_REC_OUT (1 * 200 * 18710)
/* A rank-5 tensor is impossible in a CNN but legal in bm_shape_t; used to check
 * the binding does not assume a fixed rank. */
#define NET_MAX_RANK 8

static int g_net_handle = 0;
static const char* g_net_error = 0;
static int g_net_kind = 0;  /* 1 = det, 2 = rec */
static struct {
  int ran;
  int stage;
  float in_first;
  float in_max;
  double in_sum;
  long long in_count;
  int out_written;
} g_net_call;

int llm_test_net_ran(void) { return g_net_call.ran; }
int llm_test_net_stage(void) { return g_net_call.stage; }
float llm_test_net_in_first(void) { return g_net_call.in_first; }
float llm_test_net_in_max(void) { return g_net_call.in_max; }
double llm_test_net_in_sum(void) { return g_net_call.in_sum; }
long long llm_test_net_in_count(void) { return g_net_call.in_count; }
int llm_test_net_out_written(void) { return g_net_call.out_written; }

void llm_test_net_reset(void) {
  memset(&g_net_call, 0, sizeof(g_net_call));
  g_net_kind = 0;
  g_net_error = 0;
}

void* cv_net_create(const char* model, int dev, const char** err) {
  (void)dev;
  if (model == 0 || model[0] == '\0') {
    g_net_error = "net: empty model path";
    if (err) *err = g_net_error;
    return 0;
  }
  /* The path picks the graph. Anything mentioning "rec" is the recogniser, so
   * the 48x1600 build; otherwise the 736 detector. A path containing
   * "multi" fails, standing in for a bmodel with more than one graph. */
  if (strstr(model, "multi") != 0) {
    g_net_error = "bmodel contains 94 graphs; this engine runs exactly one";
    if (err) *err = g_net_error;
    return 0;
  }
  g_net_kind = strstr(model, "rec") != 0 ? 2 : 1;
  return &g_net_handle;
}

void cv_net_destroy(void* h) { (void)h; }

int cv_net_info(void* h, int* n_in, int* n_out, int* n_stage, int* ranks,
                int dims_cap, int* dims) {
  (void)h;
  if (n_in) *n_in = 1;
  if (n_out) *n_out = 1;
  if (n_stage) *n_stage = 1;
  if (ranks == 0 || dims == 0 || dims_cap <= 0) return 0;
  ranks[0] = 4;
  ranks[1] = g_net_kind == 2 ? 3 : 4;
  if (g_net_kind == 2) {
    const int in[4] = {1, 3, 48, 1600};
    const int out[4] = {1, 200, 18710};
    for (int i = 0; i < 4; i++) {
      dims[0 * dims_cap + i] = in[i];
      dims[1 * dims_cap + i] = out[i];
    }
    /* rank 3 means only the first three of the output's entries count */
    (void)out;
  } else {
    const int in[4] = {1, 3, 736, 736};
    const int out[4] = {1, 1, 736, 736};
    for (int i = 0; i < 4; i++) {
      dims[0 * dims_cap + i] = in[i];
      dims[1 * dims_cap + i] = out[i];
    }
  }
  return 0;
}

long long cv_net_elements(void* h, int which, int index) {
  (void)h;
  if (index > 0) return -1;
  if (which == 0) return g_net_kind == 2 ? NET_REC_IN : NET_DET_IN;
  return g_net_kind == 2 ? NET_REC_OUT : NET_DET_OUT;
}

int cv_net_dtype(void* h, int which, int index) {
  (void)h; (void)which; (void)index;
  return 0; /* BM_FLOAT32 */
}

int cv_net_run(void* h, int stage, const float* const* in, float* const* out,
               const char** err) {
  (void)h;
  if (in == 0 || in[0] == 0 || out == 0 || out[0] == 0) {
    g_net_error = "net: null tensor pointer";
    if (err) *err = g_net_error;
    return -1;
  }
  if (stage != 0) {
    g_net_error = "net: stage out of range";
    if (err) *err = g_net_error;
    return -1;
  }
  const long long n = g_net_kind == 2 ? NET_REC_IN : NET_DET_IN;
  const long long m = g_net_kind == 2 ? NET_REC_OUT : NET_DET_OUT;
  float max = in[0][0];
  double sum = 0.0;
  for (long long i = 0; i < n; i++) {
    if (in[0][i] > max) max = in[0][i];
    sum += (double)in[0][i];
  }
  g_net_call.ran++;
  g_net_call.stage = stage;
  g_net_call.in_first = in[0][0];
  g_net_call.in_max = max;
  g_net_call.in_sum = sum;
  g_net_call.in_count = n;
  /* A recognisable map: the max in element 0 so a test can assert the buffer
   * was read, then a descending ramp. */
  out[0][0] = max;
  for (long long i = 1; i < m; i++) {
    out[0][i] = (float)((m - i) % 97) * 0.01f;
  }
  g_net_call.out_written = 1;
  return 0;
}
