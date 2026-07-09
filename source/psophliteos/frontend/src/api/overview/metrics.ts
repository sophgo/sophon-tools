import { defHttp } from '/@/utils/http/axios';

// 端点对齐 bmssm /api/v1/metrics/*（经 sophliteos 反代，defHttp 自动加 /api 前缀 + Authorization 头）
enum Api {
  Fields = '/v1/metrics/fields',
  History = '/v1/metrics/history',
  Export = '/v1/metrics/export',
}

// /fields 返回 string[]（95 字段名，首个为 "timestamp"）
export function fieldsApi() {
  return defHttp.get<string[]>({ url: Api.Fields });
}

export interface HistoryParams {
  from: number; // unix 秒
  to: number;
  fields?: string[]; // 不传返回全部
}

export interface HistoryResult {
  fields: string[];
  points: number[][]; // 每行 [timestamp, v1, v2, ...]，缺失值可能为 null
  skipped_files: string[] | null;
  truncated: boolean;
}

// /history?from=&to=&fields=csv
export function historyApi(params: HistoryParams) {
  const query: Record<string, string> = {
    from: String(params.from),
    to: String(params.to),
  };
  if (params.fields && params.fields.length) {
    query.fields = params.fields.join(',');
  }
  return defHttp.get<HistoryResult>({
    url: Api.History,
    params: query,
  });
}

// 导出 CSV：export 在 Auth 保护组，只认 Authorization 头。
// 用 defHttp 取 text（带鉴权），再构造 Blob 触发浏览器下载。
// 不能用 window.open（无法带 Authorization 头）。
export async function exportCsv(from: number, to: number) {
  const text = await defHttp.get<string>(
    {
      url: Api.Export,
      params: { from: String(from), to: String(to), format: 'csv' },
      responseType: 'text',
    },
    { isTransformResponse: false }
  );
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `metrics-${from}-${to}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// 指标选择持久化（sophliteos 本地端点，不经 bmssm 反代）。
// defHttp 自动加 /api 前缀 → /api/device/metrics-selection
enum SelApi {
  Get = '/device/metrics-selection',
  Put = '/device/metrics-selection',
}

// 读取已存的指标选择；无则返空数组。
export async function getSelection(): Promise<string[]> {
  try {
    const res = await defHttp.get<{ fields: string[] }>(
      { url: SelApi.Get },
      { isTransformResponse: false }
    );
    // sophliteos 本地端点返回 {code,msg,result:{fields:[...]}} 或直接 {fields:[...]}
    const fields = (res as any)?.result?.fields ?? (res as any)?.fields ?? [];
    return Array.isArray(fields) ? fields : [];
  } catch {
    return [];
  }
}

// 保存指标选择。
export async function saveSelection(fields: string[]): Promise<boolean> {
  try {
    await defHttp.put(
      { url: SelApi.Put, data: { fields } },
      { isTransformResponse: false }
    );
    return true;
  } catch {
    return false;
  }
}
