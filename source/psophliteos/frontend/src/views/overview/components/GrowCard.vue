<template>
  <div class="md:flex">
    <template v-for="(item, index) in growCardList" :key="item.title">
      <Card
        size="small"
        :loading="loading"
        :title="item.title"
        class="md:w-1/4 w-full !md:mt-0 !mt-4"
        :class="[index + 1 < 4 && '!md:mr-4']"
        :canExpan="false"
      >
        <div class="py-4 px-4 flex flex-col items-center">
          <Progress
            class="text-center"
            type="circle"
            :format="(percent) => percent + '%'"
            :width="78"
            :percent="item.value"
            :strokeColor="item.color"
          />
          <div v-if="item.description" class="lg:mt-8 mt-4">
            <div v-for="des in item.description" :key="des.label" class="text-left text-xs">
              <label>{{ des.label }}</label>
              :
              <span>{{ des.value }}</span>
            </div>
          </div>
          <!-- <CountTo prefix="$" :startVal="1" :endVal="item.value" class="text-2xl" /> -->
        </div>
      </Card>
    </template>
  </div>
</template>
<script lang="ts" setup>
  import { Progress } from 'ant-design-vue';

  // import { CountTo } from '/@/components/CountTo/index';
  import { Card } from 'ant-design-vue';
  import { growCardList } from '../data';

  defineProps({
    loading: {
      type: Boolean,
    },
  });
</script>
