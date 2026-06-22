<template>
  <div style="margin: 13% 40%">
    <div class="content">
      <div style="width: 100%; font-size: 25px; font-weight: bold; margin-bottom: 20px">{{
        t('logs.logloading.sysLog')
      }}</div>
      <a-button type="primary" style="width: 80%; height: 40px; font-size: 20px" @click="loading"
        >{{ t('logs.logloading.loading') }} {{
      }}</a-button>

      <Loading :loading="compState.loading" :tip="compState.tip" />
    </div>
  </div>
</template>
<script lang="ts" setup>
  import { reactive } from 'vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { Loading } from '/@/components/Loading';
  import { LogDownload } from '/@/api/logs/index';
  // import { useMessage } from '/@/hooks/web/useMessage';
  // const { createMessage } = useMessage();
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  if (!deviceStore.deviceType) {
    deviceStore.getDeviceInfo();
  }
  const { t } = useI18n();
  const compState = reactive({
    loading: false,
    tip: '文件下载中...',
  });
  async function loading(fileName) {
    compState.loading = true;
    const ret = await LogDownload();
    const blob = new Blob([ret.data], { type: 'application/x-compressed-tar' });
    let filename = fileName || ' ';
    try {
      filename = decodeURI(ret.headers['content-disposition'].split(';')[1].split('filename=')[1]);
    } catch (e) {
      console.log(e);
    }
    // filename = filename.split('.')[0] + '.tgz';
    filename = 'sys_log.tgz';

    //  @ts-ignore
    if (typeof window.navigator.msSaveBlob !== 'undefined') {
      //  @ts-ignore
      window.navigator.msSaveBlob(blob, filename);
    } else {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.style.display = 'none';
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      //  @ts-ignore
      URL.revokeObjectURL(url.href);
      document.body.removeChild(link);
    }

    compState.loading = false;
  }
</script>
<style lang="less" scoped>
  .content {
    height: 150px;
    width: 150px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }
</style>
