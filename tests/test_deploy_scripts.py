"""部署脚本与上线手册的仓库级校验（在主机上跑，不进容器）。"""

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "infra/deploy/verify-wechat.sh"
ROTATE = ROOT / "infra/deploy/rotate-wechat-credentials.sh"
DEPLOY = ROOT / "infra/deploy/deploy.sh"
MANUAL = ROOT / "docs/operations/go-live-manual-steps.md"
BASH = shutil.which("bash")


class WeChatVerificationScriptTests(unittest.TestCase):
    """AppSecret 校验必须真向微信换 token，且任何路径都不打印密钥。

    只看“变量非空”会把错密钥当成配置完成，用户仍然登不进来。
    """

    def setUp(self):
        self.script = VERIFY.read_text(encoding="utf-8")

    def test_is_present_and_executable(self):
        self.assertTrue(VERIFY.is_file())
        self.assertTrue(os.access(VERIFY, os.X_OK))

    def test_queries_wechat_instead_of_checking_presence(self):
        self.assertIn("api.weixin.qq.com/cgi-bin/stable_token", self.script)
        self.assertIn("client_credential", self.script)

    def test_never_prints_the_secret(self):
        self.assertNotIn("set -x", self.script)
        for line in self.script.splitlines():
            if line.strip().startswith("#"):
                continue
            for command in ("printf", "echo", "say"):
                self.assertNotIn(f'{command} "$APP_SECRET"', line)
                self.assertNotIn(f"{command} $APP_SECRET", line)

    def test_reports_missing_secret_as_failure(self):
        """缺密钥要显式失败，不能悄悄放行。"""
        self.assertIn("缺少 WECHAT_APP_SECRET", self.script)
        self.assertRegex(self.script, r"缺少 WECHAT_APP_SECRET[\s\S]{0,200}exit 1")


class WeChatRotationScriptTests(unittest.TestCase):
    """换 AppID/Secret 必须成对、先验证后落盘、失败不改文件。

    分开换或先写后验都会造成登录不可用的空窗，靠人记顺序迟早出事。
    """

    def setUp(self):
        self.script = ROTATE.read_text(encoding="utf-8")

    def test_is_present_and_executable(self):
        self.assertTrue(ROTATE.is_file())
        self.assertTrue(os.access(ROTATE, os.X_OK))

    def test_verifies_before_touching_the_env_file(self):
        verify_at = self.script.index("api.weixin.qq.com/cgi-bin/stable_token")
        write_at = self.script.index("os.replace(tmp, path)")
        self.assertLess(verify_at, write_at, "校验必须在写入之前")
        self.assertIn("验证在写入之前", self.script)

    def test_backs_up_before_writing(self):
        backup_at = self.script.index(".bak-")
        write_at = self.script.index("os.replace(tmp, path)")
        self.assertLess(backup_at, write_at)

    def test_rejects_truncated_or_padded_secret(self):
        self.assertIn("-ne 32", self.script)

    def test_restarts_without_implicit_build(self):
        self.assertIn("--no-build", self.script)

    def test_never_prints_the_secret(self):
        self.assertNotIn("set -x", self.script)
        for line in self.script.splitlines():
            if line.strip().startswith("#"):
                continue
            for command in ("printf", "echo", "say"):
                self.assertNotIn(f'{command} "$NEW_APP_SECRET"', line)
                self.assertNotIn(f"{command} $NEW_APP_SECRET", line)

    def test_warns_about_identity_reset_and_client_steps(self):
        for phrase in ("openid", "服务器域名", "scripts/wechat.py build"):
            self.assertIn(phrase, self.script)

    @unittest.skipUnless(BASH, "当前主机没有 bash，跳过语法检查")
    def test_shell_syntax_is_valid(self):
        result = subprocess.run(
            [BASH, "-n", str(ROTATE)], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class MiniProgramAppIDTests(unittest.TestCase):
    """AppID 不再写死在 manifest 里。

    写死过一次的后果：换账号后忘了改，构建产物仍指向旧 AppID，
    上传“成功”但东西进了旧账号——和之前 origin 指向离线 bundle 是同一类静默错误。
    """

    def test_manifest_has_no_hardcoded_appid(self):
        manifest = json.loads(
            (ROOT / "frontend/src/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["mp-weixin"]["appid"], "")

    def test_builder_explains_where_the_appid_comes_from(self):
        script = (ROOT / "scripts/wechat.py").read_text(encoding="utf-8")
        self.assertIn("WECHAT_APP_ID", script)


class DeployScriptOriginTests(unittest.TestCase):
    """离线 bundle 曾让“发布成功”但版本没变，必须留下显式警告。"""

    def setUp(self):
        self.script = DEPLOY.read_text(encoding="utf-8")

    def test_warns_when_origin_is_a_local_path(self):
        self.assertIn("git remote get-url origin", self.script)
        warning_block = self.script.split("git remote get-url origin", 1)[1][:900]
        self.assertIn("警告", warning_block)
        self.assertIn("bundle", warning_block)

    def test_prints_code_source_on_every_pull(self):
        self.assertIn("代码来源", self.script)


class ManualPathsTests(unittest.TestCase):
    """手册里的命令必须与实际目录一致，抄下来就能跑。"""

    def setUp(self):
        self.text = MANUAL.read_text(encoding="utf-8")

    def test_uses_real_production_repo_path(self):
        self.assertIn("/opt/tiyoujie/repo/.env.prod", self.text.replace("`", ""))
        self.assertNotRegex(self.text, r"^cd /opt/tiyoujie$")

    def test_does_not_reference_nonexistent_compose_caddy_file(self):
        self.assertIsNone(re.search(r"compose\.caddy\.yaml", self.text))


class PrivacyNoticeVersionTests(unittest.TestCase):
    """监护人告知版本号必须与代码里判定同意的版本一致。

    版本漂移会让用户在旧文本下"同意"，而服务端记录的是新版本号。
    """

    def test_notice_version_matches_settings(self):
        settings_text = (ROOT / "backend/config/settings/base.py").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r'"GUARDIAN_NOTICE_VERSION":\s*"([0-9A-Za-z._-]+)"', settings_text
        )
        self.assertIsNotNone(match, "settings 中找不到 GUARDIAN_NOTICE_VERSION")
        version = match.group(1)
        notice = (ROOT / "docs/legal/privacy-notice.md").read_text(encoding="utf-8")
        self.assertIn(version, notice)


if __name__ == "__main__":
    unittest.main()
