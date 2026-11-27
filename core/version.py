"""Version constants, schema identifiers, legal compliance notice, and upstream reference metadata."""

from __future__ import annotations

CORE_VERSION = "0.1.1"
PIPELINE_SCHEMA_VERSION = "0.1.0"
HANDOFF_SCHEMA_VERSION = "0.1.0"
DSH_PLUGIN_NAME = "dsh-ww-auto-model-extractor"
SKILL_PACK_NAME = "ww-auto-model-extractor-skill"
AGENT_PACK_NAME = SKILL_PACK_NAME
CONTACT_EMAIL = "jiuyue200712@gmail.com"

UPSTREAM_REFERENCES = {
    "cue4parse": {
        "title": "CUE4Parse (UE archive & asset conversion library, Apache-2.0 License)",
        "url": "https://github.com/FabianFG/CUE4Parse",
    },
    "fmodel": {
        "title": "FModel (Unreal Engine archive explorer reference, GPL-3.0 License)",
        "url": "https://github.com/4sval/FModel",
    },
    "ueformat_blender": {
        "title": "UEFormat for Blender (.uemodel / .ueanim / .uepose importer, GPL-3.0-or-later License)",
        "url": "https://github.com/h4lfheart/UEFormat",
    },
    "pinyin_data": {
        "title": "mozillazg/pinyin-data (BMP CJK Pinyin table, MIT License)",
        "url": "https://github.com/mozillazg/pinyin-data",
    },
}

LEGAL_NOTICE_ZH = (
    "【非官方声明与免责条款】"
    "1. 非官方性质：本项目为非官方第三方技术研究管线，与广州库洛科技有限公司（Kuro Games）无任何官方关联、合作、授权或背书。"
    "2. 仅限个人学习与技术研究：本工具及产出工程严格限于个人离线学习、风格化 3D 渲染与骨骼动画管线研究及非营利技术交流。"
    "3. 严禁商业用途与私人交易：严禁将本工具或任何衍生角色资产（模型、贴图、骨骼、动画、形态键、材质及工程文件）用于商业用途、"
    "盈利活动、有偿商单、代做服务、付费社群/网盘变现、私下买卖或私人交易，亦严禁公开二次分发任何游戏资产或密钥。"
    "4. 严禁测试服拆包与未公开内容泄密：严禁将本工具用于任何未公开测试服（Beta）、预下载包、未正式实装上线角色/皮肤/动作/废案的解析、"
    "渲染、截图或外泄传播，严禁侵犯商业秘密。"
    "5. 零技术保护规避与零进程干预：本仓库不内置任何密钥，不提供自动联网寻钥服务，不注入或读取游戏进程内存，不修改客户端文件，不触碰反作弊系统（如 ACE）。"
    "6. 禁止违规衍生与协议隔离：严禁用于架设私服、外挂、竞品换皮、色情低俗或侮辱损害角色形象内容（NSFW）及商业 AI 训练投喂。"
    "《鸣潮》全部美术资产与商标版权归广州库洛科技有限公司（Kuro Games）所有；MIT 开源协议仅适用于本项目原创源代码"
    "（随包第三方开源组件按 THIRD_PARTY_LICENSES.md 各自上游协议授权），不授予对任何游戏资产的任何许可。使用者须确保本机客户端合法正版，一切违规法律与账号风险由使用者自行承担。"
    "7. 版权方响应：若原版权方认为本项目存在侵权或不妥，请通过项目 GitHub Issues 或联系邮箱 jiuyue200712@gmail.com 告知，维护者核实后将第一时间配合修改或下架。"
)

LEGAL_NOTICE = (
    "UNOFFICIAL DISCLAIMER & LEGAL NOTICE: "
    "(1) Non-Affiliation: This is an unofficial third-party technical research pipeline and is NOT affiliated with, endorsed, sponsored, or approved by Kuro Games (广州库洛科技有限公司). "
    "(2) Personal Study & Research Only: This tool and all generated files are strictly for personal offline learning, stylized 3D rendering/animation pipeline research, and non-commercial study. "
    "(3) Strictly No Commercial Use or Private Trading: Any commercial use, monetization, paid commissions, paid or public redistribution of game assets/keys, or private buying/selling/trading of models, textures, rigs, animations, or project files is strictly prohibited. "
    "(4) Strictly No Beta/Unreleased Leaks: Using this tool on closed-beta clients, pre-download packages, unreleased characters/skins, or confidential content for datamining or public leaking is strictly forbidden. "
    "(5) No Circumvention or Process Tampering: This repository bundles zero AES keys, provides NO automated remote key fetching, and never injects into game processes, reads game memory, modifies game files, or interacts with anti-cheat systems. "
    "(6) Prohibited Derivatives & License Scope: Private servers, cheats, commercial asset flips, NSFW/defamatory content, and commercial AI dataset training are prohibited. All Wuthering Waves assets and trademarks remain the exclusive IP of Kuro Games. The MIT License applies solely to this project's original source code (bundled open-source components remain under their upstream licenses in THIRD_PARTY_LICENSES.md) and grants no rights to any game assets. Users must hold legitimate local access to the official live client and assume all legal and account risks. "
    "(7) Rights Holder Contact: Rights holders may contact maintainers via GitHub Issues or jiuyue200712@gmail.com for prompt review, modification, or removal."
)
