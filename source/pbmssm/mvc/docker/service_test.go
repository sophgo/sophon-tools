package docker

import (
	"errors"
	"testing"
	"time"

	dockerclient "github.com/fsouza/go-dockerclient"
)

// ----------------------------------------------------------------
// fakeDockerClient — DockerAPI 的 fake 实现，用于 service 单测。
// ----------------------------------------------------------------

type fakeDockerClient struct {
	containers []dockerclient.APIContainers
	images     []dockerclient.APIImages
	logs       map[string]string // container name -> log text

	// 错误注入
	listContainersErr error
	startContainerErr error
	stopContainerErr  error
	removeContainerErr error
	listImagesErr     error
	removeImageErr    error
	logsErr           error
}

func newFakeDockerClient() *fakeDockerClient {
	return &fakeDockerClient{
		logs: make(map[string]string),
	}
}

func (f *fakeDockerClient) ListContainers(opts dockerclient.ListContainersOptions) ([]dockerclient.APIContainers, error) {
	if f.listContainersErr != nil {
		return nil, f.listContainersErr
	}

	// 按 status 过滤
	if statusFilter, ok := opts.Filters["status"]; ok && len(statusFilter) > 0 {
		filtered := make([]dockerclient.APIContainers, 0)
		for _, c := range f.containers {
			if c.State == statusFilter[0] {
				filtered = append(filtered, c)
			}
		}
		return filtered, nil
	}
	return f.containers, nil
}

func (f *fakeDockerClient) StartContainer(id string, hostConfig *dockerclient.HostConfig) error {
	if f.startContainerErr != nil {
		return f.startContainerErr
	}
	for i, c := range f.containers {
		if c.ID == id || (len(c.Names) > 0 && c.Names[0] == "/"+id) {
			f.containers[i].State = "running"
			return nil
		}
	}
	return errors.New("no such container")
}

func (f *fakeDockerClient) StopContainer(id string, timeout uint) error {
	if f.stopContainerErr != nil {
		return f.stopContainerErr
	}
	for i, c := range f.containers {
		if c.ID == id || (len(c.Names) > 0 && c.Names[0] == "/"+id) {
			f.containers[i].State = "exited"
			return nil
		}
	}
	return errors.New("no such container")
}

func (f *fakeDockerClient) RemoveContainer(opts dockerclient.RemoveContainerOptions) error {
	if f.removeContainerErr != nil {
		return f.removeContainerErr
	}
	for i, c := range f.containers {
		if c.ID == opts.ID || (len(c.Names) > 0 && c.Names[0] == "/"+opts.ID) {
			if c.State == "running" && !opts.Force {
				return errors.New("cannot remove running container")
			}
			f.containers = append(f.containers[:i], f.containers[i+1:]...)
			return nil
		}
	}
	return errors.New("no such container")
}

func (f *fakeDockerClient) ListImages(opts dockerclient.ListImagesOptions) ([]dockerclient.APIImages, error) {
	if f.listImagesErr != nil {
		return nil, f.listImagesErr
	}
	return f.images, nil
}

func (f *fakeDockerClient) RemoveImage(name string) error {
	if f.removeImageErr != nil {
		return f.removeImageErr
	}
	for i, img := range f.images {
		if img.ID == name {
			f.images = append(f.images[:i], f.images[i+1:]...)
			return nil
		}
		for _, tag := range img.RepoTags {
			if tag == name {
				f.images = append(f.images[:i], f.images[i+1:]...)
				return nil
			}
		}
	}
	return errors.New("no such image")
}

func (f *fakeDockerClient) Logs(opts dockerclient.LogsOptions) error {
	if f.logsErr != nil {
		return f.logsErr
	}
	if logText, ok := f.logs[opts.Container]; ok {
		opts.OutputStream.Write([]byte(logText))
		return nil
	}
	return errors.New("no such container")
}

// ----------------------------------------------------------------
// 便捷构造函数
// ----------------------------------------------------------------

func fakeContainers() []dockerclient.APIContainers {
	return []dockerclient.APIContainers{
		{
			ID:      "abc123",
			Names:   []string{"/nginx"},
			Image:   "nginx:latest",
			State:   "running",
			Created: time.Now().Unix(),
			Ports: []dockerclient.APIPort{
				{PrivatePort: 80, PublicPort: 8080, Type: "tcp"},
			},
		},
		{
			ID:      "def456",
			Names:   []string{"/redis"},
			Image:   "redis:7",
			State:   "exited",
			Created: time.Now().Unix() - 3600,
		},
	}
}

func fakeImages() []dockerclient.APIImages {
	return []dockerclient.APIImages{
		{
			ID:       "sha256:aaa",
			RepoTags: []string{"nginx:latest"},
			Size:     142000000,
			Created:  time.Now().Unix(),
		},
		{
			ID:       "sha256:bbb",
			RepoTags: []string{"redis:7"},
			Size:     111000000,
			Created:  time.Now().Unix() - 86400,
		},
	}
}

// ----------------------------------------------------------------
// Service 单测
// ----------------------------------------------------------------

func TestServiceListContainers(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	containers, err := svc.ListContainers("")
	if err != nil {
		t.Fatalf("ListContainers: %v", err)
	}
	if len(containers) != 2 {
		t.Fatalf("expected 2 containers, got %d", len(containers))
	}
	if containers[0].Name != "nginx" {
		t.Errorf("expected first container name 'nginx', got '%s'", containers[0].Name)
	}
	if containers[1].Name != "redis" {
		t.Errorf("expected second container name 'redis', got '%s'", containers[1].Name)
	}
}

func TestServiceListContainersWithStatusFilter(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	containers, err := svc.ListContainers("running")
	if err != nil {
		t.Fatalf("ListContainers: %v", err)
	}
	if len(containers) != 1 {
		t.Fatalf("expected 1 running container, got %d", len(containers))
	}
	if containers[0].State != "running" {
		t.Errorf("expected state 'running', got '%s'", containers[0].State)
	}
}

func TestServiceStartContainer(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	err := svc.StartContainer("nginx")
	if err != nil {
		t.Fatalf("StartContainer: %v", err)
	}

	// 验证状态已更新
	containers, _ := svc.ListContainers("running")
	if len(containers) != 1 {
		t.Fatalf("expected 1 running container after start, got %d", len(containers))
	}
}

func TestServiceStopContainer(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	err := svc.StopContainer("nginx", 10)
	if err != nil {
		t.Fatalf("StopContainer: %v", err)
	}
}

func TestServiceRemoveContainer(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	err := svc.RemoveContainer("redis", false)
	if err != nil {
		t.Fatalf("RemoveContainer: %v", err)
	}

	containers, _ := svc.ListContainers("")
	if len(containers) != 1 {
		t.Fatalf("expected 1 container after remove, got %d", len(containers))
	}
}

func TestServiceRemoveContainerForce(t *testing.T) {
	fake := newFakeDockerClient()
	fake.containers = fakeContainers()
	svc := NewDockerServiceWithClient(fake)

	// nginx is running, force remove should work
	err := svc.RemoveContainer("nginx", true)
	if err != nil {
		t.Fatalf("RemoveContainer force: %v", err)
	}

	containers, _ := svc.ListContainers("")
	if len(containers) != 1 {
		t.Fatalf("expected 1 container after force remove, got %d", len(containers))
	}
}

func TestServiceListImages(t *testing.T) {
	fake := newFakeDockerClient()
	fake.images = fakeImages()
	svc := NewDockerServiceWithClient(fake)

	images, err := svc.ListImages()
	if err != nil {
		t.Fatalf("ListImages: %v", err)
	}
	if len(images) != 2 {
		t.Fatalf("expected 2 images, got %d", len(images))
	}
	if images[0].RepoTags[0] != "nginx:latest" {
		t.Errorf("expected 'nginx:latest', got '%s'", images[0].RepoTags[0])
	}
}

func TestServiceRemoveImage(t *testing.T) {
	fake := newFakeDockerClient()
	fake.images = fakeImages()
	svc := NewDockerServiceWithClient(fake)

	err := svc.RemoveImage("sha256:aaa")
	if err != nil {
		t.Fatalf("RemoveImage: %v", err)
	}

	images, _ := svc.ListImages()
	if len(images) != 1 {
		t.Fatalf("expected 1 image after remove, got %d", len(images))
	}
}

func TestServiceGetLogs(t *testing.T) {
	fake := newFakeDockerClient()
	fake.logs["nginx"] = "2024-01-01 nginx started\n2024-01-01 nginx ready\n"
	svc := NewDockerServiceWithClient(fake)

	logs, err := svc.GetLogs("nginx", "100", 0)
	if err != nil {
		t.Fatalf("GetLogs: %v", err)
	}
	if logs == "" {
		t.Fatal("expected non-empty logs")
	}
}

func TestServiceDegradedListContainers(t *testing.T) {
	svc := NewDegradedService()

	_, err := svc.ListContainers("")
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedStartContainer(t *testing.T) {
	svc := NewDegradedService()

	err := svc.StartContainer("test")
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedStopContainer(t *testing.T) {
	svc := NewDegradedService()

	err := svc.StopContainer("test", 10)
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedRemoveContainer(t *testing.T) {
	svc := NewDegradedService()

	err := svc.RemoveContainer("test", false)
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedListImages(t *testing.T) {
	svc := NewDegradedService()

	_, err := svc.ListImages()
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedRemoveImage(t *testing.T) {
	svc := NewDegradedService()

	err := svc.RemoveImage("test")
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceDegradedGetLogs(t *testing.T) {
	svc := NewDegradedService()

	_, err := svc.GetLogs("test", "100", 0)
	if err != errUnavailable {
		t.Fatalf("expected errUnavailable, got %v", err)
	}
}

func TestServiceIsAvailable(t *testing.T) {
	svc := NewDegradedService()
	if svc.IsAvailable() {
		t.Fatal("expected IsAvailable()=false for degraded service")
	}

	fake := newFakeDockerClient()
	svc2 := NewDockerServiceWithClient(fake)
	if !svc2.IsAvailable() {
		t.Fatal("expected IsAvailable()=true for fake service")
	}
}
