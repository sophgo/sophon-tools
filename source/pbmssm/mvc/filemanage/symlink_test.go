package filemanage

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// 本文件覆盖符号链接相关的安全回归：
//   - 上传的末级组件不得是符号链接（含 dangling），否则 os.Create 会跟随链接写到
//     链接目标，绕过 ResolveWritePath 的目录校验；
//   - Delete / Rename 必须以"目录项"语义工作，只操作末级链接本身，绝不改动词链接
//     指向的目标；父目录仍需解引用并校验，保护前缀不可绕过。
// 所有用例只在 t.TempDir() 内建结构；需要"受保护目录"时用 protectDir 把临时目录
// 临时加入 readonlyPrefixes，不触碰真实系统文件。

// protectDir 在测试期间把临时目录标记为受保护（readonly）目录，测试结束自动还原。
// 注意：不要与 t.Parallel 同时使用（修改的是包级变量）。
func protectDir(t *testing.T, dir string) {
	t.Helper()
	old := readonlyPrefixes
	readonlyPrefixes = append(append([]string{}, old...), dir)
	t.Cleanup(func() { readonlyPrefixes = old })
}

// mustSymlink 创建符号链接，失败即终止测试。
func mustSymlink(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Symlink(target, link); err != nil {
		t.Fatalf("symlink %s -> %s: %v", link, target, err)
	}
}

// TestSaveUploadRejectsSymlinkToFile 上传目标名已是指向普通文件的链接：拒绝，且
// 目标文件内容不变（原实现 os.Create 会跟随链接覆盖目标）。
func TestSaveUploadRejectsSymlinkToFile(t *testing.T) {
	dir := t.TempDir()
	target := writeFile(t, dir, "target.txt", "ORIGINAL")
	link := filepath.Join(dir, "upload.txt")
	mustSymlink(t, target, link)

	svc := NewService()
	if _, _, err := svc.SaveUpload(dir, "upload.txt", strings.NewReader("PWNED")); err == nil {
		t.Fatal("expected refusal when upload target is a symlink")
	}
	got, err := os.ReadFile(target)
	if err != nil {
		t.Fatalf("target should still exist: %v", err)
	}
	if string(got) != "ORIGINAL" {
		t.Fatalf("symlink target was overwritten: %q", got)
	}
	if _, err := os.Lstat(link); err != nil {
		t.Fatalf("symlink should be left untouched: %v", err)
	}
}

// TestSaveUploadRejectsDanglingSymlink 上传目标名是 dangling 链接：拒绝，链接保留，
// 链接指向的目标仍不存在（原实现会新建出目标文件）。
func TestSaveUploadRejectsDanglingSymlink(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "not-exist.txt")
	link := filepath.Join(dir, "upload.txt")
	mustSymlink(t, target, link)

	svc := NewService()
	if _, _, err := svc.SaveUpload(dir, "upload.txt", strings.NewReader("PWNED")); err == nil {
		t.Fatal("expected refusal when upload target is a dangling symlink")
	}
	if _, err := os.Lstat(link); err != nil {
		t.Fatalf("dangling symlink should be left untouched: %v", err)
	}
	if _, err := os.Lstat(target); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("dangling symlink target must not be created: %v", err)
	}
}

// TestSaveUploadRejectsSymlinkToBlockedPath 上传目标名是指向 /dev/null 的链接
// （父 issue 的复现路径）：拒绝，且不产生写入副作用。
func TestSaveUploadRejectsSymlinkToBlockedPath(t *testing.T) {
	dir := t.TempDir()
	link := filepath.Join(dir, "devnull")
	mustSymlink(t, "/dev/null", link)

	svc := NewService()
	if _, _, err := svc.SaveUpload(dir, "devnull", strings.NewReader("0123456789abcde")); err == nil {
		t.Fatal("expected refusal when upload target links into /dev")
	}
}

// TestSaveUploadRejectsDirectorySymlink 上传目标名是指向目录的链接：拒绝，目录仍在。
func TestSaveUploadRejectsDirectorySymlink(t *testing.T) {
	dir := t.TempDir()
	realDir := filepath.Join(dir, "realdir")
	if err := os.Mkdir(realDir, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "dirlink")
	mustSymlink(t, realDir, link)

	svc := NewService()
	if _, _, err := svc.SaveUpload(dir, "dirlink", strings.NewReader("x")); err == nil {
		t.Fatal("expected refusal when upload target is a directory symlink")
	}
	if st, err := os.Stat(realDir); err != nil || !st.IsDir() {
		t.Fatalf("real dir should still exist: %v", err)
	}
}

// TestSaveUploadNormalAndOverwrite 普通文件上传行为不变：新文件可写，已存在的普通
// 文件可被覆盖，返回写入字节数。
func TestSaveUploadNormalAndOverwrite(t *testing.T) {
	dir := t.TempDir()
	svc := NewService()

	dst, n, err := svc.SaveUpload(dir, "a.txt", strings.NewReader("hello"))
	if err != nil {
		t.Fatalf("normal upload failed: %v", err)
	}
	if n != 5 || dst != filepath.Join(dir, "a.txt") {
		t.Fatalf("dst=%q n=%d", dst, n)
	}
	if got, _ := os.ReadFile(dst); string(got) != "hello" {
		t.Fatalf("content=%q", got)
	}

	if _, n, err = svc.SaveUpload(dir, "a.txt", strings.NewReader("0123456789")); err != nil {
		t.Fatalf("overwrite regular file should be allowed: %v", err)
	}
	if n != 10 {
		t.Fatalf("n=%d, want 10", n)
	}
	if got, _ := os.ReadFile(dst); string(got) != "0123456789" {
		t.Fatalf("content=%q, want overwritten", got)
	}
	st, err := os.Lstat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode()&os.ModeSymlink != 0 {
		t.Fatal("uploaded file must be a regular file, not a symlink")
	}
}

// TestSaveUploadRejectsSymlinkToProtectedDir 目标名是指向受保护目录内文件的链接：
// 同样拒绝（链接本身在可写目录，但它会让写入落到保护目录）。
func TestSaveUploadRejectsSymlinkToProtectedDir(t *testing.T) {
	protected := t.TempDir()
	protectDir(t, protected)
	target := writeFile(t, protected, "guard.txt", "KEEP")

	dir := t.TempDir()
	mustSymlink(t, target, filepath.Join(dir, "up.txt"))

	svc := NewService()
	if _, _, err := svc.SaveUpload(dir, "up.txt", strings.NewReader("PWNED")); err == nil {
		t.Fatal("expected refusal for upload through link into protected dir")
	}
	if got, _ := os.ReadFile(target); string(got) != "KEEP" {
		t.Fatalf("protected file modified: %q", got)
	}
}

// TestSaveUploadRejectsExistingDirectory 上传目标名已是目录：拒绝，目录不受影响。
func TestSaveUploadRejectsExistingDirectory(t *testing.T) {
	dir := t.TempDir()
	sub := filepath.Join(dir, "existing")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, _, err := NewService().SaveUpload(dir, "existing", strings.NewReader("x")); err == nil {
		t.Fatal("expected refusal when upload target is a directory")
	}
	if st, err := os.Stat(sub); err != nil || !st.IsDir() {
		t.Fatalf("directory must survive: %v", err)
	}
}

// TestDeleteViaSymlinkParentAllowed 父目录是链接但指向普通可写目录：解引用后正常删除。
func TestDeleteViaSymlinkParentAllowed(t *testing.T) {
	root := t.TempDir()
	realDir := filepath.Join(root, "real")
	if err := os.Mkdir(realDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, realDir, "a.txt", "x")
	mustSymlink(t, realDir, filepath.Join(root, "dirlink"))

	if err := NewService().Delete(filepath.Join(root, "dirlink", "a.txt")); err != nil {
		t.Fatalf("delete through normal dir symlink should work: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(realDir, "a.txt")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("file should be gone: %v", err)
	}
}

// TestRenameSourceViaSymlinkParentBlocked 源路径父目录链接指向受保护目录：拒绝，
// 受保护目录内文件不得被移走。
func TestRenameSourceViaSymlinkParentBlocked(t *testing.T) {
	protected := t.TempDir()
	protectDir(t, protected)
	guard := writeFile(t, protected, "guard.txt", "KEEP")

	dir := t.TempDir()
	mustSymlink(t, protected, filepath.Join(dir, "guardlink"))

	err := NewService().Rename(filepath.Join(dir, "guardlink", "guard.txt"), filepath.Join(dir, "stolen.txt"))
	if err == nil {
		t.Fatal("expected refusal to move file out of symlinked protected parent")
	}
	if _, serr := os.Stat(guard); serr != nil {
		t.Fatalf("protected file must stay: %v", serr)
	}
	if _, serr := os.Stat(filepath.Join(dir, "stolen.txt")); !errors.Is(serr, os.ErrNotExist) {
		t.Fatalf("destination must not be created: %v", serr)
	}
}

// TestResolveEntryRejectsEmpty 空路径拒绝，不把家目录当成删除目标。
func TestResolveEntryRejectsEmpty(t *testing.T) {
	if err := NewService().Delete("   "); err == nil {
		t.Fatal("expected refusal for blank path")
	}
}

type errReader struct{ err error }

func (e errReader) Read(p []byte) (int, error) { return 0, e.err }

// TestSaveUploadWriteErrorNotSuccess 读取/写入失败必须返回错误，不得报成功。
func TestSaveUploadWriteErrorNotSuccess(t *testing.T) {
	dir := t.TempDir()
	svc := NewService()
	dst, _, err := svc.SaveUpload(dir, "bad.txt", errReader{err: errors.New("boom")})
	if err == nil {
		t.Fatalf("write failure reported as success (dst=%q)", dst)
	}
	if !strings.Contains(err.Error(), "boom") {
		t.Fatalf("err=%v, want wrapped reader error", err)
	}
}

// TestDeleteSymlinkKeepsTarget 删除指向普通文件的链接：链接消失，目标文件保留。
func TestDeleteSymlinkKeepsTarget(t *testing.T) {
	dir := t.TempDir()
	target := writeFile(t, dir, "target.txt", "KEEP")
	link := filepath.Join(dir, "link.txt")
	mustSymlink(t, target, link)

	if err := NewService().Delete(link); err != nil {
		t.Fatalf("delete symlink: %v", err)
	}
	if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("symlink should be gone: %v", err)
	}
	if got, err := os.ReadFile(target); err != nil || string(got) != "KEEP" {
		t.Fatalf("target must be untouched: content=%q err=%v", got, err)
	}
}

// TestDeleteDanglingSymlink 删除 dangling 链接：成功，且不报 stat 失败。
func TestDeleteDanglingSymlink(t *testing.T) {
	dir := t.TempDir()
	link := filepath.Join(dir, "dangling")
	mustSymlink(t, filepath.Join(dir, "missing.txt"), link)

	if err := NewService().Delete(link); err != nil {
		t.Fatalf("delete dangling symlink: %v", err)
	}
	if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("dangling symlink should be gone: %v", err)
	}
}

// TestDeleteDirectorySymlink 删除指向目录的链接：删链接本身，真实目录保留。
func TestDeleteDirectorySymlink(t *testing.T) {
	dir := t.TempDir()
	realDir := filepath.Join(dir, "realdir")
	if err := os.Mkdir(realDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, realDir, "inner.txt", "KEEP")
	link := filepath.Join(dir, "dirlink")
	mustSymlink(t, realDir, link)

	if err := NewService().Delete(link); err != nil {
		t.Fatalf("delete directory symlink: %v", err)
	}
	if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("dir symlink should be gone: %v", err)
	}
	if st, err := os.Stat(realDir); err != nil || !st.IsDir() {
		t.Fatalf("real dir must be untouched: %v", err)
	}
	if got, err := os.ReadFile(filepath.Join(realDir, "inner.txt")); err != nil || string(got) != "KEEP" {
		t.Fatalf("inner file must be untouched: %q %v", got, err)
	}
}

// TestDeleteRealDirectoryRefused 真实目录仍不可删除（护栏不放宽）。
func TestDeleteRealDirectoryRefused(t *testing.T) {
	dir := t.TempDir()
	sub := filepath.Join(dir, "sub")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	err := NewService().Delete(sub)
	if err == nil {
		t.Fatal("expected refusal to delete real directory")
	}
	if !strings.Contains(err.Error(), "directory") {
		t.Fatalf("err=%v, want directory refusal", err)
	}
	if st, serr := os.Stat(sub); serr != nil || !st.IsDir() {
		t.Fatalf("directory must still exist: %v", serr)
	}
}

// TestDeleteViaSymlinkParentBlocked 父目录是符号链接且指向受保护目录：拒绝，
// 且受保护目录内的文件不受影响。
func TestDeleteViaSymlinkParentBlocked(t *testing.T) {
	protected := t.TempDir()
	protectDir(t, protected)
	guard := writeFile(t, protected, "guard.txt", "KEEP")

	dir := t.TempDir()
	mustSymlink(t, protected, filepath.Join(dir, "guardlink"))

	err := NewService().Delete(filepath.Join(dir, "guardlink", "guard.txt"))
	if err == nil {
		t.Fatal("expected refusal to delete through symlinked protected parent")
	}
	if _, serr := os.Stat(guard); serr != nil {
		t.Fatalf("protected file must survive: %v", serr)
	}
}

// TestDeleteViaSymlinkParentIntoBlocked 父目录链接指向 /dev：拒绝。
func TestDeleteViaSymlinkParentIntoBlocked(t *testing.T) {
	dir := t.TempDir()
	mustSymlink(t, "/dev", filepath.Join(dir, "devlink"))
	if err := NewService().Delete(filepath.Join(dir, "devlink", "null")); err == nil {
		t.Fatal("expected refusal to delete through link into /dev")
	}
}

// TestRenameSymlinkMovesLinkOnly 重命名链接：移动的是链接本身，目标文件保持原位。
func TestRenameSymlinkMovesLinkOnly(t *testing.T) {
	dir := t.TempDir()
	target := writeFile(t, dir, "target.txt", "KEEP")
	link := filepath.Join(dir, "link.txt")
	mustSymlink(t, target, link)
	newLink := filepath.Join(dir, "moved.txt")

	if err := NewService().Rename(link, newLink); err != nil {
		t.Fatalf("rename symlink: %v", err)
	}
	if _, err := os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("old link should be gone: %v", err)
	}
	st, err := os.Lstat(newLink)
	if err != nil || st.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("moved entry should still be a symlink: %v", err)
	}
	if got, err := os.ReadFile(target); err != nil || string(got) != "KEEP" {
		t.Fatalf("target must be untouched: content=%q err=%v", got, err)
	}
	if read, err := os.ReadFile(newLink); err != nil || string(read) != "KEEP" {
		t.Fatalf("moved link should still point at target: %q %v", read, err)
	}
}

// TestRenameOntoExistingSymlinkKeepsReferent 重命名到已存在的链接名上：覆盖链接本身，
// 绝不改动其指向的目标文件。
func TestRenameOntoExistingSymlinkKeepsReferent(t *testing.T) {
	dir := t.TempDir()
	target := writeFile(t, dir, "target.txt", "KEEP")
	link := filepath.Join(dir, "link.txt")
	mustSymlink(t, target, link)
	src := writeFile(t, dir, "src.txt", "SRC")

	if err := NewService().Rename(src, link); err != nil {
		t.Fatalf("rename onto symlink: %v", err)
	}
	if got, err := os.ReadFile(target); err != nil || string(got) != "KEEP" {
		t.Fatalf("referent must be untouched: content=%q err=%v", got, err)
	}
	st, err := os.Lstat(link)
	if err != nil {
		t.Fatalf("destination should exist: %v", err)
	}
	if st.Mode()&os.ModeSymlink != 0 {
		t.Fatal("destination should now be the renamed regular file")
	}
	if got, _ := os.ReadFile(link); string(got) != "SRC" {
		t.Fatalf("destination content=%q", got)
	}
}

// TestRenameViaSymlinkParentBlocked 目标父目录是符号链接且指向受保护目录：拒绝，
// 受保护目录内不出现新文件。
func TestRenameViaSymlinkParentBlocked(t *testing.T) {
	protected := t.TempDir()
	protectDir(t, protected)

	dir := t.TempDir()
	src := writeFile(t, dir, "src.txt", "SRC")
	mustSymlink(t, protected, filepath.Join(dir, "guardlink"))

	err := NewService().Rename(src, filepath.Join(dir, "guardlink", "moved.txt"))
	if err == nil {
		t.Fatal("expected refusal to move into symlinked protected parent")
	}
	if _, serr := os.Stat(filepath.Join(protected, "moved.txt")); !errors.Is(serr, os.ErrNotExist) {
		t.Fatalf("protected dir must not receive the file: %v", serr)
	}
	if got, _ := os.ReadFile(src); string(got) != "SRC" {
		t.Fatalf("source must be untouched: %q", got)
	}
}

// TestRenameRegularFileUnchanged 普通文件重命名行为不变。
func TestRenameRegularFileUnchanged(t *testing.T) {
	dir := t.TempDir()
	src := writeFile(t, dir, "a.txt", "hi")
	dst := filepath.Join(dir, "b.txt")
	if err := NewService().Rename(src, dst); err != nil {
		t.Fatalf("rename regular file: %v", err)
	}
	if got, err := os.ReadFile(dst); err != nil || string(got) != "hi" {
		t.Fatalf("dst content=%q err=%v", got, err)
	}
	if _, err := os.Lstat(src); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("src should be gone: %v", err)
	}
}

// TestDeleteRegularFileUnchanged 普通文件删除行为不变。
func TestDeleteRegularFileUnchanged(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "a.txt", "x")
	if err := NewService().Delete(p); err != nil {
		t.Fatalf("delete regular file: %v", err)
	}
	if _, err := os.Lstat(p); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("file should be gone: %v", err)
	}
}
