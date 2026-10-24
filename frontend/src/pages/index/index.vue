<script setup lang="ts">
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { api, confirmAction, errorText, familyQuery } from "../../api/client";
import {
  clearSession,
  session,
  setLogin,
  type Family,
  type LoginResult,
} from "../../state";

interface Child {
  id: string;
  nickname: string;
  grade: number | null;
}
interface Consent {
  id: string;
  scope: string;
  revoked_at: string | null;
}
const capabilities = ref({
  dev_login_available: false,
  wechat_configured: false,
  guardian_notice_version: "",
});
const busy = ref(false),
  message = ref(""),
  identity = ref("");
const families = ref<Family[]>([]),
  children = ref<Child[]>([]),
  nextPage = ref<number | null>(null);
const familyName = ref(""),
  nickname = ref(""),
  grade = ref("");
const editing = ref(""),
  guardianConfirmed = ref(false),
  inviteToken = ref("");
const generatedInvite = ref(""),
  inviteChild = ref(""),
  inviteRole = ref<"student" | "guardian">("student");
const members = ref<{ id: string; user_id: number; role: string }[]>([]);
const owner = computed(
  () => !!session.user && session.family?.owner_id === session.user.id,
);
const guardian = computed(() => session.family?.role === "guardian");
const selectedFamilyIndex = computed(() =>
  families.value.findIndex((item) => item.id === session.family?.id),
);
const otherMembers = computed(() =>
  members.value.filter((item) => item.user_id !== session.user?.id),
);
const activeConsents = ref<Record<string, Consent[]>>({});
const receiptMessage = ref("");
const setupOnly = ref(false);
// #ifdef MP-WEIXIN
setupOnly.value = !import.meta.env.VITE_API_BASE_URL?.startsWith("https://");
// #endif

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
async function loadChildren(append = false) {
  if (!session.family) return;
  const page = append ? nextPage.value : 1;
  const result = await api<{ results: Child[]; next: number | null }>(
    `children/?${familyQuery()}&page=${page}`,
  );
  children.value = append
    ? [...children.value, ...result.results]
    : result.results;
  nextPage.value = result.next;
  activeConsents.value = {};
  members.value = [];
  if (guardian.value) {
    const consents = await Promise.all(
      children.value.map(async (child) => {
        const result = await api<{ results: Consent[] }>(
          `children/${child.id}/consents/`,
        );
        return [
          child.id,
          result.results.filter((item) => !item.revoked_at),
        ] as const;
      }),
    );
    activeConsents.value = Object.fromEntries(consents);
  }
  if (owner.value)
    members.value = (
      await api<{ results: typeof members.value }>(
        `families/${session.family.id}/members/`,
      )
    ).results;
}
async function loadFamilies(preferId?: string) {
  const all: Family[] = [];
  let page: number | null = 1;
  while (page) {
    const result: { results: Family[]; next: number | null } = await api(
      `families/?page=${page}`,
    );
    all.push(...result.results);
    page = result.next;
  }
  families.value = all;
  // 列表按创建时间升序，缺省取 all[0] 是"最早的家庭"。
  // 新建/加入后必须显式指定目标家庭，否则会在旧家庭里继续操作（孩子档案会建错地方）。
  const wanted = preferId || session.family?.id;
  session.family = all.find((item) => item.id === wanted) || all[0] || null;
  children.value = [];
  members.value = [];
  activeConsents.value = {};
  await loadChildren();
}
function selectFamily(event: { detail: { value: string | number } }) {
  session.family = families.value[Number(event.detail.value)] || null;
  generatedInvite.value = "";
  cancelEdit();
  void run(() => loadChildren());
}
onShow(() => {
  if (setupOnly.value) return;
  void run(async () => {
    capabilities.value = await api("auth/capabilities/");
    if (session.user) await loadFamilies();
  });
});
function devLogin() {
  void run(async () => {
    setLogin(
      await api<LoginResult>("auth/dev-login/", "POST", {
        identity: identity.value.trim(),
      }),
    );
    identity.value = "";
    await loadFamilies();
  });
}
function wechatLogin() {
  void run(async () => {
    // #ifdef MP-WEIXIN
    const code = await new Promise<string>((resolve, reject) =>
      uni.login({
        provider: "weixin",
        success: (result) =>
          result.code
            ? resolve(result.code)
            : reject(new Error("微信授权未完成。")),
        fail: () => reject(new Error("微信授权失败，请重试。")),
      }),
    );
    setLogin(await api<LoginResult>("auth/wechat-login/", "POST", { code }));
    await loadFamilies();
    // #endif
    // #ifdef H5
    message.value = "微信登录请在小程序中使用，并由管理员先完成服务端配置。";
    // #endif
  });
}
function createFamily() {
  void run(async () => {
    const created = await api<Family>("families/", "POST", {
      name: familyName.value.trim(),
    });
    familyName.value = "";
    await loadFamilies(created.id);
  });
}
function saveChild() {
  void run(async () => {
    const parsedGrade = grade.value.trim() ? Number(grade.value) : null;
    if (
      !nickname.value.trim() ||
      (parsedGrade !== null &&
        (!Number.isInteger(parsedGrade) || parsedGrade < 1 || parsedGrade > 12))
    ) {
      throw new Error("请填写昵称，年级可留空或填写 1–12 的整数。");
    }
    if (editing.value) {
      await api(`children/${editing.value}/update/`, "POST", {
        nickname: nickname.value.trim(),
        grade: parsedGrade,
      });
    } else {
      if (!guardianConfirmed.value)
        throw new Error("请先阅读并确认监护人告知。");
      await api("children/", "POST", {
        family_id: session.family?.id,
        nickname: nickname.value.trim(),
        grade: parsedGrade,
        guardian_confirmed: true,
        notice_version: capabilities.value.guardian_notice_version,
      });
    }
    cancelEdit();
    await loadChildren();
    message.value = "档案已保存。";
  });
}
function editChild(child: Child) {
  editing.value = child.id;
  nickname.value = child.nickname;
  grade.value = child.grade?.toString() || "";
}
function cancelEdit() {
  editing.value = "";
  nickname.value = "";
  grade.value = "";
  guardianConfirmed.value = false;
}
async function deleteChild(child: Child) {
  if (
    !(await confirmAction(
      `删除“${child.nickname}”的档案？确认后立即停止访问，并由后台清理。`,
    ))
  )
    return;
  void run(async () => {
    await api(`children/${child.id}/`, "DELETE", { confirm: true });
    await loadChildren();
    message.value = "档案已停止访问，后台正在清理。";
  });
}
async function changeConsent(child: Child) {
  const consent = activeConsents.value[child.id]?.find(
    (item) => item.scope === "profile",
  );
  if (
    !(await confirmAction(
      consent
        ? "撤回档案管理授权后，将停止编辑。"
        : "确认你有监护权限，同意为此孩子保存和管理学习档案。当前不向 AI 服务发送资料。",
    ))
  )
    return;
  void run(async () => {
    if (consent)
      await api(`children/${child.id}/consents/${consent.id}/`, "DELETE");
    else
      await api(`children/${child.id}/consents/`, "POST", {
        scope: "profile",
        notice_version: capabilities.value.guardian_notice_version,
      });
    await loadChildren();
    message.value = "授权状态已更新。";
  });
}
function joinFamily() {
  void run(async () => {
    const joined = await api<Family>("invitations/accept/", "POST", {
      invitation_token: inviteToken.value.trim(),
    });
    inviteToken.value = "";
    await loadFamilies(joined.id);
    message.value = "已加入获授权的家庭。";
  });
}
function createInvitation() {
  void run(async () => {
    const selected = inviteChild.value || children.value[0]?.id;
    if (!selected) throw new Error("请先创建孩子档案。");
    const result = await api<{ invitation_token: string }>(
      `families/${session.family?.id}/invitations/`,
      "POST",
      { role: inviteRole.value, child_ids: [selected] },
    );
    generatedInvite.value = result.invitation_token;
  });
}
async function removeMember(id: string) {
  if (!(await confirmAction("移除该成员？其访问授权和登录会话会立即撤销。")))
    return;
  void run(async () => {
    await api(`family-members/${id}/`, "DELETE");
    await loadChildren();
  });
}
function navigate(url: string) {
  uni.navigateTo({ url });
}
function logout() {
  void run(async () => {
    await api("auth/logout/", "POST");
    clearSession();
    children.value = [];
    families.value = [];
    generatedInvite.value = "";
  });
}
async function deleteAccount() {
  if (
    !(await confirmAction(
      "申请注销当前账号及自己拥有的家庭数据？后台清理不可撤销；家庭有其他成员时需先移除成员。",
    ))
  )
    return;
  void run(async () => {
    const result = await api<{ task_id: string; deletion_receipt: string }>(
      "account-deletion-jobs/",
      "POST",
      { confirm: true },
    );
    clearSession();
    families.value = [];
    children.value = [];
    generatedInvite.value = "";
    receiptMessage.value = `注销已受理。任务：${result.task_id}；查询凭据：${result.deletion_receipt}。请自行妥善保存。`;
  });
}
</script>

<template>
  <view class="page">
    <view class="brand"
      ><text class="brand-name">题有解</text
      ><text class="muted small">学习的每一步，都算数</text></view
    >
    <view class="intro"
      ><text class="eyebrow">让进步，有迹可循。</text
      ><text class="heading"
        >从一份<text class="accent">学习档案</text>开始。</text
      ><text class="muted"
        >管理家庭与孩子资料，为接下来的错题学习做好准备。</text
      ></view
    >
    <view v-if="message" class="feedback" role="status" aria-live="polite">{{
      message
    }}</view>
    <view v-if="receiptMessage" class="panel break-word">{{
      receiptMessage
    }}</view>
    <view v-if="!session.user" class="panel">
      <view v-if="setupOnly" class="inset">
        <text class="section-title">小程序界面预览</text>
        <text class="note"
          >后端服务尚未连接。连接后才能登录、保存学习资料和管理错题；当前预览不会发送登录或题目请求。</text
        >
      </view>
      <text class="section-title">登录题有解</text>
      <text class="note"
        >微信登录需在小程序中完成。登录会话仅保存在当前页面内存，刷新后需重新登录。</text
      >
      <button
        class="primary"
        :disabled="busy || !capabilities.wechat_configured"
        @click="wechatLogin"
      >
        微信登录
      </button>
      <text v-if="!capabilities.wechat_configured" class="note"
        >服务端尚未配置微信登录。</text
      >
      <view v-if="capabilities.dev_login_available" class="inset">
        <text class="label">本地测试登录 · 无真实微信授权</text
        ><text class="note"
          >仅用于本机验收。测试身份使用 3–32
          位字母、数字、下划线或短横线。</text
        >
        <input
          v-model="identity"
          class="input"
          aria-label="测试身份"
          placeholder="输入测试身份"
          maxlength="32"
          :disabled="busy"
        />
        <button
          class="secondary"
          :disabled="busy || !identity.trim()"
          @click="devLogin"
        >
          使用测试身份登录
        </button>
      </view>
    </view>
    <template v-else>
      <view class="toolbar"
        ><text class="badge">{{
          session.user.is_test_login ? "本地测试会话" : "微信会话"
        }}</text
        ><button class="text-button" :disabled="busy" @click="logout">
          退出登录
        </button></view
      >
      <view class="panel">
        <view class="row"
          ><text class="section-title">我的家庭</text
          ><text class="muted small">{{ families.length }} 个家庭</text></view
        >
        <picker
          v-if="families.length"
          :range="families"
          range-key="name"
          :value="selectedFamilyIndex"
          :disabled="busy"
          @change="selectFamily"
          ><view class="picker-field"
            >{{ session.family?.name }} <text class="muted">⌄</text></view
          ></picker
        >
        <text v-else class="note"
          >还没有家庭。创建自己的家庭，或使用邀请加入。</text
        >
        <view class="form-row"
          ><input
            v-model="familyName"
            class="input"
            aria-label="家庭名称"
            placeholder="新的家庭名称"
            maxlength="40"
            :disabled="busy"
          /><button
            class="secondary compact"
            :disabled="busy || !familyName.trim()"
            @click="createFamily"
          >
            创建家庭
          </button></view
        >
      </view>
      <view v-if="session.family" class="panel">
        <view class="row"
          ><text class="section-title">孩子档案</text
          ><text class="badge">{{
            session.family.role === "student" ? "学生 · 只读" : "监护人"
          }}</text></view
        >
        <text class="note">只填写学习所需资料，使用昵称即可。</text>
        <view v-if="!children.length" class="empty">暂无可访问的孩子档案</view>
        <view v-for="child in children" :key="child.id" class="child-row">
          <button
            class="text-button"
            @click="navigate('/pages/problems/index?child_id=' + child.id)"
          >
            查看错题本 →
          </button>
          <view class="row"
            ><view
              ><text class="child-name">{{ child.nickname }}</text
              ><text class="note">{{
                child.grade ? `${child.grade} 年级` : "年级未填写"
              }}</text></view
            ><text class="child-mark">学</text></view
          >
          <view v-if="guardian" class="actions"
            ><button
              class="text-button"
              :disabled="busy"
              @click="editChild(child)"
            >
              编辑档案</button
            ><button
              class="text-button"
              :disabled="busy"
              @click="changeConsent(child)"
            >
              管理授权</button
            ><button
              class="text-button danger"
              :disabled="busy"
              @click="deleteChild(child)"
            >
              删除档案
            </button></view
          >
          <text v-if="guardian" class="small muted">{{
            activeConsents[child.id]?.some((item) => item.scope === "profile")
              ? "档案管理已授权"
              : "档案管理授权已撤回"
          }}</text>
        </view>
        <button
          v-if="nextPage"
          class="secondary"
          :disabled="busy"
          @click="run(() => loadChildren(true))"
        >
          加载更多档案
        </button>
        <view v-if="owner || (guardian && editing)" class="inset">
          <text class="label">{{ editing ? "编辑学习档案" : "添加孩子" }}</text>
          <view class="form-row"
            ><input
              v-model="nickname"
              class="input"
              aria-label="孩子昵称"
              placeholder="孩子昵称"
              maxlength="32"
              :disabled="busy" /><input
              v-model="grade"
              class="input grade-input"
              aria-label="年级"
              placeholder="年级（可选）"
              maxlength="2"
              type="number"
              :disabled="busy"
          /></view>
          <template v-if="!editing"
            ><text class="note"
              >监护人告知（{{
                capabilities.guardian_notice_version
              }}）：确认你有权为孩子建立档案，资料用于家庭学习管理；可以撤回授权或申请删除。向第三方
              AI 服务发送资料需在具体任务中另行确认。</text
            ><checkbox-group
              @change="
                guardianConfirmed = ($event.detail.value as string[]).includes(
                  'yes',
                )
              "
              ><label class="checkbox-label"
                ><checkbox
                  value="yes"
                  :checked="guardianConfirmed"
                  color="#315b45"
                  :disabled="busy"
                />我已阅读，并以监护人身份同意</label
              ></checkbox-group
            ></template
          >
          <button
            class="primary"
            :disabled="
              busy || !nickname.trim() || (!editing && !guardianConfirmed)
            "
            @click="saveChild"
          >
            保存学习档案
          </button>
          <button
            v-if="editing"
            class="text-button"
            :disabled="busy"
            @click="cancelEdit"
          >
            取消编辑
          </button>
        </view>
      </view>
      <view v-if="session.family" class="link-grid"
        ><button class="nav-card" @click="navigate('/pages/problems/index')">
          <text class="section-title">我的错题本</text
          ><text class="note">图片、题干与人工校对 →</text></button
        ><button class="nav-card" @click="navigate('/pages/practice/index')">
          <text class="section-title">今日复习</text
          ><text class="note">间隔复习与学习趋势 →</text></button
        ><button class="nav-card" @click="navigate('/pages/worksheets/index')">
          <text class="section-title">练习题单</text
          ><text class="note">组题、作答与导出 →</text></button
        ><button class="nav-card" @click="navigate('/pages/settings/index')">
          <text class="section-title">AI 设置</text
          ><text class="note">管理自己的服务凭证 →</text></button
        ><button class="nav-card" @click="navigate('/pages/benefits/index')">
          <text class="section-title">免费权益</text
          ><text class="note">查看家庭功能与到期时间 →</text>
        </button></view
      >
      <view class="panel">
        <text class="section-title">家庭协作</text
        ><text class="note"
          >邀请仅授予指定孩子的访问范围。邀请码限时、单次使用，请只交给你认可的人。</text
        >
        <view v-if="owner && children.length" class="inset">
          <picker
            :range="children"
            range-key="nickname"
            @change="
              inviteChild = children[Number($event.detail.value)]?.id || ''
            "
            ><view class="picker-field"
              >{{
                children.find((item) => item.id === inviteChild)?.nickname ||
                children[0]?.nickname
              }}
              · 选择授权档案 ⌄</view
            ></picker
          >
          <radio-group
            class="actions"
            @change="inviteRole = $event.detail.value as 'student' | 'guardian'"
            ><label
              ><radio
                value="student"
                :checked="inviteRole === 'student'"
                color="#315b45"
              />学生（只读）</label
            ><label
              ><radio
                value="guardian"
                :checked="inviteRole === 'guardian'"
                color="#315b45"
              />监护人（可管理）</label
            ></radio-group
          >
          <button class="secondary" :disabled="busy" @click="createInvitation">
            生成单次邀请</button
          ><text v-if="generatedInvite" class="note break-word" selectable
            >邀请码：{{ generatedInvite }}（24 小时有效）</text
          >
        </view>
        <view class="form-row"
          ><input
            v-model="inviteToken"
            class="input"
            aria-label="邀请码"
            placeholder="输入收到的邀请码"
            maxlength="256"
            :disabled="busy"
          /><button
            class="secondary compact"
            :disabled="busy || !inviteToken.trim()"
            @click="joinFamily"
          >
            加入家庭
          </button></view
        >
        <template v-if="owner"
          ><view
            v-for="member in otherMembers"
            :key="member.id"
            class="row member-row"
            ><text class="small"
              >成员 {{ member.user_id }} ·
              {{ member.role === "student" ? "学生" : "监护人" }}</text
            ><button
              class="text-button danger"
              :disabled="busy"
              @click="removeMember(member.id)"
            >
              移除成员
            </button></view
          ></template
        >
      </view>
      <view class="footer"
        ><text>AI 结果需要人工核对</text
        ><button
          class="text-button danger"
          :disabled="busy"
          @click="deleteAccount"
        >
          申请注销账号
        </button></view
      >
    </template>
    <text class="footnote">用认真，陪伴每一次进步。</text>
  </view>
</template>
