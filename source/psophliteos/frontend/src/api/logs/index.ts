import { defHttp } from '/@/utils/http/axios';
import { getToken } from '/@/utils/auth';
import { useGlobSetting } from '/@/hooks/setting';
import { AlarmRecordParams } from './model/index';

const { apiUrl } = useGlobSetting();

enum Api {
  // ssm 审计日志端点（经 sophliteos 反代）
  OperRecord = '/v1/audit',
  // ssm 告警历史端点（经 sophliteos 反代）
  AlarmRecord = '/v1/alarms',
  // ssm 系统日志下载（流式 tar.gz: /var/log/kern* + syslog*）
  LogDownload = '/v1/logs/download',
}

// ssm /v1/alarms 分页参数对齐 audit：pageNo/pageSize + componentType 过滤。
// ssm 返回 {total, items:[]}，useTable 期望 {items, total}，映射（参考 getOperRecord）。
export function getAlarmRecord(params: AlarmRecordParams) {
  return defHttp.get({ url: Api.AlarmRecord, params }).then((res) => ({
    items: res?.items || res?.logs || [],
    total: res?.total || 0,
  }));
}

export function getOperRecord(params: AlarmRecordParams) {
  // ssm audit 分页参数对齐：pageNo/pageSize
  // ssm 返回 {total, logs:[]}，useTable 期望 {items, total}，映射。
  return defHttp.get({ url: Api.OperRecord, params }).then((res) => ({
    items: res?.logs || [],
    total: res?.total || 0,
  }));
}

// 系统日志下载：GET /v1/logs/download，ssm 端流式打包 tar.gz（kern*+syslog*），
// 浏览器收 blob 后触发下载。返回 {data:Blob, headers} 供视图取 content-disposition。
export async function LogDownload(): Promise<{ data: Blob; headers: Record<string, string> }> {
  const token = getToken();
  const resp = await fetch(`${apiUrl}${Api.LogDownload}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    throw new Error(`log download failed: ${resp.status}`);
  }
  const data = await resp.blob();
  const headers: Record<string, string> = {};
  resp.headers.forEach((v, k) => (headers[k.toLowerCase()] = v));
  return { data, headers };
}
