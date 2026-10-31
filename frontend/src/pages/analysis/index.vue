<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { onLoad, onShow, onHide, onUnload } from "@dcloudio/uni-app";
import { api, confirmAction, errorText, familyQuery } from "../../api/client";
import { type Problem, type OCRJob } from "../../api/problems";
import {
  ensureProviderConsent,
  type AnalysisModel,
  type AnalysisItem,
  type FeedbackItem,
} from "../../api/analysis";
import { session } from "../../state";

interface Credential {
  id: string;
  provider: string;
  masked_key: string;
  enabled: boolean;
}
const id = ref(""),
  problem = ref<Problem | null>(null),
  busy = ref(false),
  message = ref("");
const guardian = computed(() => session.family?.role === "guardian");
const models = ref<AnalysisModel[]>([]),
  modelIndex = ref(0),
  outbound = ref(false);
const model = computed(() => models.value[modelIndex.value]);
const modelNames = computed(() =>
  models.value.map((item) => `${item.provider} · ${item.model_name}`),
);
const mode = ref<"platform_trial" | "byok">("platform_trial"),
  costConfirmed = ref(false);
const credentials = ref<Credential[]>([]),
  credentialIndex = ref(0);
const usableKeys = computed(() =>
  credentials.value.filter(
    (item) => item.enabled && item.provider === model.value?.provider,
  ),
);
const credentialNames = computed(() =>
  usableKeys.value.map((item) => item.masked_key),
);
const remaining = ref(0),
  platformEnabled = ref(false),
  work = ref("");
const job = ref<OCRJob | null>(null),
  pending = computed(
    () => !!job.value && ["queued", "running"].includes(job.value.status),
  );
const items = ref<AnalysisItem[]>([]),
  nextResult = ref<number | null>(null),
  selectedId = ref("");
const selected = computed(
  () =>
    items.value.find((item) => item.id === selectedId.value) || items.value[0],
);
const hintCount = ref(0),
  full = ref(false),
  feedback = ref<FeedbackItem[]>([]),
  nextFeedback = ref<number | null>(null);
const correction = ref("");
let visible = false,
  timer: ReturnType<typeof setTimeout> | undefined;
let preferenceLoaded = false;
let requestIdentity: { fingerprint: string; key: string } | undefined;
const categories: Record<string, string> = {
  concept: "概念理解",
  formula: "公式使用",
  calculation: "计算过程",
  reading: "审题条件",
  missing_step: "解题步骤",
  diagram: "图形条件",
  transfer: "知识迁移",
  unknown: "暂无法判断",
};
const states: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  completed: "分析已生成·待核验",
  failed: "分析未完成",
  cancelled: "已取消",
};
const errors: Record<string, string> = {
  AI_DISABLED: "分析外发已关闭。",
  INPUT_CHANGED: "题干已更新，请重新载入。",
  TASK_ACCESS_REVOKED: "资料或授权已变化，结果未发布。",
  MODEL_CAPABILITY_MISMATCH: "模型不支持本次任务。",
  AI_OUTPUT_INVALID: "结果不符合安全结构要求，未发布。",
  PROVIDER_TIMEOUT: "供应商结果未能确认，费用需要核对，请勿连续重试。",
  PROVIDER_OUTCOME_UNKNOWN: "任务中断、费用待核对，系统不会自动重发。",
  CREDENTIAL_REVOKED: "凭证已更改或停用，请重新选择。",
  CREDENTIAL_INVALID: "所选凭证格式不可用，请检查自己的配置。",
  PROVIDER_AUTH_INVALID: "供应商拒绝了所选凭证，请核对后重试。",
  PROVIDER_BALANCE_INSUFFICIENT: "所选供应商账户余额不足，不会切换费用模式。",
  PROVIDER_RATE_LIMITED: "供应商当前限流，请稍后检查任务状态。",
  PROVIDER_PERMISSION_DENIED: "所选账户没有该模型的使用权限。",
  PROVIDER_INPUT_INVALID: "供应商不接受本次输入，请核对模型能力和题干。",
  BUDGET_RECHECK_FAILED: "预算或价格发生变化，任务未发送。",
};
const feeNames: Record<string, string> = {
  reserved: "平台费用已预占",
  settled: "平台费用已结算",
  not_sent: "确认未发送",
  unknown: "费用待核对",
  byok_pending: "由你的供应商账户计费",
  byok_usage_known: "已记录 BYOK 用量，实际费用以供应商账单为准",
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
function resetReveal() {
  hintCount.value = 0;
  full.value = false;
  correction.value = "";
  feedback.value = [];
  nextFeedback.value = null;
}
watch(() => selected.value?.id, resetReveal);
function openSettings() {
  uni.switchTab({ url: "/pages/settings/index" });
}
async function loadResults(append = false) {
  const result = await api<{ results: AnalysisItem[]; next: number | null }>(
    `problems/${id.value}/analyses/?page=${append ? nextResult.value : 1}`,
  );
  items.value = append ? [...items.value, ...result.results] : result.results;
  nextResult.value = result.next;
}
async function load() {
  problem.value = await api<Problem>(`problems/${id.value}/`);
  const config = await api<{
    results: AnalysisModel[];
    outbound_enabled: boolean;
  }>("ai/models/");
  models.value = config.results;
  outbound.value = config.outbound_enabled;
  await loadResults();
  job.value =
    (await api<{ results: OCRJob[] }>(`problems/${id.value}/analysis-jobs/`))
      .results[0] || null;
  if (guardian.value) {
    credentials.value = (
      await api<{ results: Credential[] }>(
        `provider-credentials/?${familyQuery()}`,
      )
    ).results;
    const usage = await api<{
      platform_trial: { remaining_units: number; enabled: boolean };
    }>(`usage/summary/?${familyQuery()}`);
    remaining.value = usage.platform_trial.remaining_units;
    platformEnabled.value = usage.platform_trial.enabled;
    const preference = await api<{
      billing_mode: "platform_trial" | "byok" | null;
    }>(`ai/preference/?${familyQuery()}`);
    if (preference.billing_mode && !preferenceLoaded)
      mode.value = preference.billing_mode;
    preferenceLoaded = true;
  }
  schedule();
}
function schedule() {
  if (timer) clearTimeout(timer);
  if (visible && pending.value) timer = setTimeout(poll, 3000);
}
async function poll() {
  if (!visible || !job.value) return;
  try {
    job.value = await api<OCRJob>(`tasks/${job.value.id}/`);
    if (!pending.value) {
      selectedId.value = "";
      resetReveal();
      await load();
    } else schedule();
  } catch (error) {
    message.value = errorText(error);
    if (visible) timer = setTimeout(poll, 8000);
  }
}
onLoad((options) => {
  id.value = options?.id || "";
});
onShow(() => {
  visible = true;
  if (session.user && id.value) void run(load);
});
function dispose() {
  visible = false;
  if (timer) clearTimeout(timer);
  work.value = "";
  correction.value = "";
  costConfirmed.value = false;
  resetReveal();
}
onHide(dispose);
onUnload(dispose);
function back() {
  uni.redirectTo({ url: `/pages/problems/detail?id=${id.value}` });
}
function setMode(value: "platform_trial" | "byok") {
  mode.value = value;
  costConfirmed.value = false;
}
function changeModel(event: { detail: { value: string | number } }) {
  modelIndex.value = Number(event.detail.value);
  credentialIndex.value = 0;
  costConfirmed.value = false;
}
function changeCredential(event: { detail: { value: string | number } }) {
  credentialIndex.value = Number(event.detail.value);
  costConfirmed.value = false;
}
function savePreference() {
  void run(async () => {
    await api(`ai/preference/?${familyQuery()}`, "POST", {
      billing_mode: mode.value,
    });
    message.value = "已保存你的费用模式偏好。每次任务仍需确认，不会自动切换。";
  });
}
function start() {
  void run(async () => {
    if (!problem.value?.current_text || !model.value || !costConfirmed.value)
      throw new Error("请先确认题干、选择模型并阅读外发说明。");
    const selectedKey = usableKeys.value[credentialIndex.value];
    if (mode.value === "byok" && !selectedKey)
      throw new Error("请选择自己可用的凭证。");
    await ensureProviderConsent(problem.value.child_id, model.value.provider);
    const data = {
      model_id: model.value.id,
      text_version_id: problem.value.current_text.id,
      expected_revision: problem.value.revision,
      billing_mode: mode.value,
      student_answer: work.value,
      notice_version: model.value.notice_version,
      cost_confirmed: true,
      ...(mode.value === "byok" ? { credential_id: selectedKey.id } : {}),
    };
    const fingerprint = JSON.stringify(data);
    if (!requestIdentity || requestIdentity.fingerprint !== fingerprint)
      requestIdentity = {
        fingerprint,
        key: `analysis_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`,
      };
    job.value = await api<OCRJob>(
      `problems/${id.value}/analysis-jobs/`,
      "POST",
      data,
      { "Idempotency-Key": requestIdentity.key },
    );
    requestIdentity = undefined;
    costConfirmed.value = false;
    schedule();
    message.value = "分析任务已受理。离开页面后仍会处理。";
  });
}
async function cancel() {
  if (
    !job.value ||
    !(await confirmAction(
      "取消未发送的任务；已发送请求可能仍计费，结果将不再发布。",
    ))
  )
    return;
  void run(async () => {
    job.value = await api<OCRJob>(`tasks/${job.value!.id}/cancel/`, "POST");
    schedule();
  });
}
function chooseResult(item: AnalysisItem) {
  selectedId.value = item.id;
  resetReveal();
}
async function loadFeedback(append = false) {
  if (!selected.value) return;
  const result = await api<{ results: FeedbackItem[]; next: number | null }>(
    `analyses/${selected.value.id}/feedback/?page=${append ? nextFeedback.value : 1}`,
  );
  feedback.value = append
    ? [...feedback.value, ...result.results]
    : result.results;
  nextFeedback.value = result.next;
}
function submitFeedback(kind: "report" | "correction") {
  void run(async () => {
    if (!selected.value || !correction.value.trim())
      throw new Error("请填写需要复核的问题或人工修订内容。");
    await api(`analyses/${selected.value.id}/feedback/`, "POST", {
      kind,
      text: correction.value,
    });
    correction.value = "";
    await loadFeedback();
    await loadResults();
    message.value = "已保存记录，原始 AI 分析保持可追溯。";
  });
}
</script>

<template>
  <view class="page">
    <button class="text-button" @click="back">← 返回错题校对</button>
    <view class="intro"><text class="heading">分析与提示</text></view>
    <view v-if="message" class="feedback" role="status">{{ message }}</view>
    <view v-if="!session.user" class="panel"
      >请先返回家庭页登录，再打开本题。</view
    >
    <template v-else-if="problem">
      <view class="panel"
        ><view class="row"
          ><text class="section-title">本次题干</text
          ><text class="badge">{{
            problem.current_text ? "已人工确认" : "待校对"
          }}</text></view
        ><text class="math-text">{{
          problem.current_text?.text || "请先返回校对页，确认题干后再分析。"
        }}</text
        ><text class="note"
          >仅发送已确认题干、年级和下方填写的作答；本轮不发送图片。含图形条件时，请先将必要条件补充到题干。</text
        ></view
      >
      <view v-if="guardian" class="panel">
        <text class="section-title">提交学习线索</text>
        <text class="note"
          >可填写孩子当时的答案与步骤。暂未提供作答时，只能给解题线索，无法判断具体错误原因。</text
        >
        <textarea
          v-model="work"
          aria-label="孩子原作答"
          class="work-input"
          :maxlength="4000"
          :disabled="busy || pending"
          placeholder="填写当时的作答与步骤（可留空）"
        />
        <view v-if="!outbound || !models.length" class="empty"
          >分析服务尚未开放或未配置可用模型。你仍可整理题目、补充作答，稍后重新载入。</view
        >
        <template v-else>
          <picker
            :range="modelNames"
            :value="modelIndex"
            :disabled="busy || pending"
            @change="changeModel"
            ><view class="picker-field"
              >{{ modelNames[modelIndex] || "选择模型" }} ⌄</view
            ></picker
          >
          <text v-if="model && !model.integration_verified" class="note"
            >该模型尚未完成真实接入验收，输出需特别复核。</text
          >
          <view class="mode-grid"
            ><button
              :class="mode === 'platform_trial' ? 'primary' : 'secondary'"
              :disabled="busy || pending"
              @click="setMode('platform_trial')"
            >
              平台 AI 体验</button
            ><button
              :class="mode === 'byok' ? 'primary' : 'secondary'"
              :disabled="busy || pending"
              @click="setMode('byok')"
            >
              使用我的 API
            </button></view
          >
          <text v-if="mode === 'platform_trial'" class="note"
            >剩余体验点 {{ remaining }} · 本次 {{ model?.analysis_quota_units || 1 }} 点</text
          >
          <template v-else
            ><text class="note"
              >费用由你的供应商账户承担，失败时不会切换至平台额度。</text
            ><picker
              v-if="usableKeys.length"
              :range="credentialNames"
              :value="credentialIndex"
              :disabled="busy || pending"
              @change="changeCredential"
              ><view class="picker-field"
                >{{ credentialNames[credentialIndex] }} ⌄</view
              ></picker
            ><button v-else class="text-button" @click="openSettings">
              前往配置自己的凭证
            </button></template
          >
          <button
            class="text-button"
            :disabled="busy || pending"
            @click="savePreference"
          >
            保存为我的费用模式偏好
          </button>
          <text class="note">{{ model?.notice }}</text>
          <checkbox-group
            @change="costConfirmed = $event.detail.value.includes('confirm')"
            ><label class="check-line"
              ><checkbox
                value="confirm"
                :checked="costConfirmed"
                :disabled="busy || pending"
                color="#2563eb"
              />我已阅读第三方处理说明，并确认本次内容与费用方式</label
            ></checkbox-group
          >
          <button
            class="primary"
            :disabled="
              busy ||
              pending ||
              !costConfirmed ||
              !problem.current_text ||
              (mode === 'platform_trial' &&
                (!platformEnabled ||
                  remaining < (model?.analysis_quota_units || 1))) ||
              (mode === 'byok' && !usableKeys.length)
            "
            @click="start"
          >
            提交分析
          </button>
        </template>
        <button class="text-button" :disabled="busy" @click="run(load)">
          重新载入服务状态
        </button>
      </view>
      <view v-if="job" class="panel"
        ><text class="section-title">最近分析任务</text
        ><text class="note"
          >{{ states[job.status] || job.status }} ·
          {{ job.billing_mode === "byok" ? "我的 API" : "平台体验" }}</text
        ><text class="note">{{
          feeNames[job.fee_status] || "费用状态待确认"
        }}</text
        ><text v-if="job.error_code" class="feedback">{{
          errors[job.error_code] ||
          "本次分析未发布，请检查服务配置、预算或凭证后再操作。"
        }}</text
        ><button
          v-if="pending && guardian"
          class="secondary"
          :disabled="busy"
          @click="cancel"
        >
          取消分析任务
        </button></view
      >
      <view class="panel"
        ><view class="row"
          ><text class="section-title">分析版本</text
          ><text class="badge">AI 生成·待核验</text></view
        ><text v-if="!items.length" class="empty"
          >还没有分析记录。这里不会显示示例解析。</text
        ><view
          v-for="(item, index) in items"
          :key="item.id"
          class="version-row"
          @click="chooseResult(item)"
          ><text
            >{{ index + 1 }} · 题干版本 {{ item.text_version_number }} ·
            {{ item.task.provider }}</text
          ><text class="small"
            >{{
              item.stale
                ? "题干已更新"
                : item.reported
                  ? "有问题反馈"
                  : "查看提示"
            }}
            →</text
          ></view
        ><button
          v-if="nextResult"
          class="text-button"
          :disabled="busy"
          @click="run(() => loadResults(true))"
        >
          加载更多分析版本
        </button></view
      >
      <view v-if="selected" class="panel">
        <text class="section-title">先看一条提示</text
        ><text v-if="selected.stale" class="feedback"
          >这份分析基于旧题干。请核对版本，不能直接套用到当前题目。</text
        ><text v-if="selected.reported" class="feedback"
          >这份分析已收到问题反馈，请优先参考人工修订并自行核验。</text
        >
        <text class="note"
          >提示与解析可能含有错误，遇到条件不清或结果矛盾请返回原题核对。</text
        >
        <view
          v-for="hint in selected.payload.hints.slice(0, hintCount)"
          :key="hint.level"
          class="hint"
          ><text class="badge">提示 {{ hint.level }}</text
          ><text class="math-text">{{ hint.text }}</text></view
        >
        <button
          v-if="hintCount < selected.payload.hints.length"
          class="primary"
          @click="hintCount++"
        >
          再看一条提示
        </button>
        <button v-if="!full" class="secondary" @click="full = true">
          展开完整分析与答案候选</button
        ><button v-else class="text-button" @click="full = false">
          收起完整分析
        </button>
        <view v-if="full" class="full-analysis"
          ><text class="section-title">题目理解</text
          ><text class="math-text">{{ selected.payload.understanding }}</text
          ><text class="section-title">关键条件</text
          ><text
            v-for="(line, index) in selected.payload.conditions"
            :key="index"
            class="math-text"
            >{{ line }}</text
          ><text class="section-title">可能的错误原因</text
          ><text class="math-text">{{ selected.payload.error_location }}</text
          ><view
            v-for="(cause, index) in selected.payload.root_causes"
            :key="index"
            ><text class="badge">{{
              categories[cause.category] || "暂无法判断"
            }}</text
            ><text class="math-text">{{ cause.evidence }}</text></view
          ><text class="section-title">解析候选·尚未验证</text
          ><text
            v-for="(step, index) in selected.payload.solution_steps"
            :key="index"
            class="math-text"
            >{{ index + 1 }}. {{ step }}</text
          ><text class="math-text"
            >答案候选：{{
              selected.payload.answer_candidate || "暂无法确定"
            }}</text
          ><text class="section-title">建议复核</text
          ><text
            v-for="(line, index) in [
              ...selected.payload.uncertainties,
              ...selected.payload.review_items,
            ]"
            :key="index"
            class="math-text"
            >{{ line }}</text
          ><text class="note"
            >知识点建议：{{
              selected.payload.knowledge_points.join("、") || "暂无法确定"
            }}</text
          ></view
        >
        <view class="feedback-section"
          ><text class="section-title">人工修订与问题反馈</text
          ><button
            class="text-button"
            :disabled="busy"
            @click="run(() => loadFeedback())"
          >
            查看已有修订记录</button
          ><view v-for="item in feedback" :key="item.id" class="hint"
            ><text class="badge"
              >记录 {{ item.number }} ·
              {{ item.kind === "report" ? "问题反馈" : "人工修订" }}</text
            ><text class="math-text">{{ item.text }}</text></view
          ><button
            v-if="nextFeedback"
            class="text-button"
            :disabled="busy"
            @click="run(() => loadFeedback(true))"
          >
            加载更多修订记录</button
          ><template v-if="guardian">
            <textarea
              v-model="correction"
              aria-label="人工修订或问题说明"
              class="work-input"
              :maxlength="4000"
              :disabled="busy"
              placeholder="说明哪一步需要核对，或写下你的修订（不覆盖原始分析）"
            /><view class="mode-grid"
              ><button
                class="secondary"
                :disabled="busy || !correction.trim()"
                @click="submitFeedback('report')"
              >
                报告分析问题</button
              ><button
                class="secondary"
                :disabled="busy || !correction.trim()"
                @click="submitFeedback('correction')"
              >
                保存人工修订
              </button></view
            ></template
          ></view
        >
      </view>
    </template>
  </view>
</template>

<style scoped>
.work-input {
  width: 100%;
  min-height: 150px;
  box-sizing: border-box;
  background: #fbfcfd;
  border: 1px solid #eef0f4;
  padding: 14px;
  font-size: 16px;
  line-height: 1.8;
  margin: 16px 0;
  border-radius: 12px;
}
.math-text {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.9;
  margin: 14px 0;
}
.mode-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 14px 0;
}
.mode-grid button {
  flex: 1;
  min-width: 130px;
  margin: 0;
}
.picker-field {
  padding: 14px;
  border: 1px solid #eef0f4;
  margin: 12px 0;
  border-radius: 12px;
}
.check-line {
  display: flex;
  align-items: flex-start;
  font-size: 14px;
  line-height: 1.8;
  margin: 16px 0;
}
.version-row {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  padding: 18px 0;
  border-bottom: 1px solid #eef0f4;
  line-height: 1.8;
}
.hint {
  background: #f2f4ec;
  padding: 18px;
  margin: 14px 0;
  border-radius: 6px;
}
.full-analysis,
.feedback-section {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid #eef0f4;
}
.full-analysis .section-title {
  margin-top: 20px;
}
</style>
