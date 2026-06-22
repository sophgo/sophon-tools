<template>
  <BasicModal
    :footer="null"
    :title="t('layout.header.changePassword')"
    v-bind="$attrs"
    :class="prefixCls"
    @register="register"
  >
    <div :class="`${prefixCls}__entry`">
      <BasicForm @register="registerForm" />

      <div :class="`${prefixCls}__footer`">
        <a-button
          type="primary"
          block
          class="mt-2"
          @click="handleChangePassword"
          :loading="loading"
        >
          {{ t('sys.btn.confirm') }}
        </a-button>
      </div>
    </div>
  </BasicModal>
</template>
<script lang="ts">
  import { defineComponent, ref } from 'vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useDesign } from '/@/hooks/web/useDesign';
  import { BasicModal, useModalInner } from '/@/components/Modal/index';
  import { BasicForm, useForm } from '/@/components/Form/index';
  import { passwordCheck } from '/@/utils/validateFuncs';
  import { changePassword } from '/@/api/sys/user';
  import { useUserStore } from '/@/store/modules/user';
  import md5 from 'md5';

  export default defineComponent({
    name: 'ChangePassword',
    components: { BasicModal, BasicForm },

    setup() {
      const loading = ref(false);

      const { t } = useI18n();
      const { prefixCls } = useDesign('header-change-password-modal');

      const userStore = useUserStore();

      const [register, { closeModal }] = useModalInner();

      const [registerForm, { validateFields, resetFields, getFieldsValue }] = useForm({
        showActionButtonGroup: false,
        labelWidth: 140,
        schemas: [
          {
            field: 'password',
            label: t('layout.header.oldPassword'),
            colProps: {
              span: 24,
            },
            component: 'InputPassword',
            required: true,
          },
          {
            field: 'newPassword',
            label: t('layout.header.newPassword'),
            colProps: {
              span: 24,
            },
            component: 'InputPassword',
            rules: [
              {
                required: true,
                validator: passwordCheck,
                trigger: 'blur',
              },
            ],
          },
          {
            field: 'repeatNewPassword',
            label: t('layout.header.repeatNewPassword'),
            colProps: {
              span: 24,
            },
            component: 'InputPassword',
            rules: [
              {
                required: true,
                validator: async (_rule, value) => {
                  if (value === '') {
                    return Promise.reject(t('layout.header.inputRepeatNew'));
                  }
                  if (value !== getFieldsValue().newPassword) {
                    return Promise.reject(t('layout.header.diffNewPassword'));
                  }
                  return Promise.resolve();
                },
                trigger: 'blur',
              },
            ],
            // dynamicRules: ({ values }) => {
            //   if (values.repeatNewPassword.trim() === '') {
            //     return [{required: true, message: '请输入确认新密码'}]
            //   } else if (values.repeatNewPassword !== values.newPassword) {
            //     return [{required: true, message: '请输入确认新密码'}]
            //   }
            //   return values.newPassword ? [{ required: true, message: '字段4必填' }] : [];
            // },
          },
        ],
      });

      //  login out
      function handleLoginOut() {
        userStore.logout(true);
      }

      async function handleChangePassword() {
        const values = (await validateFields()) as any;
        const params = {
          password: md5(md5(values.password)),
          newPassword: md5(md5(values.newPassword)),
        };
        loading.value = true;
        try {
          await changePassword(params);
          closeModal();
          await resetFields();
          handleLoginOut();
        } catch (error) {
          console.log(error);
        } finally {
          loading.value = false;
        }
      }

      return {
        loading,
        t,
        prefixCls,
        register,
        registerForm,
        handleChangePassword,
      };
    },
  });
</script>
<style lang="less">
  @prefix-cls: ~'@{namespace}-header-change-password-modal';

  .@{prefix-cls} {
    &__entry {
      position: relative;
      //height: 240px;
      padding: 30px;
      border-radius: 10px;
    }

    &__header {
      position: absolute;
      top: 0;
      left: calc(50% - 45px);
      width: auto;
      text-align: center;
    }

    &__footer {
      text-align: center;
    }
  }
</style>
