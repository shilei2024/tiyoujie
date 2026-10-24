<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, errorText, familyQuery } from "../../api/client";
import {
  createExport,
  downloadExport,
  gradeProblem,
  reviewQueue,
  trends,
  type Queue,
  type QueueRow,
  type Trend,
} from "../../api/practice";
import { session } from "../../state";

interface Child {
  id: string;
  nickname: string;
  grade: number | null;
}
const children = ref<Child[]>([]);
const childId = ref("");
const queue = ref<Queue | null>(null);
const trend = ref<Trend | null>(null);
const busy = ref(false);
const message = ref("");
const grading = ref("");
const maxAttempts = computed(() =>
  Math.max(1, ...(trend.value?.weeks || []).map((week) => week.attempts)),
);
const selectedIndex = computed(() =>
  children.value.findIndex((item) => item.id === childId.value),
);
const stageText: Record<string, string> = {
  new: "新错题",
  learning: "学习中",
  review: "复习中",
  mastered: "已掌握",
};

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
async function load() {
  if (!childId.value) return;
  const [queueData, trendData] = await Promise.all([
    reviewQueue(childId.value),
    trends(childId.value, 8),
  ]);
  queue.value = queueData;
  trend.value = trendData;
}
async function grade(row: QueueRow, value: string) {
  if (grading.value) return;
  grading.value = row.problem_id;
  try {
    await run(async () => {
      const result = await gradeProblem(row.problem_id, value);
      message.value = `已记录：下次复习 ${result.due_on}，间隔 ${result.interval_days} 天。`;
      await load();
    });
  } finally {
    grading.value = "";
  }
}
async function exportSummary() {
  await run(async () => {
    const ticket = await createExport({
      kind: "summary",
      child_id: childId.value,
    });
    await downloadExport(ticket.url);
    message.value = "已生成学习概览导出。";
  });
}
function selectChild(event: { detail: { value: number | string } }) {
  childId.value = children.value[Number(event.detail.value)]?.id || "";
  void run(load);
}
function openProblem(problemId: string) {
  uni.navigateTo({ url: `/pages/problems/detail?id=${problemId}` });
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
      ><text class="brand-name">今日复习</text
      ><text class="badge">间隔复习</text></view
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
      <text class="note"
        >复习间隔为 1、3、7、14、30、60、120 天；答错会回到 1
        天。全部按本地日历日计算，不调用 AI。</text
      >
    </view>
    <view v-if="queue" class="panel">
      <view class="toolbar"
        ><text class="section-title">今天待复习 {{ queue.counts.due }} 题</text
        ><text class="small muted">{{ queue.date }}</text></view
      >
      <view class="stats"
        ><text class="note">新错题 {{ queue.counts.new }}</text
        ><text class="note">学习中 {{ queue.counts.learning }}</text
        ><text class="note">复习中 {{ queue.counts.review }}</text
        ><text class="note">已掌握 {{ queue.counts.mastered }}</text></view
      >
      <text v-if="!queue.results.length" class="note"
        >今天没有待复习的题目。可以到错题本添加新错题，或创建题单练习。</text
      >
      <view v-for="row in queue.results" :key="row.problem_id" class="task">
        <view class="toolbar"
          ><text class="badge">{{ stageText[row.stage] || row.stage }}</text
          ><text class="small muted"
            >{{ row.due_on
            }}<text v-if="row.overdue_days"
              >· 逾期 {{ row.overdue_days }} 天</text
            ></text
          ></view
        >
        <text class="question">{{ row.text }}</text>
        <text class="note"
          >上次间隔 {{ row.interval_days }} 天 · 连续答对
          {{ row.streak }} 次</text
        >
        <view class="row actions"
          ><button
            class="secondary"
            :disabled="grading === row.problem_id"
            @click="grade(row, 'correct')"
          >
            答对
          </button>
          <button
            class="secondary"
            :disabled="grading === row.problem_id"
            @click="grade(row, 'unsure')"
          >
            不确定
          </button>
          <button
            class="secondary"
            :disabled="grading === row.problem_id"
            @click="grade(row, 'wrong')"
          >
            答错
          </button>
        </view>
        <button class="text-button" @click="openProblem(row.problem_id)">
          查看错题详情 →
        </button>
      </view>
    </view>
    <view v-if="trend" class="panel">
      <text class="section-title">最近 8 周</text>
      <text class="note">{{ trend.sample.note }}</text>
      <view class="chart">
        <view v-for="week in trend.weeks" :key="week.start" class="bar-wrap">
          <view
            class="bar"
            :style="{ height: `${(week.attempts / maxAttempts) * 72}px` }"
          />
          <text class="small muted">{{ week.start.slice(5) }}</text>
          <text class="small muted">{{ week.attempts }}</text>
        </view>
      </view>
      <text class="note"
        >新增错题：{{
          trend.weeks.reduce((sum, week) => sum + week.problems_added, 0)
        }}
        道；待复习 {{ trend.review.due }} 道。</text
      >
      <view v-for="point in trend.knowledge_points" :key="point.code">
        <text class="note"
          >{{ point.code }}：作答 {{ point.attempts }} 次，{{
            point.accuracy === null
              ? "样本不足，不计算正确率"
              : `正确率 ${Math.round(point.accuracy * 100)}%`
          }}</text
        >
      </view>
      <button class="secondary" :disabled="busy" @click="exportSummary">
        导出学习概览（CSV）
      </button>
    </view>
    <text v-if="message" class="notice" role="status">{{ message }}</text>
  </view>
</template>

<style scoped>
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 12px 0;
}
.task {
  border-top: 1px solid #dce2d8;
  padding-top: 18px;
  margin-top: 18px;
}
.actions {
  gap: 8px;
  margin: 12px 0;
}
.actions button {
  flex: 1;
  margin: 0;
}
.chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  margin: 16px 0;
  min-height: 96px;
}
.bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.bar {
  width: 100%;
  min-height: 2px;
  background: #315b45;
  border-radius: 4px 4px 0 0;
}
.question {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
  margin: 10px 0;
}
</style>
