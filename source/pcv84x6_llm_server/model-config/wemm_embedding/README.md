# WeMM-Embedding-2B 配套配置

对应 `tencent/WeMM-Embedding-2B` revision
`bbd6cd4bf52cfc6716f752a2df80b2706720bd95`，Apache-2.0。
保留该 revision 的完整 `LICENSE`，包括第三方组件说明。

`distribution.json` 固定已验证的 W8BF16 bmodel 摘要、dfss 地址和本目录原始配置摘要。
`embedding_config.json` 是编译器输出的运行契约；tokenizer 保留 checkpoint 的
`<embedding>` 后处理，禁止换成 Qwen3-VL 或 Qwen3 文本 embedding 的配置。

服务在下载目录没有 `config/` 时使用此配置。用户自行编译模型时，应随 bmodel
携带同次输出的完整 `config/`；该目录优先于内置配置。
