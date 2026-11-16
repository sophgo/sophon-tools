// Typed access to the management API plus the SSE reader for streaming chat.

/** What a model is doing right now, from the backend.
 *
 *  `null` is idle. `loading` covers the whole window between spawning the
 *  worker and the model being usable, which for the 35B is a minute or more --
 *  during that time `loaded` is still false, so `operation` is the only honest
 *  answer to "may I click load?". It lives on the server, so a page refresh (or
 *  a second browser) sees exactly the same thing.
 */
export type ModelOperation = 'loading' | 'unloading' | null

/** What a model can serve, read by the backend off the bmodel's file name.
 *  `ocr_vl` (PaddleOCR-VL) is a vision chat model driven with OCR prompts. */
export type ModelKind = 'chat' | 'embedding' | 'rerank' | 'asr' | 'ocr' | 'ocr_vl'

/** A missing `kind` is a server older than the auxiliary models: chat. */
export function kindOf(m: { kind?: string | null }): ModelKind {
  const k = m.kind ?? 'chat'
  return (['chat', 'embedding', 'rerank', 'asr', 'ocr', 'ocr_vl'] as const)
    .find((x) => x === k) ?? 'chat'
}

export type Model = {
  id: string
  display_name: string
  path: string
  kind?: ModelKind
  /** Output vector width (embedding: the MRL ceiling). Known once loaded. */
  hidden_size?: number | null
  bmodel_files?: string[]
  size_bytes: number
  has_config: boolean
  context_length: number | null
  supports_vision: boolean
  // False when the bmodel fuses argmax into lm_head, so temperature/top_p have
  // no effect. Undefined for models that are not loaded yet.
  supports_sampling?: boolean
  loaded: boolean
  port: number | null
  pid: number | null
  load_error: string | null
  load_seconds: number | null
  /** Epoch seconds of the last load or inference request (auxiliary kinds). */
  last_used_at?: number | null
  /** When an idle auxiliary model will be unloaded (epoch s), or null. */
  idle_unload_at?: number | null
  /** "idle" when the model was unloaded by the idle sweep, else null. */
  unloaded_reason?: string | null
  /** The operation in flight, or null. The console locks and polls on this. */
  operation: ModelOperation
  /** Epoch seconds the operation started, for an elapsed-time label. */
  operation_since: number | null
  /** A worker this service found but could not take over (it never answered its
   *  health check, or another instance owns it). Not `loaded` and not idle:
   *  loading is refused with 409 until it is unloaded, because a second worker
   *  for the same bmodel would put two allocations on the NPU heap. */
  conflict: string | null
  /** True when this service attached to a worker that survived a restart
   *  instead of starting one. Shown so an operator can tell why a model is
   *  online seconds after a restart. */
  adopted: boolean
  /** True while a download job is still writing this model's directory: the
   *  .bmodel is incomplete, and the backend refuses load and delete with 409.
   *  Optional for servers older than v0.6.17. */
  downloading?: boolean
  /** Per-model overrides as saved (null = follow the default). MYS-2675. */
  settings?: ModelSettingsRaw
  /** What is in force right now, defaults resolved. */
  effective?: { idle_unload_min: number; auto_load: boolean; mem_limit_bytes: number | null }
  mem_limit_default_bytes?: number | null
  /** Weights + neuron + instructions; measured once loaded, estimated before. */
  mem_static_bytes?: number | null
  /** Static + session KV + prefix cache; null while not loaded. */
  mem_used_bytes?: number | null
}

export type ModelSettingsRaw = { idle_unload_min: number | null; auto_load: boolean | null; mem_limit_mb: number | null }
export type ModelSettingsView = {
  id: string
  kind: ModelKind
  settings: ModelSettingsRaw
  effective: { idle_unload_min: number; auto_load: boolean; mem_limit_bytes: number | null }
  mem_limit_default_bytes: number | null
  mem_static_bytes: number | null
  mem_used_bytes: number | null
  limits: { idle_unload_min_max: number; mem_limit_mb_min: number; mem_limit_mb_max: number }
  auto_load_note: string
}

/** What bm-smi reports: TPU clock limits and NPU memory. Empty on a host that
 *  has no board (or no bm-smi), so every field is optional.
 *
 *  There is deliberately no "current clock" here. The `0M` that bm-smi prints
 *  in the card row is `tpuc` -- utilisation in percent -- and reading it as a
 *  frequency is what made the dashboard claim "current 0 MHz" on an idle board.
 *  The live frequency is `DeviceStats.tpu_freq`. */
export type SmiStats = {
  tpu_min_clock_mhz?: number
  tpu_max_clock_mhz?: number
  tpu_util_percent?: number
  /** @deprecated The backend no longer sends this, and it never was a clock.
   *
   *  It held bm-smi's `tpuc` column (utilisation %), which is why the dashboard
   *  said "current 0 MHz". Kept in the type only so `Overview.tsx` -- owned by
   *  the console-UX task -- still compiles; that page is being rewritten to read
   *  `DeviceStats.tpu_freq` instead. Remove once it has. */
  tpu_clock_mhz?: number
  mem_used_bytes?: number
  mem_total_bytes?: number
}

/** The TPU frequency as the backend measured it, with its unit and source.
 *
 *  `source` exists because the board has three probes that disagree: the DVFS
 *  sysfs node (the real current frequency, e.g. 2000 MHz), bm-smi's nominal
 *  min/max (25/1000 MHz) and the root-only debugfs register. The UI says which
 *  one it is showing rather than presenting one number as if the others did not
 *  exist; `mhz` is never clamped to `max_mhz`. */
export type TpuFreq = {
  mhz: number | null
  source: 'sysfs' | 'bm-smi' | 'debugfs' | 'none'
  unit: string
  min_mhz: number | null
  max_mhz: number | null
  debugfs_hz: number | null
}

/** A model this release is built and tested for (GET /api/catalog). */
export type CatalogModel = {
  id: string
  kind?: ModelKind
  title: string
  dfss: string | null   // null: not published on dfss yet
  size_bytes: number | null
  context?: number
  prefix_cache?: boolean
  vision: boolean
  verified: boolean
  installed: boolean
  /** A download job is writing this model right now (it is not installed). */
  downloading?: boolean
  /** Installed and its dfss download tag now points at a different build.
   *  Absent when the tag index could not be read (offline board). */
  update_available?: boolean
  latest_file?: string | null
}

export type DeviceStats = {
  cpu_percent: number | null
  load_average: number[]
  memory: { total_bytes: number | null; available_bytes: number | null; used_bytes: number | null }
  temperatures: { zone: string; name: string; celsius: number }[]
  npu: {
    total_percent: number | null
    cores: number[]
    heap: Record<string, { total_bytes: number | null; alloc_bytes: number | null }>
    smi?: SmiStats
  }
  clocks: { tpu_hz?: number | null; cpu_hz: number | null }
  /** @deprecated Always empty since the device-memory change (MYS-2673): the
   *  console shows `tpu_usage` instead of a frequency. */
  tpu_freq?: TpuFreq
  /** Device memory = every heap the TPU can hold models in (NPU + VPP on
   *  CV84X6). `max_block_bytes` is the largest single allocation that still
   *  fits -- one block cannot span heaps, so it is not the same as free. */
  device_mem?: DeviceMem
  /** TPU utilisation, percent, from the driver's sysfs counter. */
  tpu_usage?: { percent: number | null; cores: number[]; source: string }
  disk: { total_bytes: number; free_bytes: number; used_bytes: number }
}

export type DeviceHeap = { name: string; total_bytes: number; used_bytes: number; free_bytes: number }
export type DeviceMem = {
  total_bytes: number | null
  used_bytes: number | null
  free_bytes: number | null
  max_block_bytes: number | null
  heaps: DeviceHeap[]
  source: 'bmlib' | 'ion' | 'mock' | 'none'
}
/** The VPP block the service holds back for the board's multimedia stack. */
export type VppReserve = {
  requested_bytes: number
  held_bytes: number
  acquired: boolean
  reason: string | null
}

export type Stats = {
  device: DeviceStats
  vpp_reserve?: VppReserve | null
  usage: {
    prompt_tokens: number
    completion_tokens: number
    cached_tokens: number
    requests: number
    tps_history: [number, number][]
    cache_hit_rate: number
  }
  models: Model[]
  max_loaded_models: number
  kv_cache: Record<string, {
    entries: number
    location: string
    // False when the backend cannot verify KV snapshots, which is the case for
    // every model in v0.2.0 -- the prefix cache is off, not merely cold.
    enabled?: boolean
    bytes: number
    // The cache ceiling actually in force for this model. It is the configured
    // budget trimmed to the NPU memory the model can spare, so it can be lower
    // than what the settings page asks for.
    max_bytes?: number
    max_entries?: number
    ttl_s?: number
    expirations?: number
    hit_rate: number
    tokens_reused: number
    tokens_prompted: number
  }>
  workers: Record<string, any>
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; models_bytes: number; models_root: string }
}

export type DownloadJob = {
  id: string
  kind: string
  target: string
  name: string
  state: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  total_bytes: number | null
  done_bytes: number
  percent: number
  message: string
  started_at: number
  finished_at: number | null
}

export type ApiKey = {
  id: string
  name: string
  prefix: string
  created_at: number
  revoked: boolean
  prompt_tokens: number
  completion_tokens: number
  requests: number
  cached_tokens: number
  /** `inference` (default) may call /v1 only; `admin` may also call /api/*. */
  scope?: 'inference' | 'admin'
}

/** Server-side limits, as GET /api/settings reports them.
 *
 *  The backend clamps every field on save, so the values read back here can be
 *  narrower than what was submitted -- the settings page shows the result, not
 *  the input. */
export type Settings = {
  max_concurrent_per_model: number
  // The hard ceiling the server enforces (currently 3); the input is bounded
  // by this rather than a hard-coded number.
  max_concurrency_limit: number
  prefix_cache_entries: number
  prefix_cache_ttl_min: number
  max_queue: number
  prefill_exact_tail: number
  require_api_key: boolean
  /** Inference audit log: on/off and how much history to keep. */
  inference_logging_enabled: boolean
  inference_log_retention_count: number
  inference_log_retention_days: number
  /** Auxiliary models (embedding / rerank / ASR / OCR) unload after this many
   *  idle minutes; 0 = never. `aux_idle_unload_limit_min` is the server's cap. */
  aux_idle_unload_min: number
  aux_idle_unload_limit_min: number
  /** Load an unloaded auxiliary model when a request needs it. */
  aux_auto_load: boolean
}

/** Only the fields the console lets an operator change. */
export type SettingsPatch = Partial<Pick<Settings,
  'max_concurrent_per_model' | 'prefix_cache_entries' |
  'prefix_cache_ttl_min' | 'max_queue' | 'prefill_exact_tail' |
  'inference_logging_enabled' | 'inference_log_retention_count' |
  'inference_log_retention_days' | 'aux_idle_unload_min' | 'aux_auto_load'>>

/** One recorded inference, as the list route returns it (MYS-2496).
 *
 *  The list deliberately omits the conversation and the answer text: a page of
 *  200 records that each carried a 128k-token prompt would be tens of megabytes
 *  on every poll. Ask the detail route for one record to read those. */
export type InferenceRecordSummary = {
  /** Equal to the request id the worker saw; unique per inference. */
  id: string
  source: string            // "/v1/chat/completions" | "/api/chat/stream" | "/api/chat"
  model: string | null
  actor_type: 'api_key' | 'admin' | 'anonymous' | null
  actor_id: string | null
  actor_name: string | null
  started_at: number        // epoch seconds
  finished_at: number
  started_iso: string       // UTC ISO8601
  finished_iso: string
  status: 'ok' | 'error' | 'cancelled'
  finish_reason: string | null
  error_type: string | null
  error_message: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  cached_tokens: number | null
  first_token_latency_s: number | null
  decode_tps: number | null
  output_chars: number | null
  raw_output_chars: number | null
  /** The stop string that cut the output, if one did. */
  stop_hit: string | null
}

/** An input picture: dimensions only. The bytes are never stored. */
export type ImageMeta = { index?: number; count?: number; width: number | null; height: number | null }

export type RecordedMessage = {
  role: string
  // A string, or the parts list with each image replaced by its metadata.
  content: string | Record<string, any>[] | null
  name?: string
  tool_call_id?: string
  reasoning_content?: string
  tool_calls?: Record<string, any>[]
}

/** One record in full: the conversation, what was sent, and what came back. */
export type InferenceRecord = InferenceRecordSummary & {
  params: Record<string, any> | null
  tools: Record<string, any>[] | null
  tool_choice: any
  messages: RecordedMessage[] | null
  images: ImageMeta[] | null
  message_images: ImageMeta[][] | null
  /** The generation as the API's semantics define it (stop string removed). */
  output_text: string | null
  /** Exactly what the model emitted before the stop string cut it. */
  raw_output_chars: number | null
  response_content: string | null
  reasoning_content: string | null
  tool_calls: Record<string, any>[] | null
  error: { type: string | null; message: string | null } | null
}

/** What the record store itself reports: is it readable, how big, last failure. */
export type InferenceRecordStatus = {
  path: string
  enabled: boolean
  total: number
  bytes: number | null
  schema_version: number
  retention_count: number
  retention_days: number
  /** False only when the database cannot be opened at all (corrupt, disk full). */
  readable: boolean
  /** True while a data-directory move has the log parked: writes are dropped on
   *  purpose and the row count is read through a throwaway read-only handle. */
  moving: boolean
  /** The most recent reason a record was not stored -- including a record
   *  dropped for a move, so a paused log cannot look like an idle one. */
  last_error: string | null
  last_error_at: number | null
  error?: string
}

/** What one loaded worker reports after the new limits were pushed to it. */
export type AppliedModel = {
  max_concurrent?: number
  max_queue?: number
  exact_tail?: number
  // NPU bytes parked sessions + prefix cache may share on this model.
  kv_budget_bytes?: number | null
  // Effective ceiling: the configured budget, or the NPU cap when that is
  // smaller. null/absent when the model failed to apply.
  cache_max_bytes?: number
  // Bytes the NPU can spare for the cache after weights and parked sessions.
  // null when the board figures are unavailable (mock backend, no bm-smi).
  cache_npu_cap_bytes?: number | null
  cache_ttl_s?: number
  cache_entries?: number
  error?: string
}

/** Where the mutable data lives and how much room it takes (GET /api/storage).
 *
 *  `fs_*` describe the filesystem holding `data_dir`; `dir_bytes` and `parts`
 *  are what this service itself occupies, which is a different (smaller) number
 *  than the filesystem's used space. */
export type StorageInfo = {
  data_dir: string
  fs_total_bytes: number
  fs_used_bytes: number
  fs_free_bytes: number
  dir_bytes: number
  parts: { models: number; agents: number; state: number; downloads: number }
}

/** The data-directory move: one at a time, polled once a second by the UI. */
export type MoveState =
  | 'idle' | 'checking' | 'stopping' | 'copying' | 'verifying' | 'switching' | 'done' | 'failed'

export type MoveJob = {
  id: string
  state: MoveState
  copied_bytes: number
  total_bytes: number
  message: string
  old: string
  new: string
  started_at?: number
  finished_at?: number | null
}

export type SaveSettingsResult = {
  settings: Settings
  /* Keyed by model id; a model that failed reports {error}. */
  applied: Record<string, AppliedModel>
}

/** What an agent is doing right now, from the backend (MYS-2388).
 *
 *  `status` is a four-value summary that folds "starting" into "stopped" --
 *  there is no ready process to point at yet -- so it cannot answer "is a
 *  start already running?". `operation` can, and because the server owns it a
 *  page refresh (or a second browser) locks the same buttons. */
export type AgentOperation =
  | 'installing' | 'starting' | 'stopping' | 'restarting'
  | 'resetting' | 'uninstalling' | 'configuring' | null

/** One open-source agent the service can install and run (GET /api/agents).
 *
 *  `status` is the four states a card can show: `not_installed` (nothing on
 *  disk), `stopped`, `running`, and `failed` (gave up restarting). `running`
 *  and `status === 'running'` agree; the boolean is there for the overview
 *  shortcut, which only lists what is up. An agent that is starting reports
 *  `status: 'stopped'` with `operation: 'starting'` -- read both.
 *
 *  `web_url` is a path on the console's own origin (`/agents/<id>/`), not an
 *  address on the agent's port. That matters on a customer site, where only the
 *  console's port is forwarded: a link to `http://<board>:14096` does not
 *  resolve there, so the iframe stayed blank and "打开" dead-ended. The proxy
 *  serves the agent's UI on this origin, presents the agent's own login
 *  upstream, and keeps every asset/API/WS call under the same prefix.
 *
 *  `web.password` is the agent's own server password, shown in the clear on the
 *  card: the operator needs it to log in from another device or browser, and
 *  over plain http the clipboard API is usually unavailable, so a masked value
 *  could not be copied at all. It is only ever returned to an admin session. */
export type Agent = {
  id: string
  name: string
  version: string
  latest_version: string
  default_port: number
  port: number
  installed: boolean
  status: 'not_installed' | 'stopped' | 'running' | 'failed'
  /** The operation in flight, or null; the console locks and polls on this. */
  operation: AgentOperation
  operation_since: number | null
  /** Convenience: `operation !== null`, computed by the server. */
  busy: boolean
  /** Chinese label for `operation` ("加载中"-style), for the button text. */
  operation_label: string
  running: boolean
  pid: number | null
  health: boolean
  /** True when this service attached to an agent process that survived a
   *  restart, instead of spawning one. */
  adopted: boolean
  /** A surviving process that matched this agent but never passed its health
   *  check. It is reported (its port and memory are real) and `stop` clears it,
   *  but the agent is never `running` while this is set -- a start is refused
   *  rather than racing a second copy onto the same port. */
  orphan_pid: number | null
  rss_bytes: number
  disk_bytes: number
  autostart: boolean
  default_model: string
  thinking: boolean
  embeddable: boolean
  proxied: boolean
  memory_floor_bytes: number
  card_note: string
  web_url: string
  web: { username: string; password: string }
  models: { id: string; context: number; vision: boolean }[]
  started_at: number | null
  uptime_s: number | null
  exit_code: number | null
  last_error: string
  job: AgentJob | null
}

export type AgentJob = {
  agent_id: string
  state: 'pending' | 'running' | 'done' | 'error'
  done_bytes: number
  total_bytes: number | null
  percent: number
  message: string
  started_at: number
  finished_at: number | null
}

/** Only the agent fields the console lets an operator change. */
export type AgentPatch = Partial<Pick<Agent, 'port' | 'autostart' | 'default_model' | 'thinking'>>

export type AgentAction = 'start' | 'stop' | 'restart' | 'reset' | 'uninstall' | 'sync'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: 'same-origin',
    // A FormData body must not carry a JSON content type: the browser writes
    // the multipart boundary into the header itself.
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) {
    let detail = r.statusText
    try {
      const body = await r.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

// -- console test routes (/api/test/*) -------------------------------------
// The same handlers as /v1, behind the admin cookie instead of an API key, so
// the shapes below are the /v1 response shapes.

export type EmbeddingResult = {
  data: { index: number; embedding: number[] }[]
  usage: { prompt_tokens: number; total_tokens: number }
}

export type RerankResult = {
  results: { index: number; relevance_score: number; document?: { text: string } }[]
  usage: { prompt_tokens: number; total_tokens: number }
}

export type TranscriptSegment = { id: number; start: number; end: number; text: string }

export type TranscriptResult = {
  language: string | null
  duration: number
  text: string
  segments: TranscriptSegment[]
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
}

/** Four [x, y] points in source pixels: TL, TR, BR, BL. */
export type OcrBox = [number, number][]

export type OcrMode = 'lines' | 'layout' | 'vl'

/** One layout region (mode `layout`), in reading order. `box` is [x1, y1, x2, y2]. */
export type OcrBlock = {
  index: number
  type: string
  label: string
  score: number
  box: [number, number, number, number]
  text: string
  lines: { text: string; score: number; box: OcrBox | null }[]
  /** mode `vl` only: the PaddleOCR-VL prompt this region was read with. */
  task?: string
  /** mode `vl` only: this region failed; the rest of the page is still returned. */
  error?: string
}

export type OcrResult = {
  /** Present only on layout responses; a lines response is the original shape. */
  mode?: OcrMode
  /** lines: the lines joined; layout / vl: the page as Markdown (vl tables are HTML). */
  text: string
  lines: { text: string; score: number; box: OcrBox | null }[]
  usage: { det_ms: number; rec_ms: number; lines: number; layout_ms?: number; blocks?: number; vl_ms?: number; vl_tokens?: number }
  blocks?: OcrBlock[]
}


// ---------- logs & audit (MYS-2674, docs/logs.md) ----------
export type LogSource = {
  id: string            // "platform" | "worker:<model>" | "agent:<name>"
  label: string
  kind: 'platform' | 'worker' | 'agent' | string
  size_bytes: number
  updated_at: number | null
  updated_at_iso?: string | null
}
export type LogLine = { ts: string | null; level: string | null; logger: string | null; message: string }
export type LogPage = {
  source: string
  label: string
  lines: LogLine[]        // old -> new
  cursor: string | null   // the page before this one; null = nothing older
  has_more: boolean
  limit: number
  size_bytes: number
}
export type LogQuery = { since?: string; until?: string; level?: string; q?: string; limit?: number; cursor?: string }
export type AuditItem = {
  id: number
  ts: number
  ts_iso: string
  actor_type: 'console' | 'api_key' | 'anonymous' | string
  actor_id: string | null
  actor_name: string | null
  ip: string | null
  user_agent: string | null
  method: string
  path: string
  target: string | null
  status: number
  ok: boolean
  duration_ms: number | null
  summary: string | null
  result: 'success' | 'failure' | string
}
export type AuditPage = { items: AuditItem[]; total: number; limit: number; offset: number; retention_days: number; dropped: number }
export type AuditQuery = { since?: string; until?: string; actor?: string; action?: string; status?: string; q?: string; limit?: number; offset?: number }

/** `?a=1&b=2` from the set fields of a query object (empty strings dropped). */
export function qs(o: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const t = p.toString()
  return t ? `?${t}` : ''
}

export const api = {
  session: () => req<{ authenticated: boolean }>('/api/session'),
  login: (password: string) =>
    req<{ ok: boolean }>('/api/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => req<{ ok: boolean }>('/api/logout', { method: 'POST' }),
  stats: () => req<Stats>('/api/stats'),
  logSources: () => req<{ sources: LogSource[] }>('/api/logs/sources'),
  logs: (source: string, q: LogQuery) =>
    req<LogPage>(`/api/logs/${encodeURIComponent(source)}${qs(q)}`),
  logDownloadUrl: (source: string, q: LogQuery) =>
    `/api/logs/${encodeURIComponent(source)}/download${qs({ ...q, limit: undefined, cursor: undefined })}`,
  audit: (q: AuditQuery) => req<AuditPage>(`/api/audit${qs(q)}`),
  auditExportUrl: (q: AuditQuery) => `/api/audit/export${qs({ ...q, limit: undefined, offset: undefined })}`,
  models: () => req<{ models: Model[] }>('/api/models'),
  modelSettings: (id: string) => req<ModelSettingsView>(`/api/models/${encodeURIComponent(id)}/settings`),
  saveModelSettings: (id: string, body: Partial<ModelSettingsRaw>) =>
    req<ModelSettingsView>(`/api/models/${encodeURIComponent(id)}/settings`,
      { method: 'PUT', body: JSON.stringify(body) }),
  loadModel: (id: string) =>
    req<{ ok: boolean; model: Model }>(`/api/models/${encodeURIComponent(id)}/load`, { method: 'POST' }),
  unloadModel: (id: string) =>
    req<{ ok: boolean; model: Model }>(`/api/models/${encodeURIComponent(id)}/unload`, { method: 'POST' }),
  modelLog: (id: string) =>
    req<{ log: string }>(`/api/models/${encodeURIComponent(id)}/log`),
  keys: () => req<{ keys: ApiKey[] }>('/api/keys'),
  createKey: (name: string, scope: 'inference' | 'admin' = 'inference') =>
    req<{ key: string; meta: ApiKey }>('/api/keys', { method: 'POST', body: JSON.stringify({ name, scope }) }),
  revokeKey: (id: string) => req<{ ok: boolean }>(`/api/keys/${id}/revoke`, { method: 'POST' }),
  deleteKey: (id: string) => req<{ ok: boolean }>(`/api/keys/${id}`, { method: 'DELETE' }),
  catalog: () => req<{ models: CatalogModel[] }>('/api/catalog'),
  downloads: () => req<{ jobs: DownloadJob[]; orphans: { files: string[]; bytes: number } }>('/api/downloads'),
  startDownload: (body: { url: string; name: string; kind: 'url' | 'dfss'; expected_bytes?: number | null }) =>
    req<{ job: DownloadJob }>('/api/downloads', { method: 'POST', body: JSON.stringify(body) }),
  cancelDownload: (id: string) =>
    req<{ ok: boolean }>(`/api/downloads/${id}/cancel`, { method: 'POST' }),
  /** Swap the installed build for the one its download tag points at; 409
   *  while the model is loaded. Progress shows up as a download job. */
  updateModel: (id: string) =>
    req<{ job: DownloadJob }>(`/api/models/${encodeURIComponent(id)}/update`, { method: 'POST' }),
  deleteModel: (id: string) =>
    req<{ ok: boolean }>(`/api/models/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  setPassword: (password: string) =>
    req<{ ok: boolean }>('/api/password', { method: 'POST', body: JSON.stringify({ password }) }),
  getSettings: () => req<Settings>('/api/settings'),
  /** Persist limits and push them to every loaded model; the response says
   *  what each one actually took. */
  saveSettings: (patch: SettingsPatch) =>
    req<SaveSettingsResult>('/api/settings', { method: 'POST', body: JSON.stringify(patch) }),
  /** `refresh` skips the server's 30 s size cache; the overview polls the
   *  cached form, the settings page asks for a fresh walk on demand. */
  storage: (refresh = false) => req<StorageInfo>(`/api/storage${refresh ? '?refresh=true' : ''}`),
  /** Refusals (a nested path, no room, not empty) come back as 400 with the
   *  reason in `detail`; a second concurrent request gets 409. */
  startMove: (path: string) =>
    req<{ job: string }>('/api/storage/move', { method: 'POST', body: JSON.stringify({ path }) }),
  moveStatus: () => req<MoveJob>('/api/storage/move'),

  // -- inference records ---------------------------------------------
  /** One page of record summaries, newest first. `before` pages backwards by
   *  timestamp instead of by offset, so new arrivals do not shift the page. */
  inferenceRecords: (opts: { limit?: number; offset?: number; before?: number } = {}) => {
    const q = new URLSearchParams()
    q.set('limit', String(opts.limit ?? 50))
    if (opts.offset) q.set('offset', String(opts.offset))
    if (opts.before) q.set('before', String(opts.before))
    return req<{ items: InferenceRecordSummary[]; total: number; limit: number; offset: number }>(
      `/api/inference-records?${q.toString()}`)
  },
  inferenceRecord: (id: string) =>
    req<InferenceRecord>(`/api/inference-records/${encodeURIComponent(id)}`),
  inferenceRecordStatus: () => req<InferenceRecordStatus>('/api/inference-records/status'),
  /** Irreversible: every record on this service, gone. */
  clearInferenceRecords: () =>
    req<{ ok: boolean; deleted: number }>('/api/inference-records/clear', { method: 'POST' }),
  inferenceRecordsExportUrl: () => '/api/inference-records-export',

  // -- agents ---------------------------------------------------------
  agents: () => req<{ agents: Agent[] }>('/api/agents'),
  agentInstall: (id: string) =>
    req<{ job: AgentJob }>(`/api/agents/${encodeURIComponent(id)}/install`, { method: 'POST' }),
  /** Polled while a download is in flight; null before one has ever started. */
  agentJob: (id: string) =>
    req<{ job: AgentJob | null }>(`/api/agents/${encodeURIComponent(id)}/job`),
  /** A refusal (port taken, low memory, failed start) comes back as 409 with a
   *  Chinese `detail` meant to be shown to the operator verbatim. */
  agentAct: (id: string, action: AgentAction) =>
    req<Agent>(`/api/agents/${encodeURIComponent(id)}/${action}`, { method: 'POST' }),
  agentPatch: (id: string, patch: AgentPatch) =>
    req<Agent>(`/api/agents/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),
  agentLogs: (id: string, tail = 200) =>
    req<{ log: string }>(`/api/agents/${encodeURIComponent(id)}/logs?tail=${tail}`),

  // -- per-kind tests ---------------------------------------------------
  testEmbeddings: (body: { model: string; input: (string | { text?: string; image?: string })[]; dimensions?: number; instruction?: string }) =>
    req<EmbeddingResult>('/api/test/embeddings', { method: 'POST', body: JSON.stringify(body) }),
  testRerank: (body: { model: string; query: string; documents: string[]; top_n?: number }) =>
    req<RerankResult>('/api/test/rerank', { method: 'POST', body: JSON.stringify(body) }),
  testTranscribe: (model: string, file: File, opts: { language?: string; prompt?: string } = {}) => {
    const fd = new FormData()
    fd.append('model', model)
    fd.append('file', file, file.name)
    fd.append('response_format', 'verbose_json')
    if (opts.language) fd.append('language', opts.language)
    if (opts.prompt) fd.append('prompt', opts.prompt)
    return req<TranscriptResult>('/api/test/audio/transcriptions', { method: 'POST', body: fd })
  },
  testOcr: (model: string, file: File, mode: OcrMode = 'lines') => {
    const fd = new FormData()
    fd.append('model', model)
    fd.append('file', file, file.name)
    if (mode !== 'lines') fd.append('mode', mode)
    return req<OcrResult>('/api/test/ocr', { method: 'POST', body: fd })
  },
}

/** Stream an OpenAI chat completion through the console's /v1 proxy.
 *
 *  For the kinds /api/chat/stream does not serve (PaddleOCR-VL): the request
 *  and the SSE frames are exactly OpenAI's, so this reads
 *  `choices[0].delta.content` and the trailing `usage` frame. */
export async function streamOpenAIChat(
  body: Record<string, unknown>,
  opts: { signal?: AbortSignal },
  onDelta: (text: string) => void,
): Promise<{ prompt_tokens: number; completion_tokens: number; finish_reason: string | null }> {
  const r = await fetch('/api/test/chat/completions', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    signal: opts.signal,
    body: JSON.stringify({ ...body, stream: true }),
  })
  if (!r.ok || !r.body) {
    const t = await r.text()
    let msg = t || r.statusText
    try { const j = JSON.parse(t); msg = typeof j.detail === 'string' ? j.detail : msg } catch { /* plain text */ }
    throw new Error(msg)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  const out = { prompt_tokens: 0, completion_tokens: 0, finish_reason: null as string | null }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') continue
      let obj: any
      try { obj = JSON.parse(payload) } catch { continue }
      if (obj.error) throw new Error(obj.error.message ?? String(obj.error))
      const choice = obj.choices?.[0]
      if (choice?.delta?.content) onDelta(choice.delta.content)
      if (choice?.finish_reason) out.finish_reason = choice.finish_reason
      if (obj.usage) {
        out.prompt_tokens = obj.usage.prompt_tokens ?? 0
        out.completion_tokens = obj.usage.completion_tokens ?? 0
      }
    }
  }
  return out
}

/** One part of a multi-part message: text, or an image as a data: URL
 *  (`data:image/png;base64,...`), which is the only form the offline backend
 *  accepts -- it will not fetch remote URLs. */
export type ChatContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }

/** OpenAI-shaped message, as /api/chat/stream takes it under `messages`. */
export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string | ChatContentPart[]
}

export type ChatUsage = {
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  decode_tps: number | null
  first_token_latency_s: number | null
}

/** Stream a playground chat completion, invoking onDelta for each token.
 *
 *  Uses the admin endpoint (cookie auth) rather than /v1: the console operator
 *  should not have to create an API key to try a model from the UI.
 *
 *  Pass `messages` to send the whole conversation; the backend then renders it
 *  with the chat template and ignores `prompt`/`images` (so we blank them).
 *  Multi-turn is also what makes the prefix cache measurable: the repeated
 *  prefix comes back as `cached_tokens`.
 */
export async function streamChat(
  model: string,
  prompt: string,
  opts: {
    maxTokens?: number
    temperature?: number
    images?: string[]
    enableThinking?: boolean
    messages?: ChatMessage[]
    signal?: AbortSignal
  },
  onDelta: (text: string) => void,
): Promise<ChatUsage> {
  const body = opts.messages
    ? {
        model,
        prompt: '',
        max_tokens: opts.maxTokens ?? 512,
        temperature: opts.temperature ?? 0.8,
        images: [],
        enable_thinking: opts.enableThinking ?? false,
        messages: opts.messages,
      }
    : {
        model,
        prompt,
        max_tokens: opts.maxTokens ?? 512,
        temperature: opts.temperature ?? 0.8,
        images: opts.images ?? [],
        enable_thinking: opts.enableThinking ?? false,
      }
  const r = await fetch('/api/chat/stream', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    signal: opts.signal,
    body: JSON.stringify(body),
  })
  if (!r.ok || !r.body) {
    const t = await r.text()
    let msg = t || r.statusText
    try { const j = JSON.parse(t); msg = typeof j.detail === 'string' ? j.detail : msg } catch { /* plain text */ }
    throw new Error(msg)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  const usage: ChatUsage = { prompt_tokens: 0, completion_tokens: 0, cached_tokens: 0, decode_tps: null, first_token_latency_s: null }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') continue
      try {
        const obj = JSON.parse(payload)
        if (obj.error) throw new Error(obj.error)
        if (obj.text) onDelta(obj.text)
        if (obj.done) {
          usage.prompt_tokens = obj.prompt_tokens ?? 0
          usage.completion_tokens = obj.completion_tokens ?? 0
          usage.cached_tokens = obj.cached_tokens ?? 0
          usage.decode_tps = obj.decode_tps ?? null
          usage.first_token_latency_s = obj.first_token_latency_s ?? null
        }
      } catch (e) {
        if (e instanceof Error && e.message && !e.message.includes('JSON')) throw e
      }
    }
  }
  return usage
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function fmtPct(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : `${n.toFixed(1)}%`
}

/** Bytes as whole MiB. The cache limits are configured in MB and compared
 *  against an NPU cap also expressed in MB, so keeping both on that one scale
 *  is what makes "configured 2048, effective 1430" readable. */
export function fmtMb(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : `${Math.round(n / (1024 * 1024))} MB`
}

/** How often to re-read a backend operation while one is in flight.
 *
 *  A model load takes a minute or more, an agent start a few seconds; 1.5 s is
 *  fast enough that the UI stops feeling stuck and slow enough not to poll the
 *  board's management plane hard. Polling only happens while something is
 *  busy -- an idle console must not tick. */
export const OPERATION_POLL_MS = 1500

/** Whether any model has an operation in flight. */
export function anyModelBusy(models: Model[]): boolean {
  return models.some((m) => m.operation !== null)
}

/** Whether any agent has an operation in flight. */
export function anyAgentBusy(agents: Agent[]): boolean {
  return agents.some((a) => a.operation !== null)
}

/** "加载中…" plus elapsed seconds, from the server's `operation_since`.
 *
 *  The elapsed count comes from a server timestamp, not from when this browser
 *  started looking: after a refresh the label must reflect how long the
 *  operation has really been running, not restart at zero. */
export function operationElapsed(since: number | null | undefined): string {
  if (!since) return ''
  const s = Math.max(0, Math.round(Date.now() / 1000 - since))
  if (s < 90) return `${s} 秒`
  return `${Math.round(s / 60)} 分钟`
}
