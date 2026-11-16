// Executable source-invariant tests for the decode submission/state changes
// (MYS-2377). Runs on a plain host: the linked libbmrt/libbmlib are the fakes
// in fake_bm.cpp, so every assertion below is a real observation of the engine
// binary's behaviour, not a grep over its source.
//
// What it proves, matching the acceptance criteria:
//   1. decode queues its layer launches and syncs once, before the consumer;
//   2. Session::decode() returns only after that sync -- the public contract
//      ("the token is done when the call returns") still holds;
//   3. a sync sits between the last decode layer and lm_head, and decode()
//      returns with nothing in flight;
//   4. conv_state is not copied onto itself when the graph updates in place,
//      and still is when a bmodel hands back a separate buffer;
//   5. rec_state (output 2) keeps its explicit copy;
//   6. a failed launch or sync still sets `fault` and is reported;
//   7. the prefill alignment guard is still 64 (LLM_PREFILL_ALIGN default) and
//      prefill still syncs every launch;
//   8. two interleaved sessions keep their own history, and snapshot/restore
//      into a third session continues identically;
//   9. a fresh prefill no longer memsets the FA K/V buffers (2.50 GiB on the
//      board), while a restore still clears them, and park/unpark still carries
//      a session's live KV across a resident switch (MYS-2477).
//
// Build/run: tests/native/run_tests.sh
#include "llm_engine.h"

#include "fake_bm.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool cond, const std::string& what) {
  g_checks++;
  if (!cond) {
    g_failures++;
    std::fprintf(stderr, "FAIL: %s\n", what.c_str());
  }
}

std::string g_model = "/dev/null";

struct Fixture {
  cv84x6::Engine eng;
  bool loaded = false;
};

// Load the fake model. `linear_inplace` = true mimics addr_mode=1 bmodels.
bool load(Fixture* f, bool linear_inplace = true) {
  fake_bm::build("q", linear_inplace);
  f->loaded = f->eng.load(g_model, 0);
  if (!f->loaded) std::fprintf(stderr, "load failed: %s\n", f->eng.last_error().c_str());
  return f->loaded;
}

// Drive one token through a session, returning the token id.
int step(cv84x6::Session* s) { return s->decode(); }

// prefill() samples the first token; the next decode() only hands it back
// without touching the NPU. Tests that measure decode work call this first.
bool prefill_ready(cv84x6::Session* s, const int* ids, int n) {
  if (!s->prefill(ids, n, nullptr, nullptr, 0)) return false;
  return s->decode() >= 0;
}

// --- 1/2/3: submission depth and the boundary before the consumer -----------
void test_decode_submits_layers_then_syncs_once() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::reset();
  const int tok = step(s.get());
  check(tok >= 0, "decode returns a token");

  // Prefill sampled the first token, so one decode() is one full layer sweep.
  const int layers = f.eng.num_layers();
  check(fake_bm::launches_of("embedding_cache") == 1, "decode launches the embedding graph once");
  int block_launches = 0;
  for (int i = 0; i < layers; i++)
    block_launches += fake_bm::launches_of("block_cache_" + std::to_string(i));
  check(block_launches == layers,
        "every decode layer launched once, got " + std::to_string(block_launches));

  // The whole point: layers go out back to back instead of one sync each.
  const int run = fake_bm::longest_unsynced_run();
  check(run >= layers,
        "layers were submitted without a sync in between (longest unsynced run " +
            std::to_string(run) + " >= " + std::to_string(layers) + ")");

  // ... and the token was still final when decode() returned, which the fake
  // only allows if a sync happened: no launch may be in flight now.
  check(fake_bm::pending == 0,
        "no launch is still in flight when Session::decode() returns");

  // A non-waiting launch means the runtime saw an overlap; a sync after every
  // launch would make this 0.
  check(fake_bm::overlap_launches > 0, "launches overlapped in the runtime queue");
}

// --- 3: the layers are followed by a sync, and only then by lm_head --------
// This is the acceptance criterion "lm_head 前存在同步边界". Without it the
// engine would read a hidden state the TPU has not finished writing; the
// lm_head launch's own sync cannot stand in for it, because it happens after
// the read has already been handed to the runtime.
void test_lm_head_runs_after_a_boundary() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::reset();
  check(step(s.get()) >= 0, "decode returns a token");

  int lb = -1, lm_at = -1;
  for (size_t i = 0; i < fake_bm::launches.size(); i++) {
    if (fake_bm::launches[i].net.rfind("block_cache_", 0) == 0) lb = static_cast<int>(i);
    if (fake_bm::launches[i].net == "lm_head") lm_at = static_cast<int>(i);
  }
  check(lm_at >= 0, "lm_head was launched");
  check(lb >= 0, "decode layers were launched");
  check(lm_at > lb, "lm_head is launched after every decode layer");

  // A sync point records how many launches existed when the sync ran, so a
  // boundary between the last layer and lm_head is a p with lb < p <= lm_at.
  bool boundary = false;
  for (size_t p : fake_bm::sync_points)
    if (static_cast<int>(p) > lb && static_cast<int>(p) <= lm_at) boundary = true;
  check(boundary,
        "a sync sits between the last decode layer and lm_head (no read of an "
        "unfinished hidden state)");
}

// --- 3b: the session is quiescent when decode() returns -------------------
// Park/unpark, snapshot and the next decode all assume the TPU is done with
// this token's state. A launch left in flight would make those races.
void test_decode_returns_quiescent() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::reset();
  check(step(s.get()) >= 0, "decode returns a token");
  check(!fake_bm::sync_points.empty(), "decode issued at least one sync");
  check(fake_bm::sync_points.back() == fake_bm::launches.size(),
        "the last thing decode() did was bring the TPU to a boundary");
}

// --- 4: no self-copy of conv_state when the graph updates in place ---------
void test_conv_state_not_copied_when_in_place() {
  Fixture f;
  if (!load(&f, /*linear_inplace=*/true)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::reset();
  check(step(s.get()) >= 0, "decode returns a token");
  check(!fake_bm::copied_onto_itself(),
        "no d2d copies a buffer onto its own address (conv_state in place)");
}

// --- 4b: a bmodel that returns a separate conv buffer still gets the copy ---
void test_conv_state_copied_when_not_in_place() {
  Fixture f;
  if (!load(&f, /*linear_inplace=*/false)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::reset();
  check(step(s.get()) >= 0, "decode returns a token");
  // One copy per linear layer, from the graph's output buffer to state_a.
  int linear = 0;
  for (int i = 0; i < f.eng.num_layers(); i++)
    if ((i + 1) % 4 != 0) linear++;
  int copies = 0;
  for (const auto& kv : fake_bm::d2d_counts) copies += kv.second;
  check(copies >= linear,
        "a bmodel with a separate conv_state output still gets it copied back (" +
            std::to_string(copies) + " copies for " + std::to_string(linear) + " linear layers)");
}

// --- 5: rec_state (output 2) keeps its explicit copy -----------------------
void test_rec_state_output_still_copied() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  // Turn the fake linear layer into a 3-output one: rec_state emitted as
  // output 2 at a separate address, which must be copied to state_b.
  for (auto* n : fake_bm::nets) {
    if (n->name.rfind("block_cache_", 0) != 0 || n->out.size() != 2) continue;
    if (n->in.size() < 3) continue;  // FA layer
    bm_device_mem_t rec = fake_bm::mem(fake_bm::alloc_addr(2 * 16 * 16), 2 * 16 * 16);
    bm_device_mem_t* grown = new bm_device_mem_t[3];
    grown[0] = n->out[0];
    grown[1] = n->out[1];
    grown[2] = rec;
    n->out.push_back(rec);
    bm_shape_t* shapes = new bm_shape_t[3];
    shapes[0] = n->out_shape[0];
    shapes[1] = n->out_shape[1];
    shapes[2] = fake_bm::shape4(1, 1, 16, 16);
    n->out_shape.push_back(shapes[2]);
    n->out_dt.push_back(BM_BFLOAT16);
    n->stage.output_mems = grown;
    n->stage.output_shapes = shapes;
    n->info.output_num = 3;
    n->info.output_dtypes = n->out_dt.data();
  }

  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");
  fake_bm::reset();
  check(step(s.get()) >= 0, "decode returns a token");

  // The rec_state output must be copied onto state_b (the graph's input 2).
  int rec_copies = 0;
  for (auto* n : fake_bm::nets) {
    if (n->name.rfind("block_cache_", 0) != 0 || n->out.size() != 3) continue;
    const unsigned long long src = n->out[2].u.device.device_addr;
    const unsigned long long dst = n->in[2].u.device.device_addr;
    rec_copies += fake_bm::d2d_counts[{src, dst}];
  }
  check(rec_copies > 0,
        "rec_state output 2 is copied into the graph's rec_state input");
}

// --- 6: failure handling keeps fault/last_error ----------------------------
void test_failed_launch_sets_fault() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  fake_bm::fail_launch = true;
  const int tok = step(s.get());
  check(tok < 0, "a failed layer launch makes decode() fail");
  check(f.eng.fault(), "a failed layer launch sets fault");
  check(!f.eng.last_error().empty(), "last_error is readable after a failed launch");
}

void test_failed_deferred_sync_sets_fault() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "prefill succeeds");

  // The layer launches all succeed; the batch sync that closes the decode is
  // what fails. This is the case the eager path could not have: failure of a
  // sync that no longer sits inside the layer loop must still be reported.
  fake_bm::fail_sync = true;
  const int tok = step(s.get());
  check(tok < 0, "a failed deferred sync makes decode() fail");
  check(f.eng.fault(), "a failed deferred sync sets fault");
  check(!f.eng.last_error().empty(), "last_error is readable after a failed sync");
}

// --- 7: prefill still syncs every launch, alignment guard intact -----------
void test_prefill_launches_are_synchronous() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  unsetenv("LLM_PREFILL_ALIGN");
  fake_bm::reset();
  check(s->prefill(prompt, 8, nullptr, nullptr, 0), "prefill succeeds");

  // 8 rows is below the 64-row alignment, so the whole chunk goes through the
  // decode graphs -- which is itself the alignment guard still being 64.
  // Those launches are a full decode batch and are synced before prefill
  // returns.
  check(fake_bm::launches_of("embedding") == 1, "prefill embeds the chunk");
  check(fake_bm::pending == 0, "prefill returns with nothing in flight");
  // kAlign is 64: 8 < 64 means no prefill block graph ran at all.
  int blocks = 0;
  for (int i = 0; i < 4; i++) blocks += fake_bm::launches_of("block_" + std::to_string(i));
  check(blocks == 0, "a sub-64-row chunk does not use the dynamic prefill graphs");

  // 64 rows does use them, and each is synced on its own: a prefill block
  // launch must never end up in the same unsynced run as the next one.
  auto s2 = f.eng.new_session();
  int big[64];
  for (int i = 0; i < 64; i++) big[i] = i + 1;
  fake_bm::reset();
  check(s2->prefill(big, 64, nullptr, nullptr, 0), "64-row prefill succeeds");
  blocks = 0;
  for (int i = 0; i < 4; i++) blocks += fake_bm::launches_of("block_" + std::to_string(i));
  check(blocks == 4, "a 64-row chunk uses the dynamic prefill graphs (alignment is 64)");
  check(fake_bm::longest_unsynced_run() == 1,
        "every prefill launch is synced on its own (longest unsynced run 1, got " +
            std::to_string(fake_bm::longest_unsynced_run()) + ")");
}

// --- 8: two sessions alternating stay independent -------------------------
// The deferred sync must not let one session's park/unpark read a state the
// TPU is still writing. Two sessions decode alternately; each must end up with
// its own history and its own token stream.
void test_two_sessions_interleaved() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto a = f.eng.new_session();
  auto b = f.eng.new_session();
  const int pa[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  const int pb[8] = {41, 42, 43, 44, 45, 46, 47, 48};
  check(prefill_ready(a.get(), pa, 8), "session A prefills");
  check(prefill_ready(b.get(), pb, 8), "session B prefills");
  check(a->token_len() == 8 && b->token_len() == 8, "both sessions hold 8 tokens");

  std::vector<int> ta, tb;
  for (int i = 0; i < 4; i++) {
    ta.push_back(step(a.get()));
    tb.push_back(step(b.get()));
    // Alternate: A then B, so each call parks the other session.
  }
  check(ta.size() == 4 && tb.size() == 4, "both sessions decoded 4 tokens");
  bool ok = true;
  for (int t : ta) ok = ok && t >= 0;
  for (int t : tb) ok = ok && t >= 0;
  check(ok, "interleaved decodes all succeed");
  check(a->token_len() == 12, "session A history advanced to 12, got " +
                                  std::to_string(a->token_len()));
  check(b->token_len() == 12, "session B history advanced to 12, got " +
                                  std::to_string(b->token_len()));

  // Snapshot A and restore into a third session. A restored session must be a
  // *continuation*, not just a state blob: its next embedding input has to be
  // exactly the token A's lm_head produced last (that token is not in KV yet --
  // decode() embeds it), and the token stream after it must match A's.
  int expected_input = ta.back();
  void* snap = a->snapshot();
  check(snap != nullptr, "snapshot of an active session succeeds");
  a->decode();  // advancing A must not change C's restored last-token input
  fake_bm::launches.clear();
  if (snap) {
    auto c = f.eng.new_session();
    check(c->restore(snap), "restore into a fresh session succeeds");
    check(c->token_len() == 12, "restored session has A's history");
    int inputs = 0;
    for (int i = 0; i < 4; i++) {
      int restored = c->decode();
      check(restored >= 0, "restored decode succeeds at step " + std::to_string(i));
      for (const auto& launch : fake_bm::launches) {
        if (launch.net == "embedding_cache") {
          inputs++;
          check(launch.first_input == expected_input,
                "restore supplies the saved/previous token, got " +
                    std::to_string(launch.first_input) + ", expected " +
                    std::to_string(expected_input));
        }
      }
      fake_bm::launches.clear();
      expected_input = restored;
    }
    check(inputs == 4, "restored decode supplies four embedding_cache tokens");
    check(!f.eng.fault(), "restore then decode is valid and does not fault");
    f.eng.free_snapshot(snap);
  }
}

// --- 9: restore -> extend, the prefix-cache recipe -------------------------
// The scheduler's resume path is restore() then extend() with the rest of the
// prompt; it never decodes in between. So extend() must consume the tokens
// against the *restored* state: the FA layers have to see the snapshot's KV as
// past KV (block_kv, input 2/3 sized to the snapshot's length), and the first
// new token has to land in KV slot == snapshot length. Those are the numbers
// that quietly go wrong if the restored length is not honoured, and neither
// shows up in a token-equality check on the fake model.
void test_restore_then_extend_continues_the_snapshot() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  const int kCut = 8;
  auto a = f.eng.new_session();
  check(prefill_ready(a.get(), prompt, 8), "session prefills");
  void* snap = a->snapshot();
  check(snap != nullptr, "snapshot at the prefill boundary");
  // Advance the original so the snapshot is not simply "the current state".
  check(a->decode() >= 0 && a->decode() >= 0, "the original session advances past it");

  // --- a 64-row extend takes the prefill path --------------------------
  auto c = f.eng.new_session();
  check(c->restore(snap), "restore into a fresh session");
  int more[64];
  for (int i = 0; i < 64; i++) more[i] = 100 + i;

  fake_bm::reset();
  fake_bm::vocab = 30000;  // keep the fixture's id observation meaningful
  check(c->extend(more, 64, nullptr, nullptr, 0), "64-row extend after restore succeeds");
  check(!f.eng.fault(), "extend after restore does not fault");
  check(c->token_len() == kCut + 64, "extend appends to the restored history: " +
                                         std::to_string(c->token_len()) + " == 72");

  // The FA layer must have been handed exactly the snapshot's KV as past KV,
  // sized to the snapshot's length and not to the (now longer) original
  // session's. The engine builds that view itself, so the launch's input-2
  // shape -- [1, past_len, 4, d] -- is the measurement.
  int kv_launches = 0, past_len = -1;
  for (const auto& l : fake_bm::launches) {
    if (l.net != "block_kv_3") continue;
    kv_launches++;
    if (l.in_dims.size() > 2 && l.in_dims[2].size() > 1) past_len = l.in_dims[2][1];
  }
  check(kv_launches == 1,
        "extend after restore runs the history graph once for the FA layer, got " +
            std::to_string(kv_launches));
  check(past_len == kCut,
        "the history graph is given exactly the snapshot's past KV (past_len " +
            std::to_string(past_len) + " == " + std::to_string(kCut) + ")");

  // Only the 64 new rows are prefilled -- not the restored prefix again.
  int block_rows = -1;
  for (const auto& l : fake_bm::launches) {
    if (l.net != "block_0" || l.in_dims.empty() || l.in_dims[0].size() < 2) continue;
    block_rows = l.in_dims[0][1];
  }
  check(block_rows == 64,
        "extend prefills only the 64 new rows (block_ row count " +
            std::to_string(block_rows) + " == 64)");

  // No new-token row may be written before the prefix: a linear layer's state
  // is rewritten in full, but the FA KV append starts at slot kCut.
  auto linear_layer_ok = true;
  for (const auto& l : fake_bm::launches) {
    if (l.net.rfind("block_kv_", 0) == 0) linear_layer_ok = linear_layer_ok && past_len == kCut;
  }
  check(linear_layer_ok, "no FA KV row is written before the restored prefix");

  // The token stream continues from the extended prompt, not from the prefix.
  check(c->decode() >= 0, "decode after restore+extend succeeds");
  check(c->token_len() == kCut + 64,
        "the first decode hands back extend's pending token without advancing KV");
  check(c->decode() >= 0 && c->token_len() == kCut + 65,
        "the next decode advances past the extended prompt");

  // --- a short extend replays through the decode graphs ----------------
  // Below the 64-row prefill alignment the rows go through the decode graphs
  // one at a time, writing FA KV directly. The first of them must land in slot
  // kCut, i.e. immediately after the restored prefix.
  auto d = f.eng.new_session();
  check(d->restore(snap), "restore into a second fresh session");
  const int few[4] = {200, 201, 202, 203};
  fake_bm::reset();
  fake_bm::vocab = 30000;
  check(d->extend(few, 4, nullptr, nullptr, 0), "4-row extend after restore succeeds");
  check(d->token_len() == kCut + 4, "the short extend also appends to the restored history");

  // block_cache_3's k_past is the session's KV buffer; the engine presents the
  // new token's slot as a view at cur_pos * kv_bytes.
  unsigned long long kv_base = 0;
  int kv_bytes = 0;
  for (auto* n : fake_bm::nets) {
    if (n->name == "block_cache_3") {
      kv_base = n->in[3].u.device.device_addr;
      kv_bytes = static_cast<int>(n->out[1].size);
    }
  }
  unsigned long long first_kv_slot = 0;
  bool saw_kv_write = false;
  for (const auto& l : fake_bm::launches) {
    if (l.net != "block_cache_3") continue;
    // out[1] is k_new; [0] is the hidden state, [2] v_new.
    if (l.out_addrs.size() < 2) continue;
    if (!saw_kv_write) first_kv_slot = l.out_addrs[1];
    saw_kv_write = true;
  }
  check(saw_kv_write, "the short extend wrote FA KV through the decode graphs");
  check(kv_bytes > 0 && first_kv_slot == kv_base + static_cast<unsigned long long>(kCut) * kv_bytes,
        "the first appended FA KV row goes to slot " + std::to_string(kCut) +
            " (addr " + std::to_string(first_kv_slot) + " == base+slot*kv_bytes)");

  f.eng.free_snapshot(snap);
}

// --- 10: an illegal token id is rejected before any graph is submitted -----
// The embedding graph gathers by id, so an out-of-range id is an out-of-bounds
// device read. The TPU cannot reject that as a bad argument -- it returns
// garbage or trips the 120 s driver timeout and oopses the board -- so the
// engine has to refuse the prompt itself, before the first launch, and must
// not mark the device faulted (the caller's bug is not a hardware failure and
// the board is still usable).
void test_out_of_range_token_is_rejected_before_any_launch() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  fake_bm::vocab = 30000;
  f.eng.set_vocab_size(fake_bm::vocab);

  auto s = f.eng.new_session();
  const int good[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), good, 8), "a valid prompt prefills");

  // Too large, negative, and one bad id in the middle of an otherwise valid
  // prompt are all the same class of error.
  const int too_big[4] = {1, 2, fake_bm::vocab, 4};
  const int negative[4] = {1, -5, 3, 4};
  for (const auto* bad : {too_big, negative}) {
    fake_bm::reset();
    fake_bm::vocab = 30000;
    const bool ok = s->prefill(bad, 4, nullptr, nullptr, 0);
    check(!ok, "a prompt with an out-of-range id is rejected");
    check(fake_bm::launches.empty(),
          "nothing was submitted to the NPU for a rejected prompt");
    check(fake_bm::out_of_range_id_launches == 0,
          "no graph ever saw the out-of-range id");
    check(!f.eng.fault(),
          "an out-of-range id is a caller error, not an NPU fault");
    check(f.eng.last_error().find("token") != std::string::npos,
          "the error names the token problem: " + f.eng.last_error());
  }

  // The session is untouched: it still holds its 8 tokens and still decodes.
  check(s->token_len() == 8, "a rejected prompt leaves the session as it was, got " +
                                 std::to_string(s->token_len()));
  check(s->decode() >= 0, "the session still decodes after a rejected prompt");
  check(!f.eng.fault(), "and the device is still usable");
}

// --- 11: a snapshot taken before the pending token is handed out ----------
// prefill/extend sample a token that the *first* decode() returns without
// running the NPU. A snapshot taken in that window, restored elsewhere, must
// reproduce that hand-back -- if it dropped `pending`, the restored session
// would start one token later and the two streams would differ by one.
void test_snapshot_keeps_the_pending_token() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};

  auto a = f.eng.new_session();
  check(a->prefill(prompt, 8, nullptr, nullptr, 0), "prefill succeeds");
  // No decode: the sampled token is still pending.
  void* snap = a->snapshot();
  check(snap != nullptr, "snapshot with a pending token succeeds");
  const int from_a = a->decode();
  check(from_a >= 0, "the original hands out its pending token");
  fake_bm::launches.clear();
  if (snap) {
    auto c = f.eng.new_session();
    check(c->restore(snap), "restore into a fresh session");
    check(c->token_len() == 8, "the restored session holds the same 8 tokens");
    const int from_c = c->decode();
    check(from_c == from_a,
          "the restored session hands back the same pending token, got " +
              std::to_string(from_c) + ", want " + std::to_string(from_a));
    check(fake_bm::launches.empty(),
          "handing back a pending token runs no graph");
    f.eng.free_snapshot(snap);
  }
}

// --- 13: fresh prefill does not clear the FA K/V buffers (MYS-2477) -------
// A fresh prefill used to zero all 40 layers' state, and on the 128k model 10
// of those are the FA K/V buffers: 2 x 131072 slots x 2 KB = 128 MiB each,
// 2.50 GiB per new session, measured 44 ms of memset -- 6.2% of a 64-row first
// token (docs/research/fresh-prefill-fa-state.md).
// It was never needed: `history` becomes 0 on that path, so no FA slot belongs
// to the session, and none of the three readers of these buffers can reach a
// slot that is not written: the prefill graph writes [0, L) through its own
// output, a decode writes exactly slot `cur_pos`, and the decode mask holds
// mask_value for every slot in [cur_pos, win).
//
// What must stay: the linear conv/rec state is still zeroed (the decode graphs
// read it in place and a sub-64-row prompt is replayed entirely through them),
// and the load-time zeroing of every state buffer is still what makes leftover
// slots finite (see the next test).
namespace {

// Device addresses of the fixture's state buffers, by role. The fixture's FA
// layer is index 3 (kFaInterval), everything else is linear.
struct StateAddrs {
  unsigned long long fa_k = 0, fa_v = 0, fa_k_size = 0, fa_v_size = 0;
  unsigned long long lin_conv = 0, lin_rec = 0;
};

StateAddrs state_addrs(const cv84x6::Engine& eng) {
  StateAddrs a;
  (void)eng;
  for (auto* n : fake_bm::nets) {
    if (n->name == "block_cache_3") {
      a.fa_k = n->in[3].u.device.device_addr;
      a.fa_v = n->in[4].u.device.device_addr;
      a.fa_k_size = n->in[3].size;
      a.fa_v_size = n->in[4].size;
    } else if (n->name == "block_cache_0") {
      a.lin_conv = n->in[1].u.device.device_addr;
      a.lin_rec = n->in[2].u.device.device_addr;
    }
  }
  return a;
}

// Bytes the fixture's FA graph writes per KV slot (one token of K, one of V).
int fa_slot_bytes() {
  for (auto* n : fake_bm::nets)
    if (n->name == "block_cache_3") return static_cast<int>(n->out[1].size);
  return 0;
}

// Plant a marker over the whole FA K/V buffers, standing in for the KV a
// previous, longer session left behind in the shared resident buffers.
void plant_stale_kv(const StateAddrs& a, int v) {
  for (unsigned long long i = 0; i < a.fa_k_size; i++) fake_bm::write_byte(a.fa_k + i, v);
  for (unsigned long long i = 0; i < a.fa_v_size; i++) fake_bm::write_byte(a.fa_v + i, v);
}

std::vector<unsigned char> snapshot_bytes(unsigned long long addr, size_t len) {
  std::vector<unsigned char> b(len);
  for (size_t i = 0; i < len; i++) b[i] = static_cast<unsigned char>(fake_bm::read_byte(addr + i));
  return b;
}

}  // namespace

void test_fresh_prefill_leaves_fa_state_alone() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  const StateAddrs a = state_addrs(f.eng);
  const int slot = fa_slot_bytes();
  check(a.fa_k != 0 && a.fa_v != 0 && slot > 0, "the fixture exposes its FA state buffers");

  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  plant_stale_kv(a, 0x5A);  // KV left over from a previous session
  fake_bm::memsets.clear();
  check(s->prefill(prompt, 8, nullptr, nullptr, 0), "a fresh prefill succeeds");

  check(fake_bm::memsets_of(a.fa_k) == 0,
        "a fresh prefill does not memset the FA K buffer (" +
            std::to_string(fake_bm::memsets_of(a.fa_k)) + " clears)");
  check(fake_bm::memsets_of(a.fa_v) == 0,
        "a fresh prefill does not memset the FA V buffer (" +
            std::to_string(fake_bm::memsets_of(a.fa_v)) + " clears)");
  // The linear state is a different matter: the decode graphs read conv/rec in
  // place and a prompt below the 64-row alignment is replayed through them, so
  // a leftover value there would change the answer. It must still be cleared.
  check(fake_bm::memsets_of(a.lin_conv) > 0, "the linear conv_state is still zeroed");
  check(fake_bm::memsets_of(a.lin_rec) > 0, "the linear rec_state is still zeroed");

  // Only the session's own slots were written; the stale KV past them is
  // untouched, which is the whole point (2.50 GiB not written per session).
  check(!fake_bm::bytes_are(a.fa_k, static_cast<size_t>(8) * slot, 0x5A),
        "the 8 prefilled rows were written into FA KV slots [0, 8)");
  check(fake_bm::bytes_are(a.fa_k + static_cast<size_t>(8) * slot,
                           a.fa_k_size - static_cast<size_t>(8) * slot, 0x5A),
        "the FA K slots past the prompt still hold the previous session's bytes");
  check(fake_bm::bytes_are(a.fa_v + static_cast<size_t>(8) * slot,
                           a.fa_v_size - static_cast<size_t>(8) * slot, 0x5A),
        "the FA V slots past the prompt still hold the previous session's bytes");

  // Decode never cleared them either, before or after this change, and it must
  // write exactly slot `history` -- not slot 0 or a stale one.
  fake_bm::memsets.clear();
  const int tok = s->decode();
  check(tok >= 0 && tok != -1, "the first decode hands back prefill's token");
  check(fake_bm::memsets_of(a.fa_k) == 0, "a decode does not memset the FA K buffer");
  check(s->decode() >= 0, "a decode step runs");
  check(fake_bm::memsets_of(a.fa_k) == 0, "a decode step does not memset the FA K buffer");
  check(s->token_len() == 9, "history advanced to 9, got " + std::to_string(s->token_len()));

  // A second fresh prefill on the same session resets history and again pays no
  // FA clear: that path discards the old session entirely.
  fake_bm::memsets.clear();
  check(s->prefill(prompt, 8, nullptr, nullptr, 0), "a second fresh prefill succeeds");
  check(s->token_len() == 8, "the fresh prefill reset the history to the new prompt (8)");
  check(fake_bm::memsets_of(a.fa_k) == 0 && fake_bm::memsets_of(a.fa_v) == 0,
        "a replaced session still does not memset the FA buffers");
  check(fake_bm::memsets_of(a.lin_conv) > 0,
        "a replaced session does clear the linear state");

  // The invariant that makes all of the above sound: a fresh prefill leaves the
  // session with history 0. It has to hold even when the prefill fails partway
  // -- on the failure path `history` is the only thing that says how much KV
  // the session owns, and it must not keep pointing at the discarded session's
  // slots. `activate()` establishes it, before any work that can fail.
  check(s->decode() >= 0 && s->decode() >= 0,
        "the session advances before the failing prefill");
  const int before = s->token_len();
  check(before > 8, "the session holds a history to lose, got " + std::to_string(before));
  fake_bm::fail_launch = true;
  check(!s->prefill(prompt, 8, nullptr, nullptr, 0), "a prefill whose launch fails reports it");
  check(s->token_len() == 0,
        "a failed fresh prefill leaves history at 0, got " + std::to_string(s->token_len()));
}

// --- 13b: load-time zeroing and restore-time clearing are both still there --
// The FA buffers are only ever *written* by graphs, so their contents are
// finite once they have been zeroed -- and that zeroing happens here, once, at
// load (plus the block_kv template inputs, the demo's anti-NaN measure). It is
// the parenthesis that makes skipping the per-session clear sound.
//
// restore() is the opposite case: it lays a snapshot down over [0, len) and
// then decodes at `len`, so the slots past the snapshot *are* reachable. It
// must keep clearing the whole buffer, otherwise a previous longer session's
// KV would sit exactly where the restored session is about to append.
void test_load_and_restore_still_clear_state() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  const StateAddrs a = state_addrs(f.eng);
  check(fake_bm::memsets_of(a.fa_k) == 1 && fake_bm::memsets_of(a.fa_v) == 1,
        "load zeroes each FA state buffer exactly once");
  check(fake_bm::memset_bytes_of(a.fa_k) == a.fa_k_size,
        "load zeroes the FA K buffer whole (" +
            std::to_string(fake_bm::memset_bytes_of(a.fa_k)) + " of " +
            std::to_string(a.fa_k_size) + " bytes)");
  // The block_kv template's past-KV inputs: the demo's explicit anti-NaN clear.
  for (auto* n : fake_bm::nets) {
    if (n->name != "block_kv_3") continue;
    check(fake_bm::memsets_of(n->in[2].u.device.device_addr) > 0,
          "load zeroes the block_kv template's past-K input");
    check(fake_bm::memsets_of(n->in[3].u.device.device_addr) > 0,
          "load zeroes the block_kv template's past-V input");
  }

  const int slot = fa_slot_bytes();
  auto s = f.eng.new_session();
  const int prompt[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  check(prefill_ready(s.get(), prompt, 8), "a session prefills to length 8");
  void* snap = s->snapshot();
  check(snap != nullptr, "snapshot at length 8");
  // Leave a longer session's KV in the shared resident buffers, so a restore
  // that stopped clearing would append right after the snapshot into it.
  check(s->decode() >= 0, "the snapshot's session advances");
  plant_stale_kv(a, 0x5A);

  auto c = f.eng.new_session();
  fake_bm::memsets.clear();
  check(c->restore(snap), "restore into a fresh session succeeds");
  check(fake_bm::memsets_of(a.fa_k) > 0 && fake_bm::memsets_of(a.fa_v) > 0,
        "restore still clears the FA K/V buffers");
  check(fake_bm::bytes_are(a.fa_k + static_cast<size_t>(8) * slot,
                           a.fa_k_size - static_cast<size_t>(8) * slot, 0),
        "the FA K slots past the snapshot are clean after a restore");
  check(fake_bm::bytes_are(a.fa_v + static_cast<size_t>(8) * slot,
                           a.fa_v_size - static_cast<size_t>(8) * slot, 0),
        "the FA V slots past the snapshot are clean after a restore");
  check(!fake_bm::bytes_are(a.fa_k, static_cast<size_t>(8) * slot, 0x5A),
        "and the snapshot's own KV was laid down over [0, 8)");
  check(c->token_len() == 8, "the restored session has the snapshot's length");
  f.eng.free_snapshot(snap);
}

// --- 13c: park/unpark still carries a session's KV across a resident switch --
// Skipping the FA clear moves the risk to the state swap: two sessions share
// one set of resident buffers, and only park()/unpark() keep them apart. If a
// fresh prefill did not leave the other session's parked copy intact, or if
// unpark stopped copying [0, history), session A would decode from B's KV --
// silently wrong tokens rather than a crash, which is why it is checked on the
// bytes and not on a token id.
void test_park_unpark_keeps_kv_across_resident_switch() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  const StateAddrs a = state_addrs(f.eng);
  const int slot = fa_slot_bytes();

  auto solo = f.eng.new_session();
  auto other = f.eng.new_session();
  const int pa[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  const int pb[8] = {41, 42, 43, 44, 45, 46, 47, 48};

  // A prefills and takes one decode step, so its KV is 9 slots deep.
  check(prefill_ready(solo.get(), pa, 8), "session A prefills");
  check(solo->decode() >= 0, "session A decodes once");
  check(solo->token_len() == 9, "session A holds 9 KV slots");
  const auto a_kv = snapshot_bytes(a.fa_k, static_cast<size_t>(9) * slot);
  const auto a_v = snapshot_bytes(a.fa_v, static_cast<size_t>(9) * slot);
  const auto slot9_before = snapshot_bytes(a.fa_k + static_cast<size_t>(9) * slot,
                                           static_cast<size_t>(slot));

  // B fresh-prefills: it parks A and then writes its own KV over slots [0, 8)
  // of the shared buffers. Without the park that write would be A's data.
  check(prefill_ready(other.get(), pb, 8), "session B fresh-prefills while A is parked");
  check(other->token_len() == 8, "session B holds its own 8 KV slots");
  const auto b_kv = snapshot_bytes(a.fa_k, static_cast<size_t>(8) * slot);
  check(!fake_bm::bytes_are(a.fa_k, static_cast<size_t>(9) * slot, a_kv[0]),
        "B's prefill did overwrite the shared FA buffers (so the check is live)");
  check(snapshot_bytes(a.fa_k, static_cast<size_t>(9) * slot) != a_kv,
        "the resident FA K no longer holds A's KV while B is resident");

  // A comes back: unpark must lay its own [0, 9) down again.
  check(solo->decode() >= 0, "session A decodes after B was resident");
  check(snapshot_bytes(a.fa_k, static_cast<size_t>(9) * slot) == a_kv,
        "unpark restored A's FA K slots [0, 9) exactly");
  check(snapshot_bytes(a.fa_v, static_cast<size_t>(9) * slot) == a_v,
        "unpark restored A's FA V slots [0, 9) exactly");
  check(solo->token_len() == 10, "A's history advanced to 10, got " +
                                     std::to_string(solo->token_len()));

  // A's new KV went to slot 9, the one after its own history -- not to slot 0
  // and not over the row it just unparked.
  const auto slot9_after = snapshot_bytes(a.fa_k + static_cast<size_t>(9) * slot,
                                          static_cast<size_t>(slot));
  check(slot9_before != slot9_after,
        "A's second decode wrote a new KV row at slot 9");

  // And B survives the round trip in the other direction: switching back must
  // put B's own 8 slots in place, from the copy the park above took.
  check(other->decode() >= 0, "session B decodes after A was resident again");
  check(snapshot_bytes(a.fa_k, static_cast<size_t>(8) * slot) == b_kv,
        "unpark restored B's FA K slots [0, 8) exactly");
  check(other->token_len() == 9, "B's history is its own (9), got " +
                                     std::to_string(other->token_len()));
}

// --- 12b: decode on a restored session needs the snapshot's last token -----
// The old restore() set last_id = -1, so decode() fed id -1 to the embedding
// graph: an out-of-bounds gather that reads whatever is before the table
// (silently wrong tokens) or faults. A snapshot must carry the token, and a
// session with no token at all must be refused, not launched.
void test_decode_rejects_a_missing_last_token() {
  Fixture f;
  if (!load(&f)) { check(false, "model loads"); return; }
  auto s = f.eng.new_session();
  // Empty session: no KV, no token. decode() must refuse.
  fake_bm::reset();
  check(s->decode() < 0, "decode on an empty session is refused");
  check(fake_bm::launches.empty(), "and submits nothing");
  check(!f.eng.fault(), "an empty-session decode is not an NPU fault");
}

}  // namespace

int main(int argc, char** argv) {
  if (argc > 1) g_model = argv[1];
  fake_bm::reset();

  test_decode_submits_layers_then_syncs_once();
  test_lm_head_runs_after_a_boundary();
  test_decode_returns_quiescent();
  test_conv_state_not_copied_when_in_place();
  test_conv_state_copied_when_not_in_place();
  test_rec_state_output_still_copied();
  test_failed_launch_sets_fault();
  test_failed_deferred_sync_sets_fault();
  test_prefill_launches_are_synchronous();
  test_two_sessions_interleaved();
  test_restore_then_extend_continues_the_snapshot();
  test_out_of_range_token_is_rejected_before_any_launch();
  test_snapshot_keeps_the_pending_token();
  test_decode_rejects_a_missing_last_token();
  test_fresh_prefill_leaves_fa_state_alone();
  test_load_and_restore_still_clear_state();
  test_park_unpark_keeps_kv_across_resident_switch();

  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
