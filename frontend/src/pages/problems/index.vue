<script setup lang="ts">
import { computed, ref } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { api, errorText, familyQuery } from "../../api/client";
import { type Problem } from "../../api/problems";
import { navHint, session } from "../../state";
import CustomTabBar from "../../components/custom-tab-bar/index.vue";

interface Child {
  id: string;
  nickname: string;
}
const items = ref<Problem[]>([]),
  children = ref<Child[]>([]),
  childId = ref("");
const query = ref(""),
  chapter = ref(""),
  grade = ref("");
const busy = ref(false),
  message = ref(""),
  next = ref<number | null>(null),
  count = ref(0);
const guardian = computed(() => session.family?.role === "guardian");
const choices = computed(() => [
  { id: "", nickname: "全部孩子" },
  ...children.value,
]);
const selectedIndex = computed(() =>
  choices.value.findIndex((item) => item.id === childId.value),
);
onLoad((options) => {
  childId.value = options?.child_id || "";
});
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
async function load(append = false) {
  const params = `${familyQuery()}&page=${append ? next.value : 1}&q=${encodeURIComponent(query.value)}&chapter=${encodeURIComponent(chapter.value)}${childId.value ? `&child_id=${childId.value}` : ""}${grade.value ? `&grade=${grade.value}` : ""}`;
  const result = await api<{
    results: Problem[];
    next: number | null;
    count: number;
  }>(`problems/?${params}`);
  items.value = append ? [...items.value, ...result.results] : result.results;
  next.value = result.next;
  count.value = result.count;
}
onShow(() => {
  if (navHint.childId) {
    childId.value = navHint.childId;
    navHint.childId = "";
  }
  if (session.user && session.family)
    void run(async () => {
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
      await load();
    });
});
function select(event: { detail: { value: number | string } }) {
  childId.value = choices.value[Number(event.detail.value)]?.id || "";
  void run(() => load());
}
function open(id: string) {
  uni.navigateTo({ url: `/pages/problems/detail?id=${id}` });
}
function create() {
  void run(async () => {
    if (!childId.value) throw new Error("请先选择要录入错题的孩子。");
    const problem = await api<Problem>("problems/", "POST", {
      child_id: childId.value,
    });
    open(problem.id);
  });
}
function back() {
  uni.switchTab({ url: "/pages/index/index" });
}
</script>
<template>
  <view class="page page-tab">
    <view class="intro"
      ><text class="heading">错题本</text></view
    >
    <view v-if="message" class="feedback" role="status">{{ message }}</view>
    <template v-if="session.user && session.family">
      <view class="panel"
        ><view class="row"
          ><text class="section-title">查找错题</text
          ><text class="badge">{{ count }} 道</text></view
        >
        <picker
          :range="choices"
          range-key="nickname"
          :value="selectedIndex"
          :disabled="busy"
          @change="select"
          ><view class="picker-field"
            >{{ choices[selectedIndex]?.nickname || "全部孩子" }} ⌄</view
          ></picker
        >
        <input
          v-model="query"
          class="input"
          aria-label="搜索题干"
          placeholder="搜索题干关键词"
          maxlength="100"
          :disabled="busy"
          @confirm="run(() => load())"
        />
        <view class="form-row"
          ><input
            v-model="chapter"
            class="input"
            aria-label="章节筛选"
            placeholder="章节（可选）"
            maxlength="64"
            :disabled="busy" /><input
            v-model="grade"
            class="input grade-input"
            aria-label="年级筛选"
            placeholder="年级（可选）"
            type="number"
            maxlength="2"
            :disabled="busy"
        /></view>
        <view class="actions"
          ><button
            class="secondary compact"
            :disabled="busy"
            @click="run(() => load())"
          >
            搜索错题</button
          ><button
            v-if="guardian"
            class="primary compact"
            :disabled="busy || !childId"
            @click="create"
          >
            录入新的错题
          </button></view
        >
        <text v-if="guardian && !childId" class="note"
          >先选择一个孩子，再开始录入。</text
        >
      </view>
      <view v-if="!items.length" class="panel empty">暂无错题<button
          class="text-button"
          @click="run(() => load())"
          >重试</button
        ></view>
      <view v-for="item in items" :key="item.id" class="panel"
        ><view class="row"
          ><text class="small muted"
            >{{
              children.find((child) => child.id === item.child_id)?.nickname
            }}
            · {{ item.chapter || "章节待整理" }}</text
          ><text
            :class="
              'badge' +
              (item.status === 'confirmed'
                ? ' badge-success'
                : item.status === 'needs_review'
                  ? ' badge-warning'
                  : '')
            "
            >{{
              item.status === "confirmed"
                ? "题干已确认"
                : item.status === "needs_review"
                  ? "OCR 待校对"
                  : "待录入"
            }}</text></view
        >
        <text class="question-preview">{{
          item.current_text?.text || "待录入的错题"
        }}</text
        ><text class="note"
          >{{ item.assets.length }} 张私有图片 ·
          {{ item.source || "来源待填写" }}</text
        ><button class="text-button" @click="open(item.id)">
          查看与校对 →
        </button>
      </view>
      <button
        v-if="next"
        class="secondary"
        :disabled="busy"
        @click="run(() => load(true))"
      >
        加载更多错题
      </button>
    </template>
    <CustomTabBar :active="1" />
  </view>
</template>
<style scoped>
.question-preview {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 18px;
  line-height: 1.9;
  margin-top: 18px;
}
</style>
