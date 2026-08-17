import { Persistent, BasicKeys } from '/@/utils/cache/persistent';
import { CacheTypeEnum } from '/@/enums/cacheEnum';
import projectSetting from '/@/settings/projectSetting';
import { TOKEN_KEY, USER_INFO_KEY, ROLES_KEY, FIRST_LOGIN_KEY } from '/@/enums/cacheEnum';

const { permissionCacheType } = projectSetting;
const isLocal = permissionCacheType === CacheTypeEnum.LOCAL;

// MYS-383：认证缓存已切换为 sessionStorage。此处做一次性存量清理——
// 把旧版本（permissionCacheType=LOCAL）写入 localStorage 的认证数据（含 JWT）
// 从 localStorage 中移除，避免令牌长期残留在 localStorage 中。
if (!isLocal) {
  [TOKEN_KEY, USER_INFO_KEY, ROLES_KEY, FIRST_LOGIN_KEY].forEach((key) =>
    Persistent.removeLocal(key, true),
  );
}

export function getToken() {
  return getAuthCache(TOKEN_KEY);
}

export function getAuthCache<T>(key: BasicKeys) {
  const fn = isLocal ? Persistent.getLocal : Persistent.getSession;
  return fn(key) as T;
}

export function setAuthCache(key: BasicKeys, value) {
  const fn = isLocal ? Persistent.setLocal : Persistent.setSession;
  return fn(key, value, true);
}

export function clearAuthCache(immediate = true) {
  const fn = isLocal ? Persistent.clearLocal : Persistent.clearSession;
  return fn(immediate);
}
