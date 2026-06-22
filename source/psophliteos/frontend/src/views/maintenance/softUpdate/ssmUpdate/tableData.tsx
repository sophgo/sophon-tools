import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';
// import { useDeviceInfo } from '/@/store/modules/overview';
// const deviceStore = useDeviceInfo();
const { t } = useI18n();

export function getBasicColumns(): BasicColumn[] {
  return [
    {
      title: t('maintenance.ssmUpdate.boardName'),
      dataIndex: 'chipIndex',
      align: 'center',
      ellipsis: true,
      width: 200,
    },
    {
      title: t('maintenance.ssmUpdate.boardSn'),
      dataIndex: 'deviceSn',
      align: 'left',
    },
    {
      title: t('maintenance.ssmUpdate.boardHost'),
      dataIndex: 'host',
      align: 'left',
    },
    {
      title: t('maintenance.ssmUpdate.version'),
      dataIndex: 'version',
      align: 'left',
    },
  ];
}
