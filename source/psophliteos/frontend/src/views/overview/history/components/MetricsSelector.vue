<template>
  <Modal title="选择指标" :visible="open" :width="760" @cancel="emit('update:open', false)">
    <div v-if="categories.length === 0" class="text-center py-40px">
      <Spin />
    </div>
    <div v-else class="selector-body">
      <!-- 顶部工具栏 -->
      <div class="toolbar">
        <div class="toolbar-left">
          <Input
            v-model:value="keyword"
            placeholder="搜索字段名"
            allow-clear
            style="width: 220px"
          />
        </div>
        <div class="toolbar-right">
          <span class="count-text">
            已选 <b class="count-num">{{ checkedCount }}</b> / {{ totalCount }}
          </span>
          <Checkbox :checked="allChecked" @change="toggleAll($event)">全选 / 全不选</Checkbox>
        </div>
      </div>

      <!-- 分组卡片 -->
      <div class="group-list">
        <div v-for="cat in catStats" :key="cat.key" class="group-card">
          <div class="group-head">
            <span class="group-title">{{ cat.title }}</span>
            <Checkbox
              class="group-check"
              :checked="cat.allChecked"
              :indeterminate="cat.someChecked && !cat.allChecked"
              @change="toggleCategory(cat, $event)"
            >
              全选
            </Checkbox>
            <span class="group-count">{{ cat.checkedCount }}/{{ cat.fields.length }}</span>
          </div>
          <CheckboxGroup v-model:value="localSel[cat.key]" class="group-fields">
            <Checkbox v-for="f in cat.fields" :key="f" :value="f" class="field-check">
              {{ fieldLabel(f) }}
            </Checkbox>
          </CheckboxGroup>
        </div>
      </div>
    </div>

    <!-- 底部操作 -->
    <template #footer>
      <div class="modal-footer">
        <span class="footer-hint" v-if="!saving">提示：勾选后点击「保存并应用」生效</span>
        <Button @click="emit('update:open', false)">取消</Button>
        <Button type="primary" :loading="saving" @click="onApply"> 保存并应用 </Button>
      </div>
    </template>
  </Modal>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, computed, watch } from 'vue';
  import { Modal, Checkbox, CheckboxGroup, Input, Button, Spin, message } from 'ant-design-vue';
  import { GROUP_DEFS, fieldToGroup, fieldLabel } from '../metricsGroup';
  import { saveSelection } from '/@/api/overview/metrics';

  const props = defineProps<{
    open: boolean;
    allFields: string[];
    selected: string[];
  }>();
  const emit = defineEmits<{
    (e: 'update:open', v: boolean): void;
    (e: 'apply', fields: string[]): void;
  }>();

  const keyword = ref('');
  const saving = ref(false);

  // 按分组组织全部字段（排除 timestamp）
  const categories = computed(() => {
    return GROUP_DEFS.map((g) => {
      const fields = props.allFields.filter((f) => fieldToGroup(f) === g.key);
      return { ...g, fields };
    }).filter((g) => g.fields.length > 0);
  });

  const localSel = ref<Record<string, string[]>>({});

  watch(
    () => props.open,
    (o) => {
      if (!o) return;
      keyword.value = '';
      const init: Record<string, string[]> = {};
      for (const g of GROUP_DEFS) init[g.key] = [];
      for (const f of props.selected) {
        const k = fieldToGroup(f);
        if (k && init[k]) init[k].push(f);
      }
      localSel.value = init;
    },
    { immediate: true },
  );

  const filteredCategories = computed(() => {
    const kw = keyword.value.trim().toLowerCase();
    if (!kw) return categories.value;
    return categories.value
      .map((c) => ({
        ...c,
        fields: c.fields.filter((f) => f.toLowerCase().includes(kw) || fieldLabel(f).includes(kw)),
      }))
      .filter((c) => c.fields.length > 0);
  });

  const catStats = computed(() => {
    return filteredCategories.value.map((c) => {
      const sel = localSel.value[c.key] || [];
      const checkedCount = sel.filter((f) => c.fields.includes(f)).length;
      return {
        ...c,
        checkedCount,
        allChecked: c.fields.length > 0 && checkedCount === c.fields.length,
        someChecked: checkedCount > 0,
      };
    });
  });

  const checkedCount = computed(() => catStats.value.reduce((s, c) => s + c.checkedCount, 0));
  const totalCount = computed(() => catStats.value.reduce((s, c) => s + c.fields.length, 0));
  const allChecked = computed(
    () => totalCount.value > 0 && checkedCount.value === totalCount.value,
  );

  function toggleCategory(cat: any, e: any) {
    const checked = e.target.checked;
    const cur = new Set(localSel.value[cat.key] || []);
    if (checked) {
      for (const f of cat.fields) cur.add(f);
    } else {
      for (const f of cat.fields) cur.delete(f);
    }
    localSel.value = { ...localSel.value, [cat.key]: [...cur] };
  }

  function toggleAll(e: any) {
    const checked = e.target.checked;
    const init: Record<string, string[]> = {};
    for (const c of filteredCategories.value) {
      init[c.key] = checked ? [...c.fields] : [];
    }
    localSel.value = init;
  }

  async function onApply() {
    const all = Object.values(localSel.value).flat();
    saving.value = true;
    const ok = await saveSelection(all);
    saving.value = false;
    if (!ok) {
      message.warning('保存到后端失败，仅本次生效');
    }
    emit('apply', all);
    emit('update:open', false);
  }
</script>
<style lang="less" scoped>
  .selector-body {
    padding-top: 4px;
  }

  /* 顶部工具栏 */
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    margin-bottom: 12px;
    background: #fafafa;
    border: 1px solid #f0f0f0;
    border-radius: 6px;

    .toolbar-right {
      display: flex;
      align-items: center;
      gap: 16px;

      .count-text {
        font-size: 12px;
        color: #666;

        .count-num {
          color: #0960bd;
          font-size: 14px;
        }
      }
    }
  }

  /* 分组卡片列表 */
  .group-list {
    max-height: 52vh;
    overflow-y: auto;
    padding-right: 4px;
  }

  .group-card {
    border: 1px solid #f0f0f0;
    border-radius: 8px;
    margin-bottom: 10px;
    overflow: hidden;
    transition: border-color 0.2s;

    &:hover {
      border-color: #d9d9d9;
    }

    .group-head {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 14px;
      background: #fafafa;
      border-bottom: 1px solid #f0f0f0;

      .group-title {
        font-weight: 600;
        font-size: 13px;
        color: #333;
        flex: 0 0 auto;
      }

      .group-check {
        margin-left: auto;
        font-size: 12px;
      }

      .group-count {
        font-size: 12px;
        color: #999;
        flex: 0 0 auto;
      }
    }

    .group-fields {
      display: flex;
      flex-wrap: wrap;
      padding: 10px 14px 6px;
      gap: 0;
    }
  }

  .field-check {
    width: 33.333%;
    margin-right: 0;
    margin-bottom: 6px;
    font-size: 12px;
  }

  /* 底部操作 */
  .modal-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;

    .footer-hint {
      margin-right: auto;
      font-size: 12px;
      color: #999;
    }
  }
</style>
