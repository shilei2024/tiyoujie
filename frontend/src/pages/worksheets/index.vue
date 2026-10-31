<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, confirmAction, errorText, familyQuery } from "../../api/client";
import {
  createWorksheet,
  deleteWorksheet,
  listWorksheets,
  type WorksheetSummary,
} from "../../api/practice";
import { session } from "../../state";

interface Child {
  id: string;
  nickname: string;
}
const children = ref<Child[]>([]);
const childId = ref("");
const items = ref<WorksheetSummary[]>([]);
const next = ref<number | null>(null);
const count = ref(0);
const title = ref("");
const busy = ref(false);
const message = ref("");
const guardian = computed(() => session.family?.role === "guardian");
const selectedIndex = computed(() =>
  children.value.findIndex((item) => item.id === childId.value),
);

async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  message.value = "";
  try {
    await action();
  } catch (error) {
    message.value = errorText(error);
  } finally {
    busy.value = false;
  }
}
async function loadChildren() {
  const all: Child[] = [];
  let page: number | null = 1;
  while (page) {
    const result: { results: Child[]; next: number | null } = await api(
      `children/?${familyQuery()}&page=${page}`,
    );
    all.push(...result.results);
    page = result.next;
  }
  children.value = all;
  if (!all.some((item) => item.id === childId.value))
    childId.value = all[0]?.id || "";
}
async function load(append = false) {
  if (!childId.value) return;
  const page = append ? (next.value ?? 1) : 1;
  const data = await listWorksheets(childId.value, page);
  items.value = append ? [...items.value, ...data.results] : data.results;
  next.value = data.next;
  count.value = data.count;
}
async function create() {
  if (!title.value.trim()) {
    message.value = "请填写题单名称。";
    return;
  }
  await run(async () => {
    const created = await createWorksheet(childId.value, title.value.trim());
    title.value = "";
    await load();
    open(created.id);
  });
}
async function remove(id: string) {
  if (!(await confirmAction("删除这份题单？作答记录也会一并删除。"))) return;
  await run(async () => {
    await deleteWorksheet(id);
    await load();
    message.value = "题单已删除。";
  });
}
function open(id: string) {
  uni.navigateTo({
    url: `/pages/worksheets/detail?id=${id}&child_id=${childId.value}`,
  });
}
function selectChild(event: { detail: { value: number | string } }) {
  childId.value = children.value[Number(event.detail.value)]?.id || "";
  void run(() => load());
}
onShow(() => {
  if (!session.user || !session.family) return;
  void run(async () => {
    await loadChildren();
    await load();
  });
});
</script>

<template>
  <view class="page">
    <view class="toolbar"
      ><text class="brand-name">练习题单</text
      ><text class="badge">共 {{ count }} 份</text></view
    >
    <view class="panel">
      <text class="section-title">选择孩子</text>
      <picker
        v-if="children.length"
        :range="children.map((item) => item.nickname)"
        :value="selectedIndex"
        @change="selectChild"
        ><view class="picker-field"
          >{{ children[selectedIndex]?.nickname }} ▾</view
        ></picker
      >
      <text v-else class="note">还没有孩子档案，请先在首页创建。</text>
      <template v-if="guardian"
        ><input
          v-model="title"
          class="input"
          placeholder="题单名称，如：周五错题复习"
          :maxlength="40"
        /><button class="primary" :disabled="busy" @click="create">
          新建题单
        </button></template
      >
      <text v-else class="note">学生账号可以练习家长创建的题单。</text>
    </view>
    <view v-if="!items.length" class="panel">
      <text class="note">暂无题单</text>
      <button class="text-button" @click="run(() => load())">重试</button>
    </view>
    <view v-for="item in items" :key="item.id" class="panel">
      <view class="toolbar"
        ><text class="section-title">{{ item.title }}</text
        ><text class="small muted">{{
          item.created_at.slice(0, 10)
        }}</text></view
      >
      <button class="secondary" @click="open(item.id)">打开题单</button>
      <button
        v-if="guardian"
        class="text-button"
        :disabled="busy"
        @click="remove(item.id)"
      >
        删除题单
      </button>
    </view>
    <button
      v-if="next"
      class="secondary"
      :disabled="busy"
      @click="run(() => load(true))"
    >
      更多题单
    </button>
    <text v-if="message" class="notice" role="status">{{ message }}</text>
  </view>
</template>
