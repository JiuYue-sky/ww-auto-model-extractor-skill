# 开源协议适用范围、第三方组件许可与知识产权声明（Notice & IP Scope）

> **[!WARNING] 非官方项目声明（Unofficial Project Notice）**
> 本项目为非官方第三方 3D 风格化角色渲染与动画管线技术研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、合作、授权或背书。

---

## 1. 许可证适用边界隔离（License Scope Isolation）

- **原创编排与管线代码（MIT License）**：本仓库根目录的 [`LICENSE`](LICENSE)（MIT License）**仅适用于本项目作者原创编写的管线编排、贴图三级审计、Blender 材质/动作装配与验证源代码及文档**。
- **随包第三方开源组件（Upstream Open-Source Licenses）**：随包分发的独立子模块与编译产物均保留并遵循各自上游开源许可证（完整许可证全文与版权声明见 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) 及对应子目录）：
  - `bundled_addons/io_scene_ueformat/`（**UEFormat for Blender**）：遵循 **GPL-3.0-or-later**（完整协议正文见 `bundled_addons/io_scene_ueformat/LICENSE`），仅在隔离 Blender 沙盒进程中作为独立 Blender 扩展加载。
  - `bin/ww-extract/ww-extract.exe` 及随附开源原生库（`CUE4Parse-Natives.dll`、`zlib-ng2.dll`、`Detex.dll`）：作为独立命令行子进程调用，基于 **CUE4Parse**（**Apache-2.0 License**）及 MIT / BSD / Zlib / Six Labors 非商业开源条款组件构建（详见 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)）。
  - `core/pinyin_index.py` 数据表：源自 **mozillazg/pinyin-data**（**MIT License**）。
- **零闭源商业解码库内嵌**：本开源仓库与发行包**不内嵌、不分发**专有 `oodle-data-shared.dll`；运行时仅复用宿主机已有合法工具环境（如 FModel / Unreal Engine），或在 Stage 0 征得宿主机明确同意后按需下载至本地隔离目录 `runtime/native/`。
- **游戏资产零授权声明**：上述任何开源许可证**绝不授予**任何人对《鸣潮》（Wuthering Waves）任何游戏资产、角色形象、3D 模型、贴图、骨骼、动画、形态键、材质参数或商标的任何版权、商标权或商业使用许可。

---

## 2. 游戏知识产权归属与合规红线（IP Ownership & Strict Usage Boundaries）

1. **知识产权归属**：《鸣潮》（Wuthering Waves）全部美术资产、角色形象与商标的知识产权均归**广州库洛科技有限公司（Kuro Games）**及相关合法权利方独家所有。
2. **仅限正式服已实装内容与个人离线研究**：本工具及产出工程严格限于个人离线学习、风格化 3D 渲染与骨骼动画技术研究及非营利交流；**严禁**用于任何未公开测试服（Beta）、预下载包、未正式上线角色/皮肤/动作/废案资产的拆包、渲染、截图或泄密传播。
3. **零密钥与零技术保护规避**：本仓库与插件**不内嵌、不提供任何私有 AES 密钥，亦不代为联网搜索密钥**（宿主机如尚未准备，可先临时关闭本插件并另开新会话执行或手动寻找；当检索到本机已有本地密钥配置或宿主机直接提供本地 `.json`/`.zip`/`.txt`/目录路径时，插件不询问来源，自动备份原 `AppSettings.json` 后仅写入用户本机配置，仅在密钥本身不可用时提示「密钥本身存在问题，请使用正确可用的密钥」）；本工具绝不自动下载游戏客户端、不注入游戏进程、不读取内存、不触碰反作弊系统（如 ACE）。
4. **严禁商用、交易与违规衍生**：**严禁**将本工具或任何衍生角色资产用于任何商业用途、盈利活动、有偿商单、代做服务、付费社群/网盘变现、公开打包分发或一切私下买卖交易；严禁用于私服、外挂、竞品换皮、色情低俗或侮辱角色形象内容（NSFW）及商业 AI 训练投喂。使用者须确保本机客户端来源合法正版，一切违规引发的法律与账号风险由使用者自行承担。

---

## 3. 版权方侵权响应与维护者联系方式（Rights Holder Takedown & Contact）

若原版权方或合法权利人认为本项目的任何内容涉及侵权或不当，或宿主机用户需反馈技术兼容问题，请通过本仓库 GitHub Issues 或联系邮箱 **`jiuyue200712@gmail.com`** 告知，维护者核实后将第一时间配合修改、移除或下架处理。

---

> **English Notice**: This is an **unofficial** third-party technical research pipeline and is NOT affiliated with or endorsed by **Kuro Games (广州库洛科技有限公司)**. The MIT License in `LICENSE` applies **solely to this project's original source code** and grants **no rights** over any Wuthering Waves game assets or trademarks. Bundled open-source components (`UEFormat` under GPL-3.0-or-later, `CUE4Parse` under Apache-2.0, `mozillazg/pinyin-data` under MIT, etc.) remain governed by their respective upstream licenses in `THIRD_PARTY_LICENSES.md`. Proprietary Oodle binaries, game assets, and AES keys are **not** bundled, and automated remote key fetching is **not** provided. Strictly for personal offline study on officially released live content only — closed-beta/unreleased leaks, commercial use, paid commissions, asset redistribution, private trading, NSFW/defamatory content, and commercial AI training are strictly prohibited. Contact `jiuyue200712@gmail.com` or open a GitHub Issue for prompt review or takedown.
