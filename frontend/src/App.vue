<script lang="ts">
export default {};
</script>

<style>
page {
  background: #f6f6f1;
  color: #253c34;
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 16px;
}
button::after,
.primary::after,
.secondary::after,
.text-button::after,
.nav-card::after {
  border: 0;
}
.page {
  max-width: 820px;
  padding: 36px 28px;
  margin: 0 auto;
}
.brand,
.row,
.toolbar,
.form-row,
.actions,
.footer {
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand {
  padding-bottom: 22px;
  border-bottom: 1px solid #dce2d8;
}
.brand-name {
  font-size: 25px;
  font-weight: 700;
  letter-spacing: 2px;
}
.intro {
  padding: 44px 0 32px;
}
.eyebrow {
  display: block;
  color: #758078;
  font-size: 13px;
  margin-bottom: 12px;
}
.heading {
  display: block;
  font-size: 34px;
  font-weight: 600;
  line-height: 1.6;
  margin-bottom: 12px;
}
.accent {
  color: #51775f;
}
.muted,
.note {
  color: #718078;
}
.small {
  font-size: 12px;
}
.note {
  display: block;
  font-size: 13px;
  line-height: 1.85;
  margin: 9px 0;
}
.panel {
  padding: 26px;
  border: 1px solid #dce2d8;
  border-radius: 12px;
  background: #fffefa;
  margin-bottom: 20px;
}
.section-title {
  display: block;
  font-size: 18px;
  font-weight: 600;
}
.row,
.toolbar,
.footer {
  justify-content: space-between;
}
.toolbar {
  margin-bottom: 16px;
}
.badge {
  background: #edf1e8;
  color: #60715e;
  padding: 5px 10px;
  border-radius: 5px;
  font-size: 12px;
}
.label {
  display: block;
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}
.input,
.picker-field {
  box-sizing: border-box;
  border: 1px solid #d5ded3;
  background: #fff;
  border-radius: 6px;
  padding: 12px;
  min-height: 46px;
  font-size: 14px;
  margin: 12px 0;
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
  border-radius: 6px;
  line-height: 46px;
  min-height: 46px;
  margin: 16px 0 0;
  padding: 0 20px;
}
.primary {
  background: #315b45;
  color: #fff;
}
.secondary {
  background: #edf1e8;
  color: #315b45;
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
  outline: 3px solid #a4b69d;
  outline-offset: 3px;
}
.text-button {
  margin: 0;
  padding: 4px 0;
  background: transparent;
  color: #42654f;
  font-size: 13px;
  line-height: 32px;
  text-align: left;
}
.danger {
  color: #a15a43;
}
.inset {
  margin-top: 24px;
  border-top: 1px solid #e6e9df;
  padding-top: 22px;
}
.empty {
  color: #849082;
  text-align: center;
  padding: 28px 0;
  font-size: 14px;
}
.child-row {
  border-top: 1px solid #e6e9df;
  padding: 20px 0 12px;
}
.child-name {
  font-size: 19px;
  font-weight: 600;
}
.child-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  color: #6b8465;
  background: #edf1e8;
}
.actions {
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
  margin: 10px 0;
}
.checkbox-label {
  display: flex;
  align-items: center;
  font-size: 13px;
  line-height: 1.8;
}
.link-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
.nav-card {
  background: #eaf0e5;
  padding: 22px;
  text-align: left;
  margin: 0;
  border-radius: 10px;
  line-height: 1.6;
}
.member-row {
  border-top: 1px solid #e6e9df;
  margin-top: 12px;
  padding-top: 12px;
}
.feedback {
  margin-bottom: 18px;
  padding: 12px 16px;
  border-left: 3px solid #7f976d;
  color: #42583d;
  background: #eef1e7;
  font-size: 14px;
  line-height: 1.8;
}
.footer {
  color: #7c897e;
  font-size: 12px;
}
.footnote {
  display: block;
  text-align: center;
  color: #83907f;
  font-size: 12px;
  margin: 30px 0 8px;
}
.break-word {
  word-break: break-all;
}
@media (max-width: 520px) {
  .page {
    padding: 26px 18px;
  }
  .brand .small {
    display: none;
  }
  .intro {
    padding: 34px 0 24px;
  }
  .heading {
    font-size: 27px;
  }
  .panel {
    padding: 20px;
  }
  .link-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .nav-card {
    padding: 18px 20px;
  }
  .form-row {
    gap: 8px;
  }
  .compact {
    padding: 0 12px;
  }
}
</style>
