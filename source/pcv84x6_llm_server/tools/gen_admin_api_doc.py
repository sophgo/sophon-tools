#!/usr/bin/env python3
"""Generate ``docs/admin-api.md`` from the live OpenAPI document (MYS-2676).

    python3 tools/gen_admin_api_doc.py            # rewrite docs/admin-api.md
    python3 tools/gen_admin_api_doc.py --check    # exit 1 if it is out of date

The document is generated, not written: it is the same ``/api/openapi.json`` the
Swagger page renders, so a route that gains a field or changes its error codes
cannot leave the markdown behind. ``tests/test_admin_api_docs.py`` runs
``--check``, which is what makes "the docs are in sync" an enforced fact rather
than a habit.

What the generator adds over the raw schema, and why it is not in the schema:

* the **hand-written** chapters -- authentication, the error-code table, the
  paging and timestamp conventions, the ``/v1`` decision. Those are prose about
  *this* service that no OpenAPI document can carry, and they are the part a
  reader needs first. They live in this file as constants so the generated
  document has one source and one owner.
* a copy-pasteable ``curl`` example per operation. OpenAPI has no place for one;
  a reader of the offline document is on a board with no Swagger "Try it out"
  (the page is generated with it off, and the board may have no network anyway).
* the per-code meanings gathered in one table instead of repeated under
  sixty routes.

Deterministic output: no timestamps, no version-dependent ordering. The only
volatile figure is the service version, which comes from ``app/__init__.py`` and
is the same value ``tests/test_packaging.py`` guards.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

OUT = BASE / "docs" / "admin-api.md"

#: The service's own version, read from the one place it lives.
from app import __version__  # noqa: E402

# ---------------------------------------------------------------------------
# hand-written chapters
# ---------------------------------------------------------------------------
HEADER = """\
# 管理 API 文档

本文件由 `tools/gen_admin_api_doc.py` 从服务的 OpenAPI 文档生成（当前服务版本
`{version}`），**不要手改**：改接口后重新生成，`tests/test_admin_api_docs.py` 会检查
两者是否一致。手写的几节（本节的约定、错误码、分页与时间格式、`/v1` 的文档）写在生成
脚本里，其余全部来自 `app/api/*.py` 的注解与 `app/api/admin_schemas.py` 的模型。

交互式文档（离线可用，不依赖任何 CDN）：服务启动后打开 `/api/docs`（Swagger）或
`/api/redoc`（ReDoc）。两者都需要管理员会话 cookie 或 admin key。

## 认证

两套凭据，按调用方选一种：

| 调用方 | 凭据 | 说明 |
|---|---|---|
| 脚本 / CI | `Authorization: Bearer <admin key>` | 推荐。key 的 `scope` 必须是 `admin`。 |
| 控制台（浏览器） | 会话 cookie `cv84x6_admin` | `POST /api/login` 换取，12 小时有效。 |

```bash
# 1. 用控制台会话签发一把 admin key（只需一次）
curl -s -c jar -X POST http://<板子>:8000/api/login \\
     -H 'Content-Type: application/json' -d '{{"password":"admin"}}' >/dev/null
curl -s -b jar -X POST http://<板子>:8000/api/keys \\
     -H 'Content-Type: application/json' \\
     -d '{{"name":"ci","scope":"admin"}}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["key"])'

# 2. 之后所有管理调用都用它
export CV84X6_KEY=sk-...
curl -s -H "Authorization: Bearer $CV84X6_KEY" http://<板子>:8000/api/models
```

规则：

- key 的权限范围（`scope`）分两种：`inference`（默认，只能调 `/v1`）和 `admin`
  （还能调 `/api/*`）。**用 `inference` key 调 `/api/*` 返回 403，`code` 是
  `forbidden_scope`** —— 这是为了给 agent 发推理 key 时不会顺带交出管理权。
- 本功能之前创建的 key 没有 `scope` 字段，读取时一律按 `inference` 处理（不需要迁移）。
- 用 Bearer 认证的请求**不需要 CSRF 防护**：浏览器不会自动带上它，没有可伪造的东西。
- 用 cookie 认证的写请求（`POST`/`PUT`/`PATCH`/`DELETE`）会校验 `Origin`：缺失放行，
  存在则必须是本机回环、`CV84X6_MCP_ORIGINS` 里声明的地址，或与本次请求的 `Host`
  完全一致，否则 403（防止别的页面用操作者的浏览器改这台板子）。
- 审计记录里的操作者显示 key 的**名字**（`actor_type: api_key`，`actor_name: <名字>`）。

## 错误格式

所有 `/api/*` 的错误都是同一个形状：

```json
{{"detail": "模型 qwen3-4b 正在加载中，请等待加载完成后再请求", "code": "model_busy"}}
```

- `detail`：中文说明，控制台直接显示。**保持原有约定不变**（老的控制台读的就是它）。
- `code`：稳定的英文错误码。脚本应据此分支，而不是解析 `detail` 的文字。
- `422` 校验错误也转成这个格式，`detail` 里的字段名和原因用中文，`code` 是
  `validation_error`。
- `/v1/*` 不受影响：那里仍是 OpenAI 的错误体，已有 SDK 依赖它。

{error_table}

## 分页与时间格式

- **分页**：列表类接口用 `limit` + `offset`，响应用
  `{{"items": [...], "total": N, "limit": N, "offset": N}}`（推理记录、审计）；日志用
  **字节游标**：响应给 `cursor`，取更旧的一页时原样传回；`has_more` 说明还有没有。
- **时间**：响应里的时间统一是 **epoch 秒（浮点）**；同时给 `*_iso` 字段的地方是
  本地时区带偏移的 ISO8601（给人和 Excel 用）。请求里的 `since` / `until`
  （只有日志与审计接口有）接受三种写法：epoch 秒、ISO8601、相对时间（`-30m`、`-2h`、`-7d`）。
- **大小**：一律字节数，字段名以 `_bytes` 结尾。
- **布尔**：真布尔，不用 0/1。

## /v1 的文档

`/v1/*` 的 OpenAPI **单独提供**，在 `/v1/openapi.json`，不在本文件里。理由：

1. **凭据不同。** `/api` 用 admin key 或会话 cookie，`/v1` 用 inference key。混在一份
   文档里，Swagger 的「Authorize」只能表达一个凭据，另一种总要靠文字补充说明。
2. **错误体不同。** `/v1` 是 OpenAI 的错误封装，`/api` 是 `{{detail, code}}`。同一份文档
   里每个接口都要写「本接口的错误体是另一种」，读者反而更容易记错。
3. **读者不同。** 读 `/api` 的是要写运维脚本的人，读 `/v1` 的是要接 OpenAI SDK 的人；
   后者的第一手材料是 OpenAI 的规范，本服务的 `/v1` 只是它的一个实现。
4. **暴露面不同。** `/v1` 的 key 会发给板子上的 agent，而枚举整个管理面不该是这些 key
   的能力；分成两份文档后，`/v1/openapi.json` 也能要求管理凭据才能读。

两份文档由同一个 app 生成、只做路径过滤，所以 schema 定义不会互相漂移。

## 约定

- 所有路径都以服务根为基准（默认 `http://<板子>:8000`）。
- 模型 id 就是 `models/` 下的目录名；路径参数里的 id 不做转义假设，含特殊字符的目录名
  请用 URL 编码。
- 本服务不改版本号本文件就更新；接口字段只增不改——新增字段是兼容的，控制台已读的字段
  不会被改名（`docs/console-design.md` 的契约）。
"""


def error_table() -> str:
    """The codes, grouped by HTTP status, as one markdown table."""
    from app.core.errors import ERROR_CODES

    lines = ["## 错误码", "",
             "`code` 是稳定的：这里的取值不会改名，新增会追加在表尾。", "",
             "| `code` | HTTP | 含义 |", "|---|---|---|"]
    for row in sorted(ERROR_CODES, key=lambda r: (r.status, r.code)):
        lines.append(f"| `{row.code}` | {row.status} | {row.description} |")
    lines.append("")
    lines.append("状态码与 `code` 的对应关系不是一一的：`409` 覆盖了「状态不对」的一整类"
                 "拒绝，具体是哪一种由 `code` 说明——这正是一个脚本需要区分的"
                 "（等一会儿重试 / 先卸载 / 改设置 / 人工确认）。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# helpers over the OpenAPI document
# ---------------------------------------------------------------------------
#: Header rows the curl examples set. The document is generated offline, so the
#: example can only show the credential's shape.
AUTH_HEADER = '-H "Authorization: Bearer $CV84X6_KEY"'


def _schema_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _resolve(spec: dict, schema: dict | None, depth: int = 0) -> dict:
    """Inline a ``$ref`` one level (the tables below only need one or two)."""
    if not isinstance(schema, dict) or depth > 3:
        return schema or {}
    ref = schema.get("$ref")
    if ref:
        name = _schema_name(ref)
        target = spec.get("components", {}).get("schemas", {}).get(name, {})
        return _resolve(spec, target, depth + 1)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema and schema[key]:
            # A union of one object and nulls is how pydantic renders `X | None`.
            for option in schema[key]:
                if option.get("type") != "null":
                    return _resolve(spec, option, depth + 1)
    return schema


def _type_label(spec: dict, schema: dict) -> str:
    schema = _resolve(spec, schema)
    if "$ref" in (schema or {}):  # pragma: no cover - _resolve inlines already
        return _schema_name(schema["$ref"])
    kind = schema.get("type")
    if kind == "array":
        return f"{_type_label(spec, schema.get('items') or {})}[]"
    if kind == "object" or "properties" in schema:
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"map[string, {_type_label(spec, extra)}]"
        return "object"
    if isinstance(kind, list):
        kind = " | ".join(k for k in kind if k != "null")
    if schema.get("enum"):
        return " \\| ".join(f"`{v}`" for v in schema["enum"])
    return {"integer": "int", "number": "float", "boolean": "bool",
            "string": "string", "null": "null"}.get(kind or "", kind or "any")


def _field_rows(spec: dict, schema: dict) -> list[str]:
    """Markdown table rows for one object's properties."""
    schema = _resolve(spec, schema)
    props = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    rows = []
    for name, prop in props.items():
        description = (prop.get("description") or "").replace("\n", " ").strip()
        flag = "必填" if name in required else "可选"
        rows.append(f"| `{name}` | {_type_label(spec, prop)} | {flag} | {description} |")
    return rows


def _walk_schema(spec: dict, name: str, seen: set[str]) -> list[str]:
    """A section per named component schema, children indented by nesting."""
    if name in seen:
        return []
    seen.add(name)
    schema = spec.get("components", {}).get("schemas", {}).get(name)
    if not schema:
        return []
    out = [f"#### `{name}`", ""]
    description = (schema.get("description") or "").strip()
    if description:
        out += [description, ""]
    rows = _field_rows(spec, schema)
    if rows:
        out += ["| 字段 | 类型 | | 说明 |", "|---|---|---|---|", *rows, ""]
    else:
        out += ["（无字段）", ""]
    # Nested models get their own subsection, so a reader can follow the tree
    # without a schema viewer.
    for prop in (schema.get("properties") or {}).values():
        ref = prop.get("$ref")
        if ref:
            out += _walk_schema(spec, _schema_name(ref), seen)
    return out


def _request_example(spec: dict, operation: dict) -> str | None:
    """A JSON body example from the request schema, if the route takes one."""
    body = (operation.get("requestBody") or {}).get("content", {}).get(
        "application/json")
    if not body:
        return None
    schema = _resolve(spec, body.get("schema") or {})
    example = body.get("example") or schema.get("example")
    if example is not None:
        return json.dumps(example, ensure_ascii=False, indent=2)
    props = schema.get("properties") or {}
    if not props:
        return None
    sample: dict = {}
    for name, prop in props.items():
        if "example" in prop:
            sample[name] = prop["example"]
        elif prop.get("examples"):
            sample[name] = prop["examples"][0]
    return json.dumps(sample, ensure_ascii=False, indent=2) if sample else None


def _curl(spec: dict, method: str, path: str, operation: dict) -> str:
    """A runnable-looking ``curl`` line for one operation.

    ``/api/login`` is the one route that takes no credential -- it *produces* the
    cookie -- so its example shows the login itself rather than a bearer header it
    cannot use.
    """
    if path == "/api/login":
        return ("curl -s -c jar -X POST http://<板子>:8000/api/login \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -d '{\"password\":\"<管理员口令>\"}'")
    example = _request_example(spec, operation)
    parts = [f"curl -s -X {method.upper()} http://<板子>:8000{path}",
             f"  {AUTH_HEADER}"]
    if example:
        one_line = json.dumps(json.loads(example), ensure_ascii=False)
        parts.append(f"  -H 'Content-Type: application/json' \\\n  -d '{one_line}'")
    if method.upper() == "GET" and operation.get("parameters"):
        names = [p["name"] for p in operation["parameters"] if p.get("in") == "query"]
        if names:
            parts.append(f"  # 可选查询参数: {', '.join(names)}")
    return " \\\n".join(parts)


def _path_summary(path: str) -> str:
    params = []
    rest = path
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            if not name.endswith(":path") and "." not in name:
                params.append(name)
    return ", ".join(params)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def render(spec: dict) -> str:
    from app.api.api_docs import TAGS

    out: list[str] = [HEADER.format(version=__version__, error_table=error_table())]
    tag_titles = {entry["name"]: entry["description"] for entry in TAGS}

    out += ["## 接口一览", "",
            "按模块分组；每条给出方法、路径和一句话说明。详细字段见后面的章节。", ""]
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, operations in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, operation in operations.items():
            tags = operation.get("tags") or ["misc"]
            by_tag.setdefault(tags[0], []).append((method, path, operation))
    for tag in [t["name"] for t in TAGS]:
        rows = sorted(by_tag.get(tag, []), key=lambda r: (r[1], r[0]))
        if not rows:
            continue
        out += [f"### {tag}", "", tag_titles.get(tag, ""), "",
                "| 方法 | 路径 | 说明 |", "|---|---|---|"]
        for method, path, operation in rows:
            out.append(f"| {method.upper()} | `{path}` | {operation.get('summary','')} |")
        out.append("")

    out += ["## 接口详情", ""]
    for tag in [t["name"] for t in TAGS]:
        rows = sorted(by_tag.get(tag, []), key=lambda r: (r[1], r[0]))
        if not rows:
            continue
        out += [f"### {tag}", ""]
        for method, path, operation in rows:
            out += [f"#### `{method.upper()} {path}`", "",
                    f"**{operation.get('summary','')}**", ""]
            description = (operation.get("description") or "").strip()
            if description:
                out += [description, ""]
            params = _path_summary(path)
            if params:
                out += [f"路径参数：`{params}`", ""]
            query = [p for p in operation.get("parameters") or ()
                     if p.get("in") == "query"]
            if query:
                out += ["| 查询参数 | 类型 | 默认 | 说明 |", "|---|---|---|---|"]
                for p in query:
                    schema = _resolve(spec, p.get("schema") or {})
                    default = schema.get("default")
                    out.append(f"| `{p['name']}` | {_type_label(spec, schema)} | "
                               f"{'' if default is None else f'`{default}`'} | "
                               f"{(p.get('description') or '').strip()} |")
                out.append("")
            body = (operation.get("requestBody") or {}).get("content", {}).get(
                "application/json")
            if body:
                schema = _resolve(spec, body.get("schema") or {})
                rows = _field_rows(spec, schema)
                out += ["请求体 `application/json`：", ""]
                if rows:
                    out += ["| 字段 | 类型 | | 说明 |", "|---|---|---|---|", *rows, ""]
                example = _request_example(spec, operation)
                if example:
                    out += ["```json", example, "```", ""]
            success = operation.get("responses", {}).get(
                str(operation.get("x-status", 200)))
            if success is None:
                codes = [c for c in operation.get("responses", {}) if c.startswith("2")]
                success = operation["responses"][codes[0]] if codes else {}
            content = success.get("content") or {}
            if "application/json" in content:
                schema = content["application/json"].get("schema") or {}
                rows = _field_rows(spec, schema)
                for key in ("allOf", "oneOf", "anyOf"):
                    if key in schema and schema[key]:
                        rows = _field_rows(spec, schema[key][0])
                        break
                out += ["响应 `200 application/json`：", ""]
                if rows:
                    out += ["| 字段 | 类型 | | 说明 |", "|---|---|---|---|", *rows, ""]
                else:
                    name = schema.get("$ref")
                    out += [f"`{_schema_name(name)}`（见下方模型定义）" if name
                            else "（无字段）", ""]
            elif content:
                media = next(iter(content))
                out += [f"响应内容类型 `{media}`，流式输出。", ""]
            errors = sorted(c for c in operation.get("responses", {})
                            if c[0] in "45")
            if errors:
                out += [f"可能的状态码：{', '.join(f'`{c}`' for c in errors)}"
                        "（错误体见「错误格式」）", ""]
            out += ["```bash", _curl(spec, method, path, operation), "```", ""]

    seen: set[str] = set()
    model_sections: list[str] = []
    for name in sorted(spec.get("components", {}).get("schemas", {})):
        model_sections += _walk_schema(spec, name, seen)
    if model_sections:
        out += ["## 数据模型", "",
                "各接口的响应模型。字段说明与接口里的表格相同，这里按类型集中列一次，"
                "便于写客户端时照着建结构体。", "", *model_sections]
    return "\n".join(out).rstrip() + "\n"


def build_spec() -> dict:
    """The live OpenAPI document, filtered the way ``/api/openapi.json`` serves it.

    The same filter is applied here rather than duplicated: the generated markdown
    must describe exactly what the interactive page shows, and a route that is in
    one but not the other is a documentation bug this file would otherwise hide.
    """
    from app.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app = create_app(data_dir=root / "data", models_dir=root / "models",
                         backend_kind="mock", web_dir=root / "web")
        spec = app.openapi()
    return {**spec,
            "paths": {p: item for p, item in spec["paths"].items()
                      if p.startswith("/api/")}}


def generate() -> str:
    return render(build_spec())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if docs/admin-api.md is out of date")
    args = parser.parse_args(argv)
    text = generate()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is out of date: run python3 tools/gen_admin_api_doc.py",
                  file=sys.stderr)
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
