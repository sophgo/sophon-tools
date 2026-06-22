/**
 * Independent time operation tool to facilitate subsequent switch to dayjs
 */
import dayjs from 'dayjs';

const DATE_TIME_FORMAT = 'YYYY-MM-DD HH:mm:ss';
const DATE_FORMAT = 'YYYY-MM-DD';

export function formatToDateTime(
  date: dayjs.Dayjs | undefined = undefined,
  format = DATE_TIME_FORMAT,
): string {
  return dayjs(date).format(format);
}

export function formatToDate(
  date: dayjs.Dayjs | undefined = undefined,
  format = DATE_FORMAT,
): string {
  return dayjs(date).format(format);
}
// 秒 => 天：小时：分钟：秒
export function getFormatTime(seconds, t) {
  const units = [t('overview.second'), t('overview.minute'), t('overview.hour'), t('overview.day')];
  let i = 0;
  let reset = seconds;
  let str = '';
  while (i < 2 && reset) {
    str = ('' + (reset % 60)).padStart(2, '00') + units[i++] + str;
    reset = Math.floor(reset / 60);
  }
  if (reset) {
    const day = Math.floor(reset / 24);
    const hours = ('' + (reset % 24)).padStart(2, '00');
    str = (day ? day + units[3] : '') + hours + units[2] + str;
  }
  return str;
}
export const dateUtil = dayjs;
