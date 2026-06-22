<template>
  <a-row :gutter="20" :class="is2xl ? 'h-180px' : 'h-200px'">
    <a-col :span="spanCol" v-for="(item, index) in gridList" :key="item.title">
      <div class="h-full bg-white container">
        <p class="font-bold text-base">{{ item.title }}</p>
        <a-progress
          type="circle"
          :stroke-color="{
            '0%': '#108ee9',
            '100%': '#87d068',
          }"
          :percent="Number(item.usage).toFixed(1)"
          :format="(percent) => `${percent} %`"
          class="!flex justify-center"
        />
        <div class="absolute top-64px" v-show="is2xl">
          <p v-if="item.text">{{ item.text }}</p>
          <template v-if="item.total">
            <p>{{ unitSize((item.total * item.usage) / 100) + ' / ' + unitSize(item.total) }}</p>
          </template>
        </div>
        <div class="absolute w-full text-center top-170px statics" v-show="!is2xl">
          <p v-if="item.text">{{ item.text }}</p>
          <template v-if="item.total">
            <p>{{ unitSize((item.total * item.usage) / 100) + '/' + unitSize(item.total) }}</p>
          </template>
        </div>
        <a-divider
          v-if="index !== gridList.length - 1"
          type="vertical"
          style="height: 100%; position: absolute; right: 0"
        />
      </div>
    </a-col>
  </a-row>
</template>
<script setup>
  import { Row, Col, Progress, Divider } from 'ant-design-vue';
  import { toRefs, computed } from 'vue';
  import { useWindowSize } from '@vueuse/core';
  // import { useI18n } from '/@/hooks/web/useI18n';

  // const { t } = useI18n();
  const ARow = Row;
  const ACol = Col;
  const AProgress = Progress;
  const ADivider = Divider;

  const props = defineProps({
    gridList: {
      type: Array,
      default: () => [],
    },
  });
  const { gridList } = toRefs(props);

  const spanCol = computed(() => {
    return 24 / (gridList.value.length || 24);
  });
  const unitSize = computed(() => {
    return function (size, suffix = '') {
      if (!size) return size;
      const unitStep = ['M', 'G', 'T', 'P', 'E'];
      let step = 0;
      while (size >= 1024) {
        size = size / 1024;
        step++;
      }
      return size.toFixed(1) + unitStep[step] + suffix;
    };
  });
  const { width } = useWindowSize();
  const is2xl = computed(() => {
    return width.value > 2200 ? true : false;
  });
</script>
