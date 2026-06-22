import { MockMethod } from 'vite-plugin-mock';
import { resultSuccess } from '../_util';
const data = {
  token: 'wqerfasdofsafindfiaeorfobfuabfoasndfioj',
};
export default [
  {
    url: '/api/login',
    statusCode: 200,
    method: 'post',
    response: () => {
      return resultSuccess(data);
    },
  },
] as MockMethod[];
