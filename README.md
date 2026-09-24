# CalaplayUpper

[English](README.en.md) | **中文**

为 CalaPlayer 打造的傻瓜式素材打包与注入工具。

把你喜欢的图片、音乐、音效丢进一个文件夹，点一下按钮，就能生成可以直接在游戏里使用的补丁包。不污染游戏原文件，随时可以一键卸载。

本项目是基于社区开源的 CalaPlayer 编辑器开发的辅助工具，仅用于个人学习与娱乐。

---

## ✨ 功能特性

* **一键打包**：把素材整理好，点一下就能生成游戏补丁
* **安全无污染**：所有修改都以补丁形式加载，不覆盖游戏原始文件
* **随时回滚**：不满意？一键卸载，游戏恢复原样
* **中英双语**：界面支持中文和 English 切换
* **新手引导**：第一次打开会有九步引导，带你熟悉每个按钮
* **桌面端 GUI**：无需命令行，双击 exe 就能用
* **自动化校验**：打包过程自动检查每一步，出错会告诉你卡在哪里

## 📥 下载

去 **[Releases](https://github.com/killa0132/CalaplayUpper/releases)** 页面下载最新版本。

| 版本 | 说明 |
|---|---|
| **完全体（Full）** | **推荐**。自带 FFmpeg，支持 MP3 自动转码，开箱即用 |
| **精简版（Minimal）** | 体积更小，但不含 FFmpeg。你的电脑需要已经装好 FFmpeg 才能处理 MP3，否则只能用 WAV 格式 |

两个版本解压后都是 `CalaPlayerSrcmBuilderGUI.exe`，双击就能用，**不需要安装 Python 或 .NET**。

## 🚀 快速上手

### 第一步：准备素材

新建一个文件夹（比如 `我的素材`），在里面创建四个子文件夹：

```text
我的素材/
├── bg/        ← 背景图片（.png / .jpg / .jpeg）
├── BGM/       ← 背景音乐（.wav / .mp3）
├── Sound/     ← 音效（物品声、人物语音等）
└── Ambient/   ← 环境音（场景氛围音）
```

* 图片建议：1080P 及以上，支持 PNG、JPG、JPEG。
* 音频格式：**WAV 最稳**；MP3 需要 Full 版或本机已装 FFmpeg。

（四个目录名**大小写不敏感**；缺哪个就跳过哪个。）

### 第二步：打开工具

双击 `CalaPlayerSrcmBuilderGUI.exe`。第一次打开会有新手引导，跟着走一遍就行。

### 第三步：选择路径

* **游戏 Paks 目录**：选择你的 CalaPlayer 游戏根目录（比如 `D:\CalabiyanGalgameMaker\CalaPlayer`）
* **素材根目录**：选择你刚才创建的素材文件夹

### 第四步：开始打包

点击 **「开始打包」**，等待进度条跑完。成功后会在素材文件夹旁边生成一个 `out_patch` 文件夹，里面就是你的补丁包。

### 第五步：安装到游戏

> ⚠️ **安装前请先关闭游戏！**

进入 `out_patch` 文件夹，右键 `install.ps1` → 选择「在终端中运行」。如果 Windows 提示脚本被禁止，按照[开发文档](docs/DEVELOPER_GUIDE.md)里的说明放开执行策略即可，也可以直接跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装完成后打开游戏，在 Create 编辑器里就能看到你新增的素材了。

## 🖼️ 界面预览

| 主界面 | 新手引导 |
|---|---|
| [<img src="docs/images/ui-layout.jpg" width="430">](docs/images/ui-layout.jpg) | [<img src="docs/images/guide.jpg" width="430">](docs/images/guide.jpg) |

| 成功弹窗 | 失败弹窗 |
|---|---|
| [<img src="docs/images/modal-ok.jpg" width="430">](docs/images/modal-ok.jpg) | [<img src="docs/images/modal-fail.jpg" width="430">](docs/images/modal-fail.jpg) |

进度条跑起来是这样的（`chongci.gif` 当推进头部）：

<img src="docs/images/chongci.gif" width="430">

更多截图（社区弹窗四入口、下拉与选项动效、乱码解码波纹、英文界面、最小窗口、几只猫）在[开发文档](docs/DEVELOPER_GUIDE.md)末尾。

## ⚙️ 进阶选项

工具界面里有几个选项，新手可以先不用管：

| 选项 | 作用 |
|---|---|
| 背景适配 | `cover` 填满裁边（推荐）；`contain` 保留完整图片，四周补黑边 |
| DryRun | 只试跑不安装，用来检查素材有没有问题 |
| Combined | 在上一次打包的基础上追加新素材，而不是重新开始 |
| Force | 当素材超过默认限制时，强制打包 |

默认限制：背景 ≤ 50 张、音频总时长 ≤ 10 分钟、图片质量 ≥ 25 dB。

## ⚠️ 注意事项

* **安装前必须先关闭游戏。** 游戏运行时 `.ucas` 文件被占用，会导致安装失败甚至游戏崩溃。
* Windows 可能提示"未知发布者"。这是因为 exe 没有签名，点击"更多信息" → "仍要运行"即可。
* 路径建议使用**纯英文**。游戏目录和素材目录都尽量避开中文和特殊符号，以免出现奇怪的问题。
* 你需要先拥有 **CalaPlayer 游戏本体**。这个工具只负责打包素材，不包含游戏。

## 📁 项目结构（开发者）

<details>
<summary>点开查看目录说明</summary>

```text
core/            打包引擎（不可改）
cli/             命令行入口（不可改）
gui/             界面层（可改）
  frontend/      Vue 3 源码
  dist/          构建产物
kit/             自包含工具链
tools-src/       C# 工具源码
tests/           回归测试
docs/            文档与图片
dist/            交付件（走 Release）
```

详细的「改哪个文件」对照表、CLI 开关说明、A0~A7 判据、原理与开发/调试指南，见
**[开发文档 `docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)**
（英文版 [`docs/DEVELOPER_GUIDE.en.md`](docs/DEVELOPER_GUIDE.en.md)）。

</details>

## 💬 社区与支持

* **GitHub Issues**：[提交问题或建议](https://github.com/killa0132/CalaplayUpper/issues)
* **Discord**：[加入频道](https://discord.com/invite/BGeYfMBwaw/login)
* **QQ 群**：1054243070

如果你觉得这个工具对你有帮助，欢迎在 GitHub 上点一个 ⭐ Star，这是对开发者最大的鼓励喵～

## 📜 许可证

本项目基于 [MIT License](LICENSE) 开源。

CalaplayUpper 是社区项目，与 CalaPlayer 官方无关。游戏素材版权归原作者所有。
