<template>
  <Modal
    title="选择指标"
    :visible="open"
    :width="720"
    @cancel="emit('update:open', false)"
  >
    <div v-if="categories.length === 0" class="text-center py-20px">
      <Spin />
    </div>
    <div v-else>
      <div class="mb-12px flex items-center gap-8px">
        <Input
          v-model:value="keyword"
          placeholder="搜索字段名"
          allow-clear
          style="width: 240px"
        />
        <Checkbox :checked="allChecked" @change="toggleAll($event)">
          全选/全不选 ({{ checkedCount }}/{{ totalCount }})
        </Checkbox>
      </div>

      <div v-for="cat in catStats" :key="cat.key" class="mb-16px">
        <div class="flex items-center mb-8px">
          <span class="font-bold" style="min-width: 140px">{{ cat.title }}</span>
          <Checkbox
            :checked="cat.allChecked"
            :indeterminate="cat.someChecked && !cat.allChecked"
            @change="toggleCategory(cat, $event)"
          >
            全选 ({{ cat.checkedCount }}/{{ cat.fields.length }})
          </Checkbox>
        </div>
        <CheckboxGroup
          v-model:value="localSel[cat.key]"
          style="display: flex; flex-wrap: wrap"
        >
          <Checkbox
            v-for="f in cat.fields"
            :key="f"
            :value="f"
            style="width: 33%; margin-right: 0; margin-bottom: 4px"
          >
            {{ fieldLabel(f) }}
          </Checkbox>
        </CheckboxGroup>
      </div>
    </div>

    <template #footer>
      <Button @click="emit('update:open', false)">取消</Button>
      <Button type="primary" :loading="saving" @click="onApply">
        保存并应用
      </Button>
    </template>
  </Modal>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, computed, watch } from 'vue';
  import {
    Modal,
    Checkbox,
    CheckboxGroup,
    Input,
    Button,
    Spin,
    message,
  } from 'ant-design-vue';
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
    { immediate: true }
  );

  const filteredCategories = computed(() => {
    const kw = keyword.value.trim().toLowerCase();
    if (!kw) return categories.value;
    return categories.value
      .map((c) => ({
        ...c,
        fields: c.fields.filter(
          (f) => f.toLowerCase().includes(kw) || fieldLabel(f).includes(kw)
        ),
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

  const checkedCount = computed(() =>
    catStats.value.reduce((s, c) => s + c.checkedCount, 0)
  );
  const totalCount = computed(() =>
    catStats.value.reduce((s, c) => s + c.fields.length, 0)
  );
  const allChecked = computed(
    () => totalCount.value > 0 && checkedCount.value === totalCount.value
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
