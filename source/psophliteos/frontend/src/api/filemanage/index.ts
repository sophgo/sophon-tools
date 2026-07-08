import { defHttp } from '/@/utils/http/axios';
import { getToken } from '/@/utils/auth';
import { useGlobSetting } from '/@/hooks/setting';

const { apiUrl } = useGlobSetting();

export interface FileInfo {
  name: string;
  size: number;
  mode: string;
  modTime: number;
  isDir: boolean;
  owner: string;
  group: string;
}

enum Api {
  List = '/v1/files',
  Content = '/v1/files/content',
  Download = '/v1/files/download',
  Upload = '/v1/files/upload',
  Chmod = '/v1/files/chmod',
  Chown = '/v1/files/chown',
  Mkdir = '/v1/files/mkdir',
  Rename = '/v1/files/rename',
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// 统一解析 ssm 信封响应，失败时抛出 error_message
function parseSsmEnvelope(data: any, fallback: string) {
  if (data && Reflect.has(data, 'code')) {
    if (data.code === 0) return data.result;
    const msg = data.error_message || data.msg || data.message || fallback;
    throw new Error(msg);
  }
  return data;
}

// 列目录：GET /v1/files?path=
export function listFiles(path?: string) {
  return defHttp.get<{ path: string; files: FileInfo[] }>({
    url: Api.List,
    params: { path },
  });
}

// 查看文件内容：GET /v1/files/content?path=
export function getContent(path: string) {
  return defHttp.get<{ content: string }>({
    url: Api.Content,
    params: { path },
  });
}

// 下载：原生 <a download>，浏览器流式落盘（低内存，浏览器自带下载进度条）。
// token 走 query（<a download> 无法带 Authorization 头），后端 /files/download 支持 query token。
// 不再用 XHR responseType=blob，避免把整个文件缓冲进浏览器内存。
export function downloadFile(path: string): { url: string; name: string } {
  const token = getToken();
  const name = path.split('/').pop() || 'download';
  const url = `${apiUrl}${Api.Download}?path=${encodeURIComponent(path)}&token=${encodeURIComponent(
    token || '',
  )}`;
  return { url, name };
}

// 上传：XHR multipart + onUploadProgress 流式回调
export function uploadFile(
  path: string,
  file: File,
  onUploadProgress?: (loaded: number, total: number) => void,
): Promise<{ path: string; size: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = `${apiUrl}${Api.Upload}?path=${encodeURIComponent(path)}`;
    const fd = new FormData();
    fd.append('file', file);
    xhr.open('POST', url, true);
    const headers = authHeaders();
    Object.keys(headers).forEach((k) => xhr.setRequestHeader(k, headers[k]));
    if (onUploadProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onUploadProgress(e.loaded, e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          const result = parseSsmEnvelope(data, 'upload failed');
          resolve(result || { path, size: file.size });
        } catch (e) {
          reject(e instanceof Error ? e : new Error('upload parse error'));
        }
      } else {
        reject(new Error('upload failed: ' + xhr.status));
      }
    };
    xhr.onerror = () => reject(new Error('upload network error'));
    xhr.send(fd);
  });
}

export function chmod(path: string, mode: string) {
  return defHttp.post({ url: Api.Chmod, params: { path, mode } });
}

export function chown(path: string, owner: string, group: string) {
  return defHttp.post({ url: Api.Chown, params: { path, owner, group } });
}

export function mkdir(path: string) {
  return defHttp.post({ url: Api.Mkdir, params: { path } });
}

export function renameFile(oldPath: string, newPath: string) {
  return defHttp.post({ url: Api.Rename, params: { oldPath, newPath } });
}

// 删除：DELETE /v1/files?path=<abs>
// ssm 后端只接受 query 上的 path（删文件成功，删目录拒绝）。
// 注意：不能用 defHttp.delete + params，因为 defHttp 的 transform 会把
// 非空 params 塞进 request body，后端读不到 path，会回退成"删除根目录"被拒绝。
// 改用 fetch 直接拼 query（encodeURIComponent，与 upload/download 一致）。
export async function deleteFile(path: string): Promise<{ ok: boolean }> {
  const url = `${apiUrl}${Api.List}?path=${encodeURIComponent(path)}`;
  const resp = await fetch(url, { method: 'DELETE', headers: authHeaders() });
  let data: any = null;
  try {
    data = await resp.json();
  } catch {
    /* ignore */
  }
  if (!resp.ok) {
    const msg = data?.error_message || data?.msg || `delete failed: ${resp.status}`;
    throw new Error(msg);
  }
  return parseSsmEnvelope(data, 'delete failed');
}
