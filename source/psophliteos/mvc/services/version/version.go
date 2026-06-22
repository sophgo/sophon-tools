package services

import (
	"io/ioutil"
	"regexp"
	"sophliteos/logger"
	"strings"
)

type BuildInfo struct {
	Modules   []Module `json:"modules"`
	BuildName string   `json:"buildname"`
	BuildTime string   `json:"buildtime"`
}

type Module struct {
	Name   string `json:"module"`
	Commit string `json:"commit"`
}

func VersionInit(versionFile string) BuildInfo {
	// 读取文件内容
	fileContent, err := ioutil.ReadFile("/var/lib/sophliteos/release_version.txt")
	if err != nil {
		logger.Error("无法读取文件:", err)
		return BuildInfo{}
	}

	// 解析文件内容
	buildInfo := parseBuildInfo(string(fileContent))

	return buildInfo
}

func parseBuildInfo(content string) BuildInfo {
	buildInfo := BuildInfo{}
	modules := strings.Split(content, "module:")

	for _, module := range modules {
		lines := strings.Split(module, "\n")
		if len(lines) < 2 {
			continue
		}

		moduleName := ""
		commit := ""

		isModuleName := true
		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}

			if isModuleName {
				moduleName = line
				isModuleName = false
			} else if strings.HasPrefix(line, "commit") {
				re := regexp.MustCompile(`commit\s+(.+)`)
				match := re.FindStringSubmatch(line)
				if len(match) > 1 {
					commit = match[1]
				}
			}
		}

		if moduleName != "" && commit != "" {
			buildInfo.Modules = append(buildInfo.Modules, Module{Name: moduleName, Commit: commit})
		}
	}

	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		if strings.HasPrefix(line, "buildname:") {
			buildInfo.BuildName = strings.TrimSpace(strings.TrimPrefix(line, "buildname:"))
		} else if strings.HasPrefix(line, "buildtime:") {
			buildInfo.BuildTime = strings.TrimSpace(strings.TrimPrefix(line, "buildtime:"))
		}
	}

	return buildInfo
}
