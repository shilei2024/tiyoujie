"""部署脚本与上线手册的仓库级校验（在主机上跑，不进容器）。"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "infra/deploy/verify-wechat.sh"
DEPLOY = ROOT / "infra/deploy/deploy.sh"
MANUAL = ROOT / "docs/operations/go-live-manual-steps.md"


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


if __name__ == "__main__":
    unittest.main()
