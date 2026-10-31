<script setup lang="ts">
const props = defineProps<{ active: number }>();

function dataUri(svg: string): string {
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

const OUTLINE = "#9ca3af";
const PRIMARY = "#2563eb";

const ICONS: Record<string, { outline: string; filled: string }> = {
  home: {
    outline: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${OUTLINE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5"/><path d="M9.5 21v-6h5v6"/></svg>`,
    ),
    filled: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="${PRIMARY}" d="M12 2.6 2.8 10.3a1 1 0 0 0 .7 1.7H5v8a1.5 1.5 0 0 0 1.5 1.5h4.5v-6h2v6h4.5A1.5 1.5 0 0 0 19 20v-8h1.5a1 1 0 0 0 .7-1.7L12 2.6Z"/></svg>`,
    ),
  },
  book: {
    outline: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${OUTLINE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4a1 1 0 0 1 1-1h15v16H6a2 2 0 0 0-2 2z"/><path d="M4 4v15a2 2 0 0 0 2 2"/><path d="M8 7h7"/><path d="M8 10.5h7"/></svg>`,
    ),
    filled: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="${PRIMARY}" d="M5.5 2.5h13A1.5 1.5 0 0 1 20 4v16a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 20V4a1.5 1.5 0 0 1 1.5-1.5z"/><path d="M8 7h6M8 10.5h6" fill="none" stroke="#ffffff" stroke-width="1.6" stroke-linecap="round"/></svg>`,
    ),
  },
  review: {
    outline: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${OUTLINE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.2l2.5 6.5 6.5 1.5-5 4.4 1.5 6.9-5.5-3.4-5.5 3.4 1.5-6.9-5-4.4 6.5-1.5z"/></svg>`,
    ),
    filled: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="${PRIMARY}" d="M12 2.2l2.5 6.5 6.5 1.5-5 4.4 1.5 6.9-5.5-3.4-5.5 3.4 1.5-6.9-5-4.4 6.5-1.5z"/></svg>`,
    ),
  },
  me: {
    outline: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${OUTLINE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5c0-3.6 3.4-5.7 7.5-5.7s7.5 2.1 7.5 5.7"/></svg>`,
    ),
    filled: dataUri(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle fill="${PRIMARY}" cx="12" cy="8" r="4"/><path fill="${PRIMARY}" d="M4 21c0-4 3.6-6.3 8-6.3s8 2.3 8 6.3z"/></svg>`,
    ),
  },
};

const tabs = [
  { label: "首页", path: "/pages/index/index", icon: "home" },
  { label: "错题本", path: "/pages/problems/index", icon: "book" },
  { label: "智能复习", path: "/pages/practice/index", icon: "review" },
  { label: "我的", path: "/pages/settings/index", icon: "me" },
];

function switchTo(path: string, index: number): void {
  if (index === props.active) return;
  uni.switchTab({ url: path });
}
</script>

<template>
  <view class="tab-bar">
    <view
      v-for="(tab, index) in tabs"
      :key="tab.path"
      class="tab-item"
      :class="{ active: index === active }"
      @click="switchTo(tab.path, index)"
    >
      <image
        class="tab-icon"
        :src="ICONS[tab.icon][index === active ? 'filled' : 'outline']"
        mode="aspectFit"
      />
      <text class="tab-label">{{ tab.label }}</text>
    </view>
  </view>
</template>

<style scoped>
.tab-bar {
  position: fixed;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100%;
  max-width: 820px;
  display: flex;
  background: #ffffff;
  border-top: 1px solid #eef0f4;
  padding-bottom: constant(safe-area-inset-bottom);
  padding-bottom: env(safe-area-inset-bottom);
  z-index: 999;
}
.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 10px 0 8px;
}
.tab-icon {
  width: 23px;
  height: 23px;
  transition: transform 160ms ease;
}
.tab-item.active .tab-icon {
  transform: translateY(-3px);
}
.tab-label {
  font-size: 10px;
  line-height: 1;
  color: #9ca3af;
  transition: color 160ms ease;
}
.tab-item.active .tab-label {
  color: #2563eb;
  font-weight: 600;
}
</style>
