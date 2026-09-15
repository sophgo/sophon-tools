// 归档探测速度基准 (MYS-1062 二十轮, Linux 可跑)
//
// 现场反馈: "界面打开后分析镜像特别慢, 70MB 的包要 10 分钟"。
// 实测根因是**格式**: 顺序压缩流 (tar.xz / tar.zst) 没有索引, 要枚举条目必须把整条
// 流解一遍; 而 Go 的纯 xz 实现只有 ~5.7 MB/s —— 83MB 的 .txz 要 37.6 秒, 写卡与
// 写后校验各自还要再来一遍, 全流程 115 秒。zip 有中央目录, 探测**一个字节都不用解**。
//
// 这个测试把"探测耗时"钉成可复现的量化指标:
//
//	SE7_PROBE_FILES="a.zip b.txz" go test -run TestProbeSpeed -v
//
// 不设该环境变量时跳过 (普通 `go test ./...` 不受影响)。
package main

import (
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

// 探测耗时上限: 超过就说明包格式选错了 (顺序压缩流会远超这个数)
const probeBudget = 5 * time.Second

func TestProbeSpeed(t *testing.T) {
	files := strings.Fields(os.Getenv("SE7_PROBE_FILES"))
	if len(files) == 0 {
		t.Skip("未设置 SE7_PROBE_FILES (用法: SE7_PROBE_FILES=\"a.zip b.txz\" go test -run TestProbeSpeed -v)")
	}
	for _, f := range files {
		t0 := time.Now()
		a, err := ProbeArchive(f, nil, nil)
		d := time.Since(t0)
		if err != nil {
			t.Errorf("%s: %v", f, err)
			continue
		}
		sz := int64(0)
		for _, e := range a.Files {
			sz += e.Size
		}
		fmt.Printf("PROBE %-58s %8.2fs  模式=%v 文件=%d 目录=%d 内容=%s\n",
			shortName(f), d.Seconds(), a.Mode, len(a.Files), len(a.Dirs), HumanBytes(sz))
		if strings.HasSuffix(f, ".zip") && d > probeBudget {
			t.Errorf("%s 探测耗时 %v 超过 %v —— zip 有中央目录, 不该这么慢", f, d, probeBudget)
		}
	}
}

func shortName(p string) string {
	if i := strings.LastIndexByte(p, '/'); i >= 0 {
		return p[i+1:]
	}
	return p
}
