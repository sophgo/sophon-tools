import { defHttp } from '/@/utils/http/axios';

// 单点登录（单会话）端点——sophliteos web 层本地维护，不经过 ssm。
// 注意：
// 1. defHttp 的 apiUrl 已带 /api 前缀（VITE_GLOB_API_URL=/api），此处只写后面的路径。
// 2. 这些端点返回裸 JSON（{active,username} / {ok:true}），不套 ssm 的 {code,msg,data} 信封，
//    故必须 isTransformResponse:false，否则默认 transform 会因缺 code 字段判为失败并弹空 error toast。
enum Api {
  Active = '/sso/active',
  Register = '/sso/register',
  Logout = '/sso/logout',
}

// 跳过信封解析的请求选项：返回裸 res.data，不弹错误提示。
const RAW = { isTransformResponse: false } as const;

export interface SsoActive {
  active: boolean;
  username: string;
}

// 查询当前在线用户（活跃会话）。登录前用于判断是否有冲突。
export function getSsoActive() {
  return defHttp.get<SsoActive>({ url: Api.Active }, RAW);
}

// 登录成功后注册会话为活跃（踢掉之前的会话）。
export function ssoRegister(username: string, token: string) {
  return defHttp.post({ url: Api.Register, params: { username, token } }, RAW);
}

// 注销：清除活跃会话（仅 token 匹配时）。
export function ssoLogout() {
  return defHttp.post({ url: Api.Logout }, RAW);
}
