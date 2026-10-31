<script lang="ts">
export default {};
</script>

<style>
page {
  background: #f5f6f8;
  color: #1f2937;
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 15px;
  line-height: 1.6;
}
button::after,
.primary::after,
.secondary::after,
.text-button::after,
.nav-card::after {
  border: 0;
}
.page {
  box-sizing: border-box;
  width: 100%;
  max-width: 820px;
  padding: 32px 24px;
  padding-bottom: calc(32px + env(safe-area-inset-bottom));
  margin: 0 auto;
}
.page-tab {
  padding-bottom: calc(120px + env(safe-area-inset-bottom));
}
.brand,
.row,
.toolbar,
.form-row,
.actions,
.footer {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand {
  padding-bottom: 16px;
  border-bottom: 1px solid #eef0f4;
}
.brand-name {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #111827;
}
.intro {
  padding: 24px 0 16px;
}
.eyebrow {
  display: block;
  color: #9ca3af;
  font-size: 12px;
  margin-bottom: 8px;
}
.heading {
  display: block;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.4;
  margin-bottom: 8px;
  color: #111827;
}
.accent {
  color: #2563eb;
}
.muted,
.note {
  color: #6b7280;
}
.small {
  font-size: 12px;
}
.note {
  display: block;
  font-size: 13px;
  line-height: 1.7;
  margin: 8px 0;
}
.panel {
  box-sizing: border-box;
  padding: 20px;
  border: 1px solid #eef0f4;
  border-radius: 16px;
  background: #ffffff;
  margin-bottom: 16px;
}
.section-title {
  display: block;
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}
.row,
.toolbar,
.footer {
  justify-content: space-between;
}
.toolbar {
  margin-bottom: 12px;
}
.badge {
  background: #eaf1fe;
  color: #2563eb;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
}
.badge-success {
  background: #e7f6ec;
  color: #16a34a;
}
.badge-warning {
  background: #fdf3e3;
  color: #b45309;
}
.label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #1f2937;
}
.input,
.picker-field {
  box-sizing: border-box;
  border: 1px solid #eef0f4;
  background: #fbfcfd;
  border-radius: 12px;
  padding: 12px;
  min-height: 44px;
  font-size: 14px;
  margin: 8px 0;
}
.picker-field {
  display: flex;
  justify-content: space-between;
}
.form-row .input {
  flex: 1;
  min-width: 0;
}
.grade-input {
  max-width: 150px;
}
.primary,
.secondary {
  font-size: 14px;
  border-radius: 12px;
  line-height: 44px;
  min-height: 44px;
  margin: 12px 0 0;
  padding: 0 20px;
}
.primary {
  background: #2563eb;
  color: #fff;
}
.secondary {
  background: #eaf1fe;
  color: #2563eb;
}
.success-button {
  background: #e7f6ec;
  color: #16a34a;
}
.danger-button {
  background: #fee2e2;
  color: #dc2626;
}
.warning-button {
  background: #fef3c7;
  color: #b45309;
}
.compact {
  flex-shrink: 0;
  margin: 0;
}
button[disabled] {
  opacity: 0.5;
}
button:focus-visible,
input:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 3px;
}
.text-button {
  margin: 0;
  padding: 4px 0;
  background: transparent;
  color: #2563eb;
  font-size: 13px;
  line-height: 32px;
  text-align: left;
}
.danger {
  color: #dc2626;
}
.success {
  color: #16a34a;
}
.warning {
  color: #f59e0b;
}
.inset {
  margin-top: 20px;
  border-top: 1px solid #eef0f4;
  padding-top: 16px;
}
.empty {
  color: #9ca3af;
  text-align: center;
  padding: 24px 0;
  font-size: 14px;
}
.child-row {
  border-top: 1px solid #eef0f4;
  padding: 16px 0 8px;
}
.child-name {
  font-size: 17px;
  font-weight: 600;
  color: #111827;
}
.child-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  color: #2563eb;
  background: #eaf1fe;
}
.actions {
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  margin: 8px 0;
}
.checkbox-label {
  display: flex;
  align-items: center;
  font-size: 13px;
  line-height: 1.7;
}
.link-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.nav-card {
  background: #ffffff;
  border: 1px solid #eef0f4;
  padding: 20px;
  text-align: left;
  margin: 0;
  border-radius: 16px;
  line-height: 1.5;
}
.member-row {
  border-top: 1px solid #eef0f4;
  margin-top: 8px;
  padding-top: 8px;
}
.feedback {
  margin-bottom: 16px;
  padding: 12px 16px;
  border-left: 3px solid #2563eb;
  color: #1f2937;
  background: #eaf1fe;
  font-size: 14px;
  line-height: 1.7;
  border-radius: 8px;
}
.notice {
  display: block;
  margin: 12px 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: #eaf1fe;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.6;
}
.footer {
  color: #9ca3af;
  font-size: 12px;
}
.footnote {
  display: block;
  text-align: center;
  color: #9ca3af;
  font-size: 12px;
  margin: 24px 0 8px;
}
.break-word {
  word-break: break-all;
}
@media (max-width: 520px) {
  .page {
    padding: 20px 16px;
    padding-bottom: calc(20px + env(safe-area-inset-bottom));
  }
  .page-tab {
    padding-bottom: calc(116px + env(safe-area-inset-bottom));
  }
  .brand .small {
    display: none;
  }
  .intro {
    padding: 20px 0 12px;
  }
  .heading {
    font-size: 24px;
  }
  .panel {
    padding: 16px;
    border-radius: 14px;
  }
  .link-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .nav-card {
    padding: 16px;
  }
  .form-row {
    gap: 8px;
  }
  .compact {
    padding: 0 12px;
  }
}
</style>
