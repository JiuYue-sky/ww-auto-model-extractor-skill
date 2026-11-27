# 贡献与反馈指南（Contributing Guide）

欢迎提交 Bug 报告、正式服已实装角色非拼音别名补充、风格化材质/着色器优化或文档改进！

## 1. 联系与反馈渠道

- **GitHub Issues**：推荐优先使用本仓库 Issue 模板提交问题或建议（便于其他宿主机检索）。
- **维护者联系邮箱**：`jiuyue200712@gmail.com`（适用于跨宿主机疑难排查、私有环境日志沟通或版权方响应）。

## 2. 提交 Pull Request 前的本地必跑核验

在提交任何代码或文档改动前，请务必在项目根目录运行全套自检与测试：

```bash
# 1. 包体内部防篡改、许可证与合规红线自检（必须 PASS）
python orchestrator.py --self-audit

# 2. 核心引擎全量单元测试与回归测试
python tests/test_pipeline_suite.py
```

## 3. 贡献红线与提交规范

1. **严禁提交任何游戏资产、AES 密钥、密钥拉取链接、专有闭源 DLL 或本机绝对路径**（如个人用户名路径、`output/`、`keys.json`、`AppSettings.json`）。
2. **严禁提交任何测试服（Beta）或未在正式服公开实装的角色名称、内部研发代号与相关内容**。
3. **所有文档相对链接必须真实可达**（`--self-audit` 会自动拦截死链与合规词缺失）。
4. **Commit 信息规范**：遵循 [Conventional Commits](https://www.conventionalcommits.org/)（如 `feat:`、`fix:`、`docs:`、`test:`、`chore:`）。
5. 所有原创贡献代码均按本仓库 MIT License（仅适用于原创源代码，详见 [`NOTICE.md`](NOTICE.md) 与 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)）开源。
