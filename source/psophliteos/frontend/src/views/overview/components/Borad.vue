<template>
  <a-card :title="t('overview.boardInfor')" :loading="loading">
    <div class="tags flex mb-3 justify-end max-w-900px">
      <div v-for="item in tags" :key="item.label" class="flex justify-center items-center mr-4">
        <i :class="item.status" class="w-8px h-8px mr-1"></i>
        <span>{{ item.label }}</span>
      </div>
    </div>
    <div class="boards">
      <div class="control board" :class="controlBoard.status" @click="toDetail(null)">
        <label>{{ t('overview.controlBoard1') }}</label>
        <span class="num"> {{ 1 }} </span>
        <!-- <div class="actions">
          <div class="restart" title="重启" @click="boardRestart(1, controlBoard.deviceSn)"
            ><ReloadOutlined
          /></div>
        </div> -->
      </div>
      <div class="line">-</div>
      <div
        v-for="(item, index) in coreBoards"
        :key="item.sn"
        @mouseover="currentBoard = item.sn"
        @mouseleave="currentBoard = ''"
        class="spinBox"
      >
        <div class="board" :class="item.status" @click="toDetail(item.sn)">
          <label v-if="index === 0">{{ t('overview.coreBoard1') }}</label>
          <span class="num">{{ item.number }}</span>
          <!-- <div class="actions">
            <div class="restart" title="重启" @click.stop="boardRestart(1, item.number)"
              ><ReloadOutlined
            /></div>
            <div class="shutdown" title="关机" @click.stop="boardRestart(2, item.number)"
              ><PoweroffOutlined
            /></div>
          </div> -->
        </div>
        <a-spin
          :spinning="boardLoading && currentBoard === item.sn"
          v-show="boardLoading && currentBoard === item.sn"
        />
      </div>
    </div>
  </a-card>
</template>
<script lang="ts" setup>
  // const colorsMap = {
  //   error: '#d9d9d9',
  //   running: '#1890ff',
  // };
  import { ref } from 'vue';
  import { Card, Spin } from 'ant-design-vue';
  // import { PoweroffOutlined, ReloadOutlined } from '@ant-design/icons-vue';
  import { storeToRefs } from 'pinia';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useGo } from '/@/hooks/web/usePage';
  // import { operationApi } from '/@/api/overview/index';
  // import { useDebounceFn } from '@vueuse/core';

  const { t } = useI18n();
  const go = useGo();

  defineProps({
    loading: Boolean,
  });
  // const emit = defineEmits(['getDeciveInfo']);

  const ACard = Card;
  const ASpin = Spin;
  const tags = [
    {
      label: t('sys.boardStatus.error'),
      status: 'error',
    },
    {
      label: t('sys.boardStatus.running'),
      status: 'running',
    },
  ];

  // 设备基础信息
  const deviceInfoStore = useDeviceInfo();
  const { deviceStatus: coreBoards, deviceInfo: controlBoard } = storeToRefs(deviceInfoStore);

  // const controlBoard = {
  //   sn: 'control-1',
  //   status: 'running',
  // };

  // 核心板升级 type，1：重启 2：关机 3：唤醒（暂不支持
  // const boardRestart = useDebounceFn(async (type, number) => {
  //   const params = {
  //     type,
  //     number,
  //   };
  //   // console.log(params);
  //   boardLoading.value = true;
  //   try {
  //     const { code } = await operationApi(params);
  //     if (code === 0) {
  //       emit('getDeciveInfo');
  //     }
  //   } catch (error) {
  //     console.log(error);
  //   } finally {
  //     boardLoading.value = false;
  //   }
  // }, 300);

  const toDetail = (sn) => {
    if (!sn) {
      go({ name: 'OverviewDetail' });
    } else {
      go({ name: 'OverviewDetailDny', params: { sn } });
    }
  };

  const boardLoading = ref(false);
  const currentBoard = ref('');
</script>
<style lang="less" scoped>
  .tags {
    i {
      background-color: #1890ff;

      &.error {
        background-color: #e21717;
      }
    }
  }

  .boards {
    display: flex;

    .board {
      width: 52px;
      height: 160px;
      background-color: #1890ff;
      border-radius: 8px;
      margin-right: 16px;
      display: flex;
      justify-content: center;
      align-items: center;
      position: relative;
      cursor: pointer;
      // transition: all 1s 0.2s;
      // &:hover {
      //   background-color: #0050b3;

      //   .num {
      //     opacity: 0;
      //   }

      //   .actions {
      //     transform: rotateY(180deg);
      //     opacity: 1;
      //     transition: all 0.2s;
      //   }
      // }

      &.error {
        background-color: #e21717;
      }

      .num,
      .actions > div {
        width: 24px;
        height: 24px;
        background-color: #fff;
        border-radius: 50%;
        text-align: center;
        line-height: 24px;
      }

      .actions {
        position: absolute;
        display: flex;
        flex-direction: column;
        height: 100%;
        justify-content: space-around;
        // transform: rotateY(180deg);
        opacity: 0;

        .restart {
          color: green;
          cursor: pointer;
        }

        .shutdown {
          color: #e21717;
          cursor: pointer;
        }
      }

      label {
        position: absolute;
        top: -32px;
      }
    }

    .line {
      margin-right: 16px;
      height: 160px;
      line-height: 160px;
      text-align: center;
    }

    .spinBox {
      position: relative;

      :deep(.ant-spin) {
        position: absolute;
        top: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: calc(100% - 16px);
        height: 100%;
        border-radius: 8px;
        z-index: 0;
        background-color: rgb(24 144 255 / 80%);
      }
    }
  }
</style>
