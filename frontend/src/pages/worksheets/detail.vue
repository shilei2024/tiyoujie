<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { api, confirmAction, errorText, familyQuery } from "../../api/client";
import type { Problem } from "../../api/problems";
import {
  addItem,
  createExport,
  deleteWorksheet,
  downloadExport,
  itemDetail,
  removeItem,
  submitAttempt,
  worksheetDetail,
  type WorksheetDetail,
  type WorksheetItem,
} from "../../api/practice";
import { session } from "../../state";

const id = ref("");
const childId = ref("");
const sheet = ref<WorksheetDetail | null>(null);
const problems = ref<Problem[]>([]);
const answer = reactive<Record<string, string>>({});
const grade = reactive<Record<string, string>>({});
const revealed = reactive<Record<string, WorksheetItem>>({});
const busy = ref(false);
const message = ref("");
const selected = ref(0);
const guardian = computed(() => session.family?.role === "guardian");
const problemChoices = computed(() =>
  problems.value.map((problem) => {
    const text = problem.current_text?.text || "未确认题干";
    return `${text.slice(0, 18)}${text.length > 18 ? "…" : ""}`;
  }),
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
async function load() {
  sheet.value = await worksheetDetail(id.value);
}
async function loadProblems() {
  if (!guardian.value) return;
  const data = await api<{ results: Problem[] }>(
    `problems/?${familyQuery()}&child_id=${childId.value}&page=1`,
  );
  problems.value = data.results.filter((item) => item.current_text);
}
async function add() {
  const problem = problems.value[selected.value];
  if (!problem) {
    message.value = "没有可加入的错题，请先在错题本确认题干。";
    return;
  }
  await run(async () => {
    await addItem(id.value, { origin: "problem", problem_id: problem.id });
    await load();
    message.value = "已加入题单。";
  });
}
async function submit(item: WorksheetItem, choice: string) {
  const value = choice || grade[item.id];
  if (!value) {
    message.value = "请选择作答结果。";
    return;
  }
  await run(async () => {
    const result = await submitAttempt(id.value, item.id, {
      answer: answer[item.id] || "",
      self_grade: value,
    });
    grade[item.id] = "";
    answer[item.id] = "";
    await load();
    message.value = result.review
      ? `已记录：下次复习 ${result.review.due_on}，间隔 ${result.review.interval_days} 天。`
      : "已记录本次作答。";
  });
}
async function reveal(item: WorksheetItem) {
  if (revealed[item.id]) {
    delete revealed[item.id];
    return;
  }
  await run(async () => {
    revealed[item.id] = await itemDetail(id.value, item.id);
  });
}
async function drop(item: WorksheetItem) {
  if (!(await confirmAction("从题单移除这道题？"))) return;
  await run(async () => {
    await removeItem(id.value, item.id);
    await load();
  });
}
async function removeSheet() {
  if (!(await confirmAction("删除整份题单？作答记录会一并删除。"))) return;
  await run(async () => {
    await deleteWorksheet(id.value);
    uni.navigateBack();
  });
}
async function exportSheet() {
  await run(async () => {
    const ticket = await createExport({
      kind: "worksheet",
      child_id: childId.value,
      worksheet_id: id.value,
    });
    await downloadExport(ticket.url);
    message.value = "已生成题单导出。";
  });
}
const originText: Record<string, string> = {
  problem: "错题",
  bank: "授权题库",
  variant: "变式草稿",
};
onLoad((options) => {
  id.value = options?.id || "";
  childId.value = options?.child_id || "";
  void run(async () => {
    await load();
    await loadProblems();
  });
});
</script>

<template>
  <view class="page">
    <view class="toolbar"
      ><text class="brand-name">{{ sheet?.title || "题单" }}</text
      ><text class="badge">{{ sheet?.item_count || 0 }} 题</text></view
    >
    <view v-if="guardian" class="panel">
      <text class="section-title">加入错题</text>
      <picker
        v-if="problemChoices.length"
        :range="problemChoices"
        :value="selected"
        @change="selected = Number($event.detail.value)"
        ><view class="picker-field"
          >{{ problemChoices[selected] }} ▾</view
        ></picker
      >
      <text v-else class="note">暂无可加入的错题。</text>
      <button class="primary" :disabled="busy" @click="add">加入题单</button>
      <text class="note"
        >题目会保存当前题干快照，之后修改错题不会改变题单内容。</text
      >
    </view>
    <view v-if="sheet && !sheet.items.length" class="panel">
      <text class="note">题单为空</text>
    </view>
    <view v-for="item in sheet?.items || []" :key="item.id" class="panel">
      <view class="toolbar"
        ><text class="badge">{{ originText[item.origin] }}</text
        ><text class="small muted">第 {{ item.position }} 题</text></view
      >
      <text v-if="!item.source_available" class="note"
        >来源已变更或不可用，内容已隐藏。</text
      >
      <text v-else class="question">{{ item.text }}</text>
      <text class="note"
        >作答 {{ item.attempts }} 次<text v-if="item.last_grade"
          >· 上次：{{
            item.last_grade === "correct"
              ? "答对"
              : item.last_grade === "wrong"
                ? "答错"
                : "不确定"
          }}</text
        ></text
      >
      <input
        v-model="answer[item.id]"
        class="input"
        placeholder="填写答案或解题过程（可留空）"
        :maxlength="500"
      />
      <view class="row actions"
        ><button
          class="secondary"
          :disabled="busy"
          @click="submit(item, 'correct')"
        >
          答对
        </button>
        <button
          class="secondary"
          :disabled="busy"
          @click="submit(item, 'unsure')"
        >
          不确定
        </button>
        <button
          class="secondary"
          :disabled="busy"
          @click="submit(item, 'wrong')"
        >
          答错
        </button>
      </view>
      <button class="text-button" :disabled="busy" @click="reveal(item)">
        {{ revealed[item.id] ? "收起答案" : "查看答案与解析" }}
      </button>
      <view v-if="revealed[item.id]" class="answer">
        <text class="question"
          >答案：{{ revealed[item.id].answer || "未填写" }}</text
        >
        <text v-if="revealed[item.id].explanation" class="note">{{
          revealed[item.id].explanation
        }}</text>
      </view>
      <button
        v-if="guardian"
        class="text-button"
        :disabled="busy"
        @click="drop(item)"
      >
        从题单移除
      </button>
    </view>
    <view v-if="guardian" class="panel">
      <button class="secondary" :disabled="busy" @click="exportSheet">
        导出题单（HTML 打印版）
      </button>
      <button class="text-button" :disabled="busy" @click="removeSheet">
        删除整份题单
      </button>
    </view>
    <text v-if="message" class="notice" role="status">{{ message }}</text>
  </view>
</template>

<style scoped>
.question {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
  margin: 10px 0;
}
.actions {
  gap: 8px;
  margin: 10px 0;
}
.actions button {
  flex: 1;
  margin: 0;
}
.answer {
  background: #f5f6f8;
  padding: 14px;
  border-radius: 8px;
  margin-top: 12px;
}
</style>
