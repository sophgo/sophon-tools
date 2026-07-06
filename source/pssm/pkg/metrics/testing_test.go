package metrics

import (
	"errors"
	"os"
)

// --- 测试用 FileReader fakes ---

// fakeFileReader 返回 files 中预置的内容；缺失返回 os.ErrNotExist。
type fakeFileReader struct {
	files map[string]string
	err   error // 若非 nil，所有读取返回此错误
	calls map[string]int
}

func (f *fakeFileReader) ReadFile(path string) ([]byte, error) {
	if f.calls == nil {
		f.calls = map[string]int{}
	}
	f.calls[path]++
	if f.err != nil {
		return nil, f.err
	}
	if v, ok := f.files[path]; ok {
		return []byte(v), nil
	}
	return nil, os.ErrNotExist
}

// seqFileReader 对同一路径按调用顺序返回 seq 中预置的多份内容，
// 用于 /proc/stat 双采样测试。
type seqFileReader struct {
	seq map[string][]string
	idx map[string]int
}

func (f *seqFileReader) ReadFile(path string) ([]byte, error) {
	if f.idx == nil {
		f.idx = map[string]int{}
	}
	list := f.seq[path]
	i := f.idx[path]
	if i >= len(list) {
		return nil, os.ErrNotExist
	}
	f.idx[path] = i + 1
	return []byte(list[i]), nil
}

// --- 测试用 CmdRunner fake ---

type cmdResp struct {
	out string
	err error
}

// errSome 测试用通用错误。
var errSome = errors.New("some error")

// fakeCmdRunner 按 name 返回 responses 中预置的输出。
type fakeCmdRunner struct {
	responses map[string]cmdResp // keyed by command name
	calls     []string
}

func (f *fakeCmdRunner) Run(name string, args ...string) (string, error) {
	f.calls = append(f.calls, name)
	if r, ok := f.responses[name]; ok {
		return r.out, r.err
	}
	return "", errors.New("not mocked: " + name)
}
