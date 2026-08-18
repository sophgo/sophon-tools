import { defHttp } from '/@/utils/http/axios';

export interface EnvIssue { check: string; message: string; fix_cmd: string; }
export interface EnvResult { ok: boolean; issues: EnvIssue[]; }
export interface StatusResult { environment: EnvResult; protectPorts: number[]; }
export interface Intent { id?: number; type: string; params: string; enabled: boolean; }
export interface HazardChallenge { code: string; expiresInSecs: number; }

enum Api {
  Status = '/v1/firewall/status',
  Intent = '/v1/firewall/intent',
  Rebuild = '/v1/firewall/rebuild',
  Challenge = '/v1/hazard/challenge',
}

export const getStatus = () => defHttp.get<StatusResult>({ url: Api.Status }, { errorMessageMode: 'none' });
export const getIntents = () => defHttp.get<Intent[]>({ url: Api.Intent });
export const addIntent = (params: Intent) => defHttp.post({ url: Api.Intent, params });
export const deleteIntent = (id: number) => defHttp.delete({ url: `${Api.Intent}/${id}` });
// 高危操作二次确认（MYS-389）：rebuild 前须先取一次性确认码，再携带 confirm 调用。
export const getHazardChallenge = () => defHttp.get<HazardChallenge>({ url: Api.Challenge });
export const rebuildFirewall = (confirm: string) => defHttp.post({ url: Api.Rebuild, params: { confirm } });
