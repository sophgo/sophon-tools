import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';

const { t } = useI18n();

export function getBasicColumns(): BasicColumn[] {
  return [
    {
      title: t('logs.warning.id'),
      dataIndex: 'ID',
      width: 200,
      align: 'center',
    },
    {
      title: t('logs.warning.code'),
      dataIndex: 'code',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.warning.deviceSn'),
      dataIndex: 'coreUnitBoardSn',
      width: 220,
      align: 'left',
    },
    {
      title: t('logs.warning.type1'),
      dataIndex: 'componentType',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.warning.time'),
      width: 220,
      dataIndex: 'dataTime',
      align: 'left',
    },
    {
      title: t('logs.warning.description'),
      dataIndex: 'msg',
      align: 'left',
      ellipsis: true,
    },
  ];
}
