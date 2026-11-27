# 版本更新与发布运维指南（宿主机更新方式 + 开源发版流程）

本文档同时适用于以下两个**在 GitHub 分开独立发布**的非官方开源项目：
1. **DSH 插件版**（`dsh-ww-auto-model-extractor`）：发布于 **GitHub 独立仓库** 与 **DSH 插件市场（`dshmarket` / npm）**。
2. **通用包体 / 标准 Skill 版**（`ww-auto-model-extractor-skill`）：**仅发布于 GitHub 独立仓库**。

> **重要运维隔离原则**：公开开源版本与开发者个人本地实验环境保持严格物理分离；发版前必须在开源仓库目录独立运行 `--self-audit` 与洁净室回归验证，确保零闭源专有 DLL、零密钥/寻钥链接及零未公开代号混入发行包。

---

## 一、宿主机用户如何安全更新

### 1. DeepSeek Harness (DSH) 插件版更新方式
- **渠道 1（DSH 插件市场 / npm）**：在 DSH 客户端「插件管理」页面点击**「更新」**，或执行 `dsh plugin update dsh-ww-auto-model-extractor`。
- **渠道 2（GitHub Releases `.tgz` 直装）**：运行 `dsh plugin add https://github.com/JiuYue-sky/dsh-ww-auto-model-extractor/releases/download/v0.1.2/dsh-ww-auto-model-extractor-0.1.2.tgz`。
- **渠道 3（本地离线 `file:` 快照刷新）**：在 `~/.dsh/profiles/desktop` 重新执行 `pnpm add file:<插件目录> --prefer-offline --ignore-scripts` 并重启 DSH 客户端。
- **验收**：调用 `dsh_ww_self_audit` 确认 `core_version` 已变为新版（如 `0.1.2`）且 `status == "PASS"`。

### 2. 通用包体 / 标准 `Skill` 版更新方式
1. 运行时建议始终通过 `--work-dir "D:\WW_Outputs"` 将产出工程放在包体目录外部；若之前已授权下载便携版 Blender 或 Oodle 运行库至包内 `runtime/`，覆盖升级前保留 `runtime/` 目录即可避免重复下载。
2. 解压新版 `ww-auto-model-extractor-skill-v0.1.2.zip`（核对 `.sha256`）替换原 `skills/ww-auto-model-extractor/` 目录，运行 `python orchestrator.py --self-audit` 确认全部检查项为 `PASS`。

---

## 二、维护者开源发版标准流程

1. **同步两个独立开源仓库版本号与更新日志**：
   - Skill 仓库：更新 `core/version.py`、`PIPELINE_MANIFEST.json`、`SKILL.md`、`README.md` 与 `CHANGELOG.md`；
   - DSH 仓库：更新 `core/version.py`、`package.json`、`skills/ww-auto-model-extractor/SKILL.md`、`README.md` 与 `CHANGELOG.md`。
2. **在两个开源仓库分别运行全套合规自检与契约单测**：
   ```bash
   # Skill 仓库：
   python orchestrator.py --self-audit
   python tests/test_pipeline_suite.py

   # DSH 仓库：
   python orchestrator.py --self-audit
   node tests/test_dsh_contract.mjs
   python tests/test_pipeline_suite.py
   npm pack --dry-run
   ```
3. **构建发行归档并做洁净室解压交叉核验**：
   运行 `D:\Github_Preson_Program\build_online_release.py`，自动在无环境变量污染的临时洁净目录解压双包复验 `--self-audit`、全套单测及合规边界扫描，确认 `ok: true` 后再手动上传 GitHub Releases / 更新市场索引。

> 问题反馈与版权响应联系邮箱：`jiuyue200712@gmail.com`。
