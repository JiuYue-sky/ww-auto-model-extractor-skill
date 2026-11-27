# [非官方]《鸣潮》（Wuthering Waves）角色风格化 Blender 动作展示与 UE 交接管线 (`ww-auto-model-extractor-skill`)

**面向本机合法《鸣潮》（Wuthering Waves）正式服已实装自机角色的风格化贴图审计、隔离 Blender 沙盒卡渲与动作表情展示及标准化 UE 交接包工作流（通用 Agent 包体 + 标准 `SKILL.md` 双形态）**

![Version](https://img.shields.io/badge/version-v0.1.2-blue)
![Unofficial](https://img.shields.io/badge/status-Unofficial_Research_Tool-orange)
![License](https://img.shields.io/badge/license-MIT_(Original_Code)-green)
![Platform](https://img.shields.io/badge/platform-Windows_10%2F11_x64-0078D6)
![Blender](https://img.shields.io/badge/Blender-3.6%2B_%7C_4.x_%7C_5.x-E87D0D)
![Unreal Engine](https://img.shields.io/badge/Unreal_Engine-Not_Required-lightgrey)

> [!WARNING]
> **非官方项目声明与合规红线（Unofficial Notice & Compliance Boundaries）**
> - **非官方性质**：本项目为非官方第三方 3D 渲染与动画管线研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、合作、授权或背书。
> - **零资产 / 零密钥 / 零自动寻钥**：本仓库与插件**不分发任何游戏原始资产、不内嵌专有商业 Oodle 动态库、不内置不提供任何 AES 密钥，亦不代为联网搜索密钥**。如宿主机尚未准备本地密钥，可**先临时关闭本插件并另开新会话执行，或由宿主机手动寻找**；当检索到本机已有本地密钥配置或宿主机直接提供本地路径（`.json` / `.zip` / `.txt` 或目录）时，插件不询问来源，自动备份原 `AppSettings.json` 后直接完成本地 FModel 关联并使用，仅在密钥本身无效或过期时提示「密钥本身存在问题，请使用正确可用的密钥」。
> - **严禁商用、交易与测试服泄密**：严格仅限个人针对**正式服已公开实装角色**进行离线渲染与骨骼动画学习研究；**严禁用于任何测试服（Beta）拆包泄密、商业变现、有偿代做、公开资产分发、私下买卖交易或不良二创（NSFW）**。完整条款见文末及 [`NOTICE.md`](NOTICE.md)、[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)。

> [!IMPORTANT]
> **首次打开生成的 `.blend` 时弹出「自动运行 Python 脚本」安全提示说明（非恶意脚本，请放心）**
>
> 产出的 `<ModelId>_showcase.blend` 内嵌了完全开源、可在 Blender「脚本」标签页查看全文的辅助脚本 **`ww_action_sync.py`**（**零联网、零磁盘读写、且绝不修改原始动画关键帧数据**），仅用于在切换身体动作时自动贴合底部时间轴首尾帧、自动联动同步/清零面部伴生表情轨（`*_ShapeKeys`），并在右侧按 `N` 提供 **`WW Showcase`** 快捷面板。点击 **「允许执行 / Allow Execution」** 即可启用；即使选择拒绝，模型、卡渲材质与动作依然完整可用。

---

## 一、项目定位与双版本说明（请勿混装）

本项目面向 **跨平台 AI Agent Skill（标准 `SKILL.md`）与独立工作区命令行**，聚焦解决风格化角色在 DCC 软件中贴图通道复杂、材质连线繁琐、物理飘带与面部形态键表情难以联动的工程痛点，实现 **「一包两用」**：

1. **作为标准 Agent Skill（推荐）**：根目录内置 [`SKILL.md`](SKILL.md)，将文件夹放入 Antigravity / Claude Code / Cursor / Codex 等客户端的 `skills/` 目录后，即可通过自然语言对话按 `Stage 0 环境门禁 → 本地校验与解析 → 三级贴图审计 → Blender 隔离沙盒风格化展示 → UE 交接包封装` 确定性执行。
2. **作为独立工作区包体 / CLI**：直接解压运行 `python orchestrator.py`，或由任意 Agent 按 [`AGENT_START_HERE.md`](AGENT_START_HERE.md) 与 [`PIPELINE_MANIFEST.json`](PIPELINE_MANIFEST.json) 分步调度。

| 独立发布项目 | 发布渠道 | 适用客户端 | 说明 |
| :--- | :--- | :--- | :--- |
| **本仓库（Skill / 通用包体版）**<br>`ww-auto-model-extractor-skill` | **仅 GitHub 独立仓库**（Release `.zip`） | **Antigravity / Claude Code / Cursor / Codex / Windsurf** 或命令行 | 含根目录 `SKILL.md`、`AGENT_START_HERE.md` 与 `orchestrator.py`，**不上架 DSH 插件市场** |
| **DSH 专用插件版（另一独立仓库）**<br>`dsh-ww-auto-model-extractor` | **GitHub 独立仓库 + DSH 插件市场** | **DeepSeek Harness (DSH)** 桌面端 / Web / CLI 专用 | 内置 Cordis 4 `package.json` / `lib/index.js` 工具注册；与本仓库同源，请勿混装 |

---

## 二、运行环境与合规门禁要求

| 组件 | 版本要求 | 是否必需 | 说明 |
| :--- | :--- | :---: | :--- |
| **操作系统** | Windows 10 / 11 (x64) | **必需** | 支持国服、国际服、Steam、Epic、WeGame 与自定义安装目录探测 |
| **《鸣潮》正式服客户端** | 本地官方正版正式服客户端 | **必需（硬门禁）** | 缺失时立即报错终止（`FATAL_MISSING_WUTHERING_WAVES`），**严禁自动下载游戏** |
| **本地 FModel 密钥关联** | 宿主机本地 FModel 配置或自备 `.json`/`.zip`/`.txt`/目录 | **自动复用 / 缺失时暂停** | **本仓库不提供且不搜索密钥**（未准备时可先关闭本插件另开会话执行或手动寻找）；检测到本机已有配置或提供本地路径时不询问来源、自动备份并直接关联使用，仅在密钥本身不可用时报错提醒 |
| **Blender** | `3.6 LTS` / `4.2 LTS` / `5.x`（实测 `5.2.3 LTS`） | **必需** | 缺失时返回 `CONSENT_REQUIRED`，仅在宿主机明确同意后下载官方便携版至隔离 `runtime/` |
| **解码运行库 (Oodle)** | 自动复用本机 FModel/UE 或授权按需下载 | **按需授权** | 开源包不随包分发闭源 Oodle DLL；裸机首次运行在征得宿主机同意后下载至 `runtime/native/` |
| **Python** | `3.10+`（或复用 Blender 内置 Python） | **必需** | 核心引擎仅用标准库 + Blender 内置 `OpenImageIO`/`numpy`，**零额外 `pip install`** |
| **Unreal Engine** | — | **不需要** | 仅输出标准化 `ue_handoff/` 交接包供下游独立 UE 导入插件消费 |

---

## 三、核心管线能力

1. **正式服自机体型覆盖 + 中文多形态直检角色目录**
   - 仅面向正式服已实装自机角色（`Role/<BodyType>/<Name>`，`IsNpc = false`），不含 NPC/Boss/怪物。
   - 内置零依赖全汉字拼音引擎（源自 MIT `mozillazg/pinyin-data`），输入中文自动按**中文、小写英文/拼音、首字母大写/驼峰英文**三通道匹配角色命名目录（如 `今汐` → `Jinxi`、`长离` → `ChangLi`、`莉莉` → `Lili`、`琳奈` → `LinNai`）。
2. **三级贴图通道审计与隔离沙盒风格化装配**
   - 自动结合 `MI_*.json`、后缀规则与像素统计拆分 `_N`（`_N_Normal` BC5 + `_MR` BC7）、校验 `_SDF` 面部阴影对称性并保护 `_D` 数据 Alpha 通道防误裁切。
   - 在隔离 `BLENDER_USER_*` 沙盒中自动完成自研风格化卡渲与 `UseFurry` 毛发着色器组装、物理飘带曲线合并、面部形态键（`*_ShapeKeys`）联动、近景自动构图与宿主机语言导航栏本地化，绝不污染宿主机全局 Blender 配置。
3. **动作烘焙判据（决策 D1–D4）与 Rest-Pose FBX 往返校验**
   - 自动识别并过滤源资产中不含逐帧骨骼姿态的未烘焙控制曲线片段（如 `Land_Roll_Attack01_2`）移交 `deferred_to_ue_animations`；空中循环动作（如 `Jump_Loop`）保留并标注 `is_aerial_loop: true`。
   - 对导出的 `<ModelId>_ue_handoff.fbx` 执行新空场景往返重导核验，确保无双 Root 陷阱且 100% 保留物理骨链与面部形态键。

---

## 四、快速开始

```bash
# 0. 包体合规自检 + 宿主机环境与本地 FModel 关联门禁（强制第一步）
python orchestrator.py --step 0

# 如门禁提示 FModel 未关联或缺本地密钥（以及裸机缺 Blender/Oodle），获用户提供本地路径并明确同意后执行：
python orchestrator.py --step 0 --keys-file "D:\UserKeys\keys.zip" --consent-link-fmodel
# （若裸机同时需下载便携 Blender / Oodle 运行库至隔离 runtime/，可附加 --consent-download blender,oodle）

# 1. 查看本机正式服客户端内已检出的自机角色
python orchestrator.py --list-characters
python orchestrator.py --list-characters --query "今汐"

# 2. 一键生成风格化 Blender 动作展示工程、预览图与标准化 UE 交接包（建议输出到包体外部目录）
python orchestrator.py --auto --character "今汐" --work-dir "D:\WW_Outputs"

# 单独运行包体合规与防篡改自检及全量单元测试
python orchestrator.py --self-audit
python tests/test_pipeline_suite.py
```

---

## 五、目录结构与文档导航

```text
ww-auto-model-extractor-skill/
├── .github/                     # Issue 模板、CI 合规验证与 Tag 打包工作流
├── bin/ww-extract/              # 无头解析子进程及开源解码库（Zlib-ng/Detex/ACL，不含专有 Oodle DLL）
├── bundled_addons/              # 随包 UEFormat Blender 扩展（含完整 GPL-3.0 LICENSE）
├── core/                        # 核心状态机、拼音直检、三级贴图审计、Blender 风格化装配与合规自检
├── docs/                        # 使用指南、发版运维指南与上游组件登记
├── tests/                       # 单元、安全与合规回归测试套件
├── AGENT_START_HERE.md          # 通用 Agent 标准操作规程 (SOP)
├── CHANGELOG.md                 # 语义化版本更新日志
├── CONTRIBUTING.md              # 贡献红线与本地验证指南
├── LICENSE                      # MIT 开源许可证（仅适用于本项目原创代码）
├── NOTICE.md                    # 非官方声明、协议边界隔离与游戏 IP 归属说明
├── THIRD_PARTY_LICENSES.md      # 随包第三方开源组件许可证全文与版权归属汇编
├── PIPELINE_MANIFEST.json       # 机器可读 5 阶段管线与安全合规清单
├── README.md                    # 项目总览文档
├── SECURITY.md                  # 安全红线、漏洞反馈与版权方侵权响应通道
├── SKILL.md                     # 跨平台标准 Skill 定义文件
├── orchestrator.py              # 单入口 JSON CLI 调度器
└── requirements.txt             # 可选依赖说明（默认复用 Blender 内置 Python 零安装）
```

- **详细使用须知（D1–D4 与 Blender 避坑）**：[`docs/USER_GUIDE_AND_NOTICES.md`](docs/USER_GUIDE_AND_NOTICES.md)
- **宿主机升级与发版流程**：[`docs/UPDATING_AND_RELEASE_GUIDE.md`](docs/UPDATING_AND_RELEASE_GUIDE.md)
- **第三方开源组件与许可证全文**：[`docs/REFERENCES.md`](docs/REFERENCES.md) | [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) | [`NOTICE.md`](NOTICE.md)
- **安全与版权方联系邮箱**：`jiuyue200712@gmail.com`（参阅 [`SECURITY.md`](SECURITY.md)）

---

## 六、免责声明与安全合规条款（Disclaimer & Legal Notice）

1. **非官方声明（Unofficial & Non-Affiliation）**：本项目为非官方第三方技术研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、合作、授权或背书。
2. **仅限个人学习与技术研究**：本工具、脚本及产出的工程文件严格仅限用于**个人离线学习、风格化 3D 渲染与骨骼动画管线研究及非营利性技术交流**。建议研究验证完成后自行妥善清理本地衍生文件。
3. **严禁商业用途与一切私人交易**：**严禁**将本工具或任何衍生角色资产（包括但不限于 3D 模型、贴图、骨骼、动画、形态键、材质参数、Blender/FBX 工程文件等）用于**任何形式的商业用途、盈利性活动、有偿商单、代做服务、付费社群/网盘变现、私下买卖或私人交易**；亦严禁公开二次分发、打包传播任何游戏原始或衍生资产及密钥。
4. **严禁测试服拆包与未公开内容泄密（Anti-Leak）**：**严禁**将本工具用于任何未公开测试服（Beta）、前瞻预下载包、未正式实装上线角色/皮肤/动作/废案资产的解析、渲染、截图或外泄传播，严禁侵犯商业秘密。
5. **零技术保护规避与零进程干预**：本仓库**不内嵌任何游戏资产、不分发专有商业解码 DLL、不内置任何 AES 密钥，且不提供自动联网寻钥服务**；本工具绝不注入或读取游戏进程内存、不修改游戏客户端文件、不触碰或绕过反作弊系统（如 ACE）。
6. **禁止违规衍生与知识产权隔离**：严禁用于架设私服、外挂、竞品换皮、色情低俗或侮辱损害角色形象内容（NSFW）及商业 AI 训练投喂。《鸣潮》（Wuthering Waves）全部游戏资产与商标知识产权均归**广州库洛科技有限公司（Kuro Games）**独家所有；根目录 [`LICENSE`](LICENSE)（MIT）**仅适用于本项目原创源代码**（随包第三方开源组件按 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) 各自上游协议授权），绝不授予对任何游戏资产的许可。使用者须确保本机客户端来源合法正版，一切违规引发的法律与账号风险由使用者自行承担。
7. **版权方侵权响应**：若原版权方或合法权利人认为本开源项目的任何内容涉及侵权或不当，请通过项目 GitHub Issues 或联系邮箱 `jiuyue200712@gmail.com` 告知，维护者核实后将第一时间配合删除、修改或下架处理。

> **English Disclaimer**: (1) **Non-Affiliation** — Unofficial third-party technical research pipeline, NOT affiliated with or endorsed by Kuro Games (广州库洛科技有限公司). (2) **Personal Offline Study Only** — Strictly limited to personal offline learning and non-commercial stylized 3D rendering/animation research on officially released live characters. (3) **No Commercial Use or Private Trading** — Commercial use, monetization, paid commissions, asset/key redistribution, and private buying/selling/trading are strictly prohibited. (4) **No Beta/Unreleased Leaks** — Using this tool on closed-beta clients, pre-download packages, or unreleased content is strictly forbidden. (5) **No Circumvention or Process Tampering** — Bundles zero game assets, zero proprietary Oodle DLLs, and zero AES keys; provides no automated remote key fetching; never touches game memory, client files, or anti-cheat. (6) **IP & License Scope** — Private servers, cheats, NSFW/defamatory derivatives, and commercial AI training are prohibited. All Wuthering Waves IP belongs exclusively to Kuro Games. The MIT License applies solely to original source code (third-party open-source components are governed by `THIRD_PARTY_LICENSES.md`). Users assume all legal and account risks. (7) **Rights Holder Contact** — Contact maintainers via GitHub Issues or `jiuyue200712@gmail.com` for prompt review or removal.
