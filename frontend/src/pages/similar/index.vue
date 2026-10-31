<script setup lang="ts">
import { computed, ref } from "vue";
import { onHide, onLoad } from "@dcloudio/uni-app";
import { api, errorText } from "../../api/client";
import type { Problem } from "../../api/problems";
import { session } from "../../state";

interface BankItem {
  id: string;
  revision: number;
  text: string;
  answer: string;
  explanation: string;
  answer_source: string;
  explanation_source: string;
  grade: number;
  difficulty: number;
  question_type: string;
  solution_structure: string;
  verification_status: string;
  verification_method: string;
  verification_scope: string;
  match_reasons: string[];
  source: {
    name: string;
    source_type: string;
    source_reference: string;
    license_name: string;
    attribution: string;
    usage_conditions: string;
    valid_until: string;
  };
}
interface Draft {
  id: string;
  intent: string;
  generator: string;
  stale: boolean;
  source_available: boolean;
  payload: {
    text: string;
    answer: string;
    explanation: string;
    machine_check: { result: string; scope: string };
  } | null;
}
const id = ref(""),
  problem = ref<Problem | null>(null),
  busy = ref(false),
  message = ref("");
const points = ref<{ code: string; name: string }[]>([]),
  selectedPoint = ref("");
const keyword = ref(""),
  grade = ref(""),
  difficulty = ref(""),
  questionType = ref(""),
  structure = ref("");
const items = ref<BankItem[]>([]),
  searched = ref(false),
  reason = ref(""),
  truncated = ref(false);
const drafts = ref<Draft[]>([]),
  nextPage = ref<number | null>(null),
  reveal = ref("");
const intents = ["换数字", "变条件", "逆向思考", "情境应用"],
  intentKeys = ["numbers", "conditions", "reverse", "context"];
const intent = ref(0);
const guardian = computed(() => session.family?.role === "guardian");
const pointNames = computed(() => [
  "沿用原题知识点",
  ...points.value.map((p) => p.name),
]);
const pointIndex = computed(
  () => points.value.findIndex((p) => p.code === selectedPoint.value) + 1,
);
const status = (item: BankItem) =>
  item.verification_status === "human_verified"
    ? "答案经人工复核"
    : "结构化算式经机器核对";
let pending: { fingerprint: string; key: string } | undefined;
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
async function search() {
  const params: string[] = [];
  for (const [key, value] of Object.entries({
    q: keyword.value.trim(),
    knowledge_point: selectedPoint.value,
    grade: grade.value,
    difficulty: difficulty.value,
    question_type: questionType.value.trim(),
    solution_structure: structure.value.trim(),
  })) {
    if (value) params.push(`${key}=${encodeURIComponent(value)}`);
  }
  const data = await api<{
    results: BankItem[];
    reason: string;
    truncated: boolean;
  }>(`problems/${id.value}/similar/?${params.join("&")}`);
  items.value = data.results;
  reason.value = data.reason;
  truncated.value = data.truncated;
  searched.value = true;
  reveal.value = "";
}
async function loadDrafts(page = 1) {
  const data = await api<{ results: Draft[]; next: number | null }>(
    `problems/${id.value}/variants/?page=${page}`,
  );
  drafts.value = page === 1 ? data.results : [...drafts.value, ...data.results];
  nextPage.value = data.next;
}
async function generate(item: BankItem) {
  if (!problem.value?.current_text) return;
  const body = {
    bank_item_id: item.id,
    text_version_id: problem.value.current_text.id,
    expected_revision: problem.value.revision,
    intent: intentKeys[intent.value],
  };
  const fingerprint = JSON.stringify(body);
  if (pending?.fingerprint !== fingerprint)
    pending = {
      fingerprint,
      key: `variant_${Date.now()}_${Math.random().toString(36).slice(2, 14)}`,
    };
  await api(`problems/${id.value}/variants/`, "POST", body, {
    "Idempotency-Key": pending.key,
  });
  pending = undefined;
  await loadDrafts();
  message.value = "已保存规则变式草稿，仍需人工核对。";
}
onLoad((options) => {
  id.value = options?.id || "";
  void run(async () => {
    const [p, dictionary] = await Promise.all([
      api<Problem>(`problems/${id.value}/`),
      api<{ results: { code: string; name: string }[] }>("knowledge-points/"),
    ]);
    problem.value = p;
    points.value = dictionary.results;
    await loadDrafts();
    await search();
  });
});
onHide(() => {
  reveal.value = "";
});
</script>

<template>
  <view class="page">
    <view class="toolbar"
      ><text class="brand-name">同类题与变式</text
      ><text class="badge">来源可追溯</text></view
    >
    <view v-if="problem?.current_text" class="panel">
      <text class="eyebrow">从这道错题出发</text
      ><text class="question">{{ problem.current_text.text }}</text>
      <text class="note"
        >优先查找授权有效、审核通过的题目。匹配理由用于说明检索依据。</text
      >
    </view>
    <view class="panel">
      <text class="section-title">找准下一道题</text>
      <input
        v-model="keyword"
        class="input"
        placeholder="题干关键词（可选）"
        :maxlength="80"
      />
      <picker
        :range="pointNames"
        :value="pointIndex"
        @change="
          selectedPoint = points[Number($event.detail.value) - 1]?.code || ''
        "
        ><view class="picker-field"
          >知识点：{{ pointNames[pointIndex] }} ▾</view
        ></picker
      >
      <view class="form-row"
        ><input
          v-model="grade"
          class="input"
          type="number"
          placeholder="年级 1–12"
          :maxlength="2" /><input
          v-model="difficulty"
          class="input"
          type="number"
          placeholder="难度 1–5"
          :maxlength="1"
      /></view>
      <input
        v-model="questionType"
        class="input"
        placeholder="题型（与题库标签一致，可选）"
        :maxlength="48"
      />
      <input
        v-model="structure"
        class="input"
        placeholder="解题结构（与题库标签一致，可选）"
        :maxlength="64"
      />
      <button class="primary" :disabled="busy" @click="run(search)">
        查找同类题
      </button>
      <text class="note">{{ reason }}</text
      ><text v-if="truncated" class="note"
        >候选较多，本次比较前 200 题，请增加筛选条件。</text
      >
      <text v-if="searched && !items.length" class="note">暂无符合条件的题目</text>
    </view>
    <view v-if="guardian && items.length" class="panel">
      <text class="section-title">举一反三方向</text>
      <picker
        :range="intents"
        :value="intent"
        @change="intent = Number($event.detail.value)"
        ><view class="picker-field">{{ intents[intent] }} ▾</view></picker
      >
      <text class="note"
        >当前提供有理数算式的规则变式，不调用
        AI、不消耗体验点。生成结果只保存为私人草稿，需核对题意、单位与解析。</text
      >
    </view>
    <view v-for="item in items" :key="item.id" class="panel">
      <view class="toolbar"
        ><text class="badge">{{ status(item) }}</text
        ><text class="small muted"
          >{{ item.grade }} 年级 · 难度 {{ item.difficulty }}/5</text
        ></view
      >
      <text class="question">{{ item.text }}</text>
      <text class="note"
        >{{ item.question_type }} · {{ item.solution_structure }}</text
      >
      <text v-for="why in item.match_reasons" :key="why" class="note"
        >匹配：{{ why }}</text
      >
      <text class="note"
        >来源：{{ item.source.name }} · {{ item.source.source_reference }}</text
      >
      <text class="note"
        >许可：{{ item.source.license_name }} · 有效至
        {{ item.source.valid_until.slice(0, 10) }}</text
      >
      <text class="note"
        >署名：{{ item.source.attribution }}；使用条件：{{
          item.source.usage_conditions
        }}</text
      >
      <button
        class="secondary"
        @click="reveal = reveal === item.id ? '' : item.id"
      >
        展开或收起答案
      </button>
      <view v-if="reveal === item.id" class="answer"
        ><text class="question">答案：{{ item.answer }}</text
        ><text class="question">{{ item.explanation }}</text
        ><text class="note"
          >答案来源：{{ item.answer_source }}；解析来源：{{
            item.explanation_source
          }}</text
        ><text class="note">{{ item.verification_scope }}</text></view
      >
      <button
        v-if="guardian"
        class="secondary"
        :disabled="busy"
        @click="run(() => generate(item))"
      >
        保存一份变式草稿
      </button>
    </view>
    <view class="panel">
      <text class="section-title">变式草稿</text
      ><text class="note">草稿未通过发布审核，不能作为已验证题使用。</text>
      <text v-if="!drafts.length" class="note"
        >暂无草稿。找到合适的题库题目后，可选择方向生成。</text
      >
      <view v-for="draft in drafts" :key="draft.id" class="draft">
        <text class="badge">规则生成 · 待人工核验</text>
        <text v-if="draft.stale" class="note">关联的是原题的历史版本。</text>
        <text v-if="!draft.source_available" class="note"
          >来源已变更、到期或撤回，本草稿内容暂不可展示。</text
        >
        <template v-else-if="draft.payload">
          <text class="question">{{ draft.payload.text }}</text>
          <button
            class="secondary"
            @click="reveal = reveal === draft.id ? '' : draft.id"
          >
            展开或收起草稿答案
          </button>
          <view v-if="reveal === draft.id"
            ><text class="question">候选答案：{{ draft.payload.answer }}</text
            ><text class="note">{{ draft.payload.explanation }}</text
            ><text class="note">{{
              draft.payload.machine_check.scope
            }}</text></view
          >
        </template>
      </view>
      <button
        v-if="nextPage"
        class="secondary"
        :disabled="busy"
        @click="run(() => loadDrafts(nextPage!))"
      >
        更多草稿
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
  margin: 12px 0;
}
.draft {
  border-top: 1px solid #eef0f4;
  padding-top: 20px;
  margin-top: 20px;
}
.answer {
  background: #f5f6f8;
  padding: 16px;
  border-radius: 8px;
  margin-top: 16px;
}
</style>
