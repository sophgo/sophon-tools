package main

// 测试服务器上的最小 SFTP 服务端实现。
//
// 只实现本工具实际用到的子集：INIT / REALPATH / STAT / LSTAT / FSTAT /
// OPEN / READ / WRITE / CLOSE / SETSTAT。够用来跑通上传与下载两条真实路径。
//
// 协议要点：除 INIT/VERSION 外，每个响应报文的第一段必须是请求里的 id，
// 客户端靠它对号入座（漏掉会直接 panic 在 unmarshal 里）。

import (
	"encoding/binary"
	"io"
	"sync"

	"golang.org/x/crypto/ssh"
)

const (
	fxpInit     = 1
	fxpVersion  = 2
	fxpOpen     = 3
	fxpClose    = 4
	fxpRead     = 5
	fxpWrite    = 6
	fxpLstat    = 7
	fxpFstat    = 8
	fxpSetstat  = 9
	fxpRealpath = 16
	fxpStat     = 17

	fxpStatus = 101
	fxpHandle = 102
	fxpData   = 103
	fxpName   = 104
	fxpAttrs  = 105

	fxfWrite = 0x00000002
	fxfCreat = 0x00000008
	fxfTrunc = 0x00000010

	sfxOK      = 0
	sfxEOF     = 1
	sfxNoSuch  = 2
	sfxFailure = 4
)

type sftpHandle struct {
	path string
	w    bool
}

func (s *testSSHServer) serveSFTP(ch ssh.Channel) {
	var mu sync.Mutex
	handles := map[string]*sftpHandle{}
	next := 0

	for {
		typ, payload, err := readSFTPPacket(ch)
		if err != nil {
			return
		}
		if typ == fxpInit {
			// 只回版本号 3，不声明任何扩展。
			_ = writeSFTPPacket(ch, fxpVersion, u32(3))
			continue
		}

		// 所有非 INIT 报文都以 uint32 id 开头。
		if len(payload) < 4 {
			return
		}
		reqID := binary.BigEndian.Uint32(payload[:4])
		body := payload[4:]

		reply := func(t byte, b []byte) {
			_ = writeSFTPPacket(ch, t, append(u32(reqID), b...))
		}
		status := func(code uint32, msg string) {
			reply(fxpStatus, statusBody(code, msg))
		}

		switch typ {
		case fxpRealpath:
			p, _ := parseString(body)
			if p == "" || p == "." {
				p = "/"
			}
			// 只回一条「名字」记录，属性全 0（客户端不依赖）。
			reply(fxpName, nameBody(p, 0))

		case fxpStat, fxpLstat:
			p, _ := parseString(body)
			s.mu.Lock()
			data, ok := s.files[p]
			s.mu.Unlock()
			if !ok {
				status(sfxNoSuch, "no such file")
				continue
			}
			reply(fxpName, nameBody(p, int64(len(data))))

		case fxpFstat:
			hs, _ := parseString(body)
			mu.Lock()
			h := handles[hs]
			mu.Unlock()
			if h == nil {
				status(sfxFailure, "bad handle")
				continue
			}
			s.mu.Lock()
			n := int64(len(s.files[h.path]))
			s.mu.Unlock()
			// FSTAT 必须回 SSH_FXP_ATTRS，不是 NAME（客户端按类型分派）。
			reply(fxpAttrs, attrsBody(n))

		case fxpOpen:
			p, rest := parseString(body)
			if len(rest) < 4 {
				status(sfxFailure, "bad open")
				continue
			}
			flags := binary.BigEndian.Uint32(rest[:4])
			if flags&fxfCreat != 0 {
				s.mu.Lock()
				if _, ok := s.files[p]; !ok || flags&fxfTrunc != 0 {
					s.files[p] = []byte{}
				}
				s.mu.Unlock()
			}
			mu.Lock()
			next++
			hs := string(u32(uint32(next)))
			handles[hs] = &sftpHandle{path: p, w: flags&fxfWrite != 0}
			mu.Unlock()
			reply(fxpHandle, appendString(nil, []byte(hs)))

		case fxpWrite:
			hs, rest := parseString(body)
			if len(rest) < 8 {
				status(sfxFailure, "bad write")
				continue
			}
			off := binary.BigEndian.Uint64(rest[:8])
			data, _ := parseString(rest[8:])
			mu.Lock()
			h := handles[hs]
			mu.Unlock()
			if h == nil {
				status(sfxFailure, "bad handle")
				continue
			}
			s.mu.Lock()
			cur := s.files[h.path]
			end := int(off) + len(data)
			if end > len(cur) {
				grown := make([]byte, end)
				copy(grown, cur)
				cur = grown
			}
			copy(cur[off:], data)
			s.files[h.path] = cur
			s.mu.Unlock()
			status(sfxOK, "")

		case fxpRead:
			hs, rest := parseString(body)
			if len(rest) < 12 {
				status(sfxFailure, "bad read")
				continue
			}
			off := binary.BigEndian.Uint64(rest[:8])
			n := binary.BigEndian.Uint32(rest[8:12])
			mu.Lock()
			h := handles[hs]
			mu.Unlock()
			if h == nil {
				status(sfxFailure, "bad handle")
				continue
			}
			s.mu.Lock()
			data := s.files[h.path]
			s.mu.Unlock()
			if int(off) >= len(data) {
				status(sfxEOF, "eof")
				continue
			}
			endOff := int(off) + int(n)
			if endOff > len(data) {
				endOff = len(data)
			}
			reply(fxpData, appendString(nil, data[off:endOff]))

		case fxpClose:
			hs, _ := parseString(body)
			mu.Lock()
			delete(handles, hs)
			mu.Unlock()
			status(sfxOK, "")

		case fxpSetstat:
			status(sfxOK, "")

		default:
			status(sfxFailure, "unsupported")
		}
	}
}

func readSFTPPacket(r io.Reader) (byte, []byte, error) {
	var hdr [4]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		return 0, nil, err
	}
	n := binary.BigEndian.Uint32(hdr[:])
	if n == 0 || n > 1<<20 {
		return 0, nil, io.ErrUnexpectedEOF
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return 0, nil, err
	}
	return buf[0], buf[1:], nil
}

func writeSFTPPacket(w io.Writer, typ byte, payload []byte) error {
	var hdr [5]byte
	binary.BigEndian.PutUint32(hdr[:4], uint32(len(payload)+1))
	hdr[4] = typ
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	if len(payload) > 0 {
		_, err := w.Write(payload)
		return err
	}
	return nil
}

func u32(v uint32) []byte {
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, v)
	return b
}

func u64(v uint64) []byte {
	b := make([]byte, 8)
	binary.BigEndian.PutUint64(b, v)
	return b
}

func appendString(dst []byte, s []byte) []byte {
	dst = append(dst, u32(uint32(len(s)))...)
	return append(dst, s...)
}

func parseString(p []byte) (string, []byte) {
	if len(p) < 4 {
		return "", nil
	}
	n := binary.BigEndian.Uint32(p[:4])
	if int(n) > len(p)-4 {
		return "", nil
	}
	return string(p[4 : 4+n]), p[4+n:]
}

func statusBody(code uint32, msg string) []byte {
	b := u32(code)
	b = appendString(b, []byte(msg))
	b = appendString(b, nil) // language tag
	return b
}

// attrsBody SSH_FXP_ATTRS 的负载：只有 size 与权限位有效。
func attrsBody(size int64) []byte {
	b := u32(1 | 4) // flags: size | permissions
	b = append(b, u64(uint64(size))...)
	b = append(b, u32(0o644)...)
	return b
}

// nameBody 一条 NAME 记录：文件名 + 长名 + attrs(size 有效)。
func nameBody(name string, size int64) []byte {
	b := u32(1) // count
	b = appendString(b, []byte(name))
	b = appendString(b, []byte(name))
	b = append(b, u32(1)...) // attrs flags: size
	b = append(b, u64(uint64(size))...)
	b = append(b, u32(0)...) // uid
	b = append(b, u32(0)...) // gid
	b = append(b, u32(0)...) // permissions
	b = append(b, u32(0)...) // atime
	b = append(b, u32(0)...) // mtime
	b = append(b, u32(0)...) // extended count
	return b
}
