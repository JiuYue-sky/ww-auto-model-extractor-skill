# [非官方]《鸣潮》（Wuthering Waves）角色风格化 Blender 动作展示与交接管线 — 使用指南与注意事项 (`v0.1.2`)

> 本文档同时适用于两个**底层同源、在 GitHub 分开独立发布**的非官方开源项目：
> - **通用包体 / 标准 Skill 版**（`ww-auto-model-extractor-skill`）— **仅发布于 GitHub 独立仓库**
> - **DeepSeek Harness (DSH) 插件版**（`dsh-ww-auto-model-extractor`）— **同时发布于 GitHub 独立仓库与 DSH 插件市场**

> [!WARNING]
> **非官方声明与合规前提**：本项目与**广州库洛科技有限公司（Kuro Games）**无任何官方关联。仅限面向本机正版正式服已公开实装角色进行个人离线渲染与动画技术研究；**严禁用于测试服（Beta）拆包泄密、商业用途、私人交易或不良二创**。本插件本身不提供且不代为联网搜索密钥；如尚未准备，可先临时关闭本插件并另开新会话执行，或由宿主机手动寻找。

> [!IMPORTANT]
> **首次打开 `.blend` 弹出「自动运行 Python 脚本」安全提示说明（非恶意脚本，请放心）**
>
> 产出的 `<ModelId>_showcase.blend` 内嵌了开源可读的 **`ww_action_sync.py`**（**零联网、零磁盘读写、绝不修改原始关键帧**），仅负责切换身体主动作时自动校准时间轴起止帧、联动同步/清零面部伴生表情轨（`*_ShapeKeys`），并在右侧按 `N` 提供 **`WW Showcase`** 快捷面板。点击 **「允许执行 / Allow Execution」** 即可激活；若拒绝，模型、材质与动作依然完整可用。

---

## 一、适用范围与本地密钥说明

1. **仅面向正式服已公开实装「自机角色」+ 中文多形态直检目录**
   - 仅识别 `Client/Content/Aki/Character/Role/<BodyType>/<Name>/` 下 `IsNpc = false` 的已实装可玩角色，不含 NPC、Boss、怪物与场景道具，且**严禁用于测试服或未公开内容**。
   - 输入中文角色名时，自动展开为**中文原形、小写英文/拼音、首字母大写/驼峰英文**三通道检索角色文件夹（如 `今汐`→`Jinxi`、`长离`→`ChangLi`、`莉莉`→`Lili`、`琳奈`→`LinNai`）。
2. **本地密钥识别、自动关联与失效提示机制（BYOK · 不提供不搜索密钥）**
   - 为严格遵守合规边界，本插件与开源仓库**本身不内置、不提供任何 AES 密钥，亦不代为联网搜索密钥**。若宿主机尚未准备好密钥，可**先临时关闭本插件并另开新会话执行，或由宿主机手动寻找并准备好本地密钥文件**。
   - 当本机 FModel 已有本地密钥配置，或宿主机直接提供本机现有的密钥路径（支持 `.json`、`.zip`、`.txt`/`.key` 或**包含密钥文件的本地目录路径**）时，插件**不询问文件来源、不翻阅目录内无关文档**，自动备份原 `AppSettings.json` 为 `.bak-时间戳` 并直接完成本地 FModel 关联与使用（`.zip` 仅在内存只读解析，绝不释放可执行文件）。
   - 仅当检测到密钥本身格式有误、无效或随版本更新已过期无法挂载当前客户端时，程序明确提示：**「密钥本身存在问题，请使用正确可用的密钥」**。
3. **无需安装 Unreal Engine**
   - 本项目完成三级贴图审计拆分、隔离沙盒 Blender 风格化展示及标准化 `ue_handoff/handoff_manifest.json` + Rest-Pose `.fbx` 封装，供下游独立 UE 导入插件消费。

---

## 二、双版本安装与快速使用方式（请勿混装）

### 方式 A / B：通用包体 / 标准 `Skill` 版（`ww-auto-model-extractor-skill`）
1. 从 GitHub Releases 下载并解压 `ww-auto-model-extractor-skill-v0.1.2.zip`，可放入 Agent 客户端的 `skills/` 目录自动唤醒，或直接在终端运行：

```bash
# 0. 包体合规自检 + 宿主机环境与本地 FModel 关联门禁（强制第一步）
python orchestrator.py --step 0

# 如门禁暂停提示 FModel 未关联或缺密钥，获用户提供本地 .json/.zip 路径并同意后一键备份关联：
python orchestrator.py --step 0 --keys-file "D:\UserKeys\keys.zip" --consent-link-fmodel
# （如裸机同时缺少 Blender 或 Oodle 运行库，可附加 --consent-download blender,oodle）

# 1. 查看本机正式服可用自机角色
python orchestrator.py --list-characters

# 2. 一键完成贴图审计 + Blender 风格化动作展示装配 + UE 交接包（推荐将输出放在包体外部）
python orchestrator.py --auto --character "今汐" --work-dir "D:\WW_Outputs"
```

### 方式 C：DeepSeek Harness (DSH) 插件版（`dsh-ww-auto-model-extractor`）
1. 在 DSH 插件市场或通过 GitHub Release `.tgz` 安装（升级步骤详见 [`UPDATING_AND_RELEASE_GUIDE.md`](UPDATING_AND_RELEASE_GUIDE.md)）。
2. 在对话中说明需展示的正式服角色（如本地密钥文件不在默认 FModel 配置中，可一并告知本地 `keys.json` 路径及外部 `work_dir`），插件会按顺序执行：`dsh_ww_preflight_check` → `dsh_ww_extract_and_showcase` → `dsh_ww_verify_delivery`。

---

## 三、跨宿主机环境自检与授权规则

| 场景 | 工具行为 | 是否需宿主机授权 |
| :--- | :--- | :---: |
| **未安装《鸣潮》正式服客户端** | **硬门禁立即终止**（`FATAL_MISSING_WUTHERING_WAVES`），**严禁自动下载游戏** | 不允许下载 |
| **未检测到 Blender (3.6+/4.x/5.x)** | 返回 `CONSENT_REQUIRED`，**获明确同意后**下载官方便携版（SHA256 校验）至 `runtime/blender/` | **必须先同意** |
| **裸机缺少 Oodle 运行时解码库** | 优先复用本机已有 FModel/UE 环境；若无则返回 `CONSENT_REQUIRED`，**获同意后**按需下载（SHA256 校验）至 `runtime/native/` | **必须先同意** |
| **本机已有 FModel / 本地密钥配置** | **不询问来源直接使用并自动备份关联本地 FModel**；仅在密钥本身无效/过期时提示「密钥本身存在问题，请使用正确可用的密钥」 | 自动复用 + `.bak` 备份 |
| **本机无任何本地密钥配置** | **暂停工作**（`CONSENT_REQUIRED`），提示本插件不提供也不搜索密钥（可先关闭本插件另开会话执行或手动寻找，或直接提供本地 `.json`/`.zip`/`.txt`/目录路径完成自动关联） | 宿主机自行准备/提供 |
| **未安装 FModel GUI** | 可选建议；**获明确同意后**下载官方 FModel 发布包至隔离目录 `runtime/fmodel/` | **必须先同意** |
| **Blender 4.x/5.x 插件 API 差异** | 仅在隔离沙盒 `sandbox_blender/` 内 AST 热修补并冒烟测试，**绝不改动宿主机全局配置** | 沙盒隔离 + 通告 |

---

## 四、动作过滤规则（决策 D1–D4）与 Blender 避坑指南

1. **未烘焙动作自动移交（决策 D1 / D4）**：部分动画片段（如 `Land_Roll_Attack01_2`）仅含 `Root` / `IK_*` 控制曲线而无逐帧骨骼姿态，Stage 1 会自动过滤并记入 `handoff_manifest.json -> deferred_to_ue_animations` 移交下游 UE 烘焙；空中循环动作（如 `Jump_Loop`）保留并标注 `is_aerial_loop: true`（决策 D3）。
2. **Blender 开箱操作提醒**：
   - 贴图已全量内嵌打包（`pack_all`），3D 视口已按角色身高自动拉近居中并设为 `MATERIAL` 材质预览，顶部 11 个工作区已按宿主机语言本地化，按**空格键**即可播放。
   - **切勿将 `*_ShapeKeys` 手动挂到 `Armature` 上**：`*_ShapeKeys` 属于网格形态键（`KEY` 槽位）面部伴生表情轨，不是废动作；请直接选不含 `_ShapeKeys` 后缀的身体主动作或用右侧 `N` 面板 `WW Showcase` 切换。
   - **切勿执行 `Reorient Bones`**：保持 `UEFormat` 原生 `+X` 骨骼轴向，避免 `.ueanim` 动作扭曲。

---

## 五、免责声明与安全合规条款（Disclaimer & Legal Notice）

1. **非官方声明**：本项目为非官方第三方技术研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、合作、授权或背书。
2. **仅限个人学习与技术研究**：本工具及产出工程文件严格限于**个人离线学习、风格化 3D 渲染与骨骼动画技术研究及非营利性技术交流**。
3. **严禁商业用途与一切私人交易**：**严禁**将本工具或任何衍生《鸣潮》角色资产用于**任何商业用途、盈利活动、有偿商单、代做服务、付费社群/网盘变现、私下买卖或私人交易**，亦严禁公开二次分发任何游戏资产或密钥。
4. **严禁测试服拆包与未公开内容泄密**：**严禁**用于任何未公开测试服（Beta）、预下载包、未正式实装上线角色/皮肤/动作/废案资产的解析、渲染、截图或外泄传播。
5. **零技术保护规避与知识产权隔离**：本仓库不内嵌任何游戏资产、闭源专有 DLL 或 AES 密钥，不提供自动联网寻钥，不注入客户端进程，不触碰反作弊系统；严禁用于私服、外挂、不良二创（NSFW）及商业 AI 训练投喂。《鸣潮》全部资产与商标知识产权归**广州库洛科技有限公司（Kuro Games）**所有；MIT 许可证仅适用于本项目原创源代码（随包第三方开源组件协议详见 [`../THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)）。使用者须确保客户端合法正版，一切违规风险自负。
6. **版权方侵权响应**：若原版权方或权利人认为本项目存在侵权或不当，请通过 GitHub Issues 或联系邮箱 `jiuyue200712@gmail.com` 告知，维护者核实后将第一时间配合修改或下架。

第三方开源组件登记见 [`REFERENCES.md`](REFERENCES.md)。
