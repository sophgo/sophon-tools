package docker

import (
	"bytes"
	"fmt"
	"sync"

	dockerclient "github.com/fsouza/go-dockerclient"
)

// DockerAPI 定义 Docker 操作的最小接口，生产用 *dockerclient.Client 实现，测试用 fake。
type DockerAPI interface {
	ListContainers(opts dockerclient.ListContainersOptions) ([]dockerclient.APIContainers, error)
	StartContainer(id string, hostConfig *dockerclient.HostConfig) error
	StopContainer(id string, timeout uint) error
	RemoveContainer(opts dockerclient.RemoveContainerOptions) error
	ListImages(opts dockerclient.ListImagesOptions) ([]dockerclient.APIImages, error)
	RemoveImage(name string) error
	Logs(opts dockerclient.LogsOptions) error
}

// DockerService 封装 Docker 客户端操作，对 gin 无依赖，可单测。
type DockerService struct {
	client DockerAPI

	mu        sync.RWMutex
	available bool
}

// defaultService 包级懒初始化单例。
var (
	defaultService     *DockerService
	defaultServiceOnce sync.Once
)

// DefaultService 返回懒初始化的包级 DockerService。
// 首次调用时尝试连接 docker socket（路径从 config 读取），
// 连接失败则 available=false，后续所有方法返回降级响应。
func DefaultService() *DockerService {
	defaultServiceOnce.Do(func() {
		defaultService = NewDockerService()
	})
	return defaultService
}

// NewDockerService 创建 DockerService，尝试连接 unix:///var/run/docker.sock。
func NewDockerService() *DockerService {
	svc := &DockerService{}
	client, err := dockerclient.NewClient("unix:///var/run/docker.sock")
	if err != nil {
		svc.available = false
		return svc
	}
	// 尝试 ping 验证连接是否可用
	if err := client.Ping(); err != nil {
		svc.available = false
		return svc
	}
	svc.client = client
	svc.available = true
	return svc
}

// NewDockerServiceWithClient 用指定 DockerAPI 创建 DockerService（测试注入用）。
func NewDockerServiceWithClient(client DockerAPI) *DockerService {
	return &DockerService{
		client:    client,
		available: true,
	}
}

// NewDegradedService 创建降级（不可用）的 DockerService（测试用）。
func NewDegradedService() *DockerService {
	return &DockerService{available: false}
}

// IsAvailable 返回 docker 是否可用。
func (s *DockerService) IsAvailable() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.available
}

// ListContainers 返回容器列表，可按 status 过滤。
func (s *DockerService) ListContainers(status string) ([]ContainerSummary, error) {
	if !s.IsAvailable() {
		return nil, errUnavailable
	}

	opts := dockerclient.ListContainersOptions{All: true}
	if status != "" {
		opts.Filters = map[string][]string{"status": {status}}
	}

	containers, err := s.client.ListContainers(opts)
	if err != nil {
		return nil, fmt.Errorf("list containers: %w", err)
	}

	return fromAPIContainers(containers), nil
}

// StartContainer 启动指定名称的容器。
func (s *DockerService) StartContainer(name string) error {
	if !s.IsAvailable() {
		return errUnavailable
	}
	return s.client.StartContainer(name, nil)
}

// StopContainer 停止指定名称的容器。
func (s *DockerService) StopContainer(name string, timeout uint) error {
	if !s.IsAvailable() {
		return errUnavailable
	}
	return s.client.StopContainer(name, timeout)
}

// RemoveContainer 删除指定名称的容器。
func (s *DockerService) RemoveContainer(name string, force bool) error {
	if !s.IsAvailable() {
		return errUnavailable
	}
	return s.client.RemoveContainer(dockerclient.RemoveContainerOptions{
		ID:    name,
		Force: force,
	})
}

// ListImages 返回镜像列表。
func (s *DockerService) ListImages() ([]ImageSummary, error) {
	if !s.IsAvailable() {
		return nil, errUnavailable
	}

	images, err := s.client.ListImages(dockerclient.ListImagesOptions{All: true})
	if err != nil {
		return nil, fmt.Errorf("list images: %w", err)
	}

	return fromAPIImages(images), nil
}

// RemoveImage 删除指定镜像。
func (s *DockerService) RemoveImage(id string) error {
	if !s.IsAvailable() {
		return errUnavailable
	}
	return s.client.RemoveImage(id)
}

// GetLogs 获取容器日志。
func (s *DockerService) GetLogs(name string, tail string, since int64) (string, error) {
	if !s.IsAvailable() {
		return "", errUnavailable
	}

	var buf bytes.Buffer
	opts := dockerclient.LogsOptions{
		Container:    name,
		OutputStream: &buf,
		ErrorStream:  &buf,
		Tail:         tail,
		Since:        since,
		Stdout:       true,
		Stderr:       true,
		Timestamps:   false,
		RawTerminal:  true,
	}

	if err := s.client.Logs(opts); err != nil {
		return "", fmt.Errorf("get logs: %w", err)
	}

	return buf.String(), nil
}

// errUnavailable 当 docker 不可用时返回的错误。
var errUnavailable = fmt.Errorf("docker not available")
