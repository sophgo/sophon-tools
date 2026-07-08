import { defHttp } from '/@/utils/http/axios';
import { useGlobSetting } from '/@/hooks/setting';

import {
  IpSetParams,
  AlarmParams,
  RollbackParams,
  UploadApiResult,
} from './model/index';
import { BasicApiResponse } from '../model/baseModel';

const { uploadUrl = '' } = useGlobSetting();

// 端点对齐 ssm /api/v1/*（经 sophliteos 反代同源访问）
enum Api {
  IpSet = '/v1/network/ip', // ssm PUT（静态/DHCP）/ GET（返回 []NetCard）
  Alarm = '/v1/device/configure/alarm', // GET / POST
  Upgrade = '/v1/ota/workflow', // upgradeStatusApi GET
  Rollback = '/v1/ota/rollback',
  SysTables = '/v1/network/nat', // GET 返回 []string（iptables 行）
  deleteUserIp = '/v1/network/nat', // DELETE /:num
  addUserIp = '/v1/network/nat', // POST
  getComIP = '/v1/device/basic',
  modComIP = '/v1/device/configure/basic',
}

// IP地址设置（ssm PUT /network/ip，参数映射）
export function ipSet(params: IpSetParams) {
  const body = {
    device: params.device,
    policy: params.ipType === 2 ? 'dhcp' : 'static',
    ip: params.ip,
    mask: params.subnetMask,
    gateway: params.gateway,
    dns: params.dns,
  };
  return defHttp.put<BasicApiResponse>({ url: Api.IpSet, params: body }, { isTransformResponse: false });
}

// IP地址查询（ssm GET /network/ip 返 []NetCard，字段 ip/netMask/gateway/dns/dynamic）
export function ipGet() {
  return defHttp.get({ url: Api.IpSet }).then((res) => {
    const netCard = Array.isArray(res) ? res : res?.result || [];
    return Array.isArray(netCard) ? netCard : [];
  });
}

// 告警阈值设置
export function setAlarm(params: AlarmParams) {
  return defHttp.post<BasicApiResponse>({ url: Api.Alarm, params });
}

// 告警阈值查询
export function getAlarm() {
  return defHttp.get({ url: Api.Alarm });
}

// OTA 升级包上传（ssm POST /ota/upload，multipart）
export function upgradeApi(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/v1/ota/upload',
      onUploadProgress,
      timeout: 1000 * 60 * 15,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isReturnNativeResponse: true,
      },
    },
    params,
  );
}

// 本地 sophliteos 已上传升级包文件列表（保留本地端点 /api/device/ota/list，
// 返回 {ctrlName, ctrlMd5, coreName, coreMd5}）
export function checkFileList() {
  return defHttp.get({ url: '/device/ota/list' });
}

// 本地 sophliteos 升级包文件列表（保留本地端点 /api/device/ota/list）
export function checkFile(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/device/ota/file',
      onUploadProgress,
      timeout: 1000 * 60 * 60 * 24,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isTransformResponse: false,
      },
    },
    params,
  );
}

// 本地 sophliteos 分片上传（保留本地端点 /api/device/ota/chunked）
export function uploadPartFile(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/device/ota/chunked',
      onUploadProgress,
      timeout: 1000 * 60 * 5,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isTransformResponse: false,
        errorMessageMode: 'none',
        retryRequest: {
          isOpenRetry: true,
          count: 2,
          waitTime: 100,
        },
      },
    },
    params,
  );
}

// 软件升级（本地 sophliteos /api/upgrade，保留）
export function upgradeSoftApi(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/upgrade',
      onUploadProgress,
      timeout: 1000 * 60 * 15,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isReturnNativeResponse: true,
      },
    },
    params,
  );
}


// OTA 升级状态
export function upgradeStatusApi() {
  return defHttp.get({ url: Api.Upgrade });
}

// OTA 回滚（ssm POST /ota/rollback）
export function rollbackApi(params: RollbackParams) {
  return defHttp.post({ url: Api.Rollback, params });
}


// 解析 iptables 行（ssm GET /network/nat 返回 []string）
// 形如 "[2] DNAT tcp -- 0.0.0.0/0 0.0.0.0/0 tcp dpt:80 to:192.168.1.10:8080"
export interface NatRow {
  key: string;
  num: string;
  target: string;
  protocol: string;
  sourceIP: string;
  sourcePort: string;
  destIp: string;
  destPort: string;
  raw: string;
}

export function parseNatLines(lines: string[]): NatRow[] {
  if (!Array.isArray(lines)) return [];
  return lines
    .map((line, idx) => {
      const raw = String(line || '');
      // 提取开头 [num]
      const numMatch = raw.match(/^\s*\[?(\d+)\]?\s*/);
      const num = numMatch ? numMatch[1] : String(idx);
      const rest = raw.replace(/^\s*\[?\d+\]?\s*/, '');
      const parts = rest.split(/\s+/).filter(Boolean);
      const target = parts[0] || '';
      const protocol = parts.find((p) => /^(tcp|udp|icmp|all)$/i.test(p)) || '';
      // dpt:80 / to:1.2.3.4:5
      const dptMatch = raw.match(/dpt:(\d+)/);
      const toMatch = raw.match(/to:([0-9.]+):?(\d+)?/);
      return {
        key: num,
        num,
        target,
        protocol,
        sourceIP: '',
        sourcePort: '',
        destIp: toMatch ? toMatch[1] : '',
        destPort: (dptMatch && dptMatch[1]) || (toMatch && toMatch[2]) || '',
        raw,
      };
    });
}

// ssm GET /network/nat 返回 []string（iptables 行），解析成 NatRow 数组
function fetchNatRows(): Promise<NatRow[]> {
  return defHttp
    .get({ url: Api.SysTables })
    .then((res) => {
      let lines: string[] = [];
      if (Array.isArray(res)) lines = res;
      else if (Array.isArray(res?.result)) lines = res.result;
      else if (Array.isArray(res?.items)) lines = res.items;
      else if (Array.isArray(res?.sysTables)) lines = res.sysTables;
      return parseNatLines(lines);
    })
    .catch(() => [] as NatRow[]);
}

export function getSysTables() {
  return fetchNatRows();
}

export function getUserTables() {
  return fetchNatRows();
}

// 删除 NAT 规则（ssm DELETE /network/nat/:num）
export function DeleteUserTables(params: any) {
  const num = params?.num ?? params?.key ?? params;
  return defHttp.delete({ url: `${Api.deleteUserIp}/${num}` });
}

// 新增 NAT 规则（ssm POST /network/nat）
export function addUserMap(params: any) {
  return defHttp.post({ url: Api.addUserIp, params });
}

export function getComIP() {
  return defHttp.get({ url: Api.getComIP }).then((res) => {
    return res?.configure ?? res;
  });
}

// 修改设备基础信息（ssm POST /device/configure/basic）
export function modComIP(params: any) {
  return defHttp.post({ url: Api.modComIP, params });
}

// 执行 OTA 升级（ssm POST /ota/upgrade）
export function executeUpgradeApi(params: any) {
  return defHttp.post({ url: '/v1/ota/upgrade', params });
}

// 远程单条命令执行（ssm POST /hardware/exec）
export function execApi(params: { command: string; timeout?: number }) {
  return defHttp.post({ url: '/v1/hardware/exec', params });
}

// 硬件重启 / 关机（ssm POST /hardware/reboot | /hardware/shutdown）
export function rebootApi() {
  return defHttp.post({ url: '/v1/hardware/reboot' });
}
export function shutdownApi() {
  return defHttp.post({ url: '/v1/hardware/shutdown' });
}

