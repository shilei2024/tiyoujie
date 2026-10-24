<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, errorText, familyQuery } from "../../api/client";
import { session } from "../../state";
interface Grant {
  id: string;
  features: string[];
  starts_at: string;
  expires_at: string;
  effective_status: string;
}
interface Campaign {
  id: string;
  name: string;
  duration_months: number;
  features: string[];
}
const grants = ref<Grant[]>([]),
  campaigns = ref<Campaign[]>([]),
  notices = ref<{ id: string; message: string }[]>([]);
const limit = ref<number | null>(null),
  busy = ref(false),
  message = ref("");
const owner = computed(
  () => !!session.user && session.family?.owner_id === session.user.id,
);
const featureNames: Record<string, string> = {
  advanced_reports: "进阶学习报告",
  bulk_management: "批量管理",
  extended_exports: "扩展导出",
  extra_child_profiles: "扩展孩子档案",
};
function features(values: string[]) {
  return (
    values.map((value) => featureNames[value] || "待开放功能").join("、") ||
    "当前未配置附加功能"
  );
}
function date(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}
async function refresh() {
  const result = await api<{ grants: Grant[]; child_profile_limit: number }>(
    `entitlements/me/?${familyQuery()}`,
  );
  grants.value = result.grants;
  limit.value = result.child_profile_limit;
  if (owner.value) {
    campaigns.value = (
      await api<{ results: Campaign[] }>(
        `promotion-campaigns/eligible/?${familyQuery()}`,
      )
    ).results;
    notices.value = (
      await api<{ results: typeof notices.value }>(
        `notifications/?${familyQuery()}`,
      )
    ).results;
  }
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
  grants.value = [];
  campaigns.value = [];
  notices.value = [];
  limit.value = null;
  if (session.user && session.family) void run(refresh);
});
function claim(campaign: Campaign) {
  void run(async () => {
    await api(`promotion-campaigns/${campaign.id}/claim/`, "POST", {
      family_id: session.family?.id,
    });
    await refresh();
    message.value = "权益已领取，到期时间以服务端记录为准。";
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
      ><text class="eyebrow">看得清楚，用得安心。</text
      ><text class="heading">家庭免费权益</text
      ><text class="muted">{{
        session.family?.name || "请先登录并选择家庭"
      }}</text></view
    >
    <view v-if="message" class="feedback" role="status">{{ message }}</view>
    <view class="panel"
      ><text class="section-title">当前档案额度</text
      ><text class="heading accent"
        >{{ limit === null ? "—" : limit }}
        <text class="small muted">个孩子档案</text></text
      ><text class="note"
        >到期后按基础额度限制新增，已经建立的学习资料继续保留。功能是否开放以实际页面为准。</text
      ></view
    >
    <view class="panel"
      ><text class="section-title">功能体验记录</text
      ><text v-if="!grants.length" class="empty">暂无领取记录</text>
      <view v-for="grant in grants" :key="grant.id" class="child-row"
        ><view class="row"
          ><text class="label">{{ features(grant.features) }}</text
          ><text class="badge">{{
            grant.effective_status === "active"
              ? "生效中"
              : grant.effective_status === "revoked"
                ? "已撤销"
                : "已到期"
          }}</text></view
        ><text class="note"
          >开始：{{ date(grant.starts_at) }}<br />到期：{{
            date(grant.expires_at)
          }}</text
        ></view
      >
    </view>
    <view v-if="owner" class="panel"
      ><text class="section-title">可领取的活动</text
      ><text v-if="!campaigns.length" class="empty"
        >当前没有符合资格的活动</text
      >
      <view v-for="campaign in campaigns" :key="campaign.id" class="child-row"
        ><text class="label">{{ campaign.name }}</text
        ><text class="note"
          >{{ campaign.duration_months }} 个自然月 ·
          {{ features(campaign.features) }}</text
        ><button class="secondary" :disabled="busy" @click="claim(campaign)">
          领取功能体验
        </button></view
      >
    </view>
    <view class="panel"
      ><text class="section-title">费用说明</text
      ><text class="note"
        >这里的权益是平台功能权限，AI
        服务当前未开放。后续平台体验将有独立调用限额；使用自己的 API
        凭证时，费用由供应商账户结算。到期不会自动扣费或删除学习资料。</text
      ></view
    >
    <view v-if="notices.length" class="panel"
      ><text class="section-title">家庭提醒</text
      ><text v-for="notice in notices" :key="notice.id" class="note">{{
        notice.message
      }}</text></view
    >
  </view>
</template>
