---
name: ww-auto-model-extractor
description: 【非官方】《鸣潮》（Wuthering Waves）正式服已实装角色风格化贴图审计、隔离 Blender 沙盒卡渲与动作表情展示及标准化 UE 交接包自动化管线（无需安装 Unreal Engine）。
version: 0.1.1
---

# [非官方]《鸣潮》（Wuthering Waves）角色风格化 Blender 动作展示与 UE 交接管线（`v0.1.1`）

> **[!WARNING] 非官方项目与合规红线**
> 本项目为非官方第三方技术研究管线，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联或背书。仅限面向本机正版正式服已实装自机角色进行个人离线渲染与骨骼动画技术研究；**严禁用于测试服（Beta）拆包泄密、商业用途或私人买卖交易**。本仓库不内置任何密钥且不提供自动联网寻钥功能。

本目录支持 **一包两用**：
- **标准跨平台 Skill**：将整个文件夹放入 Antigravity / Claude Code / Cursor / Codex 等客户端的 `skills/` 目录，客户端会自动识别本 `SKILL.md` 并按需触发。
- **独立工作区包体 / 命令行**：解压至任意目录，让任意 Agent 阅读 `AGENT_START_HERE.md` 或直接执行 `python orchestrator.py`。

## 强制执行纪律（Mandatory Execution Discipline）

1. **必须先执行 Stage 0 自检（严禁直接询问角色名）**：
   先运行 `python orchestrator.py --step 0`，完成包体合规自检（`--self-audit`）、本机正式服客户端探测、Blender/解码库检测与隔离沙盒冒烟测试。
2. **缺少《鸣潮》客户端立即终止（严禁下载游戏本体）**：
   若 Stage 0 返回 `code: "FATAL_MISSING_WUTHERING_WAVES"`，必须立即终止并告知宿主机，**绝不允许尝试下载游戏本体**。
3. **缺少软件或运行库必须先征得宿主机同意**：
   若 Stage 0 返回 `status: "CONSENT_REQUIRED"`，包含缺少 Blender 或 Oodle 运行时解码库时，必须先向宿主机完整展示 `consent_actions`（含官方 URL、SHA256 校验与隔离安装目录），**获明确同意后**才可传入 `--consent-download blender,oodle`。
4. **FModel 缺密钥 / 未关联时暂停并由宿主机提供密钥包完成本地关联**：
   本开源版本不内置密钥且不联网获取密钥。若 Stage 0 或 Stage 1 检测到本机 FModel 未关联《鸣潮》目录或缺少有效密钥（返回 `provide_keys_and_link_fmodel` 或 `HOST_KEYS_REQUIRED`），**必须立即暂停**，提醒宿主机提供其本地自备的密钥文件或压缩包路径（支持 `.json` 或含 `keys.json` 的 `.zip`，程序仅在内存只读解析 `.json`、拒绝任何可执行文件），并在征得宿主机同意后通过 `--keys-file "<本地路径>" --consent-link-fmodel` 自动备份原 `AppSettings.json` 并完成本地关联。
5. **必须向宿主机通告 `PATCHED` / `host_notice`**：
   任意阶段返回非空 `host_notice`（如隔离沙盒内 AST 热修补插件跨版本 API 差异、或本地密钥覆盖提示）均需清晰转告宿主机。
6. **不要求宿主机安装 Unreal Engine & 动作过滤规则（决策 D1–D4）**：
   面向正式服已实装自机角色（`Role/<BodyType>/<Name>`，`IsNpc = false`），支持中文、小写英文/拼音、首字母大写/驼峰英文三通道直检角色文件夹（如 `莉莉`→`Lili`、`爱弥斯`→`Aimisi`、`琳奈`→`LinNai`、`今汐`→`Jinxi`）。不含逐帧骨骼姿态的纯控制曲线片段（如 `Land_Roll_Attack01_2`）按 D4 自动过滤并记入 `handoff_manifest.json -> deferred_to_ue_animations`；空中循环动作（如 `Jump_Loop`）保留并标注 `is_aerial_loop: true`。

## 常用执行命令

```bash
# 0. 包体自检 + 环境与本地 FModel 关联门禁（强制第一步）
python orchestrator.py --step 0

# 如门禁提示 FModel 未关联或缺本地密钥，获宿主机提供本地 .json/.zip 路径并同意后一键备份关联：
python orchestrator.py --step 0 --keys-file "D:\UserKeys\keys.zip" --consent-link-fmodel

# 可选：列出本机客户端内已检出的正式服自机角色
python orchestrator.py --list-characters
python orchestrator.py --list-characters --query "今汐"

# 1. 一键完成三级贴图审计 + Blender 风格化展示装配 + FBX 往返核验 + 交付报告
python orchestrator.py --auto --character "<角色名>" --work-dir "D:\WW_Outputs"

# 或分阶段执行（Stage 1 -> 2 -> 3 -> 4）
python orchestrator.py --step 1 --character "<角色名>"
python orchestrator.py --step 2
python orchestrator.py --step 3
python orchestrator.py --step 4
```

## Blender 工程开箱提醒

- **自动脚本 `ww_action_sync.py`**：首次打开 `<ModelId>_showcase.blend` 若顶部出现脚本安全提示，点击一次 **「允许执行 / Allow Execution」** 即可激活内嵌脚本（零联网、零磁盘读写、不修改原始关键帧数据），切换动作时自动校准时间轴起止帧并联动同步/清零面部伴生表情 `*_ShapeKeys`，按 `N` 可打开右侧 **`WW Showcase`** 快捷面板。
- **面部伴生表情 `*_ShapeKeys`（非废动作）**：`*_ShapeKeys` 是角色眨眼/口型/眉毛等面部形态键（`KEY` 槽位）伴生轨，切勿手动挂到 `Armature` 上。
- **工作区本地化与骨骼提醒**：顶部 11 个工作区标签已按宿主机系统语言自动本地化；活动对象默认设为 `Armature`（仅显示 `Core_Bip001` 核心骨），切勿对骨骼执行 `Reorient Bones`。

## 免责声明与安全合规（Disclaimer & Legal Notice）

1. **非官方声明**：本项目为非官方第三方技术研究管线，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、授权或背书。
2. **仅限个人学习与技术研究**：严格限于个人离线学习、风格化 3D 渲染与骨骼动画研究及非营利交流。
3. **严禁商用、交易与测试服泄密**：严禁用于任何商业用途、盈利活动、有偿商单、代做服务、公开资产/密钥分发及一切私人买卖交易；**严禁用于测试服（Beta）、预下载包或未正式实装上线内容的拆包、渲染与外泄传播**；严禁用于私服、外挂、不良二创（NSFW）及商业 AI 训练投喂。
4. **零技术保护规避与协议隔离**：本仓库不内嵌任何游戏资产、闭源专有解码库或密钥，不提供自动联网寻钥，不注入客户端进程，不触碰反作弊系统。《鸣潮》全部资产与商标版权归广州库洛科技有限公司所有；MIT 协议仅适用于本项目原创源代码（第三方开源组件许可详见 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)）。使用者须确保客户端合法正版，一切违规风险自负。
5. **版权方响应与联系反馈**：若权利人认为存在侵权或不当，请通过 GitHub Issues 或邮箱 `jiuyue200712@gmail.com` 告知，维护者核实后将第一时间配合修改或下架。

详细文档见 [`AGENT_START_HERE.md`](AGENT_START_HERE.md)、[`PIPELINE_MANIFEST.json`](PIPELINE_MANIFEST.json)、[`NOTICE.md`](NOTICE.md)、[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)、[`docs/USER_GUIDE_AND_NOTICES.md`](docs/USER_GUIDE_AND_NOTICES.md)、[`docs/UPDATING_AND_RELEASE_GUIDE.md`](docs/UPDATING_AND_RELEASE_GUIDE.md) 与 [`docs/REFERENCES.md`](docs/REFERENCES.md)。
