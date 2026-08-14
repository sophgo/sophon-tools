# Reasonix 补丁管理目录

本目录统一管理对 **Reasonix (esengine/DeepSeek-Reasonix)** 的修复，作为 bmssm 的
一部分随版发布。设备上的 reasonix 二进制采用本目录 `bin/` 下的补丁版本。

## 版本基线

- **上游仓库**：`https://github.com/esengine/DeepSeek-Reasonix`
- **release 基线**：`v1.25.0` = commit `fa64f632d67c01737d859d5766f1b508d544aa55`
- **本地修复分支**：`fix/keep-tool-group-budget`
- 设备二进制（当前）由此基线 + 两个补丁编译：`bin/reasonix-arm64-v1.25.0-f32534ad`

## 补丁清单（按应用顺序叠加在 v1.25.0 基线上）

1. `patches/reasonix-blocked-deadlock-fix.patch`（commit `07444db4`）
   会话上下文死锁修复：blocked 且 overflow（est>=hard）时真正走 force 折叠自愈，
   防止长期工具密集会话永久死锁。详见此前 README 记录（死锁会话 4358995a 恢复验证）。

2. `patches/reasonix-remove-ask-tool.patch`（commit `f32534ad`）
   **移除模型侧 `ask` 工具（MYS-212）**：模型不再通过 `permission.request + 真实候选
   options` 弹选择题卡片，需要用户决策时改在**回答正文里直接提问并等待**。
   系统提示词 `UserDecisionPolicy` 相应改为"有真正的用户决策时直接在正文提问"。
   目标：让 host（bmssm）收到的 `permission.request` 只含**命令审批**
   （Allow/allow_always/Reject），从而**自动审批可直接全部允许**，无需启发式区分
   ask vs 命令审批。
   - 仅移除 `reg.Add(agent.NewAskTool())` 注册与系统提示词；`AskTool` 类型保留编译
     （host 驱动的 uihub 表单 AskRequest 不受影响）。
   - 同步更新 `internal/boot/boot_test.go` 断言 与 `testdata/golden/*` 快照。

## 内嵌二进制

- `bin/reasonix-arm64-v1.25.0-f32534ad` → 部署路径 `/opt/sophon/reasonix/bin/reasonix`
- 编译（release + 去 debug/symbol）：基于 v1.25.0（`fa64f632`）+ 上述两个补丁，
  `git apply` 补丁后：
  ```bash
  GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o reasonix-arm64 ./cmd/reasonix
  ```
  `-ldflags "-s -w"` 去除符号与 DWARF debug 段，产物 38M（未 strip 版约 52M）。
- 部署后 `reasonix version` 显示 `git_commit: fa64f632`（v1.25.0 基线）。