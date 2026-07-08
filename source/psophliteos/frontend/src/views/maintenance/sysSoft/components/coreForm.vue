<template>
  <div style="font-size: 16px; margin: 20px 0 0 20px; font-weight: 550">{{
    t('maintenance.systemUpdate.coreBoardUpdate')
  }}</div>
  <div style="margin-left: 20px">
    <a-form
      ref="coreForm"
      autocomplete="off"
      :model="coreFormState"
      v-bind="formItemLayout"
      @finish="handleUpload"
      class="!my-4"
      labelAlign="left"
    >
      <a-form-item
        v-if="deviceInfoStore.isSingleBoard"
        :label="t('maintenance.systemUpdate.updateType')"
        :rules="[{ required: true }]"
      >
        {{ t('maintenance.systemUpdate.localUpdate') }}
      </a-form-item>
      <a-form-item
        :label="t('maintenance.systemUpdate.selectCoreBoard')"
        name="checkedList"
        :rules="[{ required: true, message: t('maintenance.systemUpdate.selectUpgradeCoreBoard') }]"
        labelAlign="left"
      >
        <a-form-item-rest>
          <a-checkbox
            v-model:checked="checkAll"
            :indeterminate="indeterminate"
            @change="onCheckAllChange"
            class="!mt-6px"
          >
            {{ t('sys.table.selectAll') }}
          </a-checkbox>
          <br />
          <a-checkbox-group
            v-model:value="coreFormState.checkedList"
            :options="plainOptions"
            @change="checkChange"
            class="max-w-860px"
          />
        </a-form-item-rest>
      </a-form-item>

      <a-form-item
        v-if="isSsm"
        :label="t('maintenance.ssmUpdate.serverUsername')"
        name="username"
        :rules="[{ required: true }]"
      >
        <a-input
          style="width: 200px"
          width="100px"
          v-model:value="coreFormState.username"
          autocomplete="new-password"
        />
      </a-form-item>
      <a-form-item
        v-if="isSsm"
        :label="t('maintenance.ssmUpdate.serverPassword')"
        name="password"
        :rules="[{ required: true }]"
      >
        <a-input-password
          style="width: 200px"
          v-model:value="coreFormState.password"
          readonly
          onfocus="this.removeAttribute('readonly')"
          onblur="this.setAttribute('readonly', true)"
        />
      </a-form-item>
      <a-form-item
        :label="t('sys.uploadFile.btnText')"
        name="file"
        :rules="[{ required: true, message: t(t('maintenance.systemUpdate.selectNeedFile')) }]"
        v-if="coreFormState.type === 'local'"
        v-model:value="coreFormState.file"
      >
        <a-upload
          :file-list="fileList"
          :before-upload="beforeUpload"
          :progress="progress"
          @remove="handleRemove"
        >
          <a-button>
            <a-upload-outlined />
            {{ t('maintenance.systemUpdate.selectFile') }}
          </a-button>
          <span class="tips">{{ t('maintenance.systemUpdate.fileFormat') }}</span>
        </a-upload>
      </a-form-item>
      <!-- <a-form-item :wrapper-col="{ span: 8, offset: 4 }">

      </a-form-item> -->
      <a-button type="primary" :loading="uploading" html-type="submit">
        {{
          uploading
            ? t('maintenance.systemUpdate.updaing')
            : t('maintenance.systemUpdate.startUpdate')
        }}
      </a-button>
    </a-form>
  </div>
</template>
<script lang="ts" setup>
  import { reactive, ref, computed } from 'vue';
  import type { UnwrapRef } from 'vue';
  import { Checkbox, CheckboxGroup, Upload, Input, InputPassword } from 'ant-design-vue';
  import { UploadOutlined } from '@ant-design/icons-vue';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { upgradeApi, executeUpgradeApi } from '/@/api/maintenance/index';
  import { storeToRefs } from 'pinia';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { buildUUID } from '/@/utils/uuid';
  import { AxiosCanceler } from '/@/utils/http/axios/axiosCancel';
  import { useGlobSetting } from '/@/hooks/setting';
  import { useI18n } from '/@/hooks/web/useI18n';

  const { t } = useI18n();

  const { uploadUrl = '' } = useGlobSetting();

  const props = defineProps({
    isSsm: {
      type: Boolean,
      default: false,
    },
  });

  const axiosCanceler = new AxiosCanceler();

  const ACheckboxGroup = CheckboxGroup;
  const ACheckbox = Checkbox;
  const AUpload = Upload;
  const AInput = Input;
  const AInputPassword = InputPassword;
  const AUploadOutlined = UploadOutlined;
  // const ATransfer = Transfer;

  interface CoreFormState {
    type: string;
    core: string;
    ota: string;
    file: any;
    username: string;
    password: string;
    checkedList: string[];
  }
  const formItemLayout = {
    labelCol: { span: 4 },
    wrapperCol: { span: 20 },
  };

  const coreFormState: UnwrapRef<CoreFormState> = reactive({
    type: 'local',
    core: '',
    ota: '',
    file: '',
    username: '',
    password: '',
    checkedList: [],
  });

  // 上传逻辑
  const fileList = ref<any>([]);
  const uploading = ref(false);
  const progress = {
    strokeColor: {
      '0%': '#108ee9',
      '100%': '#87d068',
    },
    strokeWidth: 3,
    format: (percent) => `${parseFloat(percent.toFixed(2))}%`,
    class: 'test',
  };
  const handleRemove = (file) => {
    const index = fileList.value.indexOf(file);
    const newFileList = fileList.value.slice();
    newFileList.splice(index, 1);
    fileList.value = newFileList;
    // 取消请求
    axiosCanceler.removePending({ method: 'post', url: uploadUrl });
    uploading.value = false;
  };
  const { createMessage } = useMessage();
  const beforeUpload = (file) => {
    const isTgz = file.name.endsWith('.tgz');
    if (!isTgz) {
      createMessage.error('抱歉，仅支持上传.tgz格式文件，请重新选择文件！');
      return false;
    }
    const { size, name } = file;
    const commonItem = {
      uuid: buildUUID(),
      file,
      size,
      name,
      percent: 0,
      type: name.split('.').pop(),
    };
    fileList.value = [commonItem];
    coreFormState.file = commonItem;
    return false;
  };
  const handleUpload = async () => {
    try {
      uploading.value = true;
      let data: any[] = [];
      if (fileList.value.length === 0) {
        // 守卫：未选文件时不再发送空 file 字段（ssm 会报 "missing file field"）
        createMessage.error(t('maintenance.systemUpdate.selectNeedFile'), 3);
        uploading.value = false;
        return;
      } else {
        data = await Promise.all(
          fileList.value.map((item) => {
            return uploadApiByItem(item);
          }),
        );
      }
      uploading.value = false;
      // 生产环境:抛出错误
      const errorList = data.filter((item: any) => !item.success);
      if (errorList.length > 0) {
        throw errorList;
      } else {
        createMessage.success('升级成功！');
      }
    } catch (e) {
      uploading.value = false;
      // throw e;
    }
  };

  async function uploadApiByItem(item) {
    try {
      item.status = 'uploading';
      // isSsm 与本地均走真实 ssm /api/v1/ota/upload（不再用 mock upgradeSsmApi）
      const dataParams = {
        module: 'core',
        ip: coreFormState.checkedList.join(','),
      };
      const file = item.file;
      if (!file) {
        createMessage.error(t('maintenance.systemUpdate.selectNeedFile'), 3);
        item.status = 'error';
        return { success: false, error: 'no file' };
      }
      const { data } = await upgradeApi(
        {
          data: dataParams,
          file: file,
        },
        function onUploadProgress(progressEvent: ProgressEvent) {
          const complete = ((progressEvent.loaded / progressEvent.total) * 100) | 0;
          item.percent = complete;
        },
      );
      const body = data?.data ?? data;
      if (!body || body.code !== 0) {
        createMessage.error(body?.msg || 'upload failed', 3);
        item.status = 'error';
        return { success: false, error: body?.msg };
      }
      item.percent = 100;

      // ssm OTA：上传成功后再调 executeUpgradeApi 触发升级 workflow
      const uploaded = body.result || {};
      const fileName = uploaded.fileName || file?.name || '';
      const execBody = {
        name: fileName,
        product: deviceInfo.value.deviceType,
        fileName,
        moduleName: 'core',
        cmdFlag: '',
        version: '',
        flashData: false,
      };
      try {
        await executeUpgradeApi(execBody);
        item.responseData = data;
      } catch (e) {
        item.status = 'error';
        return { success: false, error: e };
      }
      item.status = 'success';
      return {
        success: true,
        error: null,
      };
    } catch (e) {
      item.status = 'error';
      return {
        success: false,
        error: e,
      };
    }
  }

  // 设备基础信息
  interface Board {
    ip: string;
    sn: string;
    title: string;
    number: Number;
  }
  const deviceInfoStore = useDeviceInfo();
  const { deviceStatus, deviceInfo } = storeToRefs(deviceInfoStore);
  const plainOptions = computed(() => {
    return deviceStatus.value.map((board: Board) => ({
      value: props.isSsm ? board.sn : board.ip,
      label: t('overview.coreBoard') + '-' + board.number,
    }));
  });

  // 核心板选择逻辑
  const indeterminate = ref(false);
  const checkAll = ref(false);
  // const checkedList = ref<string[]>([]);
  const onCheckAllChange = (e) => {
    indeterminate.value = false;
    coreFormState.checkedList = e.target.checked
      ? plainOptions.value.map((board) => board.value)
      : [];
  };
  const checkChange = (checked) => {
    indeterminate.value = !!checked.length && checked.length < plainOptions.value.length;
    checkAll.value = checked.length === plainOptions.value.length;
  };
  const coreForm = ref();
  const resetForm = () => {
    coreForm.value.resetFields();
  };
  defineExpose({
    resetForm,
  });
</script>
<style scoped lang="less">
  .ant-checkbox-group.max-w-860px {
    :deep(.ant-checkbox-wrapper) {
      width: 120px;
      margin-top: 12px;
    }
  }

  .ant-form .ant-form-item {
    margin-bottom: 16px;
  }

  .ant-form-item .ant-upload .tips {
    font-size: 12px;
    color: red;
    position: relative;
    top: 4px;
    margin-left: 20px;
    opacity: 0.8;
  }

  :deep(.ant-upload-list-item-progress) {
    bottom: -20px;
  }
</style>
