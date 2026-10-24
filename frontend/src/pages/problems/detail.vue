<script setup lang="ts">
import { computed, getCurrentInstance, nextTick, ref } from "vue";
import { onHide, onLoad, onShow, onUnload } from "@dcloudio/uni-app";
import { api, confirmAction, errorText, familyQuery } from "../../api/client";
import {
  downloadImage,
  releaseImages,
  uploadImage,
  type Asset,
  type OCRJob,
  type Problem,
  type TextVersion,
} from "../../api/problems";
import { session } from "../../state";
// #ifdef H5
import { cropBrowserImage } from "../../api/problems";
// #endif

interface Model {
  id: string;
  provider: string;
  model_name: string;
  notice: string;
  notice_version: string;
  integration_verified: boolean;
  ocr_quota_units: number;
}
interface Credential {
  id: string;
  provider: string;
  masked_key: string;
  enabled: boolean;
}
interface Region {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
}
const instance = getCurrentInstance();
const id = ref(""),
  problem = ref<Problem | null>(null),
  busy = ref(false),
  message = ref("");
const text = ref(""),
  answer = ref(""),
  textConfirmed = ref(false),
  dirty = ref(false),
  parentId = ref<string | null>(null);
const source = ref(""),
  chapter = ref(""),
  points = ref(""),
  errorType = ref(""),
  mistakeDate = ref("");
const versions = ref<TextVersion[]>([]),
  nextVersion = ref<number | null>(null);
const paths = ref<Record<string, string>>({}),
  selectedAssetId = ref("");
const selectedAsset = computed(
  () =>
    problem.value?.assets.find((item) => item.id === selectedAssetId.value) ||
    problem.value?.assets[0],
);
const guardian = computed(
  () => !!session.user && session.family?.role === "guardian",
);
const regionX = ref("0"),
  regionY = ref("0"),
  regionW = ref(""),
  regionH = ref(""),
  rotation = ref(0);
const rotations = [0, 90, 180, 270],
  regions = ref<Region[]>([]);
const local = ref<{ path: string; width: number; height: number } | null>(null),
  uploadPreview = ref("");
const localX = ref("0"),
  localY = ref("0"),
  localW = ref(""),
  localH = ref("");
const privacyConfirmed = ref(false),
  canvasW = ref(1),
  canvasH = ref(1);
const models = ref<Model[]>([]),
  selectedModelId = ref(""),
  outbound = ref(false);
const model = computed(
  () =>
    models.value.find((item) => item.id === selectedModelId.value) ||
    models.value[0],
);
const credentials = ref<Credential[]>([]),
  selectedCredential = ref("");
const usableCredentials = computed(() =>
  credentials.value.filter(
    (item) => item.enabled && item.provider === model.value?.provider,
  ),
);
const mode = ref<"platform_trial" | "byok">("platform_trial"),
  costConfirmed = ref(false);
const platformRemaining = ref(0),
  platformEnabled = ref(false),
  job = ref<OCRJob | null>(null);
const pending = computed(
  () => !!job.value && ["queued", "running"].includes(job.value.status),
);
const statusNames: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  needs_review: "待人工校对",
  failed: "识别未完成",
  cancelled: "已取消",
};
let visible = false,
  pollTimer: ReturnType<typeof setTimeout> | undefined;
let pendingRequest: { fingerprint: string; key: string } | undefined;
const errors: Record<string, string> = {
  OCR_DISABLED: "识别外发已关闭，可先手动录入。",
  CONSENT_REQUIRED: "授权已撤回，请重新确认。",
  CREDENTIAL_REVOKED: "凭证已更改或停用，请重新配置。",
  TASK_ACCESS_REVOKED: "资料或授权发生变化，本次任务已停止。",
  PROVIDER_TIMEOUT: "供应商结果未能确认，请查看费用状态，勿连续重复提交。",
  PROVIDER_OUTCOME_UNKNOWN: "任务中断，费用需要核对，系统不会自动重发。",
  OCR_OUTPUT_INVALID: "识别结果不符合要求，请手动录入。",
  BUDGET_RECHECK_FAILED: "预算周期、价格或平台状态发生变化，任务未发送。",
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
function resetRegion() {
  const asset = selectedAsset.value;
  regionX.value = "0";
  regionY.value = "0";
  regionW.value = asset?.width.toString() || "";
  regionH.value = asset?.height.toString() || "";
  rotation.value = 0;
  regions.value = [];
}
async function loadVersions(append = false) {
  const result = await api<{ results: TextVersion[]; next: number | null }>(
    `problems/${id.value}/text-versions/?page=${append ? nextVersion.value : 1}`,
  );
  versions.value = append
    ? [...versions.value, ...result.results]
    : result.results;
  nextVersion.value = result.next;
}
async function load() {
  const result = await api<Problem>(`problems/${id.value}/`);
  problem.value = result;
  source.value = result.source;
  chapter.value = result.chapter;
  points.value = result.knowledge_points.join("，");
  errorType.value = result.error_type;
  mistakeDate.value = result.mistake_date || "";
  if (!dirty.value) {
    text.value = result.current_text?.text || "";
    answer.value = result.current_text?.answer || "";
    parentId.value = result.current_text?.id || null;
  }
  await loadVersions();
  const list = await api<{ results: OCRJob[] }>(
    `problems/${id.value}/ocr-jobs/`,
  );
  job.value = list.results[0] || null;
  const config = await api<{ results: Model[]; outbound_enabled: boolean }>(
    "ocr/models/",
  );
  models.value = config.results;
  outbound.value = config.outbound_enabled;
  if (guardian.value) {
    credentials.value = (
      await api<{ results: Credential[] }>(
        `provider-credentials/?${familyQuery()}`,
      )
    ).results;
    const usage = await api<{
      platform_trial: { remaining_units: number; enabled: boolean };
    }>(`usage/summary/?${familyQuery()}`);
    platformRemaining.value = usage.platform_trial.remaining_units;
    platformEnabled.value = usage.platform_trial.enabled;
  }
  const oldPaths = paths.value;
  const entries = await Promise.all(
    result.assets.map(
      async (asset) =>
        [
          asset.id,
          oldPaths[asset.id] || (await downloadImage(asset.id)),
        ] as const,
    ),
  );
  if (!visible) {
    releaseImages(entries.map(([, path]) => path));
    return;
  }
  paths.value = Object.fromEntries(entries);
  releaseImages(
    Object.entries(oldPaths)
      .filter(([assetId]) => !paths.value[assetId])
      .map(([, path]) => path),
  );
  resetRegion();
  schedulePoll();
}
function schedulePoll(delay = 2500) {
  if (pollTimer) clearTimeout(pollTimer);
  if (visible && pending.value) pollTimer = setTimeout(poll, delay);
}
async function poll() {
  if (!visible || !job.value) return;
  try {
    job.value = await api<OCRJob>(`tasks/${job.value.id}/`);
    if (!pending.value) {
      await load();
    } else schedulePoll(4000);
  } catch (error) {
    message.value = errorText(error);
    schedulePoll(8000);
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
  if (pollTimer) clearTimeout(pollTimer);
  releaseImages(Object.values(paths.value));
  paths.value = {};
  releaseImages(uploadPreview.value ? [uploadPreview.value] : []);
  releaseImages(local.value ? [local.value.path] : []);
  uploadPreview.value = "";
  local.value = null;
}
onHide(dispose);
onUnload(dispose);
async function removeImage() {
  if (!problem.value || !selectedAsset.value) return;
  if (!(await confirmAction("删除这道题中的图片？其他题目的引用会保留。")))
    return;
  await run(async () => {
    await api(
      `problems/${id.value}/assets/${selectedAsset.value!.id}/remove/`,
      "POST",
      {
        expected_revision: problem.value!.revision,
      },
    );
    await load();
  });
}
function back() {
  uni.redirectTo({
    url: `/pages/problems/index?child_id=${problem.value?.child_id || ""}`,
  });
}
function openAnalysis() {
  uni.navigateTo({ url: `/pages/analysis/index?id=${id.value}` });
}
function openSimilar() {
  uni.navigateTo({ url: `/pages/similar/index?id=${id.value}` });
}
function save() {
  void run(async () => {
    if (!problem.value) return;
    if (!textConfirmed.value) throw new Error("请核对题干并确认后再保存。");
    await api(`problems/${id.value}/text/`, "POST", {
      text: text.value,
      answer: answer.value,
      expected_revision: problem.value.revision,
      confirmed: true,
      parent_id: parentId.value,
    });
    dirty.value = false;
    textConfirmed.value = false;
    await load();
    message.value = "题干已人工确认，并保存为新版本。";
  });
}
function saveMetadata() {
  void run(async () => {
    if (!problem.value) return;
    await api(`problems/${id.value}/update/`, "POST", {
      source: source.value,
      chapter: chapter.value,
      knowledge_points: points.value
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean),
      error_type: errorType.value,
      mistake_date: mistakeDate.value || null,
      expected_revision: problem.value.revision,
    });
    await load();
    message.value = "分类资料已保存。";
  });
}
function useVersion(version: TextVersion) {
  text.value = version.text;
  answer.value = version.answer;
  parentId.value = version.id;
  dirty.value = true;
  textConfirmed.value = false;
  message.value =
    version.origin === "ocr"
      ? "已放入校对区。请逐项核对原图，确认后保存。"
      : "已载入历史版本，保存时会创建新版本。";
}
async function chooseImage() {
  if (busy.value) return;
  try {
    const path = await new Promise<string>((resolve, reject) =>
      uni.chooseImage({
        count: 1,
        sizeType: ["original"],
        sourceType: ["album", "camera"],
        success: (result) => resolve(result.tempFilePaths[0]),
        fail: () => reject(new Error("未选择图片。")),
      }),
    );
    const info = await new Promise<UniApp.GetImageInfoSuccessData>(
      (resolve, reject) =>
        uni.getImageInfo({
          src: path,
          success: resolve,
          fail: () => reject(new Error("无法读取图片尺寸。")),
        }),
    );
    if (
      info.width * info.height > 12000000 ||
      Math.max(info.width, info.height) > 8192
    )
      throw new Error("图片尺寸过大，请先在相册中缩小或裁剪。");
    local.value = { path, width: info.width, height: info.height };
    localX.value = "0";
    localY.value = "0";
    localW.value = String(info.width);
    localH.value = String(info.height);
    uploadPreview.value = "";
    privacyConfirmed.value = false;
  } catch (error) {
    message.value = errorText(error);
  }
}
function checkedRegion(
  x: string,
  y: string,
  w: string,
  h: string,
  width: number,
  height: number,
  turn = 0,
): Region {
  const values = [x, y, w, h].map(Number);
  if (
    values.some((value) => !Number.isInteger(value)) ||
    values[0] < 0 ||
    values[1] < 0 ||
    values[2] < 1 ||
    values[3] < 1 ||
    values[0] + values[2] > width ||
    values[1] + values[3] > height
  )
    throw new Error("请填写图片范围内的整数裁剪坐标。");
  return {
    x: values[0],
    y: values[1],
    width: values[2],
    height: values[3],
    rotation: turn,
  };
}
function makeUploadPreview() {
  void run(async () => {
    if (!local.value) return;
    const crop = checkedRegion(
      localX.value,
      localY.value,
      localW.value,
      localH.value,
      local.value.width,
      local.value.height,
    );
    const scale = Math.min(1, 2048 / Math.max(crop.width, crop.height));
    canvasW.value = Math.max(1, Math.round(crop.width * scale));
    canvasH.value = Math.max(1, Math.round(crop.height * scale));
    privacyConfirmed.value = false;
    releaseImages(uploadPreview.value ? [uploadPreview.value] : []);
    uploadPreview.value = "";
    // #ifdef H5
    uploadPreview.value = await cropBrowserImage(
      local.value.path,
      crop,
      canvasW.value,
      canvasH.value,
    );
    // #endif
    // #ifndef H5
    await nextTick();
    const context = uni.createCanvasContext(
      "privacyCrop",
      instance?.proxy || undefined,
    );
    context.drawImage(
      local.value.path,
      crop.x,
      crop.y,
      crop.width,
      crop.height,
      0,
      0,
      canvasW.value,
      canvasH.value,
    );
    await new Promise<void>((resolve) => context.draw(false, () => resolve()));
    uploadPreview.value = await new Promise<string>((resolve, reject) =>
      uni.canvasToTempFilePath(
        {
          canvasId: "privacyCrop",
          x: 0,
          y: 0,
          width: canvasW.value,
          height: canvasH.value,
          destWidth: canvasW.value,
          destHeight: canvasH.value,
          fileType: "jpg",
          quality: 0.9,
          success: (result) => resolve(result.tempFilePath),
          fail: () => reject(new Error("裁剪未完成，请重新选择图片。")),
        },
        instance?.proxy || undefined,
      ),
    );
    // #endif
  });
}
function upload() {
  void run(async () => {
    if (!privacyConfirmed.value || !uploadPreview.value)
      throw new Error("请先预览并确认已经去除身份信息。");
    await uploadImage(id.value, uploadPreview.value);
    uploadPreview.value = "";
    local.value = null;
    privacyConfirmed.value = false;
    await load();
    message.value = "图片已保存为私有资料。";
  });
}
function currentRegion() {
  const asset = selectedAsset.value;
  if (!asset) throw new Error("请先选择图片。");
  return checkedRegion(
    regionX.value,
    regionY.value,
    regionW.value,
    regionH.value,
    asset.width,
    asset.height,
    rotation.value,
  );
}
function addRegion() {
  try {
    if (regions.value.length >= 8) throw new Error("一次最多分 8 道题。");
    regions.value.push(currentRegion());
  } catch (error) {
    message.value = errorText(error);
  }
}
function transform(split: boolean) {
  void run(async () => {
    if (!selectedAsset.value || !problem.value) return;
    const result = await api<{
      results: { problem_id: string; asset: Asset }[];
    }>(`assets/${selectedAsset.value.id}/transforms/`, "POST", {
      problem_id: id.value,
      expected_revision: problem.value.revision,
      regions: split ? regions.value : [currentRegion()],
      split,
    });
    await load();
    message.value = split
      ? `已创建 ${result.results.length} 道独立错题，可返回错题本查看。`
      : "裁剪图已添加，原图保留。";
  });
}
function selectAsset(event: { detail: { value: string | number } }) {
  selectedAssetId.value =
    problem.value?.assets[Number(event.detail.value)]?.id || "";
  resetRegion();
}
const assetNames = computed(
  () =>
    problem.value?.assets.map(
      (item, index) => `图片 ${index + 1} · ${item.width} × ${item.height}`,
    ) || [],
);
function startOCR() {
  void run(async () => {
    if (
      !model.value ||
      !selectedAsset.value ||
      !problem.value ||
      !costConfirmed.value
    )
      throw new Error("请选择图片、模型并确认外发用途与费用。");
    const notice = await api<{ guardian_notice_version: string }>(
      "auth/capabilities/",
    );
    const consents = await api<{
      results: {
        scope: string;
        revoked_at: string | null;
        notice_version: string;
      }[];
    }>(`children/${problem.value.child_id}/consents/`);
    if (
      !consents.results.some(
        (item) =>
          item.scope === model.value?.provider &&
          !item.revoked_at &&
          item.notice_version === notice.guardian_notice_version,
      )
    ) {
      await api(`children/${problem.value.child_id}/consents/`, "POST", {
        scope: model.value.provider,
        notice_version: notice.guardian_notice_version,
      });
    }
    const data = {
      model_id: model.value.id,
      asset_id: selectedAsset.value.id,
      billing_mode: mode.value,
      ...(mode.value === "byok"
        ? {
            credential_id:
              selectedCredential.value || usableCredentials.value[0]?.id,
          }
        : {}),
      expected_revision: problem.value.revision,
      notice_version: model.value.notice_version,
      cost_confirmed: true,
    };
    const fingerprint = JSON.stringify(data);
    if (!pendingRequest || pendingRequest.fingerprint !== fingerprint)
      pendingRequest = {
        fingerprint,
        key: `ocr_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`,
      };
    job.value = await api<OCRJob>(
      `problems/${id.value}/ocr-jobs/`,
      "POST",
      data,
      { "Idempotency-Key": pendingRequest.key },
    );
    pendingRequest = undefined;
    costConfirmed.value = false;
    schedulePoll();
    message.value = "任务已受理，离开页面后会继续处理。";
  });
}
async function cancelOCR() {
  if (
    !job.value ||
    !(await confirmAction(
      "停止未发送的任务。已经发送的请求可能仍会计费，但结果将不再发布。",
    ))
  )
    return;
  void run(async () => {
    job.value = await api<OCRJob>(`tasks/${job.value?.id}/cancel/`, "POST");
    schedulePoll();
  });
}
async function remove() {
  if (
    !(await confirmAction(
      "删除这道错题和不再被其他题引用的图片？确认后无法恢复。",
    ))
  )
    return;
  void run(async () => {
    await api(`problems/${id.value}/`, "DELETE", { confirm: true });
    dirty.value = false;
    back();
  });
}
</script>
<template>
  <view class="page detail-page"
    ><button class="text-button" @click="back">← 返回错题本</button>
    <view class="intro"
      ><text class="eyebrow">认真核对，比匆忙确认更有用。</text
      ><text class="heading">错题校对</text
      ><text class="muted">图片和识别仅提供线索，题干由你确认。</text></view
    >
    <view v-if="message" class="feedback" role="status">{{ message }}</view>
    <template v-if="problem && session.user">
      <view class="workspace">
        <view>
          <view class="panel"
            ><view class="row"
              ><text class="section-title">私有原图</text
              ><text class="badge">{{ problem.assets.length }} 张</text></view
            >
            <view v-if="!problem.assets.length" class="empty"
              >尚未添加图片，也可以直接手动录题。</view
            >
            <button
              class="secondary"
              :disabled="busy || !problem.current_text"
              @click="openAnalysis"
            >
              分析与分层提示
            </button>
            <button
              class="secondary"
              :disabled="busy || !problem.current_text"
              @click="openSimilar"
            >
              查找同类题与变式
            </button>
            <picker
              v-if="problem.assets.length"
              :range="assetNames"
              :disabled="busy"
              @change="selectAsset"
              ><view class="picker-field"
                >选择图片 · {{ selectedAsset?.width }} ×
                {{ selectedAsset?.height }} ⌄</view
              ></picker
            >
            <image
              v-if="selectedAsset && paths[selectedAsset.id]"
              :src="paths[selectedAsset.id]"
              class="problem-image"
              mode="widthFix"
            />
            <template v-if="guardian"
              ><button
                v-if="selectedAsset"
                class="secondary"
                :disabled="busy"
                @click="removeImage"
              >
                删除选中图片</button
              ><text class="note"
                >上传前请裁去姓名、学校、班级与条码。仅接收单帧
                JPEG/PNG/WebP，单张不超过 8 MB、1200
                万像素；服务器会去除元数据。</text
              ><button
                class="secondary"
                :disabled="busy || problem.assets.length >= 8"
                @click="chooseImage"
              >
                拍照或选择图片
              </button></template
            >
          </view>
          <view v-if="guardian && local" class="panel"
            ><text class="section-title">上传前裁剪</text
            ><image
              :src="local.path"
              mode="widthFix"
              class="problem-image"
            /><text class="note"
              >原图 {{ local.width }} ×
              {{
                local.height
              }}。坐标从左上角开始，单位为像素；选择需要保留的题目区域。</text
            >
            <view class="crop-grid"
              ><view
                ><text class="small">左侧 X</text
                ><input
                  v-model="localX"
                  class="input"
                  type="number"
                  aria-label="上传裁剪X" /></view
              ><view
                ><text class="small">顶部 Y</text
                ><input
                  v-model="localY"
                  class="input"
                  type="number"
                  aria-label="上传裁剪Y" /></view
              ><view
                ><text class="small">宽度</text
                ><input
                  v-model="localW"
                  class="input"
                  type="number"
                  aria-label="上传裁剪宽度" /></view
              ><view
                ><text class="small">高度</text
                ><input
                  v-model="localH"
                  class="input"
                  type="number"
                  aria-label="上传裁剪高度" /></view
            ></view>
            <button
              class="secondary"
              :disabled="busy"
              @click="makeUploadPreview"
            >
              生成上传预览
            </button>
            <image
              v-if="uploadPreview"
              :src="uploadPreview"
              mode="widthFix"
              class="problem-image"
            />
            <checkbox-group
              v-if="uploadPreview"
              @change="
                privacyConfirmed = $event.detail.value.includes('privacy')
              "
              ><label class="checkbox-label"
                ><checkbox
                  value="privacy"
                  :checked="privacyConfirmed"
                  color="#315b45"
                />我已确认预览中没有不必要的身份信息</label
              ></checkbox-group
            >
            <button
              class="primary"
              :disabled="busy || !uploadPreview || !privacyConfirmed"
              @click="upload"
            >
              上传这张预览图
            </button>
          </view>
          <view v-if="guardian && selectedAsset" class="panel"
            ><text class="section-title">裁剪与手动分题</text
            ><text class="note"
              >在所选图片内指定矩形，裁剪会创建新图。多个区域可分成独立错题，原图继续保留。</text
            >
            <view class="crop-grid"
              ><view
                ><text class="small">左侧 X</text
                ><input
                  v-model="regionX"
                  class="input"
                  type="number"
                  aria-label="裁剪X" /></view
              ><view
                ><text class="small">顶部 Y</text
                ><input
                  v-model="regionY"
                  class="input"
                  type="number"
                  aria-label="裁剪Y" /></view
              ><view
                ><text class="small">宽度</text
                ><input
                  v-model="regionW"
                  class="input"
                  type="number"
                  aria-label="裁剪宽度" /></view
              ><view
                ><text class="small">高度</text
                ><input
                  v-model="regionH"
                  class="input"
                  type="number"
                  aria-label="裁剪高度" /></view
            ></view>
            <picker
              :range="rotations"
              @change="rotation = rotations[Number($event.detail.value)]"
              ><view class="picker-field"
                >顺时针旋转 {{ rotation }}° ⌄</view
              ></picker
            >
            <view class="actions"
              ><button
                class="secondary compact"
                :disabled="busy || problem.assets.length >= 8"
                @click="transform(false)"
              >
                创建裁剪图</button
              ><button class="text-button" :disabled="busy" @click="addRegion">
                加入分题区域
              </button></view
            >
            <text v-for="(region, index) in regions" :key="index" class="note"
              >区域 {{ index + 1 }}：({{ region.x }}, {{ region.y }})，{{
                region.width
              }}
              × {{ region.height }}，{{ region.rotation }}°</text
            >
            <view v-if="regions.length" class="actions"
              ><button
                class="primary compact"
                :disabled="busy"
                @click="transform(true)"
              >
                按区域创建错题</button
              ><button
                class="text-button"
                :disabled="busy"
                @click="regions = []"
              >
                清空区域
              </button></view
            >
          </view>
        </view>
        <view>
          <view class="panel"
            ><view class="row"
              ><text class="section-title">题干与答案</text
              ><text class="badge">{{
                problem.current_text ? "题干已人工确认" : "待核对"
              }}</text></view
            ><text class="note"
              >保留分数、根号、上下标与负号。确认题干不代表答案已经通过数学验证。</text
            >
            <textarea
              v-model="text"
              class="editor"
              aria-label="题干"
              placeholder="输入题干，或从下方载入 OCR 候选后校对"
              maxlength="20000"
              :disabled="busy || !guardian"
              @input="
                dirty = true;
                textConfirmed = false;
              "
            />
            <textarea
              v-model="answer"
              class="editor answer-editor"
              aria-label="答案"
              placeholder="答案可暂空"
              maxlength="10000"
              :disabled="busy || !guardian"
              @input="
                dirty = true;
                textConfirmed = false;
              "
            />
            <template v-if="guardian"
              ><checkbox-group
                @change="
                  textConfirmed = $event.detail.value.includes('confirm')
                "
                ><label class="checkbox-label"
                  ><checkbox
                    value="confirm"
                    :checked="textConfirmed"
                    color="#315b45"
                    :disabled="busy"
                  />我已核对题干，确认保存此版本</label
                ></checkbox-group
              ><button
                class="primary"
                :disabled="busy || !text.trim() || !textConfirmed"
                @click="save"
              >
                确认题干并保存
              </button></template
            >
            <text v-else class="note"
              >学生账号可阅读，修改需由监护人完成。</text
            >
          </view>
          <view class="panel"
            ><text class="section-title">题干版本</text
            ><text v-if="!versions.length" class="empty">还没有文本版本</text
            ><view
              v-for="version in versions"
              :key="version.id"
              class="child-row"
              ><text class="label"
                >版本 {{ version.number }} ·
                {{
                  version.origin === "ocr" ? "OCR 候选，未定稿" : "人工确认"
                }}</text
              ><text class="version-text">{{ version.text }}</text
              ><text v-if="version.uncertainties.length" class="note"
                >需核对：{{ version.uncertainties.join("；") }}</text
              ><button
                v-if="guardian"
                class="text-button"
                :disabled="busy"
                @click="useVersion(version)"
              >
                载入校对区
              </button></view
            ><button
              v-if="nextVersion"
              class="text-button"
              :disabled="busy"
              @click="run(() => loadVersions(true))"
            >
              加载更早版本
            </button></view
          >
          <view v-if="guardian" class="panel"
            ><text class="section-title">OCR 识别</text
            ><text class="note"
              >只转录选中的题目图片，不自动求解或替你确认。识别能力尚未通过真实样本验收。</text
            >
            <text v-if="!outbound || !models.length" class="feedback"
              >当前 OCR 尚未开放或未配置可用模型。你可以继续手动录入。</text
            >
            <template v-else
              ><picker
                :range="models"
                range-key="model_name"
                @change="
                  selectedModelId =
                    models[Number($event.detail.value)]?.id || '';
                  costConfirmed = false;
                "
                ><view class="picker-field"
                  >{{ model?.provider }} / {{ model?.model_name }} ⌄</view
                ></picker
              ><text class="note">{{ model?.notice }}</text
              ><text v-if="!model?.integration_verified" class="note"
                >此模型仅完成配置，真实接入仍未验收。</text
              >
              <radio-group
                class="actions"
                @change="
                  mode = $event.detail.value as 'platform_trial' | 'byok';
                  costConfirmed = false;
                "
                ><label
                  ><radio
                    value="platform_trial"
                    :checked="mode === 'platform_trial'"
                    color="#315b45"
                  />平台限额体验</label
                ><label
                  ><radio
                    value="byok"
                    :checked="mode === 'byok'"
                    color="#315b45"
                  />我的 API</label
                ></radio-group
              >
              <text v-if="mode === 'platform_trial'" class="note"
                >平台承担本次调用费用，剩余体验点 {{ platformRemaining }}，本次
                {{ model?.ocr_quota_units || 1 }}
                点；还受平台预算与服务状态限制。</text
              >
              <template v-else
                ><text class="note"
                  >费用由你自己的供应商账户承担，功能会员不抵扣供应商费用。</text
                ><picker
                  :range="usableCredentials"
                  range-key="masked_key"
                  @change="
                    selectedCredential =
                      usableCredentials[Number($event.detail.value)]?.id || ''
                  "
                  ><view class="picker-field"
                    >{{
                      usableCredentials.find(
                        (item) => item.id === selectedCredential,
                      )?.masked_key ||
                      usableCredentials[0]?.masked_key ||
                      "请先在 AI 设置中配置凭证"
                    }}
                    ⌄</view
                  ></picker
                ></template
              >
              <checkbox-group
                @change="costConfirmed = $event.detail.value.includes('cost')"
                ><label class="checkbox-label"
                  ><checkbox
                    value="cost"
                    :checked="costConfirmed"
                    color="#315b45"
                  />我有监护权限，已阅读第三方处理说明，同意按所选模式发送此图并承担相应费用</label
                ></checkbox-group
              >
              <button
                class="primary"
                :disabled="
                  busy ||
                  pending ||
                  !selectedAsset ||
                  !costConfirmed ||
                  (mode === 'platform_trial'
                    ? !platformEnabled ||
                      platformRemaining < (model?.ocr_quota_units || 1)
                    : !usableCredentials.length)
                "
                @click="startOCR"
              >
                提交 OCR 任务
              </button>
            </template>
            <view v-if="job" class="inset"
              ><text class="label">{{
                statusNames[job.status] || job.status
              }}</text
              ><text class="note"
                >费用状态：{{
                  job.fee_status === "unknown"
                    ? "待对账，未按零费用处理"
                    : job.fee_status === "not_sent"
                      ? "未发送"
                      : job.fee_status === "reserved"
                        ? "平台已预留预算"
                        : job.fee_status === "byok_usage_known"
                          ? "用量已记录，账单以供应商为准"
                          : job.fee_status === "settled"
                            ? "平台费用已结算"
                            : "自有 API 待处理"
                }}</text
              ><text v-if="job.error_code" class="note">{{
                errors[job.error_code] ||
                "任务未完成，请检查授权、凭证与服务配置后重试。"
              }}</text
              ><button
                v-if="pending"
                class="text-button"
                :disabled="busy || job.cancel_requested"
                @click="cancelOCR"
              >
                取消未完成任务
              </button></view
            >
          </view>
          <view class="panel"
            ><text class="section-title">整理错题</text
            ><text class="note"
              >来源、章节与知识点由你填写；当前没有自动分类。</text
            ><input
              v-model="source"
              class="input"
              aria-label="题目来源"
              placeholder="来源（可选）"
              maxlength="120"
              :disabled="busy || !guardian"
            /><input
              v-model="chapter"
              class="input"
              aria-label="题目章节"
              placeholder="章节（可选）"
              maxlength="64"
              :disabled="busy || !guardian"
            /><input
              v-model="points"
              class="input"
              aria-label="知识点"
              placeholder="知识点，用逗号分隔，最多 10 个"
              maxlength="400"
              :disabled="busy || !guardian"
            /><input
              v-model="errorType"
              class="input"
              aria-label="错题原因"
              placeholder="错题原因，如概念不清（可选）"
              maxlength="32"
              :disabled="busy || !guardian"
            /><picker
              mode="date"
              :value="mistakeDate"
              :disabled="busy || !guardian"
              @change="mistakeDate = $event.detail.value"
              ><view class="picker-field">{{
                mistakeDate || "选择错题日期（可选）"
              }}</view></picker
            ><button
              v-if="guardian"
              class="secondary"
              :disabled="busy"
              @click="saveMetadata"
            >
              保存分类资料
            </button></view
          >
          <button
            v-if="guardian"
            class="text-button danger"
            :disabled="busy"
            @click="remove"
          >
            删除这道错题
          </button>
        </view>
      </view>
    </template>
    <canvas
      id="privacyCrop"
      canvas-id="privacyCrop"
      class="privacy-canvas"
      :style="{ width: `${canvasW}px`, height: `${canvasH}px` }"
    />
  </view>
</template>
<style scoped>
.detail-page {
  max-width: 1140px;
}
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 22px;
}
.workspace > view {
  min-width: 0;
}
.problem-image {
  display: block;
  width: 100%;
  height: auto;
  margin: 18px 0;
  border-radius: 6px;
  background: #f0f1ea;
}
.editor {
  box-sizing: border-box;
  width: 100%;
  min-height: 180px;
  padding: 14px;
  margin: 16px 0;
  border: 1px solid #d5ded3;
  border-radius: 6px;
  background: #fff;
  font-size: 15px;
  line-height: 1.9;
  white-space: pre-wrap;
}
.answer-editor {
  min-height: 80px;
  height: 100px;
}
.crop-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.crop-grid .input {
  width: 100%;
}
.version-text {
  display: block;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.9;
}
.privacy-canvas {
  position: fixed;
  left: -10000px;
  top: 0;
  pointer-events: none;
}
@media (max-width: 800px) {
  .workspace {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
