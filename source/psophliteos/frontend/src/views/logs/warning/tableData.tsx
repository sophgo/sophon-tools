import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';

const { t } = useI18n();

// 对齐 ssm /api/v1/alarms 字段：id / code / coreUnitBoardSn / componentType / createdAt / msg
export function getBasicColumns(): BasicColumn[] {
  return [
    {
      title: t('logs.warning.id'),
      dataIndex: 'id',
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
      dataIndex: 'createdAt',
      align: 'left',
      customRender: ({ text }) => {
        if (!text) return '-';
        const d = new Date(text);
        return isNaN(d.getTime()) ? text : d.toLocaleString();
      },
    },
    {
      title: t('logs.warning.description'),
      dataIndex: 'msg',
      align: 'left',
      ellipsis: true,
    },
  ];
}
