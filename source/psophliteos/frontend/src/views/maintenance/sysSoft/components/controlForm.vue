<template>
  <a-skeleton :loading="loading" active>
    <div
      v-if="!deviceInfoStore.isSingleBoard"
      style="font-size: 16px; margin: 20px 0 0 20px; font-weight: 550"
      >{{
        isSoftware
          ? t('maintenance.systemUpdate.softwareUpdate')
          : t('maintenance.systemUpdate.systemUpdate')
      }}</div
    >
    <div v-else style="font-size: 16px; margin: 20px 0 0 20px; font-weight: 550">{{
      t('maintenance.systemUpdate.localUpdate1')
    }}</div>
    <div class="formStyle">
      <div style="width: 20vw; margin-left: 20px; min-width: 350px; margin-right: 20px">
        <a-form
          :model="formState"
          v-bind="formItemLayout"
          class="!my-4"
          @finish="handleUpload"
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
            :label="
              isSoftware
                ? t('maintenance.systemUpdate.currentSoftVersion')
                : isSsm
                ? t('maintenance.systemUpdate.currentSsmVersion')
                : t('maintenance.systemUpdate.currentVersion')
            "
            :rules="[{ required: true }]"
          >
            <span>{{
              isSoftware ? softVersion : isSsm ? deviceInfo.bmssmVersion : deviceInfo.sdkVersion
            }}</span>
          </a-form-item>

          <a-form-item
            name="file"
            :rules="[{ required: true, message: t(t('maintenance.systemUpdate.selectNeedFile')) }]"
            :label="
              !isSsm && !isSoftware ? t('sys.uploadFile.upPackage') : t('sys.uploadFile.btnText')
            "
            v-model:value="formState.file"
          >
            <a-upload
              :file-list="fileList"
              :before-upload="beforeUpload"
              @remove="handleRemove"
              name="file"
            >
              <a-button>
                <a-upload-outlined />
                {{ t('maintenance.systemUpdate.selectFile') }}
              </a-button>
              <br />
              <span class="tips">{{ t('maintenance.systemUpdate.fileFormat') }}</span>
            </a-upload>
            <a-progress
              v-if="isSysSoft && fileList.length > 0 && (fileLoading || fileList[0]?.percent > 0)"
              :percent="+(fileList[0]?.percent * 100).toFixed(0)"
              size="small"
              :strokeColor="progress.strokeColor"
              :strokeWidth="progress.strokeWidth"
              :class="progress.class"
              :status="progressStatus"
            />
          </a-form-item>
          <a-form-item
            v-if="!isSoftware"
            :label="t('maintenance.flashData')"
          >
            <RadioGroup v-model:value="flashData">
              <Radio :value="true">是</Radio>
              <Radio :value="false">否</Radio>
            </RadioGroup>
          </a-form-item>
          <!-- <a-form-item :wrapper-col="{ span: 14, offset: 4 }" /> -->
          <a-button
            v-if="!isSsm && !isSoftware"
            type="primary"
            style="margin-right: 4.5vw"
            @click="uploadFile"
            :loading="fileLoading"
            :disabled="uploading"
            :class="{ 'is-disabled': uploading }"
            >{{
              fileLoading
                ? t('maintenance.systemUpdate.filesUploading')
                : t('maintenance.systemUpdate.uploadFiles')
            }}</a-button
          >
          <a-button
            type="primary"
            v-if="isSsm || isSoftware"
            :loading="uploading"
            html-type="submit"
            style="margin-top: 10px"
            :class="{ isSsmbtn: isSsm && !deviceInfoStore.isSingleBoard }"
          >
            {{
              uploading
                ? t('maintenance.systemUpdate.updaing')
                : t('maintenance.systemUpdate.startUpdate')
            }}
          </a-button>
        </a-form>
      </div>
      <div class="md5Style" v-if="!isSsm && !isSoftware">
        <span class="spanStyle">{{ t('maintenance.upgradePackage') }}</span>
        <a-input v-model:value="filename" addon-before="文件名" disabled />
        <a-input v-model:value="md5Name" addon-before="md5值" style="margin-top: 32px" disabled />
        <span class="tips">{{
          filename ? t('maintenance.updatedFiles') : t('maintenance.UnupdateFiles')
        }}</span>
        <a-button
          type="primary"
          :loading="uploading"
          :disabled="!show || fileLoading || MD5loading"
          @click="handleUpload"
          style="margin-top: 35px; width: 88px"
          :class="{ isClass: isClass }"
        >
          {{
            uploading
              ? t('maintenance.systemUpdate.updaing')
              : t('maintenance.systemUpdate.startUpdate')
          }}
        </a-button>
      </div>
    </div>
    <Loading :loading="MD5loading" :tip="tip" />
  </a-skeleton>
</template>
<script lang="ts" setup>
  import { reactive, ref, onMounted, watch } from 'vue';
  import type { UnwrapRef } from 'vue';
  import { storeToRefs } from 'pinia';
  import { Upload, Progress, Radio } from 'ant-design-vue';
  const RadioGroup = Radio.Group;
  import { UploadOutlined } from '@ant-design/icons-vue';

  import {
    upgradeApi,
    upgradeSoftApi,
    checkFile,
    uploadPartFile,
    checkFileList,
    executeUpgradeApi,
  } from '/@/api/maintenance/index';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { buildUUID } from '/@/utils/uuid';
  import { AxiosCanceler } from '/@/utils/http/axios/axiosCancel';
  import { useGlobSetting } from '/@/hooks/setting';
  import { getSoftwareInfoApi } from '/@/api/overview/index';
  import { Loading } from '/@/components/Loading';
  import SparkMD5 from 'spark-md5';

  import { useI18n } from '/@/hooks/web/useI18n';
  const { t } = useI18n();

  const props = defineProps({
    isSysSoft: {
      type: Boolean,
      default: false,
    },
    isSoftware: {
      type: Boolean,
      default: false,
    },
    isSsm: {
      type: Boolean,
      default: false,
    },
  });

  // 获取当前软件版本
  const softVersion = ref('');
  const getSoftInfor = async () => {
    const result = await getSoftwareInfoApi();
    softVersion.value = result.buildname;
  };
  onMounted(async () => {
    if (props.isSoftware) {
      getSoftInfor();
    }
    if (!props.isSoftware && !props.isSsm) {
      checkFileFn();
    }
  });
  const { uploadUrl = '' } = useGlobSetting();

  const axiosCanceler = new AxiosCanceler();
  const { createMessage } = useMessage();
  const AUpload = Upload;
  const AProgress = Progress;
  const AUploadOutlined = UploadOutlined;

  const deviceInfoStore = useDeviceInfo();
  const { deviceInfo } = storeToRefs(deviceInfoStore);

  const loading = ref(false);
  if (!deviceInfo.value.deviceSn) {
    loading.value = true;
    deviceInfoStore.getDeviceInfo().then(() => {
      loading.value = false;
    });
  }

  interface FormState {
    type: string;
    ota: string;
    file: any;
  }

  const formState: UnwrapRef<FormState> = reactive({
    type: 'local',
    ota: '',
    file: '',
  });

  const formItemLayout = {
    labelCol: { span: 10 },
    wrapperCol: { span: 14 },
  };
  const filename = ref('');
  const md5Name = ref('');
  const fileLoading = ref(false);
  const MD5loading = ref(false);
  const tip = ref('');
  const show = ref(false);
  // 上传逻辑
  const fileList = ref<any>([]);
  const uploading = ref(false);
  const flashData = ref(false);
  const progress = {
    strokeColor: {
      '0%': '#108ee9',
      '100%': '#87d068',
    },
    strokeWidth: 3,
    format: (percent) => `${parseFloat(percent.toFixed(2))}%`,
    class: 'test',
  };
  const progressStatus: any = ref('normal');
  const handleRemove = (file) => {
    const condition = props.isSsm || props.isSoftware;
    const valueCheck = condition ? uploading.value : fileLoading.value;

    if (!valueCheck) {
      handleFileRemoval(file);
      cancelUploadRequest();
    } else {
      createMessage.warning('正在上传中，不能删除');
      return false;
    }
  };

  const handleFileRemoval = (file) => {
    const index = fileList.value.indexOf(file);
    const newFileList = fileList.value.slice();
    newFileList.splice(index, 1);
    fileList.value = newFileList;
    uploading.value = false;
    isClass.value = false;
  };

  const cancelUploadRequest = () => {
    axiosCanceler.removePending({ method: 'post', url: uploadUrl });
  };
  // const { createMessage } = useMessage();
  const isClass = ref(false); //文件上传
  const beforeUpload = async (file) => {
    const isTgz = file.name.endsWith('.tgz');
    isClass.value = true;
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
    formState.file = commonItem;
    return false;
  };
  function calculateMD5(file) {
    return new Promise((resolve, reject) => {
      MD5loading.value = true;
      tip.value = '正在检查文件...';
      const spark = new SparkMD5.ArrayBuffer();
      const fileReader = new FileReader();

      fileReader.onload = function (e) {
        //@ts-ignore
        spark.append(e.target.result);
        resolve(spark.end());
      };

      fileReader.onerror = function () {
        reject('Error reading file');
      };

      fileReader.readAsArrayBuffer(file);
    });
  }
  function uploadFile() {
    if (fileList.value.length <= 0) {
      createMessage.error('请先选择文件');
      return;
    }
    uploadFileItem(fileList.value[0]);
  }

  // 文件分片=====START
  const chunkSize = 1024 * 1024 * 50; // 每片50M
  const upload = (model, fileMd5) => {
    let file = model.file;
    let fileReader = new FileReader();
    // 计算文件可分为多少块
    let chunks = Math.ceil(file.size / chunkSize);
    let currentChunk = 0;
    let filePart = null;
    model.chunks = chunks;
    fileReader.onload = async function () {
      const p = uploadChunk(model, filePart, chunks, currentChunk, fileMd5);
      p.then(() => {
        currentChunk++;
        model.successTrunks = currentChunk;
        model.percent = Math.min(model.successTrunks / chunks, 1);
        if (currentChunk < chunks) {
          loadNext(); // 继续切割下一块文件
        } else {
          fileLoading.value = false;
          progressStatus.value = 'success';
          createMessage.success('上传成功！');
          checkFileFn();
        }
      }).catch(() => {
        fileList.value[0].percent = 0;
        fileLoading.value = false;
        progressStatus.value = 'exception';
        createMessage.error('文件上传失败，请点击上传文件按钮，重新上传！');
      });
    };
    fileReader.onerror = function (err) {
      console.log(err);
    };
    function loadNext() {
      fileReader.readAsBinaryString(((filePart as any) = getFilePart(currentChunk, file)));
    }

    loadNext();
  };
  const uploadChunk = (model, filePart, chunks, currentChunk, md5) => {
    const params = {
      data: {
        module: 'ctrl',
        chunkIndex: currentChunk,
        totalChunks: chunks,
        fileName: model.file.name,
      },
      file: filePart,
      md5,
    };
    return uploadPartFile(params, () => {});
  };
  // 获取文件片段
  const getFilePart = (currentChunk, file) => {
    let start = currentChunk * chunkSize;
    let end = start + chunkSize >= file.size ? file.size : start + chunkSize;
    const blobSlice = File.prototype.slice;
    return blobSlice.call(file, start, end);
  };
  // 文件分片=====END

  // 定义超时时间为 15 分钟
  const timeoutDuration = 60 * 15 * 1000;
  // 计时器
  let timerId;
  async function uploadFileItem(item) {
    const fileRaw = await calculateMD5(item.file);
    MD5loading.value = false;
    fileLoading.value = true;
    progressStatus.value = 'normal';
    tip.value = '上传文件中...';
    if (props.isSysSoft) {
      // 系统升级走分片上传的逻辑
      upload(item, fileRaw);
    } else {
      try {
        const dataParams = props.isSoftware ? {} : { module: 'ctrl' };
        await checkFile(
          {
            data: dataParams,
            file: item.file,
            md5: fileRaw,
          },
          function onUploadProgress(progressEvent: ProgressEvent) {
            const complete = ((progressEvent.loaded / progressEvent.total) * 99) | 0;
            item.percent = complete;
          },
        )
          .then(async (res) => {
            fileLoading.value = false;
            item.percent = 100;
            progressStatus.value = 'success';
            if (res.data.code !== 0) {
              createMessage.error(res.data.msg, 3);
            } else {
              checkFileFn();
            }
          })
          .catch(() => {
            fileLoading.value = false;
            progressStatus.value = 'exception';
            createMessage.error('上传失败');
            clearTimeout(timerId); // 清空超级计时器
          });
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
  }
  //已上传文件升级包
  async function checkFileFn() {
    await checkFileList().then((result) => {
      if (result) {
        show.value = true;
        filename.value = result.ctrlName;
        md5Name.value = result.ctrlMd5;
      }
    });
  }
  const handleUpload = async () => {
    if ((filename.value && md5Name.value) || props.isSsm || props.isSoftware) {
      try {
        uploading.value = true;
        let data;

        if (fileList.value.length) {
          data = await Promise.all(
            fileList.value.map((item) => {
              return uploadApiByItem(item);
            }),
          );
        } else {
          data = await uploadApiByItem({ percent: 0, success: '' }).then((res) => {
            return [res];
          });
        }

        uploading.value = false;
        // 生产环境:抛出错误
        const errorList = data.filter((item: any) => !item.success);
        if (errorList.length > 0) {
          throw errorList;
        } else {
          // const text = props.isSoftware
          //   ? t('maintenance.systemUpdate.softwareUpdateStatus')
          //   : t('maintenance.systemUpdate.controlStartUpload');
          // createMessage.success(text);
        }
      } catch (e) {
        uploading.value = false;
        // throw e;
      }
    } else {
      createMessage.error('文件未上传');
    }
  };

  async function uploadApiByItem(item) {
    try {
      item.status = 'uploading';
      const product = deviceInfo.value.deviceType;
      const flashVal = flashData.value;

      // sysSoft（控制板 OTA）：文件已分片上传到 /data/ota/（与 ssm 共享目录），
      // "开始升级"只触发 ssm executeUpgradeApi，不再重复上传——
      // 否则发空 file 字段到 ssm /api/v1/ota/upload 会报 "missing file field"。
      if (props.isSysSoft && !props.isSsm && !props.isSoftware) {
        const fileName = filename.value || item?.file?.name || '';
        if (!fileName) {
          createMessage.error('请先上传升级包', 4);
          item.status = 'error';
          return { success: false, error: 'no uploaded file' };
        }
        const execBody = {
          name: fileName,
          product,
          fileName,
          moduleName: 'ctrl',
          cmdFlag: '',
          version: '',
          flashData: flashVal,
        };
        await executeUpgradeApi(execBody);
        createMessage.success(t('maintenance.systemUpdate.controlStartUpload'), 4);
        item.status = 'success';
        return { success: true, error: null };
      }

      // isSsm / isSoftware：需要上传真实文件
      // isSsm 走真实 ssm /api/v1/ota/upload（不再用 mock upgradeSsmApi）
      const currentApi = props.isSoftware ? upgradeSoftApi : upgradeApi;
      const dataParams = props.isSoftware
        ? {}
        : { module: 'ctrl', flashData: flashVal ? 'true' : 'false' };
      const file = item.file;

      // 守卫：ssm/software 升级必须选文件，否则 ssm 报 "missing file field"
      if (!file) {
        createMessage.error(t('maintenance.systemUpdate.selectNeedFile'), 4);
        item.status = 'error';
        return { success: false, error: 'no file' };
      }

      const res = await currentApi(
        {
          data: dataParams,
          file: file,
        },
        function onUploadProgress(progressEvent: ProgressEvent) {
          const complete = ((progressEvent.loaded / progressEvent.total) * 100) | 0;
          item.percent = complete;
        },
      );
      // upgradeApi / upgradeSoftApi 均 isReturnNativeResponse，res 为原生响应
      const body = res?.data ?? res;
      if (!body || body.code !== 0) {
        createMessage.error(body?.msg || 'upload failed', 4);
        item.status = 'error';
        return { success: false, error: body?.msg };
      }
      item.percent = 100;

      // ssm OTA：上传成功后再调 executeUpgradeApi 触发升级 workflow
      if (props.isSsm) {
        const uploaded = body.result || {};
        const fileName = uploaded.fileName || file?.name || '';
        const execBody = {
          name: fileName,
          product,
          fileName,
          moduleName: 'ctrl',
          cmdFlag: '',
          version: '',
          flashData: flashVal,
        };
        try {
          await executeUpgradeApi(execBody);
          createMessage.success(t('maintenance.systemUpdate.controlStartUpload'), 4);
        } catch (e) {
          // defHttp 已提示错误
          item.status = 'error';
          return { success: false, error: e };
        }
      } else {
        // isSoftware：本地 /api/upgrade 已落盘并自升级
        createMessage.success(body.msg, 4);
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
  //以下是文件上传超时逻辑
  // 监听 fileList[0]?.percent 变化
  watch(
    () => fileList.value[0]?.percent,
    (newVal, oldVal) => {
      if (oldVal === 0) {
        // 开始计时
        // 设置计时器，在 timeoutDuration 后执行超时逻辑
        timerId = setTimeout(() => {
          handleTimeout(newVal);
        }, timeoutDuration);
      } else if (newVal === 100) {
        // 清空计时器
        clearTimeout(timerId);
      }
    },
    { deep: true }, // 开启深层监听
  );

  // 超时逻辑
  const handleTimeout = (percent) => {
    if (percent < 100) {
      fileLoading.value = false;
      progressStatus.value = 'exception';
      createMessage.error('文件传输超时');
    }
  };
</script>
<style scoped lang="less">
  .ant-form-item .ant-upload .tips {
    font-size: 12px;
    color: red;
    position: relative;
    top: 4px;
    opacity: 0.8;
  }

  .formStyle {
    display: flex;
    flex-direction: row;

    .tips {
      font-size: 12px;
      color: red;
      position: relative;
      top: 4px;
      opacity: 0.8;
    }
  }

  .isSsmbtn {
    margin-top: 105px !important;
  }

  :deep(.ant-upload-list-item-progress) {
    bottom: -20px;
  }

  .md5Style {
    width: 380px;
    display: flex;
    flex-direction: column;
    position: relative;

    .spanStyle {
      margin-top: 20px;
      margin-bottom: 38px;
    }
  }

  .isClass {
    margin-top: 65px !important;
    position: absolute;
    bottom: 1rem;
  }

  .is-disabled,
  .is-disabled:hover,
  .is-disabled:focus,
  .is-disabled:active {
    border-color: #0960bd;
    background: #0960bd;
    color: #fff;
  }
</style>
