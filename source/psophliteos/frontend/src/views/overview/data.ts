import { useI18n } from '/@/hooks/web/useI18n';
const { t } = useI18n();

export interface Description {
  label: string;
  value: string;
}
export interface GrowCardItem {
  title: string;
  value: number;
  color: string;
  description?: Array<Description>;
}

export const growCardList: GrowCardItem[] = [
  {
    title: t('overview.cpuUsage'),
    value: 20,
    color: '#4A9BFB',
    description: [
      {
        label: '',
        value: '8核 @ 2.3Ghz',
      },
    ],
  },
  {
    title: t('overview.tpuUsage'),
    value: 90,
    color: '#F2C94C',
  },
  {
    title: t('overview.memoryUsage'),
    value: 0,
    color: '#64D7B9',
    description: [
      {
        label: '已用',
        value: '665.0M',
      },
      {
        label: '总共',
        value: '3.7G',
      },
    ],
  },
  {
    title: t('overview.diskUsage'),
    value: 50,
    color: '#C26FCF',
    description: [
      {
        label: '已用',
        value: '17.1G',
      },
      {
        label: '总共',
        value: '28.3G',
      },
    ],
  },
];

export interface DeviceInfo {
  name: Description;
  type: Description;
  systemRunTime: Description;
  softVersion: Description;
  sn: Description;
  ip: Description;
  wanip: Description;
  lanip: Description;
}
export const deviceInfo: DeviceInfo = {
  name: {
    label: t('overview.device.name'),
    value: 'SE5-172.28.8.6',
  },
  type: {
    label: t('overview.device.type'),
    value: 'SE5',
  },
  systemRunTime: {
    label: t('overview.device.systemRunTime'),
    value: '2017-01-01T00:00:00.000Z',
  },
  softVersion: {
    label: t('overview.device.softVersion'),
    value: '2.6.0',
  },
  sn: {
    label: t('overview.device.sn'),
    value: 'HQDZKE5BJJFJH0067',
  },
  ip: {
    label: t('overview.device.ip'),
    value: '172.28.8.6',
  },
  wanip: {
    label: t('overview.device.wanip'),
    value: '172.28.8.6',
  },
  lanip: {
    label: t('overview.device.lanip'),
    value: '192.168.0.1',
  },
};
