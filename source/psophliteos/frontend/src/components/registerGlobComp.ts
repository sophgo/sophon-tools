import type { App } from 'vue';
import { Button } from './Button';
import { Input, Layout, Form, Select, InputNumber, Skeleton } from 'ant-design-vue';

export function registerGlobComp(app: App) {
  app.use(Input).use(Button).use(Layout).use(Form).use(Select).use(InputNumber).use(Skeleton);
}
