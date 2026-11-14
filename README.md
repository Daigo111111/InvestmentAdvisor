# 基金股票投资助手

每个交易日自动分析你的基金和股票持仓，在 15:00 截止前给出「卖出 / 减仓 / 加仓 / 不动」建议，并推送到飞书和微信。手机上以 PWA 形式使用，不需要电脑开机，不需要服务器费用。

> 本项目由规则与量化指标生成建议，仅供个人学习参考，不构成投资建议。

## 功能

- **基金助手**：自动获取最新季报前十大重仓股，用重仓股实时涨跌估算当日净值（同时参考东方财富估值），结合止损、移动止盈、超买、趋势、板块强度、同类排名给出操作建议；按持有天数计算赎回费，持有不满 7 天时提醒不要赎回；趋势转弱时推荐强势板块的替代基金。
- **股票助手**：全市场约 3000 只股票按财报（ROE、增速、毛利率、现金流）、估值、分红、技术面、新闻情绪打分，分为红利低波、价值蓝筹、科技成长、消费医药、周期资源、新闻催化六个专区；持股按 ATR 移动止损、仓位上限、超买、负面新闻给出加减仓股数。
- **资产配置**：按沪深300 相对 60 日均线判断「进攻 / 均衡 / 防守」，在最大回撤约束下给出各专区目标仓位和再平衡金额；组合回撤超过 8% 时权益仓位减半。
- **回测**：配置策略自 2015 年起回测（年化、最大回撤、夏普、逐年收益），每只基金的买卖规则与一直持有对比。
- **推送**：09:00 早报、14:10 尾盘决策、20:30 晚间复盘（含估值误差检查）、周六周报。
- **持仓导入**：手动录入，或上传支付宝 / 天天基金 / 银行 App 截图，在手机本地 OCR 识别后核对保存。
- **隐私**：持仓和报告用你的口令加密（PBKDF2 + AES-256-GCM）后才存入仓库，网页在浏览器里解密。
- **大模型预留**：配置 `LLM_PROVIDER=openai_compat` 及 `LLM_BASE_URL / LLM_MODEL / LLM_API_KEY` 即可接入 DeepSeek、千帆等 OpenAI 兼容接口，未配置时完全使用规则。

## 架构

```
GitHub Actions 定时任务 ──> engine/（Python + AkShare/腾讯行情/中证指数）
        │                       │
        │                       ├─> data/*.enc.json（加密报告，提交回仓库）
        │                       └─> 飞书机器人 / WxPusher 推送
        └─> GitHub Pages ──> web/（无需构建的 PWA，浏览器内解密展示）
```

## 部署步骤

1. **建仓库**：在 GitHub 新建一个 **Public** 仓库（免费账号的 Pages 只支持公开仓库；数据已加密，别人只能看到代码），把本项目推送到 `main` 分支。
2. **开启 Pages**：仓库 Settings → Pages → Source 选 **GitHub Actions**。
3. **配置 Secrets**（Settings → Secrets and variables → Actions → Secrets）：
   - `ADVISOR_PASSPHRASE`：加密口令，**至少 12 位**，忘记后数据无法恢复
   - `FEISHU_WEBHOOK`：飞书群 → 设置 → 群机器人 → 添加「自定义机器人」后得到的地址
   - `FEISHU_SECRET`（可选）：机器人开启「签名校验」时的密钥
   - `WXPUSHER_APP_TOKEN`、`WXPUSHER_UIDS`：在 wxpusher.zjiecode.com 创建应用得到 appToken，微信扫码关注后得到 UID（多个用逗号分隔）
4. **配置 Variables**（同一页面 Variables 标签）：`PAGES_URL` = `https://<用户名>.github.io/<仓库名>/`，推送卡片里的按钮会跳转到这里。
5. **首次运行**：Actions → advisor → Run workflow，选 `refresh`。完成后打开 `PAGES_URL`，没有持仓时会显示演示数据。
6. **录入持仓**：手机打开网页 → 我的 → 填写 GitHub 用户名、仓库名和令牌 → 输入口令解锁 → 持仓管理里添加或截图导入 → 保存。保存后会自动触发重新分析。
   - 令牌在 GitHub → Settings → Developer settings → Fine-grained tokens 创建，只选这个仓库，权限给 **Contents: Read and write** 和 **Actions: Read and write**。
7. **装到手机**：iPhone 用 Safari 打开 → 分享 →「添加到主屏幕」。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt
cd engine
../.venv/bin/python -m advisor run --job close --demo --no-push --force   # 用示例持仓跑一遍
../.venv/bin/python -m pytest -q tests
../.venv/bin/python -m advisor build-site && python3 -m http.server 8000 --directory ../_site
```

其他命令：`encrypt-holdings --in 文件.json`（用 `ADVISOR_PASSPHRASE` 加密明文持仓）、`decrypt-holdings --out 文件.json`、`test-push`（测试推送配置）。持仓文件格式见 `data/demo_holdings.json`。

## 已知限制

- 基金重仓股来自季报，只有前十大且有滞后，估值误差会在晚间复盘里列出。QDII 基金无法用 A 股行情估值。
- 数据来自免费公开接口，可能限流或改版。代码已做重试、多数据源回退和熔断，单个数据源失败不会中断整份报告。
- GitHub 定时任务高峰期可能延迟几分钟到几十分钟。尾盘任务定在 14:10；如果超过 14:55 才运行，推送里会提示可能按下一交易日净值确认。
- 回测参数经过少量调试，存在过拟合风险，历史表现不代表未来。
