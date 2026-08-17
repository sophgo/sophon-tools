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
// register 失败（401 等）由登录流程统一提示，避免此处自动 toast 造成双重提示
// （默认 errorMessageMode='message' 会弹"会话已下线"误导文案）。
const REGISTER_RAW = { isTransformResponse: false, errorMessageMode: 'none' } as const;

export interface SsoActive {
  active: boolean;
  username: string;
}

// 查询当前在线用户（活跃会话）。登录前用于判断是否有冲突。
export function getSsoActive() {
  return defHttp.get<SsoActive>({ url: Api.Active }, RAW);
}

// 登录成功后注册会话为活跃（踢掉之前的会话）。失败由 user.ts login 流程提示。
export function ssoRegister(username: string, token: string) {
  return defHttp.post({ url: Api.Register, params: { username, token } }, REGISTER_RAW);
}

// 注销：清除活跃会话（仅 token 匹配时）。
export function ssoLogout() {
  return defHttp.post({ url: Api.Logout }, RAW);
}
