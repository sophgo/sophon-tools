import type { ConfigEnv } from 'vite';

import { getShortName } from './getShortName';

// 运行时全局配置在 window 上的挂载键名（__PRODUCTION__<SHORT>__CONF__）。
// _app.config.js 用此键名挂载配置对象，env.ts 用此键名读取。
export function getConfigFileName(env: ConfigEnv) {
  return getShortName(env);
}
