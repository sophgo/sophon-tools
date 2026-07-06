// Package docker 提供 Docker 容器/镜像/日志管理的 MVC 模块。
package docker

import (
	dockerclient "github.com/fsouza/go-dockerclient"
)

// ContainerSummary 容器摘要。
type ContainerSummary struct {
	ID      string   `json:"id"`
	Name    string   `json:"name"`
	Image   string   `json:"image"`
	State   string   `json:"state"`
	Ports   []Port   `json:"ports,omitempty"`
	Created int64    `json:"created"`
}

// Port 端口映射信息。
type Port struct {
	PrivatePort int64  `json:"privatePort"`
	PublicPort  int64  `json:"publicPort,omitempty"`
	Type        string `json:"type"`
	IP          string `json:"ip,omitempty"`
}

// ImageSummary 镜像摘要。
type ImageSummary struct {
	ID       string   `json:"id"`
	RepoTags []string `json:"repoTags,omitempty"`
	Size     int64    `json:"size"`
	Created  int64    `json:"created"`
}

// LogsResponse 容器日志响应。
type LogsResponse struct {
	Logs string `json:"logs"`
}

// ErrorResponse 统一错误响应（与现有模块保持一致）。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}

// DegradedResponse 降级响应（docker 不可用，仍返回 200）。
type DegradedResponse struct {
	Available bool   `json:"available"`
	Reason    string `json:"reason,omitempty"`
}

// fromAPIContainers 将 go-dockerclient 的 APIContainers 转换为本模块 ContainerSummary。
func fromAPIContainers(containers []dockerclient.APIContainers) []ContainerSummary {
	result := make([]ContainerSummary, 0, len(containers))
	for _, c := range containers {
		name := ""
		if len(c.Names) > 0 {
			// Docker 返回的名称以 "/" 开头，去掉前缀
			name = c.Names[0]
			if len(name) > 0 && name[0] == '/' {
				name = name[1:]
			}
		}
		ports := make([]Port, 0, len(c.Ports))
		for _, p := range c.Ports {
			ports = append(ports, Port{
				PrivatePort: p.PrivatePort,
				PublicPort:  p.PublicPort,
				Type:        p.Type,
				IP:          p.IP,
			})
		}
		result = append(result, ContainerSummary{
			ID:      c.ID,
			Name:    name,
			Image:   c.Image,
			State:   c.State,
			Ports:   ports,
			Created: c.Created,
		})
	}
	return result
}

// fromAPIImages 将 go-dockerclient 的 APIImages 转换为本模块 ImageSummary。
func fromAPIImages(images []dockerclient.APIImages) []ImageSummary {
	result := make([]ImageSummary, 0, len(images))
	for _, img := range images {
		tags := img.RepoTags
		if tags == nil {
			tags = []string{}
		}
		result = append(result, ImageSummary{
			ID:       img.ID,
			RepoTags: tags,
			Size:     img.Size,
			Created:  img.Created,
		})
	}
	return result
}
