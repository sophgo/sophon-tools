import { defHttp } from '/@/utils/http/axios';

// Agent 配置相关接口。
// - LLM 配置 + 转发 key 管理：走 bmssm /api/v1/llm-proxy/*（经 sophliteos 反代）
// - Service 状态/启停：bmssm agentproxy 托管 Reasonix（/api/v1/llm-proxy/service/*）
// defHttp 自动加 /api 前缀。
enum Api {
  LlmProxyConfig = '/v1/llm-proxy/config',
  LlmProxyTest = '/v1/llm-proxy/test',
  ServiceStatus = '/v1/llm-proxy/service/status',
  ServiceAction = '/v1/llm-proxy/service/action',
}

export interface TestResult {
  name: string;
  ok: boolean;
  message: string;
}

export interface TestResponse {
  results: TestResult[];
  allOk: boolean;
}

export interface AgentConfig {
  llmApiBase: string;
  llmModel: string;
  llmEnabled: boolean;
  llmOverrideModel: boolean;
  llmHasKey: boolean;
  forwardKey?: string;
  updatedAt?: string;
}

// 读取已存配置（bmssm）；无则返回 null。
export async function getAgentConfig(): Promise<AgentConfig | null> {
  try {
    const res = await defHttp.get<AgentConfig>(
      { url: Api.LlmProxyConfig },
      { isTransformResponse: false },
    );
    const data = (res as any)?.result ?? res;
    return data && typeof data === 'object' && 'llmApiBase' in data ? (data as AgentConfig) : null;
  } catch {
    return null;
  }
}

// 保存 LLM 配置（key 为空表示不修改）。
export async function saveAgentConfig(cfg: {
  llmApiBase: string;
  llmApiKey: string;
  llmModel: string;
  llmEnabled: boolean;
  llmOverrideModel: boolean;
}): Promise<{ ok: boolean; message?: string }> {
  try {
    const res = await defHttp.put(
      { url: Api.LlmProxyConfig, data: cfg },
      { isTransformResponse: false },
    );
    const data = (res as any)?.result ?? res;
    if (data && typeof data === 'object' && 'llmApiBase' in data) {
      return { ok: true };
    }
    return { ok: false, message: (res as any)?.error_message || (res as any)?.msg || '保存失败' };
  } catch (e: any) {
    return { ok: false, message: e?.message || '保存失败' };
  }
}

// 一键测试：带图分发 + LLM 推理。
export async function testAgentConfig(): Promise<{
  ok: boolean;
  data?: TestResponse;
  message?: string;
}> {
  try {
    const res = await defHttp.post<TestResponse>(
      { url: Api.LlmProxyTest },
      { isTransformResponse: false },
    );
    const data = (res as any)?.result ?? res;
    if (data && typeof data === 'object' && 'allOk' in data) {
      return { ok: true, data: data as TestResponse };
    }
    return { ok: false, message: (res as any)?.error_message || '测试失败' };
  } catch (e: any) {
    return { ok: false, message: e?.message || '测试失败' };
  }
}

export interface ServiceStatus {
  active: boolean;
  running: boolean;
  healthy?: boolean;
  enabledState?: string;
  sessionCount?: number;
}

// 查询 Reasonix（agentproxy 托管）服务状态。
export async function getServiceStatus(): Promise<ServiceStatus | null> {
  try {
    const res = await defHttp.get<ServiceStatus>(
      { url: Api.ServiceStatus },
      { isTransformResponse: false },
    );
    const data = (res as any)?.result ?? res;
    return data && typeof data === 'object' && 'active' in data ? (data as ServiceStatus) : null;
  } catch {
    return null;
  }
}

// 对 Reasonix（agentproxy 托管）执行操作（start/stop/restart）。
export async function serviceAction(action: string): Promise<{ ok: boolean; message?: string }> {
  try {
    const res = await defHttp.post(
      { url: Api.ServiceAction, data: { action } },
      { isTransformResponse: false },
    );
    const data = (res as any)?.result ?? res;
    if (data && typeof data === 'object' && data.message) {
      return { ok: true, message: data.message };
    }
    return { ok: false, message: (res as any)?.error_message || '操作失败' };
  } catch (e: any) {
    return { ok: false, message: e?.message || '操作失败' };
  }
}
