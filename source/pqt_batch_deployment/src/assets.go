package main

import (
	"embed"
	"io/fs"
	"path"
	"sort"
	"strings"
)

// 资源用 go:embed 打进二进制——这是「单二进制、不随附资源目录」的关键。
// 旧版 Qt 版把字体/QSS/预设 JSON 编进 qrc，思路一致，这里换成 embed。
//
//go:embed assets
var assetsFS embed.FS

// AssetFS 返回去掉 assets/ 前缀的资源树。
func AssetFS() fs.FS {
	sub, err := fs.Sub(assetsFS, "assets")
	if err != nil {
		// 只可能在 embed 声明写错时发生，属于编译期问题
		panic(err)
	}
	return sub
}

// ReadAsset 读取一个内嵌资源。
func ReadAsset(name string) ([]byte, error) {
	return fs.ReadFile(AssetFS(), name)
}

// BuiltinPresets 返回内置预设配置文件名（对应旧版 comboBoxJson 的预设列表）。
func BuiltinPresets() []string {
	entries, err := fs.ReadDir(AssetFS(), "batchConf")
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if strings.EqualFold(path.Ext(e.Name()), ".json") {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

// LoadBuiltinPreset 读取内置预设。
func LoadBuiltinPreset(name string) (*Config, error) {
	data, err := ReadAsset("batchConf/" + name)
	if err != nil {
		return nil, err
	}
	var c Config
	if err := unmarshalConfig(data, &c); err != nil {
		return nil, err
	}
	return &c, nil
}
