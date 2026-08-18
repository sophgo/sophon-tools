package filemanage

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

// maxContentSize 小文件文本查看上限 1MB。
const maxContentSize = 1 << 20

// blockedPrefixes 被禁止访问的路径前缀（/proc /sys /dev）。读与写均禁止。
var blockedPrefixes = []string{"/proc", "/sys", "/dev"}

// readonlyPrefixes 关键系统目录前缀：写操作（增/删/改/移动/上传）一律禁止，
// 防止 admin 误操作（如 chmod/chown/覆盖 /etc 配置文件）导致设备不可用。
// 读操作（列表/查看/下载）不受限，便于查看配置文件核对状态。
var readonlyPrefixes = []string{"/etc", "/boot", "/var", "/opt", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/run"}

type Service struct{}

func NewService() *Service { return &Service{} }

var defaultService = NewService()

func DefaultService() *Service { return defaultService }

// HomeDir 返回当前进程账户家目录。优先 os/user.Current()，失败兜底 /root。
func HomeDir() string {
	if u, err := user.Current(); err == nil && u.HomeDir != "" {
		return u.HomeDir
	}
	return "/root"
}

// ResolvePath 规范化并校验路径。空 path 返回家目录；转绝对路径并解析符号链接
// （对路径上最深已存在部分做 EvalSymlinks，防 blocklist 被 symlink 绕过）；
// 禁止访问 /proc /sys /dev 前缀。
func ResolvePath(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return HomeDir(), nil
	}
	abs, err := filepath.Abs(filepath.Clean(path))
	if err != nil {
		return "", fmt.Errorf("resolve path: %w", err)
	}
	real, err := resolveReal(abs)
	if err != nil {
		return "", err
	}
	for _, p := range blockedPrefixes {
		if real == p || strings.HasPrefix(real, p+"/") {
			return "", fmt.Errorf("access to %s is not allowed", p)
		}
	}
	return real, nil
}

// ResolveWritePath 校验写操作路径：在 ResolvePath 基础上，禁止落在
// 关键系统目录（readonlyPrefixes）内，防误操作破坏设备系统文件。
func ResolveWritePath(path string) (string, error) {
	abs, err := ResolvePath(path)
	if err != nil {
		return "", err
	}
	for _, p := range readonlyPrefixes {
		if abs == p || strings.HasPrefix(abs, p+"/") {
			return "", fmt.Errorf("write access to %s is not allowed", p)
		}
	}
	return abs, nil
}

// resolveReal 对 abs 上最深已存在部分做符号链接解引用，返回归一化真实路径；
// 不存在的尾部段保持原样拼接（写操作目标可能尚未创建）。
// 例如 /root/link->/etc 的 /root/link/passwd 解析为 /etc/passwd；
// 新建目标 /root/newdir 时 /root 存在则原样返回 /root/newdir。
// 已知限制：检查与后续操作之间存在 TOCTOU 竞态（检查后 symlink 可能被替换），
// admin-only 工具可接受；如需更强保证可用 openat2(RESOLVE_NO_SYMLINKS)。
func resolveReal(abs string) (string, error) {
	rest := abs
	var tail []string
	for {
		resolved, err := filepath.EvalSymlinks(rest)
		if err == nil {
			if len(tail) == 0 {
				return resolved, nil
			}
			return filepath.Join(append([]string{resolved}, tail...)...), nil
		}
		// 仅"不存在"（ENOENT/ENOTDIR）向上回溯父段；权限等错误直接返回
		if !errors.Is(err, os.ErrNotExist) {
			return "", fmt.Errorf("resolve path %q: %w", abs, err)
		}
		parent := filepath.Dir(rest)
		if parent == rest {
			return "", fmt.Errorf("resolve path %q: %w", abs, err)
		}
		tail = append([]string{filepath.Base(rest)}, tail...)
		rest = parent
	}
}

// List 列目录。返回绝对目录路径与每个条目的 FileInfo（含属主/组名）。
func (s *Service) List(dir string) (string, []FileInfo, error) {
	abs, err := ResolvePath(dir)
	if err != nil {
		return "", nil, err
	}
	entries, err := os.ReadDir(abs)
	if err != nil {
		return "", nil, fmt.Errorf("read dir: %w", err)
	}
	out := make([]FileInfo, 0, len(entries))
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			continue
		}
		owner, group := ownerGroup(info)
		out = append(out, FileInfo{
			Name: info.Name(), Size: info.Size(), Mode: info.Mode().String(),
			ModTime: info.ModTime().Unix(), IsDir: info.IsDir(), Owner: owner, Group: group,
		})
	}
	return abs, out, nil
}

// ReadContent 读取小文件文本内容（限 1MB）。
func (s *Service) ReadContent(path string) (string, error) {
	abs, err := ResolvePath(path)
	if err != nil {
		return "", err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return "", fmt.Errorf("stat: %w", err)
	}
	if st.IsDir() {
		return "", errors.New("cannot read content of a directory")
	}
	if st.Size() > maxContentSize {
		return "", fmt.Errorf("file too large: %d bytes (max %d)", st.Size(), maxContentSize)
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return "", fmt.Errorf("read file: %w", err)
	}
	return string(data), nil
}

// Mkdir 递归创建目录（mkdir -p）。拒绝在根目录下创建一级目录（/xxx），
// 防止污染系统根；二级及以下（如 /root/newdir）允许；关键系统目录内拒绝。
func (s *Service) Mkdir(path string) error {
	abs, err := ResolveWritePath(path)
	if err != nil {
		return err
	}
	if abs == "/" {
		return errors.New("refuse to create root")
	}
	depth := pathDepth(abs)
	if depth <= 1 {
		return errors.New("refuse to create top-level directory under root")
	}
	return os.MkdirAll(abs, 0o755)
}

// Rename 重命名/移动。源与目标均不得落在关键系统目录内。
func (s *Service) Rename(oldPath, newPath string) error {
	oldAbs, err := ResolveWritePath(oldPath)
	if err != nil {
		return err
	}
	newAbs, err := ResolveWritePath(newPath)
	if err != nil {
		return err
	}
	return os.Rename(oldAbs, newAbs)
}

// Chmod 修改权限。mode 为八进制权限串，形如 "0755" 或 "755"。关键系统目录内拒绝。
func (s *Service) Chmod(path, mode string) error {
	abs, err := ResolveWritePath(path)
	if err != nil {
		return err
	}
	m := strings.TrimPrefix(strings.TrimPrefix(mode, "0o"), "0O")
	m = strings.TrimSpace(m)
	if m == "" {
		return errors.New("empty mode")
	}
	n, err := strconv.ParseInt(m, 8, 32)
	if err != nil {
		return fmt.Errorf("invalid mode %q: %w", mode, err)
	}
	return os.Chmod(abs, os.FileMode(n))
}

// Chown 修改所有权。需 root 权限执行。关键系统目录内拒绝。
func (s *Service) Chown(path, owner, group string) error {
	abs, err := ResolveWritePath(path)
	if err != nil {
		return err
	}
	uid, gid := -1, -1
	if owner != "" {
		u, err := user.Lookup(owner)
		if err != nil {
			return fmt.Errorf("lookup user %q: %w", owner, err)
		}
		uid, _ = strconv.Atoi(u.Uid)
	}
	if group != "" {
		g, err := user.LookupGroup(group)
		if err != nil {
			return fmt.Errorf("lookup group %q: %w", group, err)
		}
		gid, _ = strconv.Atoi(g.Gid)
	}
	return os.Chown(abs, uid, gid)
}

// Delete 删除**单个文件**。
// 安全护栏（按用户要求）：
//   - 只删文件，拒绝删除目录（IsDir 直接报错）
//   - 不递归：用 os.Remove（非 os.RemoveAll），目录/非空路径会失败
//   - 拒删根、根下一级目录（depth<=1）
//   - 关键系统目录内拒绝
func (s *Service) Delete(path string) error {
	abs, err := ResolveWritePath(path)
	if err != nil {
		return err
	}
	if abs == "/" {
		return errors.New("refuse to delete root")
	}
	if pathDepth(abs) <= 1 {
		return errors.New("refuse to delete top-level directory under root")
	}
	st, err := os.Stat(abs)
	if err != nil {
		return fmt.Errorf("stat: %w", err)
	}
	if st.IsDir() {
		return errors.New("cannot delete directory: only files are allowed")
	}
	// os.Remove 不递归：对普通文件直接删；对目录（即便空）已被上面拒绝。
	return os.Remove(abs)
}

// StreamDownload 流式下载文件到 writer。
func (s *Service) StreamDownload(path string, w io.Writer) (int64, error) {
	abs, err := ResolvePath(path)
	if err != nil {
		return 0, err
	}
	f, err := os.Open(abs)
	if err != nil {
		return 0, fmt.Errorf("open: %w", err)
	}
	defer f.Close()
	return io.Copy(w, f)
}

// DownloadName 返回下载文件名（基名）与大小。
func (s *Service) DownloadName(path string) (name string, size int64, err error) {
	abs, err := ResolvePath(path)
	if err != nil {
		return "", 0, err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return "", 0, fmt.Errorf("stat: %w", err)
	}
	return filepath.Base(abs), st.Size(), nil
}

// SaveUpload 将 reader 内容流式写入 dir/<filename>。支持大文件。
// 仅取基名，禁止路径穿越（如 ../etc/passwd）；目标目录不得在关键系统目录内。
func (s *Service) SaveUpload(dir, filename string, r io.Reader) (string, int64, error) {
	abs, err := ResolveWritePath(dir)
	if err != nil {
		return "", 0, err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return "", 0, fmt.Errorf("stat upload dir: %w", err)
	}
	if !st.IsDir() {
		return "", 0, errors.New("upload target is not a directory")
	}
	safe := filepath.Base(filename)
	if safe == "" || safe == "." || safe == ".." {
		return "", 0, errors.New("invalid filename")
	}
	dst := filepath.Join(abs, safe)
	out, err := os.Create(dst)
	if err != nil {
		return "", 0, fmt.Errorf("create file: %w", err)
	}
	defer out.Close()
	n, err := io.Copy(out, r)
	if err != nil {
		return "", 0, fmt.Errorf("write file: %w", err)
	}
	return dst, n, nil
}

// pathDepth 返回绝对路径在根下的段数：/root 为 1，/root/a 为 2。
func pathDepth(abs string) int {
	return len(strings.Split(strings.Trim(filepath.ToSlash(abs), "/"), "/"))
}

// ownerGroup 从 FileInfo.Sys() 取 uid/gid 并解析为用户名/组名。
func ownerGroup(info os.FileInfo) (string, string) {
	uid, gid := -1, -1
	if stat, ok := info.Sys().(*syscall.Stat_t); ok {
		uid = int(stat.Uid)
		gid = int(stat.Gid)
	}
	owner := strconv.Itoa(uid)
	if u, err := user.LookupId(owner); err == nil {
		owner = u.Username
	}
	group := strconv.Itoa(gid)
	if g, err := user.LookupGroupId(group); err == nil {
		group = g.Name
	}
	return owner, group
}
