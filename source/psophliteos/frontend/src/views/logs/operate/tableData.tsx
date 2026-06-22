import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';

const { t } = useI18n();
export function getBasicColumns(): BasicColumn[] {
  return [
    {
      title: t('logs.operate.id'),
      dataIndex: 'recordId',
      width: 200,
      align: 'center',
    },
    {
      title: t('logs.operate.type1'),
      dataIndex: 'operationType',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.funcName'),
      dataIndex: 'operationFunc',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.people'),
      dataIndex: 'userName',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.ip'),
      dataIndex: 'operationIp',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.time'),
      width: 200,
      dataIndex: 'dataTime',
      align: 'left',
    },
    {
      title: t('logs.operate.content'),
      dataIndex: 'operationContent',
      align: 'left',
      ellipsis: true,
    },
  ];
}
