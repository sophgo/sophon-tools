import { BasicColumn, FormSchema } from '/@/components/Table';
import { useI18n } from '/@/hooks/web/useI18n';

const { t } = useI18n();

const typeLabelMap: Record<string, string> = {
  port_allow: '端口放行',
  port_deny: '端口拒绝',
  rate_limit: '速率限制',
  ip_whitelist: 'IP 白名单',
  ip_blacklist: 'IP 黑名单',
  icmp: 'ICMP',
};

// IPv4 CIDR：四段 0-255 十进制，前缀 0-32（可省略前缀，视为 /32 主机地址）。
// 0.0.0.0/0 合法（全网段）。不匹配 IPv6——后端 parseIPv4CIDR 强制 IPv4。
const cidrPattern =
  /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(\/(3[0-2]|[12]?\d))?$/;

function isCidrValue(v: string): boolean {
  if (!cidrPattern.test(v)) return false;
  // 前缀校验：/0 允许（0.0.0.0/0），其余须 1-32。正则已保证 0-32。
  return true;
}

// ---------- Intent ----------
export function getIntentColumns(): BasicColumn[] {
  return [
    { title: 'ID', dataIndex: 'id', width: 70, align: 'center' },
    {
      title: t('maintenance.firewall.intentType'),
      dataIndex: 'type',
      width: 100,
      align: 'left',
      customRender: ({ text }: { text: string }) => typeLabelMap[text] || text,
    },
    {
      title: '端口',
      dataIndex: 'params',
      width: 80,
      align: 'left',
      customRender: ({ record }: { record: Record<string, any> }) => {
        try {
          const p = JSON.parse(record.params || '{}');
          if (p.port !== undefined) return p.port;
          if (record.type === 'rate_limit') return p.rate + '/' + p.per;
          return '-';
        } catch { return '-'; }
      },
    },
    {
      title: '协议',
      dataIndex: 'params',
      width: 60,
      align: 'left',
      customRender: ({ record }: { record: Record<string, any> }) => {
        try {
          const p = JSON.parse(record.params || '{}');
          return p.proto || '-';
        } catch { return '-'; }
      },
    },
    {
      title: '源CIDR',
      dataIndex: 'params',
      align: 'left',
      ellipsis: true,
      customRender: ({ record }: { record: Record<string, any> }) => {
        try {
          const p = JSON.parse(record.params || '{}');
          return p.src || p.cidr || '-';
        } catch { return '-'; }
      },
    },
    {
      title: t('maintenance.firewall.enabled'),
      dataIndex: 'enabled',
      width: 80,
      align: 'center',
    },
  ];
}

export const intentPresetOptions = [
  { label: '端口放行', value: 'port_allow' },
  { label: '端口拒绝', value: 'port_deny' },
  { label: '速率限制', value: 'rate_limit' },
  { label: 'IP 白名单', value: 'ip_whitelist' },
  { label: 'IP 黑名单', value: 'ip_blacklist' },
  { label: 'ICMP', value: 'icmp' },
];

function portRule(label: string) {
  return { min: 1, max: 65535, type: 'number' as const, message: `${label} 须在 1-65535 之间` };
}

function cidrRule(label: string) {
  return {
    validator: (_: unknown, v: string) => {
      if (!v || v.trim() === '') return Promise.resolve();
      return isCidrValue(v.trim())
        ? Promise.resolve()
        : Promise.reject(new Error(`${label} 格式须为 IPv4 CIDR（如 10.0.0.0/8）`));
    },
  };
}

// 动态参数表单 schema —— 按 preset 重建（preset 本身由外层 a-select 管理）
export function getIntentParamSchema(preset: string): FormSchema[] {
  switch (preset) {
    case 'port_allow':
    case 'port_deny':
      return [
        { field: 'port', label: '端口', component: 'InputNumber', required: true, colProps: { span: 12 }, componentProps: { min: 1, max: 65535 }, rules: [portRule('端口')] },
        {
          field: 'proto',
          label: '协议',
          component: 'Select',
          componentProps: {
            options: [
              { label: 'tcp', value: 'tcp' },
              { label: 'udp', value: 'udp' },
            ],
          },
          required: true,
          defaultValue: 'tcp',
          colProps: { span: 12 },
        },
        { field: 'src', label: '源 CIDR', component: 'Input', colProps: { span: 24 }, rules: [cidrRule('源 CIDR')] },
      ];
    case 'rate_limit':
      return [
        { field: 'port', label: '端口', component: 'InputNumber', required: true, colProps: { span: 12 }, componentProps: { min: 1, max: 65535 }, rules: [portRule('端口')] },
        { field: 'rate', label: '速率', component: 'InputNumber', required: true, defaultValue: 100, colProps: { span: 12 }, componentProps: { min: 1 }, rules: [{ min: 1, type: 'number' as const, message: '速率须 >= 1' }] },
        { field: 'per', label: '单位', component: 'Select', componentProps: { options: [{ label: 'second', value: 'second' }, { label: 'minute', value: 'minute' }] }, defaultValue: 'second', colProps: { span: 12 } },
      ];
    case 'ip_whitelist':
    case 'ip_blacklist':
      return [
        { field: 'cidr', label: 'CIDR', component: 'Input', required: true, colProps: { span: 24 }, rules: [cidrRule('CIDR')] },
      ];
    case 'icmp':
      return [
        {
          field: 'allow',
          label: '允许 ICMP',
          component: 'Switch',
          defaultValue: true,
          colProps: { span: 24 },
        },
      ];
    default:
      return [];
  }
}
