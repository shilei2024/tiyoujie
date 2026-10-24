<script setup lang="ts">
import { computed, ref } from "vue";
import { onHide, onShow, onUnload } from "@dcloudio/uni-app";
import {
  api,
  confirmAction,
  errorText,
  familyQuery,
  secureTransport,
} from "../../api/client";
import { session } from "../../state";
interface Credential {
  id: string;
  provider: string;
  masked_key: string;
  enabled: boolean;
  credential_version: number;
  validation_status: string;
}
const items = ref<Credential[]>([]),
  provider = ref("deepseek"),
  secret = ref("");
const connectionNames: Record<string, string> = {
  not_verified: "尚未实测",
  response_received: "曾收到供应商响应",
  auth_failed: "供应商认证失败",
  insufficient_balance: "供应商余额不足",
  permission_denied: "模型权限不足",
  rate_limited: "最近一次受到限流",
  outcome_unknown: "最近请求结果未能确认",
};
const message = ref(""),
  busy = ref(false);
const canManage = computed(
  () => !!session.user && session.family?.role === "guardian",
);
const secure = secureTransport();
const selected = computed(() =>
  items.value.find((item) => item.provider === provider.value),
);
async function refresh() {
  items.value = (
    await api<{ results: Credential[] }>(
      `provider-credentials/?${familyQuery()}`,
    )
  ).results;
}
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
onShow(() => {
  secret.value = "";
  items.value = [];
  if (canManage.value) void run(refresh);
});
onHide(() => {
  secret.value = "";
});
onUnload(() => {
  secret.value = "";
});
function save() {
  void run(async () => {
    if (!secure) throw new Error("请先使用 HTTPS 安全连接。");
    try {
      const data = { key: secret.value };
      if (selected.value)
        await api(
          `provider-credentials/${selected.value.id}/replace/`,
          "POST",
          data,
        );
      else
        await api("provider-credentials/", "POST", {
          ...data,
          family_id: session.family?.id,
          provider: provider.value,
        });
      await refresh();
      message.value =
        "凭证已加密保存。连接状态将随你明确发起的任务更新，不会额外发送付费探测。";
    } finally {
      secret.value = "";
    }
  });
}
function toggle(item: Credential) {
  void run(async () => {
    await api(`provider-credentials/${item.id}/state/`, "POST", {
      enabled: !item.enabled,
    });
    await refresh();
  });
}
async function remove(item: Credential) {
  if (
    !(await confirmAction(
      "删除这份凭证？密文将被清除，旧版本任务不能再使用它。",
    ))
  )
    return;
  void run(async () => {
    await api(`provider-credentials/${item.id}/`, "DELETE");
    await refresh();
    message.value = "凭证已删除。";
  });
}
function back() {
  uni.reLaunch({ url: "/pages/index/index" });
}
</script>
<template>
  <view class="page">
    <button class="text-button" @click="back">← 返回家庭档案</button>
    <view class="intro"
      ><text class="eyebrow">自己的凭证，自己掌握。</text
      ><text class="heading">AI 设置</text
      ><text class="muted">{{
        session.family?.name || "请先登录并选择家庭"
      }}</text></view
    >
    <view v-if="message" class="feedback" role="status">{{ message }}</view>
    <view class="panel"
      ><text class="section-title">服务与费用</text
      ><text class="note"
        >使用自有凭证时，费用由对应供应商账户承担；服务是否开放以题目页显示为准。免费功能权益不代表
        AI 无限使用。使用平台额度与自有凭证须由你明确选择。</text
      ></view
    >
    <view v-if="!canManage" class="panel"
      ><text class="note"
        >请以监护人身份登录并选择家庭后管理自己的凭证。学生没有凭证管理权限。</text
      ></view
    >
    <template v-else>
      <view class="panel"
        ><text class="section-title">我的服务凭证</text
        ><text class="note">仅显示你在当前家庭创建的凭证，无法回读原值。</text>
        <view v-if="!items.length" class="empty">尚未配置凭证</view>
        <view v-for="item in items" :key="item.id" class="child-row">
          <view class="row"
            ><text class="label">{{
              item.provider === "deepseek" ? "DeepSeek" : "Kimi"
            }}</text
            ><text class="badge">{{
              item.enabled ? "已启用" : "已停用"
            }}</text></view
          >
          <text>{{ item.masked_key }}</text
          ><text class="note"
            >版本 {{ item.credential_version }} ·
            {{ connectionNames[item.validation_status] || "状态待确认" }}</text
          >
          <view class="actions"
            ><button
              v-if="item.enabled"
              class="text-button"
              :disabled="busy"
              @click="toggle(item)"
            >
              停用凭证</button
            ><button
              v-else
              class="text-button"
              :disabled="busy"
              @click="toggle(item)"
            >
              启用凭证</button
            ><button
              class="text-button danger"
              :disabled="busy"
              @click="remove(item)"
            >
              删除凭证
            </button></view
          >
        </view>
      </view>
      <view class="panel"
        ><text class="section-title">添加或替换凭证</text
        ><text v-if="!secure" class="feedback"
          >当前是本地 HTTP 连接，密钥提交已关闭。请配置 HTTPS
          后再使用真实密钥。</text
        >
        <radio-group
          class="actions"
          @change="
            provider = $event.detail.value;
            secret = '';
          "
          ><label
            ><radio
              value="deepseek"
              :checked="provider === 'deepseek'"
              color="#315b45"
            />DeepSeek</label
          ><label
            ><radio
              value="kimi"
              :checked="provider === 'kimi'"
              color="#315b45"
            />Kimi</label
          ></radio-group
        >
        <text v-if="selected" class="note"
          >保存将替换当前供应商的这份凭证，并更新凭证版本。</text
        >
        <input
          v-model="secret"
          class="input"
          password
          aria-label="API 密钥"
          placeholder="一次性输入 API 密钥"
          maxlength="512"
          :disabled="busy || !secure"
          autocomplete="off"
        />
        <text class="note"
          >提交后与离开页面时清空输入，不写入本地缓存。服务端仅保存加密密文。</text
        >
        <button
          class="primary"
          :disabled="busy || !secure || secret.trim().length < 8"
          @click="save"
        >
          加密保存凭证
        </button>
      </view>
    </template>
  </view>
</template>
