package main

// 入口：桌面 GUI / Web UI / 命令行三种模式。
//
//	qt_batch_deployment                       启动界面（桌面版=GUI，headless 版=Web UI）
//	qt_batch_deployment --web [选项]          启动 Web UI（两种构建都可用）
//	qt_batch_deployment [根目录] [配置文件] [并行数]   命令行批处理（与旧版 no_ui 一致）
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
	"sync"
)

const usageText = `用法:
  %s                              启动界面（桌面版为 GUI，headless 版为 Web UI）
  %s --web [--listen 地址:端口]     启动 Web UI
  %s [根目录] [配置文件路径] [最大并行数]   命令行批处理

  根目录        文件类操作的基准目录，需为绝对路径
  配置文件路径  JSON 配置文件路径，需为绝对路径
  最大并行数    并发执行的设备数上限，默认 %d

  --web 选项:
    --listen 地址:端口   监听地址，默认 127.0.0.1:8080
                         配置里含明文 SSH 密码，默认只监听本机;
                         确需对外提供时显式指定 0.0.0.0:8080 并自行加访问控制
`

func main() {
	args := os.Args

	if len(args) >= 2 && args[1] == "--web" {
		opts, err := parseWebArgs(args[2:])
		if err != nil {
			fmt.Fprintf(os.Stderr, "错误: %v\n\n", err)
			fmt.Fprintf(os.Stderr, usageText, args[0], args[0], args[0], defaultMaxParallel)
			os.Exit(2)
		}
		os.Exit(runWeb(opts))
	}

	if len(args) == 1 {
		// 无参数：按构建形态启动对应界面（桌面版 GUI / headless 版 Web UI）
		os.Exit(runDefaultUI())
	}

	if len(args) != 3 && len(args) != 4 {
		fmt.Fprintf(os.Stderr, usageText, args[0], args[0], args[0], defaultMaxParallel)
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

	// 超时取配置（可选字段），未配置时执行器用内置默认值。
	cmdTimeout, xferTimeout := cfg.Timeouts()

	var outMu sync.Mutex

	exec := &Executor{
		RootDir:         rootDir,
		MaxParallel:     maxParallel,
		CommandTimeout:  cmdTimeout,
		TransferTimeout: xferTimeout,
		Emit: func(ev StepEvent) {
			// Emit 会被多个设备 goroutine 并发调用；不加锁会让多台设备的
			// 输出在半行处交错，脚本无法按行解析。
			outMu.Lock()
			defer outMu.Unlock()
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
