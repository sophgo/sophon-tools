import { useEffect, useRef, useState } from 'react'

/** In-app documentation.
 *
 *  Only what an operator needs while running the box: get a model up, call the
 *  API, know where the cache helps, connect an agent, and know the limits that
 *  will bite. Version-by-version history and internal implementation detail
 *  were deliberately dropped -- they made the page long enough that the parts
 *  people actually need were hard to find. Every known limitation stays: hiding
 *  one would lead someone to build on an assumption the hardware breaks.
 */

type Section = { id: string; title: string }

const SECTIONS: Section[] = [
  { id: 'start', title: '快速开始' },
  { id: 'api', title: '常用 API' },
  { id: 'aux', title: 'Embedding、Rerank、语音与 OCR' },
  { id: 'apps', title: '应用演示' },
  { id: 'mcp', title: 'MCP 工具' },
  { id: 'admin-api', title: '管理 API' },
  { id: 'models', title: '模型与缓存' },
  { id: 'vision', title: '图片、思考与工具调用' },
  { id: 'agents', title: 'Agent 接入' },
  { id: 'records', title: '推理记录' },
  { id: 'limits', title: '故障与限制' },
  // The label must match the <h2> it points at. It read 「重启后接管进程」 while
  // the heading said 「重启后接管已有进程」, so the reader had to guess whether
  // the link led where they expected.
  { id: 'takeover', title: '重启后接管已有进程' },
  { id: 'ops', title: '运维' },
]

/** Which section the reader is looking at: the last heading whose top has
 *  passed a line a little below the viewport top. Falls back to the first. */
function useActiveSection(ids: string[]): string {
  const [active, setActive] = useState(ids[0])
  useEffect(() => {
    const onScroll = () => {
      let current = ids[0]
      for (const id of ids) {
        const el = document.getElementById(id)
        if (!el) continue
        if (el.getBoundingClientRect().top - 96 <= 0) current = id
      }
      setActive(current)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [ids])
  return active
}

export default function Docs() {
  const base = window.location.origin
  const ids = SECTIONS.map((s) => s.id)
  const active = useActiveSection(ids)
  const toc = useRef<HTMLDetailsElement>(null)
  // On a phone the list is a collapsible strip above the text and starts
  // closed, so the reader sees the first paragraph rather than eight links.
  const [wide, setWide] = useState(
    () => !window.matchMedia('(max-width: 1080px)').matches)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1080px)')
    const on = () => setWide(!mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  // The open state is imperative, not a prop: a controlled `open` would be
  // rewritten on every re-render (the active-section highlight re-renders on
  // scroll), slamming the list shut while the reader is using it.
  useEffect(() => {
    if (toc.current) toc.current.open = wide
  }, [wide])

  // A jump lands with the heading just below the top edge (scroll-margin-top in
  // CSS). On a narrow screen the strip would otherwise stay open over the text.
  const jump = (id: string) => {
    if (toc.current && !wide) toc.current.open = false
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div>
      <h1>文档</h1>
      <p className="sub">这个服务怎么用、边界在哪，以及常见 Agent 的接入方式。</p>

      <div className="docs-layout">
        <div className="docs">
          <h2 id="start">快速开始</h2>
          <ol>
            <li>
              把模型放进数据目录的 <code>models/&lt;模型名&gt;/</code>
              （默认 <code>/data/cv84x6_llm_server/models/</code>），目录里要有
              <code>*.bmodel</code> 和 <code>config/</code>；也可以在「模型」页一键从 dfss 下载。
            </li>
            <li>在「模型」页点<b>加载</b>。20 GB 级模型首次加载约 66 秒，期间请求会排队。</li>
            <li>在「API Key」页创建密钥（明文只显示一次），或者直接用「对话测试」页。</li>
            <li>按下表接入；客户端把 base URL 指向本机即可，不需要联网。</li>
          </ol>
          <pre className="code">{`Base URL: ${base}/v1
API Key:  sk-…（在「API Key」页创建）
Model:    已加载模型的 id（见「模型」页）`}</pre>

          <h2 id="api">常用 API</h2>
          <div className="table-wrap">
          <table>
            <thead><tr><th>方法</th><th>路径</th><th>说明</th></tr></thead>
            <tbody>
              <tr><td>GET</td><td className="mono">/v1/models</td><td>列出<b>当前可推理</b>的模型（未就绪的不出现）</td></tr>
              <tr><td>POST</td><td className="mono">/v1/chat/completions</td><td>对话补全，支持 <code>stream</code>；PaddleOCR-VL 也走这里</td></tr>
              <tr><td>POST</td><td className="mono">/v1/embeddings</td><td>文本向量（OpenAI 格式），见下一章</td></tr>
              <tr><td>POST</td><td className="mono">/v1/rerank</td><td>重排序（Jina/Cohere 格式），别名 <code>/rerank</code></td></tr>
              <tr><td>POST</td><td className="mono">/v1/audio/transcriptions</td><td>语音转写（OpenAI 格式，multipart 上传）</td></tr>
              <tr><td>POST</td><td className="mono">/v1/ocr</td><td>图片文字识别（本服务自有格式）</td></tr>
              <tr><td>GET</td><td className="mono">/healthz</td><td>服务存活检查，<b>不代表模型已加载</b></td></tr>
            </tbody>
          </table>
          </div>
          <p>
            请求与响应字段按 OpenAI 的格式：<code>messages</code>、<code>max_tokens</code>、
            <code>stop</code>、<code>tools</code>、流式 SSE，以及
            <code>usage.prompt_tokens_details.cached_tokens</code>（前缀缓存命中的 token 数）。
          </p>
          <p>
            <b>「已就绪」的含义</b>：只有权重、引擎、tokenizer/vision、缓存预算与调度器全部初始化
            完成，模型才算就绪。加载中、卸载中、加载失败时，<code>/v1/chat/completions</code> 与
            <code>/api/chat*</code> 一律返回 <b>409</b>，且不会产生推理记录——
            不会把请求送进半初始化的 worker。
          </p>
          <p>
            <code>/healthz</code> 只说明<b>服务进程活着</b>（<code>loaded</code> 是计数，可以是 0）：
            客户端要判断能不能推理，请查 <code>/v1/models</code>（只列可推理的模型），
            或在控制台「模型」页看到「已加载」。不要在服务刚启动时用 <code>/healthz</code> 200
            就发请求。
          </p>
          <pre className="code">{`curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer $CV84X6_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "your-model-id",
    "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
    "max_tokens": 256,
    "stream": true
  }'`}</pre>
          <pre className="code">{`from openai import OpenAI

client = OpenAI(base_url="${base}/v1", api_key="sk-…")
resp = client.chat.completions.create(
    model="your-model-id",
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=256,
)
print(resp.choices[0].message.content)
print(resp.usage)   # prompt_tokens_details.cached_tokens：缓存命中的 token 数`}</pre>
          <p>
            大多数 agent 工具都接受「OpenAI 兼容 base URL」这一种配置，把环境变量指过来即可：
          </p>
          <pre className="code">{`export OPENAI_BASE_URL="${base}/v1"
export OPENAI_API_KEY="sk-…"`}</pre>

          <h2 id="aux">Embedding、Rerank、语音与 OCR</h2>
          <p>
            除大语言模型外，服务还提供四类辅助模型，各走各的接口；鉴权与 <code>/v1/chat/completions</code>
            相同（<code>Authorization: Bearer sk-…</code>）。在「模型」页对应的页签里一键下载、加载，
            在「对话测试」页选中模型即可试用，不需要 API Key。
          </p>
          <ul>
            <li>
              <b>类型由 bmodel 文件名决定</b>，不是配置项。把模型发到不匹配的接口返回 <b>400</b>，
              并写明应该调哪个接口；未加载、加载中返回 <b>409</b>；模型不存在返回 404。
            </li>
            <li>
              <b>内存准入</b>：同时在线的模型数量不设上限，由 NPU 内存决定。辅助模型按 NPU 实测剩余内存准入，
              要求剩余 ≥ 文件大小 + 256 MiB，不足时加载返回 409 并给出两个数字；大语言模型的占用取决于上下文长度，
              加载时 NPU 不够会失败并提示「NPU 内存不足」。需要限制大语言模型的数量时，在 <code>server.env</code> 里加 <code>CV84X6_MAX_LOADED=N</code> 后重启服务。
              另外，任何一次加载之后，NPU 都必须<b>至少剩 1 GiB</b>（大语言模型按内存上限计算，会话和缓存后续还会增长）：NPU 堆接近占满时 TPU 会卡死，只能重启板子。
              因此 32 GB 的设备默认不能同时装下全部 6 个模型；确需共存时可调 <code>CV84X6_NPU_RESERVE_MB</code>（<code>0</code> 表示关闭），但会重新面临卡死风险。
            </li>
            <li>
              <b>并发</b>：Embedding、Reranker 每个模型同时只处理 1 个请求、最多 1 个排队，再多直接返回
              <b>429</b>（NPU 一次只算一个，并发不会更快，只会多占内存）；一个请求里的多条文本连续算完，先到先得。
            </li>
            <li>
              <b>不采样</b>：所有辅助模型都是确定性输出，同一输入得到同一结果；<code>temperature</code>
              之类的参数接受但不生效。
            </li>
          </ul>

          <h3>模型与 NPU 占用</h3>
          <div className="table-wrap">
          <table>
            <thead><tr><th>类型</th><th>模型</th><th>接口</th><th className="num">文件</th><th className="num">NPU 实测</th><th>输入上限</th></tr></thead>
            <tbody>
              <tr><td>Embedding</td><td>Qwen3-Embedding-0.6B</td><td className="mono">/v1/embeddings</td><td className="num">1.1 GiB</td><td className="num">1.4 GiB</td><td>单条 2048 token，1024 维</td></tr>
              <tr><td>Reranker</td><td>BGE-Reranker-v2-M3</td><td className="mono">/v1/rerank</td><td className="num">1.1 GiB</td><td className="num">1.1 GiB</td><td>每对（查询 + 文档）2048 token</td></tr>
              <tr><td>语音识别</td><td>Qwen3-ASR-0.6B</td><td className="mono">/v1/audio/transcriptions</td><td className="num">1.5 GiB</td><td className="num">1.6 GiB</td><td>50 MB、30 分钟</td></tr>
              <tr><td>语音识别</td><td>Qwen3-ASR-1.7B</td><td className="mono">/v1/audio/transcriptions</td><td className="num">3.8 GiB</td><td className="num">4.0 GiB</td><td>50 MB、30 分钟</td></tr>
              <tr><td>OCR</td><td>PP-OCRv6 medium（检测 + 识别，4 个文件）</td><td className="mono">/v1/ocr</td><td className="num">213 MiB</td><td className="num">154–230 MiB</td><td>20 MiB 图片</td></tr>
              <tr><td>OCR</td><td>PaddleOCR-VL-1.5</td><td className="mono">/v1/chat/completions</td><td className="num">2.1 GiB</td><td className="num">2.0 GiB</td><td>单张图，上下文 2048 token</td></tr>
            </tbody>
          </table>
          </div>
          <p className="lead">
            「NPU 实测」是在 CV84X6（23.75 GiB NPU 内存）上加载后 <code>bm-smi</code> 读到的占用，
            卸载后回到 0。PP-OCR 的三档识别网络按需映射，所以有一个范围。
          </p>

          <h3>Embedding：POST /v1/embeddings</h3>
          <p>
            OpenAI 格式。<code>input</code> 是字符串或字符串数组（一次最多 <b>64</b> 条）；
            <code>dimensions</code> 可在 32 到 1024 之间截断（截断后仍是单位向量）；
            <code>encoding_format</code> 支持 <code>float</code> 与 <code>base64</code>。
            非标准字段 <code>instruction</code> 会原样拼在每条文本前面。
          </p>
          <pre className="code">{`curl ${base}/v1/embeddings \\
  -H "Authorization: Bearer $CV84X6_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "qwen3-embedding-0.6b", "input": ["NPU 内存不足时会排队", "显存不够时请求进入队列"]}'

{"object": "list", "model": "qwen3-embedding-0.6b",
 "data": [{"object": "embedding", "index": 0, "embedding": [0.0123, -0.0456, …]}, …],
 "usage": {"prompt_tokens": 18, "total_tokens": 18}}`}</pre>
          <ul>
            <li>空字符串、token id 数组返回 400；单条超过 2048 token 返回 400 并给出上限，<b>不会静默截断</b>。</li>
            <li>
              检索时查询要带指令、文档不带：查询写成
              <code>{'Instruct: Given a web search query, retrieve relevant passages that answer the query\\nQuery: '}</code>
              + 查询文本，指令一个词都不要改，否则相似度会偏离参考值。
            </li>
          </ul>

          <h3>Rerank：POST /v1/rerank</h3>
          <p>
            OpenAI 没有重排序接口，这里采用 <b>Jina / Cohere 格式</b>（Dify、RAGFlow、LangChain 都按它调用），
            并在 <code>/rerank</code> 提供同一接口。<code>documents</code> 可以是字符串，也可以是
            <code>{'{"text": …}'}</code> 对象，一次最多 <b>256</b> 条；<code>top_n</code> 可选；
            <code>return_documents</code> 默认 <code>true</code>。
          </p>
          <pre className="code">{`curl ${base}/v1/rerank \\
  -H "Authorization: Bearer $CV84X6_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "bge-reranker-v2-m3", "query": "设备内存不够时会怎样？",
       "documents": ["NPU 内存不足时请求会排队", "今天天气晴"], "top_n": 1}'

{"id": "rerank-…", "model": "bge-reranker-v2-m3",
 "results": [{"index": 0, "relevance_score": 0.8429, "document": {"text": "NPU 内存不足时请求会排队"}}],
 "usage": {"prompt_tokens": 31, "total_tokens": 31}}`}</pre>
          <p>
            结果按分数<b>降序</b>，<code>index</code> 指文档在输入里的原始位置。分数是
            <code>sigmoid(logit)</code>，落在 0–1，排序与原始 logit 一致。
          </p>

          <h3>语音识别：POST /v1/audio/transcriptions</h3>
          <p>
            OpenAI 格式，<code>multipart/form-data</code> 上传。字段：<code>file</code>（必填）、
            <code>model</code>（必填）、<code>language</code>（可选，<code>zh</code> / <code>Chinese</code>
            等，未知语言返回 400 并列出可用值）、<code>prompt</code>（可选，作为上下文）、
            <code>response_format</code>（<code>json</code> 默认 / <code>text</code> /
            <code>verbose_json</code> / <code>srt</code> / <code>vtt</code>）。
          </p>
          <pre className="code">{`curl ${base}/v1/audio/transcriptions \\
  -H "Authorization: Bearer $CV84X6_KEY" \\
  -F file=@meeting.wav -F model=qwen3-asr-0.6b -F response_format=verbose_json

{"task": "transcribe", "language": "Chinese", "duration": 4.204,
 "text": "甚至出现交易几乎停滞的情况。",
 "segments": [{"id": 0, "start": 0.0, "end": 4.204, "text": "甚至出现交易几乎停滞的情况。", …}], …}`}</pre>
          <ul>
            <li>
              <b>格式与 ffmpeg</b>：WAV 由服务直接解码；mp3、m4a、flac 等交给 ffmpeg。设备自带的 Sophon SDK
              ffmpeg 不在 PATH 里，服务会自动找到它（也可用环境变量 <code>CV84X6_FFMPEG</code> 指定）；
              服务本身不安装 ffmpeg。没有 ffmpeg 或无法解码时返回 <b>415</b>。
            </li>
            <li>
              <b>长度</b>：单个文件 ≤ 50 MB、≤ 30 分钟，超出返回 400。超过 30 秒的音频按整秒切段，
              每段一个 segment，时间首尾相接。
            </li>
            <li><b>速度</b>：0.6B 在板上实测 4–18 倍实时（音频越长，每段固定开销摊得越薄）。</li>
            <li><code>temperature</code> 接受但不生效：贪心解码，相同音频得到相同文字。</li>
          </ul>

          <h3>OCR：POST /v1/ocr</h3>
          <p>
            OpenAI 没有 OCR 接口，这是本服务自有的格式。请求体可以是 JSON
            （<code>{'{"model", "image"}'}</code>，<code>image</code> 为 <code>data:image/png;base64,…</code>
            或纯 base64），也可以是 multipart 上传（<code>file</code> + <code>model</code>）。
            <code>return_boxes: false</code> 时不返回检测框。
          </p>
          <pre className="code">{`curl ${base}/v1/ocr \\
  -H "Authorization: Bearer $CV84X6_KEY" \\
  -F file=@page.png -F model=ppocrv6-medium

{"id": "ocr-…", "model": "ppocrv6-medium",
 "text": "系统状态 System Status\\nCPU 使用率\\n23%\\n…",
 "lines": [{"text": "系统状态 System Status", "score": 0.998,
            "box": [[24, 18], [402, 18], [402, 56], [24, 56]]}, …],
 "usage": {"det_ms": 41.2, "rec_ms": 88.5, "lines": 11}}`}</pre>
          <ul>
            <li><code>box</code> 是原图像素坐标的四个点，顺序为左上、右上、右下、左下。</li>
            <li>图片 ≤ 20 MiB。默认不拉取 http(s) 图片 URL（设备离线），需要时设置 <code>CV84X6_OCR_ALLOW_REMOTE=1</code>。</li>
            <li>
              <b>已知限制</b>：<b>不支持竖排文字</b>（检测与识别网络都按横排训练）；两栏正文的行会交错，
              需要分栏时先裁图。表格、公式请用 PaddleOCR-VL。
            </li>
          </ul>

          <h3>PaddleOCR-VL：视觉对话</h3>
          <p>
            PaddleOCR-VL-1.5 是一个视觉语言模型，按 OpenAI 视觉格式调用
            <code>/v1/chat/completions</code>：<code>content</code> 里放<b>一张</b>图片和一条任务指令，
            没有图或多于一张图返回 400。官方的任务指令有四种：
            <code>OCR:</code>（文字）、<code>Table Recognition:</code>（表格）、
            <code>Formula Recognition:</code>（公式）、<code>Chart Recognition:</code>（图表）。
            调用方式与官方 PaddleOCR-VL 的 vLLM 服务相同，PaddleOCR 官方客户端
            （<code>vl_rec_backend="vllm-server"</code>）可以直接把本机 <code>/v1</code> 当作识别服务。
          </p>
          <pre className="code">{`curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer $CV84X6_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "paddleocr-vl-1.5", "stream": true, "max_tokens": 1024,
       "messages": [{"role": "user", "content": [
         {"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}},
         {"type": "text", "text": "Table Recognition:"}]}]}'`}</pre>
          <ul>
            <li>
              表格以 <b>OTSL</b> 输出：<code>&lt;fcel&gt;</code> 有内容的单元格、<code>&lt;ecel&gt;</code> 空单元格、
              <code>&lt;lcel&gt;</code> / <code>&lt;ucel&gt;</code> / <code>&lt;xcel&gt;</code> 与左侧 / 上方 / 左上合并、
              <code>&lt;nl&gt;</code> 换行。转成 HTML 的规则与 PaddleX 的 <code>convert_otsl_to_html</code> 相同，
              控制台「对话测试」里显示的表格和「复制 HTML」用的就是这套规则。
            </li>
            <li>
              图片统一缩放到 784×784 后识别，适合单个区域（一段文字、一张表格、一个公式）；整页文档请先裁剪。
              输出受 2048 token 上下文约束，<code>max_tokens</code> 与 <code>max_completion_tokens</code> 都支持。
            </li>
            <li>
              解码是贪心的，<code>temperature</code>、<code>top_p</code> 不报错也不生效；不支持 <code>tools</code>。
              同一时间只处理一个请求，其余排队。它不会出现在 agent 和知识库的模型选择里。
            </li>
          </ul>

          <h2 id="apps">应用演示</h2>
          <p className="lead">
            「应用演示」页把辅助模型组合成可以直接给客户看的应用，所有处理都在本机 NPU 上完成，数据不出设备。
          </p>
          <ul>
            <li>
              <b>知识库问答</b>：上传 TXT / MD / PDF / 图片建库。PDF 中没有文字层的页和图片先 OCR，
              再按约 400 字切片、写入向量。提问时依次做关键词 BM25、向量检索、RRF 融合、Reranker 精排，
              页面画出每个片段在四步中的名次变化；加载了对话模型时，再根据前 5 条资料生成带 [n] 引用的回答。
              接口为 <code>/api/apps/kb/*</code>（仅控制台登录后可用）。
            </li>
            <li>
              <b>按已加载的模型降级</b>：64 GB 的设备（NPU 30 GiB）可以同时加载 35B、Embedding、Reranker 和 PP-OCR，
              完整演示「混合检索 + 生成回答」。32 GB 的设备上 35B 加载后 NPU 只剩约 1 GiB，放不下 Embedding（1.4 GiB）和
              Reranker（1.1 GiB），演示分两步：先加载 Embedding + Reranker + PP-OCR 建库并演示完整检索；
              再卸载这两个模型、加载 35B，用关键词检索 + 生成回答。没加载的模型对应的步骤显示「已跳过」和原因。
              建库（写向量）必须有 Embedding 模型。
            </li>
            <li>
              <b>语音转写</b>：音频按约 30 秒一段转写，每转完一段就显示，可以随时停止；点时间跳到对应位置播放，
              可导出 TXT / SRT。浏览器只在 HTTPS 或 localhost 下允许使用麦克风，局域网 HTTP 访问时只能上传文件。
            </li>
            <li>
              <b>文档识别</b>：一次选多张图片，按顺序用 PP-OCR 识别，图上标出每一行的位置，结果可以复制或保存为 TXT。
              PDF 请在知识库页上传。
            </li>
          </ul>

          <h2 id="mcp">MCP 工具</h2>
          <p className="lead">
            服务在同一端口提供 <code>POST /mcp</code>（MCP Streamable HTTP），把知识库、OCR 和语音转写作为工具提供给 agent。
            内置 agent 安装后已自动接入；局域网内其他电脑上的 MCP 客户端也可以接入。
          </p>
          <div className="table-wrap">
          <table>
            <thead><tr><th>工具</th><th>用途</th></tr></thead>
            <tbody>
              <tr><td className="mono">kb_search</td><td>在知识库中混合检索（关键词 + 向量，加载了 Reranker 时精排），返回带出处的片段</td></tr>
              <tr><td className="mono">kb_read</td><td>读取某个片段及其前后文</td></tr>
              <tr><td className="mono">kb_list · kb_list_documents · kb_document_status</td><td>查看知识库、文档和处理进度</td></tr>
              <tr><td className="mono">kb_create · kb_add_document</td><td>新建知识库；把设备上的文件或一段文字加入知识库</td></tr>
              <tr><td className="mono">ocr_read</td><td>识别图片或 PDF 中的文字（PDF 有文字层的页直接取文字，扫描页走 OCR），不写入知识库</td></tr>
              <tr><td className="mono">transcribe_audio</td><td>把音频文件转成文字，带分段时间</td></tr>
            </tbody>
          </table>
          </div>
          <ul>
            <li><b>不提供删除</b>：删除文档和知识库只能在控制台操作。也没有问答工具，回答由 agent 自己的模型生成。</li>
            <li>
              <b>鉴权</b>：与 <code>/v1</code> 相同的 API Key（<code>Authorization: Bearer &lt;key&gt;</code>）。
              浏览器跨站请求（<code>Origin</code> 不是本机或同源）会被拒绝。
            </li>
            <li>
              <b>能读哪些文件</b>：只能读取数据目录下的 <code>agents/</code>（agent 的工作区和附件）和 <code>inbox/</code>，
              以及 <code>server.env</code> 中 <code>CV84X6_MCP_PATHS</code> 列出的目录；单个文件 ≤ 50 MB。
            </li>
            <li>
              <b>前提</b>：检索需要 Embedding 模型（加载了 Reranker 时精排），OCR 需要 PP-OCR，转写需要 Qwen3-ASR。
              对应模型没有加载时，工具会返回明确的提示。
            </li>
          </ul>
          <p>其他客户端（例如 Cursor、Claude Desktop）的配置示例：</p>
          <pre className="code"><code>{`{
  "mcpServers": {
    "cv84x6": {
      "type": "streamable-http",
      "url": "http://<设备地址>:8000/mcp",
      "headers": { "Authorization": "Bearer <API Key>" }
    }
  }
}`}</code></pre>

          <h2 id="admin-api">管理 API</h2>
          <p className="lead">
            控制台能做的事（模型、下载、设置、Key、日志、审计、Agent、应用）都有对应的 <code>/api/*</code> 接口，
            脚本可以直接调用。完整的接口说明随服务一起离线提供，不需要联网：
          </p>
          <div className="link-row" data-testid="admin-api-links">
            <a className="btn ghost sm" href="/api/docs" target="_blank" rel="noreferrer" data-testid="link-api-docs">交互式文档（Swagger）</a>
            <a className="btn ghost sm" href="/api/redoc" target="_blank" rel="noreferrer" data-testid="link-api-redoc">通读版（ReDoc）</a>
            <a className="btn ghost sm" href="/api/openapi.json" target="_blank" rel="noreferrer">管理 API 的 OpenAPI</a>
            <a className="btn ghost sm" href="/v1/openapi.json" target="_blank" rel="noreferrer">/v1 的 OpenAPI</a>
          </div>
          <ul>
            <li>
              <b>认证</b>：在「API Key」页创建权限为「管理」的 Key，脚本用 <code>Authorization: Bearer sk-…</code> 调用；
              「推理」Key 调 <code>/api/*</code> 返回 403（<code>forbidden_scope</code>），这样发给 agent 的 Key 不会顺带交出管理权。
              浏览器里已登录时，上面的文档链接直接可以打开。
            </li>
            <li>
              <b>错误格式</b>：所有 <code>/api/*</code> 错误都是 <code>{'{"detail": "中文说明", "code": "稳定的英文错误码"}'}</code>，
              脚本按 <code>code</code> 分支；<code>/v1</code> 仍是 OpenAI 的错误格式。
            </li>
          </ul>
          <pre className="code">{`# 列出模型、加载一个模型（admin Key）
curl -H "Authorization: Bearer $CV84X6_ADMIN_KEY" ${base}/api/models
curl -X POST -H "Authorization: Bearer $CV84X6_ADMIN_KEY" ${base}/api/models/qwen3-embedding-0.6b/load`}</pre>

          <h2 id="models">模型与缓存</h2>
          <h3>上下文</h3>
          <p>
            上下文由 bmodel 决定，超出直接返回 400，不会静默截断。<b>图片占用的 token 也计入</b>。
          </p>
          <div className="table-wrap">
          <table>
            <thead><tr><th>版本</th><th>上下文</th><th>加载后 NPU 占用</th><th>适合</th></tr></thead>
            <tbody>
              <tr>
                <td>长上下文 128k（<code>seq131072</code>）</td>
                <td className="num">131072</td>
                <td className="num">约 22.8 / 23.75 GB</td>
                <td>单次处理很长的文档</td>
              </tr>
              <tr>
                <td>长上下文 32k（<code>seq32768</code>）</td>
                <td className="num">32768</td>
                <td className="num">约 20.4 GB</td>
                <td>多人同时用、反复追问同一份长文档</td>
              </tr>
            </tbody>
          </table>
          </div>
          <p>
            「模型」页的一键下载只提供 Qwen3.6-35B-A3B 128k（mask128 优化版：长 prompt 冷启动预填充
            快 24–55%，输出与旧版逐 token 一致）。32k 或 Qwen3.5 的 bmodel 自己放进 <code>models/</code>
            仍可加载使用。
            2k 上下文的 <code>seq2048</code> demo 版不在下载列表里：它放不下本服务面向的 prompt，
            也不是另一种权重。自己放进 <code>models/</code> 的 <code>seq2048</code> 模型仍会被扫描、
            加载并提供接口，只是不支持前缀缓存。
          </p>
          <p>
            128k 是 NPU 内存放得下的最长档，256k 放不下。剩下的内存要分给停放的会话和前缀缓存，
            所以 32k 版比 128k 版宽裕（约 3 GB 对约 1 GB），长文档反复提问用 32k 更稳。
          </p>

          <h3>前缀缓存</h3>
          <ul>
            <li>
              <b>怎么生效</b>：服务在 prefill 途中给会话拍快照（KV 与线性注意力状态），位置在 system
              消息结束处和最后一轮 assistant 开始前。之后只要请求以相同的 token 开头，就从最长的快照续算。
              多轮对话每轮都要重发历史，所以第二轮起基本都命中。
            </li>
            <li>
              <b>看命中</b>：响应里的 <code>cached_tokens</code>、「总览」页的缓存命中率、
              「对话测试」每条回答下方的「缓存 N」。
            </li>
            <li>
              <b>容量与保留</b>：在「设置」页配置上限（默认 2048 MB）和保留时间（默认 120 分钟，按 LRU 淘汰）。
              实际上限还受 NPU 剩余内存限制；推理中的会话需要内存时，缓存先让位。
              每个快照至少约 32 MB，所以短于 16 token 的前缀不缓存；多轮对话从第二轮起即可命中。
            </li>
            <li>
              <b>结果一致性</b>：同一个命中重复请求，输出完全一致；命中与冷启动措辞可能不同（两者都正确），
              因为续算走 <code>block_kv</code> 图，与冷启动计算顺序不同，bf16 不是逐位相同。
            </li>
            <li><b>只有长上下文版有</b>：自行导入的 <code>seq2048</code> 没有 <code>block_kv</code> 图，缓存自动关闭。</li>
          </ul>

          <h2 id="vision">图片、思考与工具调用</h2>
          <h3>图片（VLM）</h3>
          <ul>
            <li>
              只接受 base64 data URL：
              <code>{'{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,…"}}'}</code>。
              传远程 URL 返回 400 —— 设备离线，服务不会去取图。
            </li>
            <li>服务端自动缩放到不超过 2304 个 patch（约 768×768），不用自己预处理。</li>
            <li>每张图约占 patch/4 个 token，最多 576 token，并与文本一起计入 prompt 上限。</li>
            <li>不支持视频。</li>
          </ul>
          <h3>思考模式</h3>
          <ul>
            <li>默认<b>关闭</b>，与官方 demo 一致：模板在回答前插入一个空的 <code>&lt;think&gt;&lt;/think&gt;</code>。</li>
            <li>开启：请求体加 <code>"enable_thinking": true</code>，或
                <code>{'{"chat_template_kwargs":{"enable_thinking":true}}'}</code>。</li>
            <li>
              思考内容走 <code>message.reasoning_content</code>（流式是 <code>delta.reasoning_content</code>），
              正文里不会混进 think 标签。开启后 token 消耗和耗时都明显上升。
            </li>
          </ul>
          <h3>函数调用（tools / tool_calls）</h3>
          <ul>
            <li>
              请求带 <code>tools</code>，可选 <code>tool_choice</code>；模型决定调用时响应里有
              <code>message.tool_calls</code>（<code>id</code>、<code>function.name</code>、
              <code>function.arguments</code>），<code>finish_reason</code> 为 <code>"tool_calls"</code>。
            </li>
            <li>
              回传结果：把 <code>{'{"role":"tool","tool_call_id":…}'}</code> 加进 <code>messages</code>
              再请求一次，多轮工具调用按同样方式循环。
            </li>
            <li>
              不做强制解码：<code>"required"</code> 只是把工具放进 prompt，不保证模型一定调用；
              <code>"none"</code> 完全不提供工具。解析失败时整段文本按正文返回，不报错。
            </li>
            <li>工具定义放在首条 system 消息里，多轮工具调用每轮只 prefill 新增内容，缓存照常命中。</li>
          </ul>
          <pre className="code">{`tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询某个城市的当前天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

resp = client.chat.completions.create(
    model="your-model-id",
    messages=[{"role": "user", "content": "北京天气怎么样"}],
    tools=tools,
)
call = resp.choices[0].message.tool_calls[0]
print(call.function.name, call.function.arguments)

# 把结果回传，让模型给出最终回答
messages = [
    {"role": "user", "content": "北京天气怎么样"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": call.id, "type": "function",
         "function": {"name": call.function.name,
                      "arguments": call.function.arguments}}]},
    {"role": "tool", "tool_call_id": call.id, "content": "晴，25 度"},
]
print(client.chat.completions.create(
    model="your-model-id", messages=messages, tools=tools
).choices[0].message.content)`}</pre>

          <h2 id="agents">Agent 接入</h2>
          <p>
            「Agent」页可以在浏览器里一键安装、配置、启停、重置、卸载开源 agent，让它直接用本机的模型干活。
            所有文件都在 <code>&lt;数据目录&gt;/agents/&lt;id&gt;/</code> 下，<code>HOME</code>、
            <code>XDG_*</code>、<code>TMPDIR</code> 全部指向那里，不会写系统的
            <code>~/.config</code> 或 <code>/tmp</code>。
          </p>
          <div className="table-wrap">
          <table>
            <thead><tr><th>Agent</th><th>版本</th><th>端口</th><th>说明</th></tr></thead>
            <tbody>
              <tr>
                <td>PicoClaw</td><td className="mono">0.3.1</td>
                <td className="mono">14097<br /><small>gateway 14098</small></td>
                <td>
                  两个静态二进制，没有 Node/Python 依赖；launcher 自带网页界面与登录，
                  gateway 由 launcher 自己拉起
                </td>
              </tr>
              <tr>
                <td>opencode</td><td className="mono">1.19.4</td><td className="mono">14096</td>
                <td>单个可执行文件，不依赖 Node，自带网页界面</td>
              </tr>
              <tr>
                <td>OpenClaw</td><td className="mono">2026.10.7</td><td className="mono">18790</td>
                <td>自带私有 Node 24（要求 ≥ 24.22.1，板卡自带的 Node 22 不满足）</td>
              </tr>
            </tbody>
          </table>
          </div>
          <h3>PicoClaw 的两个进程与登录</h3>
          <p>
            PicoClaw 不是一个进程：<code>picoclaw-launcher</code> 是网页控制台，它会再拉起
            <code>picoclaw gateway</code>。<b>停止时两个一起停</b> —— 服务把 launcher 放在独立的进程组里，
            停止时对整个组发信号；如果 launcher 自己先崩了，服务会把遗留的 gateway 也收掉，
            不留着它占端口和模型连接。
          </p>
          <p>
            launcher 用<b>密码登录</b>（HttpOnly Cookie，没有 Bearer 或 URL token 登录），
            面板上的密码就是服务生成的 agent secret：首次启动时服务通过 launcher 自己的
            <code>/api/auth/setup</code> 把它写进去，之后直接用它登录即可。
            gateway 只监听 <code>127.0.0.1</code>，端口是 launcher 端口 +1（默认 14098，
            写进 <code>gateway.port</code>），<b>不占用 OpenClaw 的 18790</b>。
          </p>
          <p>
            如果面板显示「已启动」但对话没有回复，先看 agent 卡片上的提示：那是
            launcher 起来了、gateway 没起来（通常是默认模型没加载）。<b>启动成功不等于能对话</b>，
            所以启动时会额外确认 gateway 的健康检查。
          </p>
          <h3>默认配置及原因</h3>
          <div className="table-wrap">
          <table>
            <thead><tr><th>配置</th><th>值</th><th>为什么</th></tr></thead>
            <tbody>
              <tr>
                <td>上下文</td><td className="mono">= 模型上下文</td>
                <td>取自已加载模型的真实值，不让 agent 拿到比模型能吃的更大的窗口 —— 那样只会在中途被截断</td>
              </tr>
              <tr>
                <td>单次输出上限</td><td className="mono">min(16384, 上下文/2)</td>
                <td>这块板子解码约 20–30 token/s，16384 token 约 10–14 分钟的连续输出；另一半上下文留给 prompt</td>
              </tr>
              <tr>
                <td>思考模式</td><td className="mono">默认关</td>
                <td>思考 token 也按同样速度生成，开着会让每次响应多等几十秒到几分钟</td>
              </tr>
              <tr>
                <td>请求超时</td><td className="mono">1800000 ms</td>
                <td>慢速解码下一个长回答要十几分钟，SDK 默认的超时会直接掐断</td>
              </tr>
              <tr>
                <td>联网开关</td><td className="mono">全部关闭</td>
                <td>关掉自动更新、模型目录拉取、LSP 下载：板子通常离线，这些请求只会白等</td>
              </tr>
            </tbody>
          </table>
          </div>
          <p>
            安装包优先从 dfss 分发（<code>/tools/cv84x6_llm_server/agents/</code>），官方源只作备用，
            所以<b>不能访问外网的设备也能装</b>。每个包带固定 sha256，校验通过才解包，校验失败直接报错。
            dfss 调用的是 <code>python -m dfss</code>；装在别的解释器里时用
            <code>CV84X6_DFSS_PYTHON</code> 指定。
          </p>
          <p>
            <b>内存只有三件事要知道</b>：一，agent 卡片上的「预估内存」是这个 agent 自己要花的量；
            二，启动前服务把实时读取的 <code>MemAvailable</code>（「总览」页的「可用」）和该 agent
            的预估下限比一次，低于下限就直接拒绝启动并说明还差多少；三，实际用量看「总览」页的
            「系统内存」，agent 跑起来后卡片上还有实时 RSS。
          </p>
          <p>
            实测预估（10.42.0.242，2026-10-27）：PicoClaw 空闲约 55 MB、对话后约 60 MB；
            opencode 空闲约 220 MB、用过工具后约 390 MB；OpenClaw 空闲约 1.4 GB、对话后约 1.9 GB。
            数字随版本更新，以卡片为准。
          </p>
          <p>
            三个 agent 的模型配置都按同一套合同生成：<code>model</code> 是本服务的模型 id、
            <code>api_base</code> 指向 <code>127.0.0.1:8000/v1</code>、
            <code>context_window</code> 取模型真实值（32768 或 131072，不写 128000）、
            <code>max_tokens</code> 为 <code>min(16384, 上下文/2)</code>。
            切换默认模型后会自动重写配置并重启对应的 agent。
          </p>


          <h2 id="records">推理记录</h2>
          <p>
            每次<b>真正发起的推理</b>都会落一条记录：请求内容、实际生效的采样参数、完整输出、
            token 与耗时、结束原因（正常 / 出错 / 客户端断开）。用途是事后解释「这条回答为什么不对」，
            而不是统计用量——用量仍在「总览」页。
          </p>
          <ul>
            <li>
              <b>什么时候不记录</b>：请求校验失败、鉴权失败、模型不存在或未加载等 4xx/409 不记录，
              因为没有任何东西跑到 NPU 上。
            </li>
            <li>
              <b>来源</b>：<code>source</code> 是请求的路径。控制台测试走 <code>/api/chat*</code> 与
              <code>/api/test/*</code>（操作者记为 admin），API 调用是 <code>/v1/…</code>，两者一眼可分。
              辅助模型每个请求一条记录（不是每条文本一条）；音频和图片本身从不落盘，只记文件名、大小与尺寸。
            </li>
            <li>
              <b>路径</b>：「推理记录」页左侧列表按时间倒序列出，点「详情」看完整输入与输出；
              可以导出 NDJSON（每行一条完整记录）留档。
            </li>
            <li>
              <b>原始输出与展示输出</b>：<code>output_text</code> 是模型实际生成的文本，命中
              <code>stop</code> 时与客户端看到的回复一致（不含 stop 本身）；<code>response_content</code>
              是客户端拿到的 <code>content</code>，thinking 模式下两者不同属于正常。
            </li>
            <li>
              <b>不存凭证、不存图片</b>：API key 只记 id 与备注名，不存明文、哈希或会话 cookie；
              图片只记数量与宽高，不存 base64 或原图。
            </li>
            <li>
              <b>开关与保留</b>：「设置 → 推理记录」可关闭（默认开启），并设置保留条数与保留天数
              （默认 1000 条 / 30 天，两条规则同时生效，取更严的）；「推理记录」页提供「全部清空」。
            </li>
            <li>
              <b>隐私</b>：记录里是客户真实对话明文，保存在数据目录，仅管理员可查；导出文件同样敏感。
              记录库损坏或写不进去时推理照常返回，页面会显示具体错误，不会静默丢记录。
            </li>
          </ul>

          <h2 id="limits">故障与限制</h2>
          <p className="lead">
            下面这些和「OpenAI 兼容」给人的直觉不同，按直觉写代码会踩坑。
          </p>
          <ul>
            <li>
              <b>采样参数不生效</b>。bmodel 的 <code>lm_head</code> 内置 argmax，只输出一个 token id，
              图里没有可采样的概率分布。因此 <code>temperature</code> / <code>top_p</code> /
              <code>top_k</code> 都<b>不起作用</b>，同一输入永远得到同一输出。请求里带这些字段不报错，只是被忽略。
            </li>
            <li>
              <b>并发是会话级，不是批推理</b>。计算图没有 batch 维，做不到把多个请求合成一个 batch。
              并发带来的是「大家同时出字」，<b>不是总吞吐翻倍</b>：3 路并发合计约 18 token/s。
              每模型并发路数可在「设置」页调整，硬上限 3；多出的请求排队（默认最多 16 个），
              队列满返回 <b>429</b>（带 <code>Retry-After</code>）。
            </li>
            <li>
              <b>每个请求按「prompt + max_tokens」预留 KV</b>（每 token 20 KB）。加起来放不下时，
              后到的请求在队列里等前面的结束，不报错。128k 版上两个 17.7k token 的请求可以同时跑，
              第三、四个排队。
            </li>
            <li>
              <b>长 prompt 首字慢</b>。冷启动 prefill：2k token 约 10 秒、8k 约 45 秒、16k 约 100 秒、
              30k 约 4.5 分钟、62k 约 13 分钟、127k 约 46 分钟。重复出现的前缀交给缓存，这是长文档场景能用的关键。
            </li>
            <li>
              <b>速度</b>。35B-A3B 32k 上，短上下文 decode 约 24–30 token/s，130k 处约 14 token/s。
              页面上显示的是实测值，不是估算值。
            </li>
            <li>
              <b>预填充精度</b>。CV84X6 上多 token 预填充图里的路由专家（MoE）有数值误差：第 0 层与参考实现的
              余弦相似度只有 0.75，解码图是 0.9999，厂商官方 bmodel 一样。长 prompt 误差会累积，
              个别情况下改变回答。对策：2048 token 以上的 prompt，最后 64 个 token 改走解码图精确计算；
              更短的 prompt 最后 16 个 token 精确计算。否则长度刚过 64 整数倍的短问题偶尔会只写思考、不给答案
              （实测 40 条中 5 条，加精确尾部后修复）。可在「设置」页「prompt 精确尾部」调整，每 token 约 40 ms，0 = 关闭。
              证据与复现见仓库 <code>tools/precision/README.md</code>；根治需要厂商修算子。
            </li>
            <li>
              <b>NPU 故障</b>。TPU 卡死（驱动等待 120 秒超时）后，该模型的后续请求立即报错
              「NPU fault … reboot the board」，不会再挂住；<b>只能重启设备恢复</b>。
              驱动层面的间歇超时曾在一张合成 PNG 的多会话测试中触发过一次，之后同类用例反复跑都正常，
              根因未定位 —— 不宣称已永久消除。<b>不要在推理进程运行中强杀它</b>（<code>pkill</code> /
              <code>kill -9</code> 会卡死 TPU），停服务用 SIGTERM 并等它自己退出。
            </li>
            <li>
              <b>错误码</b>：参数不合法（空消息、<code>max_tokens</code> &lt; 1、不支持的内容类型、坏图片）
              返回 400；prompt 超过上下文返回 400；请求体超过 48 MB 返回 413；队列满返回 429；
              模型未加载返回 409。
            </li>
            <li><b>没有 <code>/v1/embeddings</code></b>。本项目只做生成，没有向量化模型。</li>
          </ul>

          <h2 id="takeover">重启后接管已有进程</h2>
          <p>
            <b>正常停止或重启</b>（<code>systemctl stop/restart</code>、安装新版本）时，服务会先逐个
            <b>优雅卸载模型</b>（会话 → 缓存 → 引擎，不强杀正在推理的进程）并停止 agent，然后退出；
            再次启动后模型需要重新加载，设为自启的 agent 会自动启动。
          </p>
          <p>
            <b>服务进程异常退出</b>（崩溃、被强杀）时，模型 worker 和 agent 都是独立 session 的子进程，
            <b>不会随之退出</b>（systemd 只杀主进程，<code>KillMode=process</code>）。systemd 重新拉起服务后，
            服务会先认领这些还活着的进程，不重新加载模型，也不重复启动 agent：
          </p>
          <ul>
            <li>
              <b>只认领能证明是自己启动的</b>：worker 要求命令行确实是
              <code>-m app.engine.worker</code>、<code>--model-id</code> 与
              <code>--model-path</code> 都指向本服务的数据目录、工作目录在安装树内、可执行文件是
              Python；agent 要求可执行文件与它自己的启动命令同一文件、工作目录在它自己的目录内、
              端口与配置一致，并且<b>健康检查通过</b>（agent 还要带鉴权）。只证明"进程像"不够，
              还要证明"还能服务"。
            </li>
            <li>
              <b>认领后照常可卸载/停止</b>，不会重复启动。模型卡片显示「已接管」，agent 卡片显示
              「已接管」。
            </li>
            <li>
              <b>认不出或握手不通过就不动它，也不重复启动</b>：模型卡片显示「进程冲突」并给出原因
              与 pid，点「加载」会被拒绝（409），点「卸载」才对那个 pid 发 SIGTERM（不强杀 ——
              它可能在映射权重，强杀会卡死 NPU）；agent 显示「残留进程 pid N」，点「启动」会被
              拒绝并提示先点「停止」。
            </li>
            <li>
              <b>有两个服务实例用同一个数据目录时不会接管</b>：进程有活着的归属者，两个管理端
              驱动同一个进程会互相卸掉对方在用的模型，所以只报冲突。
            </li>
            <li>
              <b>不恢复"正在加载"/"正在安装"</b>：这些操作状态是进程内的，重启后就是空闲。
              接管回答的是"哪些进程还活着、归谁、能不能用"，不是"上次做到哪一步"。
            </li>
          </ul>

          <h2 id="ops">运维</h2>
          <h3>安装、升级与卸载（v0.6.9 起用 .deb）</h3>
          <pre className="code">{`# 安装（离线，包内自带 Web 依赖与引擎库）
sudo apt install ./cv84x6-llm-server_0.6.9_arm64.deb

# 升级：装新包即可，配置、模型、密钥全部保留
sudo apt install ./cv84x6-llm-server_0.6.10_arm64.deb

# 卸载：只删程序，保留配置与数据
sudo apt remove cv84x6-llm-server
# 连配置一起删；数据目录仍保留，并打印删除命令
sudo apt purge cv84x6-llm-server`}</pre>
          <ul>
            <li>
              <b>升级时服务会被正常停止再启动</b>：先 <code>systemctl stop</code>（只发 SIGTERM，
              最多等 60 秒，<b>不强杀</b> NPU worker），装完文件后重新 enable/start。
              上一版遗留、本版不再提供的程序文件会被清掉，但 <code>etc/</code> 和数据目录不在清理范围内。
            </li>
            <li>
              <b>从 tar.gz 装的机器可以直接换成 deb</b>：装的是同一套目录，
              <code>etc/server.env</code>（端口、数据目录、解释器）与数据目录原样保留。
              tar.gz 流程（<code>scripts/install.sh</code> / <code>uninstall.sh</code>）仍可用，但不再是主入口。
            </li>
            <li>
              <b>purge 默认不删数据</b>：<code>models/</code> 里是几十 GB 的模型，
              <code>state/</code> 里是 API key 与管理密码，<code>agents/</code> 里是装好的 agent。
              purge 会打印 <code>rm -rf</code> 命令，要不要删由你决定。
            </li>
            <li>
              <b>依赖</b>：<code>python3.10</code>、<code>systemd</code>、<code>curl</code>、<code>rsync</code>、
              <code>libjpeg-turbo8</code>、<code>zlib1g</code> 都是板子上已有的系统包，安装过程不联网。
              <code>libsophon</code> 是厂商运行时、不在 apt 源里，缺了会明确提示。
            </li>
          </ul>
          <div className="table-wrap">
          <table>
            <thead><tr><th>位置</th><th>内容</th><th>升级时</th></tr></thead>
            <tbody>
              <tr>
                <td className="mono">/opt/sophgo/cv84x6_llm_server/</td>
                <td>只有程序：<code>app/ lib/ vendor/ web/ tools/ model-config/ scripts/ VERSION</code></td>
                <td>整体替换</td>
              </tr>
              <tr>
                <td className="mono">…/etc/server.env</td>
                <td>端口、数据目录、解释器（数据目录的唯一来源）</td>
                <td>保留</td>
              </tr>
              <tr>
                <td className="mono">/data/cv84x6_llm_server/</td>
                <td><code>models/</code>、<code>state/</code>（密钥、用量、日志）、<code>agents/</code>、<code>downloads/</code></td>
                <td>不动</td>
              </tr>
            </tbody>
          </table>
          </div>
          <ul>
            <li>
              <b>服务与日志</b>：systemd 托管，<code>systemctl status cv84x6-llm</code>、
              <code>journalctl -u cv84x6-llm -f</code>。每个模型的 worker 日志在
              <code>state/logs/worker-&lt;模型名&gt;.log</code>，也可以在「模型」页点「查看日志」。
            </li>
            <li>
              <b>换盘 / 改数据目录</b>：在「设置 → 数据目录」填新路径点「迁移」。服务会卸载模型、
              逐文件复制、比对文件数与字节数、改写 <code>server.env</code>、切换到新路径、删除旧目录；
              任一步失败就清掉新目录并保持原样。数据目录靠标记文件 <code>.cv84x6-data</code> 识别，
              只认带标记的目录。
            </li>
            <li>
              <b>状态文件</b>：<code>state/state.json</code>，保存密钥哈希、设置与累计用量，原子写入，
              掉电不会写坏。
            </li>
            <li>
              <b>推理记录</b>：<code>state/inference_records.sqlite3</code>，客户对话明文，随数据目录
              一起迁移；在「推理记录」页查看、导出或清空。
            </li>
            <li><b>改管理密码</b>：在「API Key」页底部。</li>
            <li><b>资源不够</b>：先卸载一个模型再加载新的；「总览」页能看到设备内存（NPU + VPP）与系统内存占用。</li>
          </ul>
        </div>

        <nav className="toc" aria-label="目录" data-testid="docs-toc">
          <details ref={toc}>
            <summary className="toc-title">本页目录</summary>
            <div className="toc-list">
              {SECTIONS.map((s) => (
                <a
                  key={s.id} href={`#${s.id}`}
                  className={active === s.id ? 'active' : ''}
                  data-testid={`toc-${s.id}`}
                  onClick={(e) => { e.preventDefault(); jump(s.id) }}
                >
                  {s.title}
                </a>
              ))}
            </div>
          </details>
        </nav>
      </div>
    </div>
  )
}
