import { defHttp } from '/@/utils/http/axios';

// 端点对齐 bmssm /api/v1/systemd/* 与 /api/v1/ports/*（经 sophliteos 反代，defHttp 自动加 /api 前缀 + Authorization 头）
enum Api {
  ServiceList = '/v1/systemd/services',
  ServiceDetail = '/v1/systemd/services/{name}',
  ServiceAction = '/v1/systemd/services/{name}/action',
  DaemonReload = '/v1/systemd/daemon-reload',
  BootReport = '/v1/systemd/boot-report',
  BootReportExport = '/v1/systemd/boot-report/export',
  ListeningPorts = '/v1/ports/listening',
}

export interface ServiceInfo {
  name: string;
  description: string;
  load_state: string;
  active_state: string;
  sub_state: string;
  enabled_state: string;
  protected: boolean;
}
export interface ServiceDetail {
  name: string;
  load_state: string;
  active_state: string;
  sub_state: string;
  main_pid: string;
  exec_start: string;
  fragment_path: string;
  unit_file: string;
  status_text: string;
  protected: boolean;
}
export interface BlameItem {
  time: number;
  unit: string;
}
export interface BootReport {
  total_seconds: number;
  kernel_seconds: number;
  userspace_seconds: number;
  blame: BlameItem[];
  critical_chain: string;
}
export interface ListeningSocket {
  proto: string;
  local_ip: string;
  local_port: number;
  pid: number;
  process: string;
  cmdline: string;
  inode: number;
}

function nameUrl(api: string, name: string) {
  return api.replace('{name}', encodeURIComponent(name));
}

export function getServices() {
  return defHttp.get<ServiceInfo[]>({ url: Api.ServiceList });
}
export function getServiceDetail(name: string) {
  return defHttp.get<ServiceDetail>({ url: nameUrl(Api.ServiceDetail, name) });
}
export function postServiceAction(name: string, action: string) {
  return defHttp.post({ url: nameUrl(Api.ServiceAction, name), data: { action } });
}
export function postDaemonReload() {
  return defHttp.post({ url: Api.DaemonReload });
}
export function getBootReport() {
  return defHttp.get<BootReport>({ url: Api.BootReport });
}
// 导出启动报告：text/svg 均为文本，走 defHttp text + isTransformResponse:false，再 Blob 触发下载。
export async function exportBootReport(format: 'text' | 'svg') {
  const text = await defHttp.get<string>(
    { url: Api.BootReportExport, params: { format }, responseType: 'text' },
    { isTransformResponse: false },
  );
  const type = format === 'svg' ? 'image/svg+xml' : 'text/plain;charset=utf-8';
  const ext = format === 'svg' ? 'svg' : 'txt';
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `boot-report.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
export function getListeningPorts(proto?: 'tcp' | 'udp') {
  return defHttp.get<ListeningSocket[]>({ url: Api.ListeningPorts, params: proto ? { proto } : {} });
}
