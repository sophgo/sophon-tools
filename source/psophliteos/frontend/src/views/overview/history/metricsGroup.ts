// @ts-nocheck
// 字段→子系统分组映射。字段名取自 bmssm ArchFields v2（21 个指标）。
// v2: 删除频率/每核/网卡/磁盘/内存绝对值/分路功耗电压/健康/核数；
//     内存改为使用率(%)。分组顺序即页面图表网格渲染顺序。

export interface MetricGroup {
  key: string;
  title: string;
  matchers: string[];
  defaults: string[];
  yAxis: string;
}

export const GROUP_DEFS: MetricGroup[] = [
  {
    key: 'cpu',
    title: 'CPU',
    matchers: ['cpu_usage_pct'],
    defaults: ['cpu_usage_pct'],
    yAxis: 'percent',
  },
  {
    key: 'accel',
    title: 'TPU / VPU / VPP / JPU',
    matchers: ['tpu_usage_pct', 'vpu_enc_usage_pct', 'vpu_dec_usage_pct', 'vpu_enc_links', 'vpu_dec_links', 'vpp_usage_pct', 'jpu_usage_pct'],
    defaults: ['tpu_usage_pct', 'vpu_enc_usage_pct'],
    yAxis: 'percent',
  },
  {
    key: 'mem',
    title: '内存使用率',
    matchers: ['system_mem_usage_pct', 'vpp_memory_usage_pct', 'vpu_memory_usage_pct', 'tpu_memory_usage_pct'],
    defaults: ['system_mem_usage_pct'],
    yAxis: 'percent',
  },
  {
    key: 'temp',
    title: '温度 & 风扇',
    matchers: ['chip_temp_c', 'board_temp_c', 'fan_speed_rpm'],
    defaults: ['chip_temp_c', 'board_temp_c'],
    yAxis: 'temp',
  },
  {
    key: 'power',
    title: '功耗',
    matchers: ['power_usage_w'],
    defaults: ['power_usage_w'],
    yAxis: 'power',
  },
  {
    key: 'sys',
    title: '系统',
    matchers: ['boot_time_s'],
    defaults: [],
    yAxis: 'raw',
  },
];

// 字段→分组键。timestamp 返回 null。
export function fieldToGroup(field: string): string | null {
  if (field === 'timestamp') return null;
  for (const g of GROUP_DEFS) {
    for (const m of g.matchers) {
      if (field === m) return g.key;
      if (m.endsWith('_') && field.startsWith(m)) return g.key;
    }
  }
  return 'sys';
}

// 巡检视图默认字段
export const DEFAULT_FIELDS: string[] = GROUP_DEFS.flatMap((g) => g.defaults);

// 字段名 → 中文标签映射（v3）
export const FIELD_LABEL_MAP: Record<string, string> = {
  cpu_usage_pct: 'CPU 使用率',
  tpu_usage_pct: 'TPU 使用率',
  vpu_enc_usage_pct: 'VPU 编码使用率',
  vpu_dec_usage_pct: 'VPU 解码使用率',
  vpu_enc_links: 'VPU 编码链路数',
  vpu_dec_links: 'VPU 解码链路数',
  vpp_usage_pct: 'VPP 使用率',
  jpu_usage_pct: 'JPU 使用率',
  system_mem_usage_pct: '系统内存使用率',
  vpp_memory_usage_pct: 'VPP 内存使用率',
  vpu_memory_usage_pct: 'VPU 内存使用率',
  tpu_memory_usage_pct: 'TPU 内存使用率',
  chip_temp_c: '芯片温度',
  board_temp_c: '板卡温度',
  fan_speed_rpm: '风扇转速',
  power_usage_w: '总功耗',
  boot_time_s: '启动时长',
};

// fieldLabel 返回字段中文名；v2 全部为静态映射，无动态字段。
export function fieldLabel(f: string): string {
  return FIELD_LABEL_MAP[f] || f;
}
