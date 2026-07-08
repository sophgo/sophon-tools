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
// 输入容错：字符串/NaN/Infinity/负数一律按 0 处理，避免出现 1.286e+122 之类的科学计数法。
export function getFormatTime(seconds, t) {
  const units = [t('overview.second'), t('overview.minute'), t('overview.hour'), t('overview.day')];
  let reset = Number(seconds);
  if (!isFinite(reset) || reset < 0) reset = 0;
  reset = Math.floor(reset);
  let i = 0;
  let str = '';
  while (i < 2 && reset > 0) {
    str = ('' + (reset % 60)).padStart(2, '00') + units[i++] + str;
    reset = Math.floor(reset / 60);
  }
  if (reset > 0) {
    const day = Math.floor(reset / 24);
    const hours = ('' + (reset % 24)).padStart(2, '00');
    str = (day ? day + units[3] : '') + hours + units[2] + str;
  }
  return str || '00' + units[0];
}
export const dateUtil = dayjs;
