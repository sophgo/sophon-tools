package main

// 命令行模式入口。
//
// 用法与旧版 no_ui 完全一致，保证脚本调用方无需修改：
//
//	qt_batch_deployment [Root Directory] [Json File Path] [Max Value]
//
// 无参数 = 图形界面。
//
// 与旧版的两处刻意差异（都属于修复）：
//  * 参数错误时返回非零退出码（旧版 exit(0)，脚本无法判断失败）。
//  * 有设备执行失败时返回非零退出码（旧版恒为 0）。

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
)

const usageText = `用法: %s [根目录] [配置文件路径] [最大并行数]

  无参数启动图形界面。

  根目录        文件类操作的基准目录，需为绝对路径
  配置文件路径  JSON 配置文件路径，需为绝对路径
  最大并行数    并发执行的设备数上限，默认 %d
`

func main() {
	args := os.Args

	if len(args) == 1 {
		// 图形界面模式
		os.Exit(runGUI())
	}

	if len(args) != 3 && len(args) != 4 {
		fmt.Fprintf(os.Stderr, usageText, args[0], defaultMaxParallel)
		os.Exit(2)
	}

	rootDir := args[1]
	jsonPath := args[2]
	maxParallel := defaultMaxParallel
	if len(args) == 4 {
		n, err := strconv.Atoi(args[3])
		if err != nil || n <= 0 {
			fmt.Fprintf(os.Stderr, "错误: 最大并行数必须是大于 0 的整数，得到 %q\n", args[3])
			os.Exit(2)
		}
		maxParallel = n
	}

	os.Exit(runCLI(rootDir, jsonPath, maxParallel))
}

func runCLI(rootDir, jsonPath string, maxParallel int) int {
	if st, err := os.Stat(rootDir); err != nil || !st.IsDir() {
		fmt.Fprintf(os.Stderr, "错误: 根目录不存在或不是目录: %s\n", rootDir)
		return 2
	}
	cfg, err := LoadConfig(jsonPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "错误: %v\n", err)
		return 2
	}
	if err := cfg.Validate(); err != nil {
		fmt.Fprintf(os.Stderr, "错误: 配置无效: %v\n", err)
		return 2
	}
	// 不完整的操作会被跳过——必须显式告知，不能让调用方以为全都跑了。
	if skipped := cfg.IncompleteOperations(); len(skipped) > 0 {
		fmt.Fprintf(os.Stderr, "警告: %d 条操作配置不完整，将被跳过:\n", len(skipped))
		for i := 0; i < len(cfg.OperationInf); i++ {
			if err, ok := skipped[i]; ok {
				fmt.Fprintf(os.Stderr, "  第 %d 条: %v\n", i+1, err)
			}
		}
	}

	exec := &Executor{
		RootDir:     rootDir,
		MaxParallel: maxParallel,
		Emit: func(ev StepEvent) {
			if ev.Log != "" {
				for _, line := range strings.Split(strings.TrimRight(ev.Log, "\n"), "\n") {
					fmt.Printf("[%s] %s\n", ev.DeviceLabel, line)
				}
			} else if ev.Err == nil && ev.Stage != "" && !ev.Done {
				fmt.Printf("[%s] %s\n", ev.DeviceLabel, ev.Stage)
			}
		},
	}

	results := exec.Run(context.Background(), cfg)

	fmt.Println(strings.Repeat("=", 56))
	failed := 0
	for i, r := range results {
		status := "成功"
		if !r.OK {
			status = "失败"
			failed++
		}
		fmt.Printf("设备[%d] %s:%d  执行状态: %s\n",
			i+1, r.Remote.IP, r.Remote.Port, status)
		if r.Err != nil {
			fmt.Printf("    原因: %v\n", r.Err)
		}
	}
	fmt.Println(strings.Repeat("=", 56))
	fmt.Printf("共 %d 台，成功 %d，失败 %d\n", len(results), len(results)-failed, failed)

	if failed > 0 {
		return 1
	}
	return 0
}
