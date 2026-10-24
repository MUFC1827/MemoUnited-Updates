# MemoUnited

Windows 10 1809 及以上／Windows 11 x64；Apple 芯片 Mac，macOS 15 及以上。

[下载安装包](https://github.com/MUFC1827/MemoUnited-Updates/releases/tag/v7.1.2)

- Windows：运行 `MemoUnited_Release_x64_Setup.exe`。
- Apple 芯片 Mac：打开 `MemoUnited_macOS_arm64.dmg`，将应用拖入 Applications。

Mac 安装包使用 ad-hoc 签名，尚未公证；系统阻止首次打开时，按「系统设置 → 隐私与安全性 → 仍要打开」操作。

Windows 默认使用 `Ctrl+Shift+M` 呼出面板、`Ctrl+Shift+L` 锁定或解锁边缘呼出。
Mac 默认使用 `⇧⌘M`（Shift + Command + M）呼出、`⇧⌘L` 锁定边缘；
`⌘N` 新建、`⌘S` 保存、`⌘F` 搜索、`⌘L` 输入消息、`⌘O` 添加附件。
Memo / Muse 切换保留 `⌃⇥`（Control + Tab），不占用系统 Command + Tab。
两区「设置 → 快捷键」可以修改组合。Mac 首次升级启用新默认，
可用「恢复原先快捷键 / 恢复 Mac 端快捷键」切换，两套修改分别记忆。

6.1.0 起，在设置中打开「更新」，选择「检查更新」和「更新并重启」。
6.2.0 起可选择启动时、每天或每周检查，并开启空闲自动安装。
旧版需要先安装一次带更新器的新版；升级保留本机个人数据。
迁移至新版后，请勿手动安装旧的 6.0 客户端。

此仓库发布安装包、SHA-256 校验值和签名更新清单。源代码保持私有。
文字、事项、附件和翻译模型保存在用户电脑，发布包不包含个人数据或模型权重。

`stable` 的 `latest.json` 提供签名更新信息；版本 Release 中保留对应清单。
Mac `.app.zip` 供更新器使用；初次安装使用 DMG。
7.1.0 起支持 `.mu` 动画分享与 `.mubackup` 整体备份；备份不含翻译模型。
6.3.4 起优先下载与已安装版本匹配的增量包；无法复用时自动使用完整包。
Windows runtime ZIP 供支持后台准备的新版更新器使用；初次安装仍使用 Setup。
