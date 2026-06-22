package httpclient

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"

	"strings"
	"time"

	"sophliteos/logger"
)

var (
	client *http.Client
)

func init() {
	client = &http.Client{
		Transport: &http.Transport{
			Dial: (&net.Dialer{
				Timeout: 3 * time.Second,
			}).Dial,
			DisableKeepAlives: true,
			IdleConnTimeout:   60 * time.Second,
		},
		Timeout: 60 * time.Second,
	}
}

func NewRequest(url string, method string, header map[string]string, content []byte) ([]byte, error) {
	var body io.Reader
	if len(content) != 0 {
		body = bytes.NewBuffer(content)
	} else {
		body = nil
	}
	req, err := http.NewRequest(method, urlBuild(url), body)
	if err != nil {
		logger.Error("构建请求失败：%s，%v", err, request)
		panic(err)
	}
	trace := fmt.Sprintf("请求地址：%s，方法：%s，参数：%s", url, method, string(content))
	return request(req, header, trace)
}

func NewMultiFileRequest(url, method string, header, params map[string]string, filename string, data []byte) ([]byte, error) {
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		return nil, err
	}
	_, err = part.Write(data)
	for key, val := range params {
		_ = writer.WriteField(key, val)
	}
	err = writer.Close()
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest(method, urlBuild(url), body)
	if err != nil {
		return nil, err
	}
	req.Header.Add("Content-Type", writer.FormDataContentType())
	trace := fmt.Sprintf("请求地址：%s，方法：%s，参数：%v，文件：%s", url, method, params, filename)
	return request(req, header, trace)
}

func urlBuild(url string) string {
	if !strings.HasPrefix(url, "http://") || !strings.HasPrefix(url, "https://") {
		url = "http://" + url
	}
	return url
}

func request(req *http.Request, header map[string]string, trace string) ([]byte, error) {

	if len(header) != 0 {
		for key, value := range header {
			req.Header.Add(key, value)
		}
	}

	resp, err := client.Do(req)
	if err != nil {
		logger.Error("发送请求失败：%s，%s", trace, err)
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		if err == nil {
			logger.Error("请求失败：%d，%s，响应：%s", resp.StatusCode, trace, string(respBody))
			return nil, errors.New(resp.Status + " " + string(respBody))
		} else {
			logger.Error("请求失败：%d，%s，响应：-", resp.StatusCode, trace)
			return nil, err
		}
	} else {
		if err != nil {
			logger.Error("请求失败：%d，%s，响应：-", resp.StatusCode, trace)
			return nil, err
		}
		return respBody, nil
	}
}
