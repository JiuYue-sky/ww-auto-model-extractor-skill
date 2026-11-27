# 上游开源组件与第三方许可合规登记（References & Third-Party Notices）

> **[!WARNING] 非官方声明**
> 本项目为非官方第三方技术研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、授权或背书。

---

## 一、上游开源组件登记

1. **CUE4Parse & CUE4Parse-Conversion**
   - Repo: `https://github.com/FabianFG/CUE4Parse`
   - License: **Apache-2.0 License**（完整协议与上游归属声明见根目录 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)）
2. **UEFormat for Blender（`.uemodel` / `.ueanim` / `.uepose` 导入扩展）**
   - Repo: `https://github.com/h4lfheart/UEFormat`
   - License: **GPL-3.0-or-later License**（完整协议正文随附于 [`bundled_addons/io_scene_ueformat/LICENSE`](../bundled_addons/io_scene_ueformat/LICENSE)）
3. **mozillazg/pinyin-data（零依赖全汉字 BMP 拼音表，用于中文多形态直检已实装角色文件夹）**
   - Repo: `https://github.com/mozillazg/pinyin-data`
   - License: **MIT License**（Copyright (c) 2016 mozillazg）
4. **FModel（外部可选归档参考工具，未随包内嵌）**
   - Repo: `https://github.com/4sval/FModel`（GPL-3.0 License）

---

## 二、随包文件边界说明

两个独立发布的开源版本（Skill / 通用包体版 `ww-auto-model-extractor-skill` 与 DSH 插件版 `dsh-ww-auto-model-extractor`）均严格遵守以下物理打包边界：
- `bin/ww-extract/ww-extract.exe`：独立命令行解析子进程（静态链接库协议清单详见 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)）。
- `bin/ww-extract/CUE4Parse-Natives.dll`、`native/zlib-ng2.dll`、`native/Detex.dll`：均为开源许可证授权的动画与纹理块解码库（MIT / Zlib）。
- **不包含专有商业 `oodle-data-shared.dll`**：运行时优先复用宿主机本地已有的 FModel / Unreal Engine 环境，或在 Stage 0 征得宿主机明确同意后按需下载并做 SHA256 校验至隔离目录 `runtime/native/`。
- **不包含任何第三方无许可插件、不包含任何游戏原始资产、不包含任何 AES 密钥且不提供自动联网寻钥端点**。
- `bundled_addons/io_scene_ueformat/`：保留原始 `blender_manifest.toml` 与完整 `GPL-3.0` `LICENSE` 正文，仅在隔离 Blender 沙盒进程中加载。

---

## 三、免责声明与安全合规条款（Disclaimer & Legal Notice）

1. **非官方声明**：本项目为非官方第三方技术研究工具，与**广州库洛科技有限公司（Kuro Games）**无任何官方关联、合作、授权或背书。
2. **仅限个人学习与技术研究**：本工具及产出文件严格限于个人离线学习、风格化 3D 渲染与骨骼动画技术研究及非营利性技术交流，建议研究测试结束后自行妥善清理本地衍生文件。
3. **严禁商业用途与一切私人交易**：严禁将本工具或任何衍生《鸣潮》角色资产（模型、贴图、骨骼、动画、形态键、材质参数及工程文件）用于任何商业用途、盈利性活动、有偿商单、代做服务、付费社群/网盘变现、私下买卖或私人交易；亦严禁公开二次分发游戏资产或密钥。
4. **严禁测试服拆包与未公开内容泄密**：严禁将本工具用于任何未公开测试服（Beta）、预下载包、未正式实装上线角色/皮肤/动作/废案资产的解析、渲染、截图或外泄传播，严禁侵犯商业秘密。
5. **零技术保护规避与协议隔离**：本仓库不内置任何密钥、不提供自动联网寻钥、不注入客户端进程、不触碰反作弊系统（ACE）；严禁用于私服、外挂、不良二创（NSFW）及商业 AI 训练投喂。《鸣潮》全部资产与商标版权归**广州库洛科技有限公司（Kuro Games）**所有；MIT 协议仅适用于本项目原创源代码（第三方开源组件协议见 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)），不授予对任何游戏资产的权利。使用者须确保本机客户端合法正版，一切违规责任自负。
6. **版权方侵权响应与联系方式**：若原版权方或合法权利人认为本项目内容存在不当或侵权，请通过项目 GitHub Issues 或联系邮箱 `jiuyue200712@gmail.com` 告知，维护者核实后将第一时间配合修改、移除或下架处理。
