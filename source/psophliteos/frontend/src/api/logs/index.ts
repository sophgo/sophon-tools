import { defHttp } from '/@/utils/http/axios';
import { useGlobSetting } from '/@/hooks/setting';
import { getSsoTicket } from '/@/api/sso';
import { AlarmRecordParams } from './model/index';

const { apiUrl } = useGlobSetting();

enum Api {
  // ssm 审计日志端点（经 sophliteos 反代）
  OperRecord = '/v1/audit',
  // ssm 告警历史端点（经 sophliteos 反代）
  AlarmRecord = '/v1/alarms',
  // 日志下载清单：将抓取哪些日志（/var/log 顶层聚合）
  LogOverview = '/v1/logs/overview',
  // ssm 系统日志下载（流式 tar.gz 整个 /var/log）
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

// 日志下载清单项（与 bmssm /logs/overview 契约对齐）。
export interface LogOverviewEntry {
  name: string;
  path: string;
  type: 'file' | 'dir' | 'symlink';
  size: number; // 目录为递归合计；symlink 为 0
  files: number; // 目录为子项数（不含顶层自身）；文件/软链为 1
  mtime: number; // Unix 秒
}

export interface LogOverview {
  root: string;
  total_size: number;
  total_entries: number;
  entries: LogOverviewEntry[];
}

// 日志下载清单：下载前展示"将抓取哪些日志"。走 defHttp（带 Authorization 头）。
export function getLogOverview() {
  return defHttp.get<LogOverview>({ url: Api.LogOverview });
}

// 系统日志下载：原生 <a download>，浏览器流式落盘（低内存、自带下载进度条），
// 后台在设备端流式 tar+gzip，不落盘整包、不占设备存储。
// MYS-383：<a download> 无法带 Authorization 头，先以 Bearer 头换取一次性票据，
// URL 只带 ?ticket=；sophliteos 校验后改写为 ?token= 转发 bmssm，JWT 不出 URL。
export async function getLogDownloadUrl(): Promise<{ url: string; name: string }> {
  const { ticket } = await getSsoTicket();
  return {
    url: `${apiUrl}${Api.LogDownload}?ticket=${encodeURIComponent(ticket)}`,
    name: 'sys_log.tgz',
  };
}
