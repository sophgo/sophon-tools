<template>
  <BasicModal v-bind="$attrs" @register="registerModal" :title="title" @ok="handleSubmit">
    <BasicForm @register="registerForm">
      <template #dst="{ model, field }">
        <a-select v-model:value="model[field]" :options="options" />
      </template>
    </BasicForm>
  </BasicModal>
</template>

<script lang="ts" setup>
  import { BasicModal, useModalInner } from '/@/components/Modal';
  import { BasicForm, useForm } from '/@/components/Form/index';
  import { addUserMap } from '/@/api/maintenance/index';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { UserSchema } from './tableData';
  import { resourceIp } from '/@/api/overview/index';
  import { onMounted, ref } from 'vue';
  const { t } = useI18n();
  const options = ref();
  const title = t('maintenance.coreBoardMap.addMap');
  const emit = defineEmits(['success', 'register']);
  const [registerForm, { setFieldsValue, resetFields, validate }] = useForm({
    labelWidth: 100,
    baseColProps: { span: 24 },
    schemas: UserSchema,
    showActionButtonGroup: false,
    actionColOptions: {
      span: 23,
    },
  });
  onMounted(async () => {
    const res = await resourceIp();
    options.value = res.map((item) => {
      //@ts-ignore
      const { ip } = item;
      return { label: ip, value: ip };
    });
  });
  const [registerModal, { setModalProps, closeModal }] = useModalInner(async (data) => {
    resetFields();
    setModalProps({ confirmLoading: false });
    setFieldsValue({
      target: 'DNAT',
      src: data.res[0].sourceIP,
    });
  });
  async function handleSubmit() {
    try {
      const values = await validate();
      setModalProps({ confirmLoading: true });
      await addUserMap({
        src: values.src,
        srcPort: values.srcPort,
        dst: values.dst,
        dstPort: values.dstPort,
        protocol: values.protocol,
      });
      emit('success');
      closeModal();
    } finally {
      setModalProps({ confirmLoading: false });
    }
  }
</script>
