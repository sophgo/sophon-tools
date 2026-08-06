import { BasicColumn, FormSchema } from '/@/components/Table';
import { useI18n } from '/@/hooks/web/useI18n';
// import { useDeviceInfo } from '/@/store/modules/overview';
// const deviceStore = useDeviceInfo();
const { t } = useI18n();

export function getSysColumns(): BasicColumn[] {
  return [
    // {
    //   title: t('maintenance.coreBoardMap.number'),
    //   dataIndex: 'num',
    //   align: 'center',
    //   ellipsis: true,
    //   width: 200,
    // },
    {
      title: t('maintenance.coreBoardMap.mode'),
      dataIndex: 'target',
      align: 'left',
    },
    {
      title: t('maintenance.coreBoardMap.protocol'),
      dataIndex: 'protocol',
      align: 'left',
    },
    {
      title: t('maintenance.coreBoardMap.ControlBoardIP'),
      dataIndex: 'sourceIP',
      align: 'left',
    },
    {
      title: t('maintenance.coreBoardMap.ControlPort'),
      dataIndex: 'sourcePort',
      align: 'left',
    },
    {
      title: t('maintenance.coreBoardMap.CoreBoardIP'),
      dataIndex: 'destIp',
      align: 'left',
    },
    {
      title: t('maintenance.coreBoardMap.CorePort'),
      dataIndex: 'destPort',
      align: 'left',
    },
  ];
}

export const UserSchema: FormSchema[] = [
  {
    field: 'target',
    label: t('maintenance.coreBoardMap.mode'),
    component: 'Input',
    componentProps: {
      disabled: true,
    },
  },
  {
    field: 'src',
    label: t('maintenance.coreBoardMap.ControlBoardIP'),
    component: 'Input',
    // 源 IP 用户可自定义；不再 disabled + 恒空（此前预填空值且不可改，导致提交空 src）。
    componentProps: {
      placeholder: '如 0.0.0.0 或 192.168.1.10',
    },
  },
  {
    field: 'srcPort',
    label: t('maintenance.coreBoardMap.ControlPort'),
    component: 'Input',
    required: true,
  },
  {
    field: 'dst',
    label: t('maintenance.coreBoardMap.CoreBoardIP'),
    component: 'Select',
    slot: 'dst',
    required: true,
  },
  {
    field: 'dstPort',
    label: t('maintenance.coreBoardMap.CorePort'),
    component: 'Input',
    required: true,
  },
  {
    field: 'protocol',
    label: t('maintenance.coreBoardMap.protocol'),
    component: 'Select',
    componentProps: {
      options: [
        { label: 'tcp', value: 'tcp' },
        { label: 'udp', value: 'udp' },
      ],
    },
    required: true,
  },
];
