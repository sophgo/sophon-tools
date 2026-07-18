import { defHttp } from '/@/utils/http/axios';

export interface EnvIssue { check: string; message: string; fix_cmd: string; }
export interface EnvResult { ok: boolean; issues: EnvIssue[]; }
export interface StatusResult { environment: EnvResult; protectPorts: number[]; }
export interface Intent { id?: number; type: string; params: string; enabled: boolean; }
export interface DockerRule { id?: number; scene: string; params: string; enabled: boolean; }
export interface LiveRule { num: number; target: string; prot: string; in: string; out: string; src: string; dst: string; pkts: number; bytes: number; raw: string; }
export interface Risk { mode: string; description: string; }
export interface ApplyResult { token: string; risks: Risk[]; protectPorts: number[]; rollbackSeconds: number; }

enum Api {
  Status = '/v1/firewall/status',
  Intent = '/v1/firewall/intent',
  DockerUser = '/v1/firewall/docker-user',
  Raw = '/v1/firewall/raw',
  Apply = '/v1/firewall/apply',
  Confirm = '/v1/firewall/confirm',
  Rollback = '/v1/firewall/rollback',
}

export const getStatus = () => defHttp.get<StatusResult>({ url: Api.Status }, { errorMessageMode: 'none' });
export const getIntents = () => defHttp.get<Intent[]>({ url: Api.Intent });
export const addIntent = (params: Intent) => defHttp.post({ url: Api.Intent, params });
export const deleteIntent = (id: number) => defHttp.delete({ url: `${Api.Intent}/${id}` });
export const getDockerRules = () => defHttp.get<DockerRule[]>({ url: Api.DockerUser });
export const addDockerRule = (params: DockerRule) => defHttp.post({ url: Api.DockerUser, params });
export const deleteDockerRule = (id: number) => defHttp.delete({ url: `${Api.DockerUser}/${id}` });
export const getRawRules = () => defHttp.get<LiveRule[]>({ url: Api.Raw });
export const addRawRule = (params: { chain: string; args: string[] }) => defHttp.post({ url: Api.Raw, params });
export const deleteRawRule = (chain: string, num: number) => defHttp.delete({ url: `${Api.Raw}/${chain}/${num}` });

// applyFirewall 返回 RAW 信封（{code,msg,result}），不抛错。调用方据 code 判成功/风险，
// 从 result.risks 取风险列表。这样 409 风险体不会在 defHttp transformResponseHook 里
// 被吞成 new Error(msg) 而丢失结构化 risks（M6 修复）。
export interface FireEnvelope {
  code: number;
  msg?: string; // 后端 Fail 设 "请求失败"（泛化）
  message?: string;
  error_message?: string; // 后端 Fail 的具体错误信息（json: error_message）
  result?: ApplyResult;
}

// envelopeErr 取非风险失败信封里的具体错误文本（优先 error_message，回退 msg）。
export function envelopeErr(data: FireEnvelope | undefined | null): string {
  return data?.error_message || data?.msg || data?.message || '';
}

export const applyFirewall = (params: { force: boolean }) =>
  defHttp.post<FireEnvelope>({ url: Api.Apply, params }, { isTransformResponse: false, errorMessageMode: 'none' });

export const confirmApply = (params: { token: string }) => defHttp.post({ url: Api.Confirm, params });
export const rollbackApply = (params: { token: string }) => defHttp.post({ url: Api.Rollback, params });

// --- 风险信封解析（Intent/Docker 共用，去重 M6 part 2）---
// isRiskEnvelope 判 RAW 信封是否为 409 风险体（code!==0 且 result.risks 非空）。
export function isRiskEnvelope(data: FireEnvelope | undefined | null): boolean {
  return !!data && data.code !== 0 && !!data.result && Array.isArray(data.result.risks) && data.result.risks.length > 0;
}

// extractRisks 从 RAW 信封 result.risks 取风险列表。
export function extractRisks(data: FireEnvelope | undefined | null): Risk[] {
  return data?.result?.risks ?? [];
}
