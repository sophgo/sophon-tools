# sophon-tools 发版规范（Release 流程指南）

> 本文档定义 sophon-tools 的发版标准流程，后续每次发版按本文档执行。
> 当前依据 v26.08.29 实际发版流程整理（MYS-809）。

## 1. 版本命名

- **Release tag**：`vYY.MM.DD`（如 `v26.08.29`）；同一天多次发版用日期后缀表示（如 `v26.08.29.1` 作为补丁说明，tag 仍为首个日期）。
- **工具版本号**：各工具独立维护，语义化 `X.Y.Z`（重大.功能.修复）。发版时的实际构建版本 = tag 对应 commit 上各工具的版本定义值。
- **TAG 更新**：发版 tag 打在 main 最新 HEAD（发版前的最终 commit），不提前打 tag。

## 2. 工具版本管理（单一权威）

每个工具的版本号在**工具代码内唯一定义**，构建时从代码提取：

| 工具 | 版本权威定义位置 | 说明 |
| --- | --- | --- |
| bmssm | `source/pbmssm/build/version.sh` → `DEFAULT_VERSION` | 2.3.x |
| sophliteos | `source/psophliteos/build/version.sh` → `DEFAULT_VERSION` | 2.2.x |
| se-rag-core | `source/se-rag-core/release.sh` 默认 VERSION | 1.0.0 |
| dfss（pip） | `source/pdfss_cpp/git_version` | v1.10.x，同步 PyPI |
| bm_set_ip | `source/pbm_set_ip/bm_set_ip/.git_version` | 执行首行打印版本 |
| ota_update | `source/pota_update/ota.sh` 内 `version: vX.Y.Z` | |
| socbak | `source/psocbak/socbak/socbak.sh` 内 `VERSION: vX.Y.Z` | |
| 其余脚本工具 | 各 `release.sh` 从源码提取的默认版本 | |

**版本 bump**：发版前若工具代码有变更，需按变更影响 bump 版本号（bug 修复 `Z+1`、功能 `Y+1`、重大 `X+1`），随 PR 合入 main。

## 3. 发版前置检查（三查）

发版前必须完成：

1. **工具清单**：依据上次 Release ~ 当前 main 的 commit（`git log <last-tag>..HEAD`）列出每个工具的变更类型（新增/更新/未变）与版本对照，逐工具核对。
2. **PR / bug 复查**：
   - 仓库 open PR 逐一 review，可合入的合入 main，未合入的确认不阻塞发版；
   - open issue 逐一确认状态（阻塞在用户侧的需注明，不阻塞发版）。
3. **代码安全/质量审查**：对增量代码做漏洞与明显缺陷审查；发现项分 P0（必须修）/P1（建议修）/P2（记录），按产品决定修复范围，修复后回归测试。

## 4. 构建

统一构建入口（全量）：

```bash
bash release.sh          # 需要统一镜像 sophon-tools-build:<IMAGE_TAG>
```

- 镜像：`docker/versions.env` 的 `IMAGE_TAG`（当前 `unified-v1.1.0`）；镜像缺失用 `bash docker/build.sh` 构建。
- 范围：**15 个子项目**（统一构建清单），`docker/build-all.sh --list` 查看。以下项目**默认不发版、不在统一构建范围**：
  - `pmulti_video_qt`（产品决定不需要）
  - `psoph_phytool`、`pspacc_efuse_demo`（产品决定默认不发版，2026-08-30；如确需发布在源码目录手动 `bash release.sh`）
- 失败隔离：单项目失败不阻塞整体，构建结束看 `output/.build-status.txt` 与 `output/MANIFEST.txt`，失败项必须修复后单独重建。
- 产物：汇聚 `output/<工具>/`，生成 `MANIFEST.txt`（清单+md5）、`git_hash.txt`。
- **构建通过是发布前提**：任何 FAIL 项都要修复并重建到 PASS。

## 5. 发布（GitHub Release + PyPI）

### 5.1 打 tag 与创建 Release

```bash
git tag -a v<YY.MM.DD> -m "sophon-tools v<YY.MM.DD> release"   # 基于发版 commit
git push origin v<YY.MM.DD>
gh release create v<YY.MM.DD> -R sophgo/sophon-tools \
  --title "sophon-tools v<YY.MM.DD>" --notes-file <notes> -a <asset> ...
```

### 5.2 Release 内容（notes）

- 版本清单表：工具 / 变更类型 / 旧版本 / 新版本 / **一句话**改动内容（表格，改动人话精炼）。
- 补充章节：发版前 review 记录、修复补丁说明（如有）。
- 附构建记录 `output/MANIFEST.txt`。

### 5.3 发布形态（分工具）

| 工具 | 发布方式 |
| --- | --- |
| dfss | **仅发布 pip 包**（`dfss-<ver>-py2.py3-none-any.whl`）；不发布各平台二进制与 sdist。同时上传 PyPI（见 5.4），两处同步最新 |
| bmssm / sophliteos | arm64 deb（前者含 `_se7`/`_noskill` 双变体） |
| pqt_batch_deployment / pqt_memory_edit | linux AppImage + windows exe |
| pbmsec | deb（all 双架构） |
| 其余工具 | 各自 release.sh 产物（zip/deb/脚本） |
| phytool / spacc_efuse_demo / pmulti_video_qt | **默认不发版** |

### 5.4 PyPI 上传（dfss）

```bash
twine upload output/pdfss_cpp/dfss-<ver>-py2.py3-none-any.whl output/pdfss_cpp/dfss-<ver>.tar.gz
```

- 凭据存于本机 `~/.pypirc`（600），**严禁**提交仓库/上传 GitHub。
- 上传前核对 PyPI 现有版本：同一版本号不允许覆盖，若 PyPI 已有同号旧构建必须 bump 版本再传。
- sdist 一并上传（PyPI 惯例，源码安装兼容）。

### 5.5 资产更新

Release 资产需与最终构建一致：修复补丁后重建的工具产物要替换旧资产（`gh release delete-asset` + `gh release upload`），旧版本资产删除。

## 6. 发版后

- 在 Issue 汇报：Release 链接、工具清单、review 记录、验证结果、遗留项。
- 工具代码如有发版后修复，按 §5.5 更新资产并在 notes 中记录补丁（`v<date>.N` 小节）。

## 7. 审查与回归

- 代码改动走 PR 合入 main（squash，账号 zfsopv，禁止 fork/其他账号）。
- 合入前跑测试：Go 工程 `go test ./...`、shell 脚本 `bash -n`、Rust `cargo test`。
- 发版构建全部 PASS 后才能发布。