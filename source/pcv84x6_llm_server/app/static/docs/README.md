# 离线交互文档的静态资源

`app/main.py` 的 `/api/docs`（Swagger UI）和 `/api/redoc`（ReDoc）用的就是这里的文件。
板上没有外网，而 Swagger UI 的默认页面会从 CDN 拉 `swagger-ui-bundle.js`、`swagger-ui.css`
和 ReDoc 的 `redoc.standalone.js`——离线打不开，所以才把资源提交进仓库。

| 文件 | 来源 | 版本 | 许可 |
|---|---|---|---|
| `swagger-ui-bundle.js` | `swagger-ui-dist` npm 包 | 5.17.14 | Apache-2.0（见 `LICENSE-swagger-ui.txt`） |
| `swagger-ui-standalone-preset.js` | 同上 | 5.17.14 | Apache-2.0 |
| `swagger-ui.css` | 同上 | 5.17.14 | Apache-2.0 |
| `redoc.standalone.js` | `redoc` npm 包 | 2.1.5 | MIT（见 `LICENSE-redoc.txt`） |

## 更新步骤

只在上游确实需要升级时做，并且要重新跑一次离线验收（`tests/test_admin_docs.py` 与
`tools/check_admin_docs_offline.py`）。

```bash
V_SWAGGER=5.17.14
V_REDOC=2.1.5
for f in swagger-ui-bundle.js swagger-ui-standalone-preset.js swagger-ui.css; do
  curl -sSfL -o "app/static/docs/$f" "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V_SWAGGER/$f"
done
curl -sSfL -o app/static/docs/redoc.standalone.js \
  "https://cdn.jsdelivr.net/npm/redoc@$V_REDOC/bundles/redoc.standalone.js"
```

版本号同时写进 `app/core/admin_docs.py` 的 `VENDORED_ASSETS`（测试会比对文件大小与 sha256，
上游换了内容却忘了改常量就会失败）。

## 为什么提交而不是打包时下载

`scripts/package.sh` 在 CI 机器上跑，那台机器有网；但发布包必须**离线可用**，而板上没有
`npm`/`pip` 的网。把三个文件（约 2.7 MB）放进源码树是唯一能保证「包里的文档一定能打开」
的做法，代价是仓库大了一点。Android/iOS 客户端和 `web/` 都不需要它们。
