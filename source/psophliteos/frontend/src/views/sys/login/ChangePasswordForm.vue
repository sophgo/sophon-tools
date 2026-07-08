<template>
  <template v-if="getShow">
    <LoginFormTitle class="enter-x" />
    <Alert
      message="为了您的账户安全，请修改初始密码后重新登录！"
      type="info"
      show-icon
      class="enter-x !mb-4"
    />
    <Form
      class="p-4 enter-x changePassword w-[404px]"
      :model="formData"
      :rules="getFormRules"
      ref="formRef"
      :label-col="{ span: 6 }"
    >
      <FormItem name="password" class="enter-x" :label="t('layout.header.oldPassword')">
        <InputPassword
          size="large"
          v-model:value="formData.password"
          :placeholder="t('common.inputText')"
        />
      </FormItem>

      <FormItem name="newPassword" class="enter-x" :label="t('layout.header.newPassword')">
        <InputPassword
          size="large"
          v-model:value="formData.newPassword"
          :placeholder="t('common.inputText')"
        />
      </FormItem>
      <FormItem
        name="repeatNewPassword"
        class="enter-x"
        :label="t('layout.header.repeatNewPassword')"
      >
        <InputPassword
          size="large"
          v-model:value="formData.repeatNewPassword"
          :placeholder="t('common.inputText')"
        />
      </FormItem>

      <FormItem class="enter-x">
        <Button type="primary" size="large" block @click="handleSubmit" :loading="loading">
          {{ t('sys.login.submit') }}
        </Button>
        <Button size="large" block class="mt-4" @click="handleBackLogin">
          {{ t('sys.login.backSignIn') }}
        </Button>
      </FormItem>
    </Form>
  </template>
</template>
<script lang="ts" setup>
  import { reactive, ref, computed, unref } from 'vue';
  import LoginFormTitle from './LoginFormTitle.vue';
  import { Form, InputPassword, Button, Alert } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useLoginState, useFormRules, LoginStateEnum, useFormValid } from './useLogin';
  import { changePassword } from '/@/api/sys/user';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { useUserStore } from '/@/store/modules/user';

  const { createMessage } = useMessage();
  const userStore = useUserStore();

  const FormItem = Form.Item;
  const { t } = useI18n();
  const { handleBackLogin, getLoginState } = useLoginState();

  const formRef = ref();
  const formData = reactive({
    password: '',
    newPassword: '',
    repeatNewPassword: '',
  });

  const { getFormRules } = useFormRules(formData);
  const { validForm } = useFormValid(formRef);

  const loading = ref(false);

  const getShow = computed(() => unref(getLoginState) === LoginStateEnum.CHANGE_PASSWORD);

  async function handleSubmit() {
    const data = await validForm();
    if (!data) return;
    const params = {
      oldPassword: data.password,
      newPassword: data.newPassword,
    };
    loading.value = true;

    try {
      await changePassword(params);
      createMessage.success(t('layout.header.changePassSuccess'));
      handleLoginOut();
      handleBackLogin();
    } catch (error) {
      console.log(error);
    } finally {
      loading.value = false;
    }
  }
  function handleLoginOut() {
    userStore.logout(true);
  }
</script>
<style lang="less" scoped>
  .sophgo-login .changePassword {
    :deep(input) {
      min-width: auto;
    }
  }
</style>
