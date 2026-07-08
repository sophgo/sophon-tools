import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';

const { t } = useI18n();

// 对齐 ssm /api/v1/audit 字段：id / action / resource / username / ip / createdAt / result
export function getBasicColumns(): BasicColumn[] {
  return [
    {
      title: t('logs.operate.id'),
      dataIndex: 'id',
      width: 200,
      align: 'center',
    },
    {
      title: t('logs.operate.type1'),
      dataIndex: 'action',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.funcName'),
      dataIndex: 'resource',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.people'),
      dataIndex: 'username',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.ip'),
      dataIndex: 'ip',
      width: 200,
      align: 'left',
    },
    {
      title: t('logs.operate.time'),
      width: 200,
      dataIndex: 'createdAt',
      align: 'left',
      customRender: ({ text }) => {
        if (!text) return '-';
        const d = new Date(text);
        return isNaN(d.getTime()) ? text : d.toLocaleString();
      },
    },
    {
      title: t('logs.operate.content'),
      dataIndex: 'result',
      align: 'left',
      ellipsis: true,
    },
  ];
}
