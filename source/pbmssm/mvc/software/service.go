package software

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"bmssm/config"
	"bmssm/database"
	"bmssm/logger"
	"bmssm/pkg/system"

	"github.com/jinzhu/gorm"
)

// ---------------------------------------------------------------
// 常量
// ---------------------------------------------------------------

const (
	// DefaultSoftwareRoot 已装软件扫描根路径。
	DefaultSoftwareRoot = "/opt/sophon"
	// DefaultPkgDir 上传软件包暂存目录。
	DefaultPkgDir = "/tmp/ssm-pkg"
	// DefaultOTADir 上传固件暂存目录。
	DefaultOTADir = "/tmp/ssm-ota"
	// DefaultMaxSize 软件包/固件上传默认大小限制（1GB）。
	DefaultMaxSize = 1 << 30
)

// versionFileNames 扫描时识别为版本文件的名称集合。
var versionFileNames = map[string]bool{
	"VERSION":      true,
	"version":      true,
	"version.txt":  true,
	".version":     true,
	"version.json": true,
}

// ---------------------------------------------------------------
// Service
// ---------------------------------------------------------------

// SoftwareService 封装软件/OTA 业务逻辑，对 gin 无依赖，可单测。
type SoftwareService struct {
	softwareRoot string // 可注入，默认 /opt/sophon
	pkgDir       string
	otaDir       string
	maxSize      int64

	// db 非 nil 时 OTA 固件记录落库 ota_files（重启后 uploadId 可继续查询，MYS-389）；
	// nil（测试/DB 不可用）时回退内存 map。
	db *gorm.DB

	mu         sync.RWMutex
	otaRecords map[string]*otaRecord // uploadID -> record（仅 db==nil 时使用）
}

// DefaultService 包级懒初始化单例。
var (
	defaultService     *SoftwareService
	defaultServiceOnce sync.Once
)

// DefaultService 返回懒初始化的包级 SoftwareService。
func DefaultService() *SoftwareService {
	defaultServiceOnce.Do(func() {
		defaultService = NewSoftwareService(DefaultSoftwareRoot, DefaultPkgDir, DefaultOTADir, maxSizeFromConfig())
		// 启动时清理 OTA 残留：上传中断的 tmp_*、解压残留 *_extracted、
		// 无 DB 记录的孤儿文件；DB 记录指向的文件缺失时删除记录。
		defaultService.reconcileOTA()
	})
	return defaultService
}

// NewSoftwareService 创建 SoftwareService（测试注入用）。
// db 取 database.DB()：生产环境 DB 已就绪；纯单测未 InitDB 时为 nil，回退内存 map。
func NewSoftwareService(softwareRoot, pkgDir, otaDir string, maxSize int64) *SoftwareService {
	// 确保上传目录存在
	_ = os.MkdirAll(pkgDir, 0o755)
	_ = os.MkdirAll(otaDir, 0o755)
	return &SoftwareService{
		softwareRoot: softwareRoot,
		pkgDir:       pkgDir,
		otaDir:       otaDir,
		maxSize:      maxSize,
		db:           database.DB(),
		otaRecords:   make(map[string]*otaRecord),
	}
}

// GetMaxSize 返回最大上传文件大小。
func (s *SoftwareService) GetMaxSize() int64 {
	return s.maxSize
}

// GetOTADir 返回 OTA 固件暂存目录。
func (s *SoftwareService) GetOTADir() string {
	return s.otaDir
}

// GetPkgDir 返回软件包暂存目录。
func (s *SoftwareService) GetPkgDir() string {
	return s.pkgDir
}

// ---------------------------------------------------------------
// OTA 残留清理（MYS-389）：启动后 /tmp/ssm-ota 不再残留无名文件
// ---------------------------------------------------------------

// reconcileOTA 清理 OTA 暂存目录与 DB 记录，保证重启后状态一致：
//   - 上传中断残留的 tmp_*（controller 保存临时文件的命名前缀）
//   - 解压残留的 *_extracted 目录（ExecuteUpgrade 崩溃/重启遗留）
//   - 无 DB 记录对应的孤儿固件文件（本应命名的 uid_filename）
//   - DB 记录指向的文件缺失时删除记录（文件已被外部清理）
//
// db 为 nil 时仅做文件清理（无法判定孤儿归属，只删 tmp_*/_extracted）。
func (s *SoftwareService) reconcileOTA() {
	entries, err := os.ReadDir(s.otaDir)
	if err != nil {
		return
	}

	recorded := s.recordedUploadIDs()

	for _, ent := range entries {
		name := ent.Name()
		switch {
		case strings.HasPrefix(name, "tmp_"):
			// 上传中断残留
			_ = os.RemoveAll(filepath.Join(s.otaDir, name))
		case strings.HasSuffix(name, "_extracted"):
			// 解压残留目录（升级中断/进程被杀遗留）
			_ = os.RemoveAll(filepath.Join(s.otaDir, name))
		default:
			// uid_filename：DB 有记录则保留（重启后仍可查询/升级），否则视为孤儿删除
			uid := name
			if idx := strings.IndexByte(name, '_'); idx > 0 {
				uid = name[:idx]
			}
			if s.db != nil && !recorded[uid] {
				_ = os.RemoveAll(filepath.Join(s.otaDir, name))
			}
		}
	}

	// DB 记录指向的文件已不存在：删除记录（uploadId 查询返回 not found 而非陈旧信息）
	if s.db == nil {
		return
	}
	var files []OTAFile
	if err := s.db.Find(&files).Error; err != nil {
		return
	}
	for _, f := range files {
		if _, err := os.Stat(f.FilePath); err != nil {
			logger.Info("reconcileOTA: drop record %s (file %s missing)", f.UploadID, f.FilePath)
			_ = s.db.Where("upload_id = ?", f.UploadID).Delete(&OTAFile{}).Error
		}
	}
}

// recordedUploadIDs 返回 DB 中全部 uploadId 集合（db 为 nil 时返回 nil）。
func (s *SoftwareService) recordedUploadIDs() map[string]bool {
	if s.db == nil {
		return nil
	}
	var files []OTAFile
	if err := s.db.Select("upload_id").Find(&files).Error; err != nil {
		return nil
	}
	out := make(map[string]bool, len(files))
	for _, f := range files {
		out[f.UploadID] = true
	}
	return out
}

// maxSizeFromConfig 从配置读取 software.maxSize，默认 1GB。
func maxSizeFromConfig() int64 {
	c := &config.Conf
	c.RLock()
	defer c.RUnlock()
	if c.GetViper() == nil {
		return DefaultMaxSize
	}
	ms := c.GetViper().GetInt64("software.maxSize")
	if ms <= 0 {
		return DefaultMaxSize
	}
	return ms
}

// ---------------------------------------------------------------
// 软件列表
// ---------------------------------------------------------------

// ListSoftware 扫描 softwareRoot 下的子目录，返回已装软件列表。
// 每个子目录若包含版本文件，则读取第一行作为版本号。
func (s *SoftwareService) ListSoftware() ([]SoftwareInfo, error) {
	entries, err := os.ReadDir(s.softwareRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return []SoftwareInfo{}, nil
		}
		return nil, fmt.Errorf("scan %s: %w", s.softwareRoot, err)
	}

	result := make([]SoftwareInfo, 0)
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		name := entry.Name()
		// 跳过隐藏目录
		if strings.HasPrefix(name, ".") {
			continue
		}
		pkgPath := filepath.Join(s.softwareRoot, name)
		ver := readVersionFile(pkgPath)
		if ver == "" {
			ver = "unknown"
		}
		result = append(result, SoftwareInfo{
			Name:    name,
			Version: ver,
			Path:    pkgPath,
		})
	}
	return result, nil
}

// readVersionFile 在目录下查找版本文件并返回版本字符串。
func readVersionFile(dir string) string {
	for vf := range versionFileNames {
		vp := filepath.Join(dir, vf)
		data, err := os.ReadFile(vp)
		if err != nil {
			continue
		}
		ver := strings.TrimSpace(string(data))
		// 取第一行
		if idx := strings.Index(ver, "\n"); idx >= 0 {
			ver = ver[:idx]
		}
		if ver != "" {
			return ver
		}
	}
	return ""
}

// ---------------------------------------------------------------
// 安装 / 升级
// ---------------------------------------------------------------

// InstallPackage 安装上传的软件包。
// 支持 .deb（dpkg -i）、.tar.gz/.tgz（解包）、.zip（解包）。
// 若配置 software.autoRunScript 为 true，解包后自动执行 install.sh/setup.sh，.deb 允许 dpkg
// 执行维护脚本；否则全部拒绝执行包内脚本（防上传即 root RCE）。
// filePath 是上传落盘后的路径，origName 是原始文件名。
func (s *SoftwareService) InstallPackage(filePath, origName string) (*InstallResponse, error) {
	lower := strings.ToLower(origName)

	switch {
	case strings.HasSuffix(lower, ".deb"):
		return s.installDeb(filePath, origName)
	case strings.HasSuffix(lower, ".tar.gz"), strings.HasSuffix(lower, ".tgz"):
		return s.installTarGz(filePath, origName)
	case strings.HasSuffix(lower, ".zip"):
		return s.installZip(filePath, origName)
	default:
		return nil, fmt.Errorf("unsupported package format: %s (supported: .deb, .tar.gz, .tgz, .zip)", origName)
	}
}

// autoRunScript 是否自动执行包内安装脚本。默认关闭（防止上传恶意脚本即 root RCE）。
// 以函数变量暴露，测试可覆盖。
var autoRunScript = func() bool {
	c := &config.Conf
	c.RLock()
	defer c.RUnlock()
	if c.GetViper() == nil {
		return false
	}
	return c.GetViper().GetBool("software.autoRunScript")
}

// installDeb 用 dpkg -i 安装 deb 包。
// dpkg 会以 root 执行包内 preinst/postinst 等维护脚本，与解包脚本同一安全口径：
// autoRunScript 默认关闭时拒绝安装，防止上传恶意 .deb 即 root RCE。
func (s *SoftwareService) installDeb(filePath, origName string) (*InstallResponse, error) {
	if !autoRunScript() {
		return &InstallResponse{
			Success: false,
			Message: "deb install disabled: dpkg would run package maintainer scripts as root; set software.autoRunScript=true to enable",
			Package: origName,
			Output:  "",
		}, nil
	}
	stdout, stderr, err := system.RunCommandArgs("dpkg", "-i", filePath)
	if err != nil {
		logger.Error("dpkg -i %s failed: %s %s", filePath, stdout, stderr)
		return &InstallResponse{
			Success: false,
			Message: "dpkg install failed",
			Package: origName,
			Output:  stderr,
		}, nil
	}
	return &InstallResponse{
		Success: true,
		Message: "package installed",
		Package: origName,
		Output:  stdout,
	}, nil
}

// installTarGz 解包 tar.gz 到软件根目录。
func (s *SoftwareService) installTarGz(filePath, origName string) (*InstallResponse, error) {
	// 从文件名推断包名（去掉 .tar.gz/.tgz）
	pkgName := packageName(origName)
	destDir := filepath.Join(s.softwareRoot, pkgName)

	if err := os.MkdirAll(destDir, 0o755); err != nil {
		return nil, fmt.Errorf("create dest dir %s: %w", destDir, err)
	}

	if err := extractTarGz(filePath, destDir); err != nil {
		return nil, fmt.Errorf("extract tar.gz: %w", err)
	}

	// 仅当显式开启 autoRunScript 才执行包内脚本；否则仅提示，避免上传即 root 执行。
	output := ""
	if autoRunScript() {
		if installScript := findInstallScript(destDir); installScript != "" {
			stdout, stderr, _ := system.RunCommandArgs("/bin/bash", installScript)
			output = stdout + stderr
		}
	}

	return &InstallResponse{
		Success: true,
		Message: "package extracted",
		Package: origName,
		Output:  output,
	}, nil
}

// installZip 解包 zip 到软件根目录。
func (s *SoftwareService) installZip(filePath, origName string) (*InstallResponse, error) {
	pkgName := packageName(origName)
	destDir := filepath.Join(s.softwareRoot, pkgName)

	if err := os.MkdirAll(destDir, 0o755); err != nil {
		return nil, fmt.Errorf("create dest dir %s: %w", destDir, err)
	}

	if err := extractZip(filePath, destDir); err != nil {
		return nil, fmt.Errorf("extract zip: %w", err)
	}

	output := ""
	if autoRunScript() {
		if installScript := findInstallScript(destDir); installScript != "" {
			stdout, stderr, _ := system.RunCommandArgs("/bin/bash", installScript)
			output = stdout + stderr
		}
	}

	return &InstallResponse{
		Success: true,
		Message: "package extracted",
		Package: origName,
		Output:  output,
	}, nil
}

// UpgradePackage 升级（语义同 InstallPackage）。
func (s *SoftwareService) UpgradePackage(filePath, origName string) (*InstallResponse, error) {
	return s.InstallPackage(filePath, origName)
}

// ---------------------------------------------------------------
// OTA 固件上传
// ---------------------------------------------------------------

// UploadFirmware 验证固件文件并保存到 OTA 目录，返回 uploadId。
func (s *SoftwareService) UploadFirmware(filePath, origName string, fileSize int64) (*OTAUploadResponse, error) {
	if !isValidFirmwareName(origName) {
		return nil, fmt.Errorf("invalid firmware file: %s (allowed: .tgz, .bin)", origName)
	}

	uid := newUploadID()
	destPath := filepath.Join(s.otaDir, uid+"_"+sanitizeFileName(origName))

	// 移动（或复制）文件到 OTA 目录
	if err := copyFile(filePath, destPath); err != nil {
		return nil, fmt.Errorf("save firmware: %w", err)
	}

	rec := &otaRecord{
		UploadID:   uid,
		FileName:   origName,
		FilePath:   destPath,
		FileSize:   fileSize,
		UploadedAt: time.Now(),
		Status:     "uploaded",
	}

	if err := s.saveOTARecord(rec); err != nil {
		logger.Warn("ota record persist failed, keep in-memory only: %v", err)
		// 文件已落盘，记录不能丢：回退内存 map（本进程内仍可查询/升级；
		// 重启后该 uploadId 会因无 DB 记录被 reconcile 清理，属降级路径）
		s.mu.Lock()
		s.otaRecords[rec.UploadID] = rec
		s.mu.Unlock()
	}

	return &OTAUploadResponse{
		UploadID:   uid,
		FileName:   origName,
		FileSize:   fileSize,
		UploadedAt: rec.UploadedAt.Format(time.RFC3339),
	}, nil
}

// saveOTARecord 保存 OTA 上传记录：db 可用落库 ota_files，否则入内存 map。
func (s *SoftwareService) saveOTARecord(rec *otaRecord) error {
	if s.db != nil {
		m := OTAFile{
			UploadID:  rec.UploadID,
			FileName:  rec.FileName,
			FilePath:  rec.FilePath,
			FileSize:  rec.FileSize,
			Status:    rec.Status,
			CreatedAt: rec.UploadedAt,
		}
		if err := s.db.Create(&m).Error; err != nil {
			return err
		}
		return nil
	}
	s.mu.Lock()
	s.otaRecords[rec.UploadID] = rec
	s.mu.Unlock()
	return nil
}

// GetFirmwareInfo 根据 uploadId 查询固件元信息。
func (s *SoftwareService) GetFirmwareInfo(uploadID string) (*OTADownloadResponse, error) {
	if s.db != nil {
		var m OTAFile
		if err := s.db.Where("upload_id = ?", uploadID).First(&m).Error; err != nil {
			return nil, fmt.Errorf("firmware not found: %s", uploadID)
		}
		return &OTADownloadResponse{
			UploadID:   m.UploadID,
			FileName:   m.FileName,
			FileSize:   m.FileSize,
			UploadedAt: m.CreatedAt.Format(time.RFC3339),
			Status:     m.Status,
		}, nil
	}

	s.mu.RLock()
	rec, ok := s.otaRecords[uploadID]
	s.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("firmware not found: %s", uploadID)
	}

	return &OTADownloadResponse{
		UploadID:   rec.UploadID,
		FileName:   rec.FileName,
		FileSize:   rec.FileSize,
		UploadedAt: rec.UploadedAt.Format(time.RFC3339),
		Status:     rec.Status,
	}, nil
}

// ExecuteUpgrade 根据 uploadId 执行固件升级。
// 解包固件 → 找 install.sh/upgrade.sh → 用 /bin/bash 执行 → 返回结果。
// 如果找不到升级脚本，返回 available=false，不返回 error。
func (s *SoftwareService) ExecuteUpgrade(uploadID string) (*OTAUpgradeResponse, error) {
	rec, err := s.getOTARecord(uploadID)
	if err != nil {
		return nil, err
	}

	// 创建解包临时目录
	extractDir := filepath.Join(s.otaDir, uploadID+"_extracted")
	if err := os.MkdirAll(extractDir, 0o755); err != nil {
		return nil, fmt.Errorf("create extract dir: %w", err)
	}
	defer os.RemoveAll(extractDir) // 升级完成后清理

	// 根据文件类型解包
	lower := strings.ToLower(rec.FileName)
	switch {
	case strings.HasSuffix(lower, ".tgz"), strings.HasSuffix(lower, ".tar.gz"):
		if err := extractTarGz(rec.FilePath, extractDir); err != nil {
			return nil, fmt.Errorf("extract firmware: %w", err)
		}
	default:
		// .bin 文件直接复制到解包目录（视为可执行）
		dest := filepath.Join(extractDir, filepath.Base(rec.FileName))
		if err := copyFile(rec.FilePath, dest); err != nil {
			return nil, fmt.Errorf("copy firmware: %w", err)
		}
	}

	// 查找升级脚本
	script := findUpgradeScript(extractDir)
	if script == "" {
		return &OTAUpgradeResponse{
			Success:   false,
			Available: false,
			Message:   "no upgrade script found",
			Reason:    "no upgrade script found",
		}, nil
	}

	// 固件内脚本自动执行默认关闭（防上传恶意固件即 root RCE），仅配置显式开启时执行。
	if !autoRunScript() {
		return &OTAUpgradeResponse{
			Success:   false,
			Available: false,
			Message:   "auto-run of firmware scripts is disabled",
			Reason:    "set software.autoRunScript=true to enable",
		}, nil
	}

	// 更新状态
	rec.Status = "upgrading"
	s.updateOTARecordStatus(rec)

	stdout, stderr, err := system.RunCommandArgs("/bin/bash", script)
	output := stdout + stderr

	if err != nil {
		rec.Status = "failed"
	} else {
		rec.Status = "completed"
	}
	s.updateOTARecordStatus(rec)

	return &OTAUpgradeResponse{
		Success:   err == nil,
		Available: true,
		Message:   "upgrade executed",
		Output:    strings.TrimSpace(output),
	}, nil
}

// getOTARecord 按 uploadId 取 OTA 记录（DB 优先，nil db 回退内存 map）。
func (s *SoftwareService) getOTARecord(uploadID string) (*otaRecord, error) {
	if s.db != nil {
		var m OTAFile
		if err := s.db.Where("upload_id = ?", uploadID).First(&m).Error; err != nil {
			return nil, fmt.Errorf("firmware not found: %s", uploadID)
		}
		return &otaRecord{
			UploadID:   m.UploadID,
			FileName:   m.FileName,
			FilePath:   m.FilePath,
			FileSize:   m.FileSize,
			UploadedAt: m.CreatedAt,
			Status:     m.Status,
		}, nil
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	rec, ok := s.otaRecords[uploadID]
	if !ok {
		return nil, fmt.Errorf("firmware not found: %s", uploadID)
	}
	return rec, nil
}

// updateOTARecordStatus 更新 OTA 记录状态（best-effort：db 或内存 map）。
func (s *SoftwareService) updateOTARecordStatus(rec *otaRecord) {
	if s.db != nil {
		if err := s.db.Model(&OTAFile{}).Where("upload_id = ?", rec.UploadID).Update("status", rec.Status).Error; err != nil {
			logger.Warn("ota record status update failed: uploadId=%s err=%v", rec.UploadID, err)
		}
		return
	}
	s.mu.Lock()
	s.otaRecords[rec.UploadID] = rec
	s.mu.Unlock()
}

// ---------------------------------------------------------------
// 文件名校验
// ---------------------------------------------------------------

// sanitizeFileName 清理文件名，防止路径穿越。
func sanitizeFileName(name string) string {
	return filepath.Base(name)
}

// allowedExt 允许的固件后缀。
var allowedFirmwareExt = map[string]bool{
	".tgz": true,
	".bin": true,
}

// isValidFirmwareName 校验固件文件名是否合法。
func isValidFirmwareName(name string) bool {
	base := filepath.Base(name)
	if base != name {
		return false // 包含路径分隔符
	}
	if base == "." || base == ".." || base == "" {
		return false
	}
	lower := strings.ToLower(base)
	for ext := range allowedFirmwareExt {
		if strings.HasSuffix(lower, ext) && len(base) > len(ext) {
			return true
		}
	}
	return false
}

// isValidPackageName 校验上传的软件包文件名是否合法。
func isValidPackageName(name string) bool {
	base := filepath.Base(name)
	if base != name {
		return false
	}
	if base == "." || base == ".." || base == "" {
		return false
	}
	// 只允许字母、数字、下划线、短横线、点号
	for _, r := range base {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || r == '_' || r == '-' || r == '.' {
			continue
		}
		return false
	}
	return true
}

// ---------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------

// packageName 从文件名提取包名（去掉后缀）。
func packageName(fileName string) string {
	base := filepath.Base(fileName)
	// 去掉 .tar.gz / .tgz / .zip / .deb
	for _, ext := range []string{".tar.gz", ".tgz", ".zip", ".deb"} {
		if strings.HasSuffix(strings.ToLower(base), ext) {
			return base[:len(base)-len(ext)]
		}
	}
	// 去掉最后一个扩展名
	if idx := strings.LastIndex(base, "."); idx >= 0 {
		return base[:idx]
	}
	return base
}

// newUploadID 生成随机 upload ID。
func newUploadID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// copyFile 复制文件。
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}

// findInstallScript 在目录（浅层）中查找 install.sh。
func findInstallScript(dir string) string {
	candidates := []string{"install.sh", "setup.sh"}
	for _, c := range candidates {
		p := filepath.Join(dir, c)
		if exists, _ := system.PathExists(p); exists {
			return p
		}
	}
	return ""
}

// findUpgradeScript 递归查找升级脚本（install.sh / upgrade.sh）。
func findUpgradeScript(dir string) string {
	candidates := []string{"install.sh", "upgrade.sh", "update.sh"}
	var found string
	_ = filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil || found != "" {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		base := filepath.Base(path)
		for _, c := range candidates {
			if base == c {
				found = path
				return filepath.SkipAll
			}
		}
		return nil
	})
	return found
}

// ---------------------------------------------------------------
// 解包函数（含 zip-slip 防护）
// ---------------------------------------------------------------

// errZipSlip zip-slip / 路径穿越攻击检测。
var errZipSlip = errors.New("zip-slip detected: entry path escapes destination directory")

// isSafePath 检查 entryPath 是否安全（不含 ..，解析后仍在 destDir 内）。
func isSafePath(destDir, entryPath string) bool {
	// 拒绝含路径穿越字符的路径
	if strings.Contains(entryPath, "..") {
		return false
	}
	cleaned := filepath.Clean(entryPath)
	if strings.Contains(cleaned, "..") {
		return false
	}
	resolved := filepath.Join(destDir, cleaned)
	absDest, err := filepath.Abs(destDir)
	if err != nil {
		return false
	}
	absResolved, err := filepath.Abs(resolved)
	if err != nil {
		return false
	}
	// 确保解析后路径以 destDir 为前缀
	return strings.HasPrefix(absResolved, absDest+string(filepath.Separator)) || absResolved == absDest
}

// maxExtractBytes 单次解包累计解压上限（防 tar/zip 炸弹撑爆磁盘）。
const maxExtractBytes = 2 << 30 // 2GiB

// extractTarGz 解压 tar.gz 到 destDir，含 zip-slip 防护与总量限制。
func extractTarGz(filePath, destDir string) error {
	f, err := os.Open(filePath)
	if err != nil {
		return err
	}
	defer f.Close()

	gzReader, err := gzip.NewReader(f)
	if err != nil {
		return fmt.Errorf("gzip reader: %w", err)
	}
	defer gzReader.Close()

	var total int64
	tarReader := tar.NewReader(gzReader)
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}

		if !isSafePath(destDir, header.Name) {
			return fmt.Errorf("%w: %s", errZipSlip, header.Name)
		}

		target := filepath.Join(destDir, filepath.Clean(header.Name))

		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			out, err := os.Create(target)
			if err != nil {
				return err
			}
			// 单条目限制（DefaultMaxSize）+ 累计总量限制（maxExtractBytes，防炸弹）。
			// CopyN 上限取 DefaultMaxSize+1：条目超过单条目上限时复制量恰好超过
			// 上限并返回 nil（达到 limit），据此报错而非静默截断（旧实现把超限
			// 条目截断为 1GiB，且剩余数据被吞导致后续条目解析错乱）。
			n, err := io.CopyN(out, tarReader, DefaultMaxSize+1)
			out.Close()
			if err != nil && err != io.EOF {
				return err
			}
			if n > DefaultMaxSize {
				return fmt.Errorf("entry %s exceeds size limit (%d bytes)", header.Name, DefaultMaxSize)
			}
			total += n
			if total > maxExtractBytes {
				return fmt.Errorf("extraction exceeds total size limit (%d bytes)", maxExtractBytes)
			}
		case tar.TypeSymlink:
			// 拒绝符号链接（安全考虑）
			continue
		}
	}
	return nil
}

// extractZip 解压 zip 到 destDir，含 zip-slip 防护与总量限制。
func extractZip(filePath, destDir string) error {
	r, err := zip.OpenReader(filePath)
	if err != nil {
		return err
	}
	defer r.Close()

	var total int64
	for _, f := range r.File {
		if !isSafePath(destDir, f.Name) {
			return fmt.Errorf("%w: %s", errZipSlip, f.Name)
		}

		target := filepath.Join(destDir, filepath.Clean(f.Name))

		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
			continue
		}

		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}

		rc, err := f.Open()
		if err != nil {
			return err
		}
		out, err := os.Create(target)
		if err != nil {
			rc.Close()
			return err
		}
		n, err := io.CopyN(out, rc, DefaultMaxSize+1)
		rc.Close()
		out.Close()
		if err != nil && err != io.EOF {
			return err
		}
		if n > DefaultMaxSize {
			return fmt.Errorf("entry %s exceeds size limit (%d bytes)", f.Name, DefaultMaxSize)
		}
		total += n
		if total > maxExtractBytes {
			return fmt.Errorf("extraction exceeds total size limit (%d bytes)", maxExtractBytes)
		}
	}
	return nil
}
