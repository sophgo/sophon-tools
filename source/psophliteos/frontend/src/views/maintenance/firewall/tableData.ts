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

// ---------- Intent ----------
export function getIntentColumns(): BasicColumn[] {
  return [
    { title: 'ID', dataIndex: 'id', width: 70, align: 'center' },
    {
      title: t('maintenance.firewall.intentType'),
      dataIndex: 'type',
      width: 120,
      align: 'left',
      customRender: ({ text }: { text: string }) => typeLabelMap[text] || text,
    },
    {
      title: t('maintenance.firewall.params'),
      dataIndex: 'params',
      align: 'left',
      ellipsis: true,
    },
    {
      title: t('maintenance.firewall.enabled'),
      dataIndex: 'enabled',
      width: 90,
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

// 动态参数表单 schema —— 按 preset 重建（preset 本身由外层 a-select 管理）
export function getIntentParamSchema(preset: string): FormSchema[] {
  switch (preset) {
    case 'port_allow':
    case 'port_deny':
      return [
        { field: 'port', label: '端口', component: 'InputNumber', required: true, colProps: { span: 12 } },
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
        { field: 'src', label: '源 CIDR', component: 'Input', colProps: { span: 24 } },
      ];
    case 'rate_limit':
      return [
        { field: 'port', label: '端口', component: 'InputNumber', required: true, colProps: { span: 12 } },
        { field: 'rate', label: '速率', component: 'InputNumber', required: true, defaultValue: 100, colProps: { span: 12 } },
        { field: 'per', label: '单位', component: 'Select', componentProps: { options: [{ label: 'second', value: 'second' }, { label: 'minute', value: 'minute' }] }, defaultValue: 'second', colProps: { span: 12 } },
      ];
    case 'ip_whitelist':
    case 'ip_blacklist':
      return [
        { field: 'cidr', label: 'CIDR', component: 'Input', required: true, colProps: { span: 24 } },
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

const sceneLabelMap: Record<string, string> = {
  ext_to_container: '外部→容器',
  container_to_ext: '容器→外部',
};

// ---------- Docker ----------
export function getDockerColumns(): BasicColumn[] {
  return [
    { title: 'ID', dataIndex: 'id', width: 70, align: 'center' },
    {
      title: t('maintenance.firewall.dockerScene'),
      dataIndex: 'scene',
      width: 120,
      align: 'left',
      customRender: ({ text }: { text: string }) => sceneLabelMap[text] || text,
    },
    {
      title: t('maintenance.firewall.params'),
      dataIndex: 'params',
      align: 'left',
      ellipsis: true,
    },
    {
      title: t('maintenance.firewall.enabled'),
      dataIndex: 'enabled',
      width: 90,
      align: 'center',
    },
  ];
}

export const dockerSceneOptions = [
  { label: '外部→容器', value: 'ext_to_container' },
  { label: '容器→外部', value: 'container_to_ext' },
];

export function getDockerParamSchema(scene: string): FormSchema[] {
  switch (scene) {
    case 'ext_to_container':
      return [
        { field: 'container_port', label: '容器端口', component: 'InputNumber', required: true, colProps: { span: 12 } },
        { field: 'proto', label: '协议', component: 'Select', componentProps: { options: [{ label: 'tcp', value: 'tcp' }, { label: 'udp', value: 'udp' }] }, defaultValue: 'tcp', required: true, colProps: { span: 12 } },
        { field: 'src', label: '源 CIDR', component: 'Input', colProps: { span: 12 } },
        { field: 'action', label: '动作', component: 'Select', componentProps: { options: [{ label: '放行 (allow)', value: 'allow' }, { label: '拒绝 (deny)', value: 'deny' }] }, defaultValue: 'allow', required: true, colProps: { span: 12 } },
      ];
    case 'container_to_ext':
      return [
        { field: 'container_cidr', label: '容器 CIDR', component: 'Input', required: true, colProps: { span: 12 } },
        { field: 'dst_except', label: '目的例外 CIDR', component: 'Input', colProps: { span: 12 } },
        { field: 'action', label: '动作', component: 'Select', componentProps: { options: [{ label: '放行 (allow)', value: 'allow' }, { label: '拒绝 (deny)', value: 'deny' }] }, defaultValue: 'allow', required: true, colProps: { span: 12 } },
      ];
    default:
      return [];
  }
}

// ---------- Raw ----------
export function getRawColumns(): BasicColumn[] {
  return [
    { title: 'num', dataIndex: 'num', width: 70, align: 'center' },
    { title: 'target', dataIndex: 'target', width: 100, align: 'left' },
    { title: 'prot', dataIndex: 'prot', width: 80, align: 'left' },
    { title: 'in', dataIndex: 'in', width: 100, align: 'left' },
    { title: 'out', dataIndex: 'out', width: 100, align: 'left' },
    { title: 'src', dataIndex: 'src', width: 140, align: 'left' },
    { title: 'dst', dataIndex: 'dst', width: 140, align: 'left' },
    { title: 'pkts', dataIndex: 'pkts', width: 90, align: 'right' },
    { title: 'bytes', dataIndex: 'bytes', width: 110, align: 'right' },
    { title: 'raw', dataIndex: 'raw', align: 'left', ellipsis: true },
  ];
}

export const rawChainOptions = [
  { label: 'INPUT', value: 'INPUT' },
  { label: 'OUTPUT', value: 'OUTPUT' },
  { label: 'FORWARD', value: 'FORWARD' },
];
