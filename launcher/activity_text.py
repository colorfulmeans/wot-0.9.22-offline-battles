"""Localize rendered launcher status templates while retaining diagnostic text."""

from collections import defaultdict
import re


_ACTIVITY_ZH = {
    "Launcher session: %s role=launcher.": "启动器会话：%s，角色为启动器。",
    "REPLAY_ENTRY: close the running LAN room before playback.": "请先关闭正在运行的局域网房间，再播放录像。",
    "REPLAY_ENTRY: %s": "无法播放录像：%(detail)s",
    "Select a .wotlanreplay file, not a native .wotreplay.": "请选择 .wotlanreplay 离线录像文件。",
    "The selected replay file does not exist.": "所选录像文件不存在。",
    "The replay contains a non-finite JSON value.": "录像包含无效的数值。",
    "Replay startup was cancelled.": "已取消启动录像回放。",
    "The replay is truncated or has an oversized record.": "录像不完整，或包含过大的记录。",
    "The replay exceeds the decompressed size limit.": "录像解压后的大小超出上限。",
    "Invalid replay record.": "录像包含无效记录。",
    "This is not a supported #1513 offline replay.": "此文件与 #1513 离线录像格式不兼容。",
    "Replay header is missing %s.": "录像头缺少字段 %s。",
    "The replay initial round identity is inconsistent.": "录像起始对局标识不一致。",
    "The replay initial %s lineup is incomplete.": "录像的起始阵容不完整（%s）。",
    "The replay timestamps are invalid.": "录像的时间戳无效。",
    "The replay footer/count is invalid.": "录像的结尾或记录数量无效。",
    "The replay contains an unsupported gameplay record.": "录像包含无法播放的战斗记录。",
    "The replay file changed during validation. Retry after saving finishes.": "校验期间录像文件发生变化。请等待保存完成后重试。",
    "REPLAY_ENTRY validating selected recording...": "正在校验所选录像…",
    "REPLAY_ENTRY validating records=%d logical_bytes=%d": "正在校验录像，已读取 %d 条记录，解压后共 %d 字节…",
    "REPLAY_ENTRY valid map=%s bots=%s records=%s duration=%.2fs; server=False worker=False": "录像已通过校验。地图 %s，BOT 数量 %s，记录数 %s，时长 %.2f 秒。回放无需服务器或模拟端。",
    "REPLAY_ENTRY launch visible-only; automatic replay after garage load.": "正在启动回放客户端，车库加载后将自动播放录像。",
    "Vehicle profiles could not be loaded: %s": "无法加载车辆属性方案：%(detail)s",
    "Saves could not be listed: %s": "无法列出存档：%(detail)s",
    "Selected save '%s'.": "已选中存档「%s」。",
    "Wait for the current launcher operation to finish.": "请等待启动器完成当前操作。",
    "The balances could not be read: %s": "无法读取账户余额：%(detail)s",
    "The earnings multiplier must be a number.": "收益倍率必须为数字。",
    "The earnings multiplier must be between %s and %s.": "收益倍率必须在 %s 到 %s 之间。",
    "A balance must be a whole number.": "余额必须为整数。",
    "The balances could not be saved: %s": "余额保存失败：%(detail)s",
    "The vehicle could not be added: %s": "无法添加战车：%(detail)s",
    "The save folder could not be opened: %s": "无法打开存档目录：%(detail)s",
    "The save could not be backed up: %s": "无法备份存档：%(detail)s",
    "The backup could not be read: %s": "无法读取备份：%(detail)s",
    "The save could not be restored: %s": "无法恢复存档：%(detail)s",
    "The save could not be initialized: %s": "无法初始化存档：%(detail)s",
    "The save editor could not be opened: %s": "无法打开存档编辑器：%(detail)s",
    "The original package must contain exactly one badge catalogue.": "原版资源包必须包含一份徽章目录。",
    "The original badge catalogue is unreadable: %s": "无法读取原版徽章目录：%(detail)s",
    "The badge catalogue is not in the expected format.": "徽章目录格式无效。",
    "Could not create the error report: %s": "无法创建错误报告：%(detail)s",
    "ProcDump could not be enabled: %s": "无法启用 ProcDump：%(detail)s",
    "Balances saved: Credits %d, Gold %d, Free experience %d, War bonds %d": "已保存余额：银币 %d、金币 %d、全局经验 %d、债券 %d。",
    "Balances saved, but the earnings multiplier could not be saved: %s": "余额已保存，收益倍率保存失败：%(detail)s",
    "Earnings multiplier saved: %sx": "已保存收益倍率：%s 倍",
    "The gold vehicles could not be listed: %s": "无法列出金币及奖励战车：%(detail)s",
    "Select a vehicle to buy.": "请选择要购入的战车。",
    "Could not create the save: %s": "无法创建存档：%(detail)s",
    "Created save '%s'.": "已创建存档「%s」。",
    "Select a save before renaming it.": "请先选择要重命名的存档。",
    "Could not rename the save: %s": "无法重命名存档：%(detail)s",
    "Renamed save to '%s'.": "存档已重命名为「%s」。",
    "Close World of Tanks before deleting a save.": "请先关闭坦克世界，再删除存档。",
    "The default save cannot be deleted.": "默认存档受保护。",
    "Save deletion was cancelled.": "已取消删除存档。",
    "Could not delete the save: %s": "无法删除存档：%(detail)s",
    "Deleted save '%s'.": "已删除存档「%s」。",
    "Select a save before opening its folder.": "请先选择要打开目录的存档。",
    "Select a save before backing it up.": "请先选择要备份的存档。",
    "Save backup was cancelled.": "已取消备份存档。",
    "Select the save to restore into.": "请选择要恢复到的存档。",
    "Save restore was cancelled.": "已取消恢复存档。",
    "Vehicle profile recovery could not be checked: %s": "无法检查车辆方案恢复状态：%(detail)s",
    "A vehicle profile is active while World of Tanks is running; close the game and reopen this launcher before any other launch so it can be cleaned safely.": "游戏正在使用车辆属性方案。请关闭游戏并重新打开启动器，以便安全清理。",
    "A stale vehicle profile could not be cleaned: %s": "无法清理上次的临时车辆方案：%(detail)s",
    "Preserved the previous vehicle edits as profile '%s'.": "已将之前的车辆修改保存为方案「%s」。",
    "Recovered an interrupted vehicle profile update.": "已恢复上次中断的车辆方案更新。",
    "Cleaned a stale temporary vehicle profile from the previous launcher session.": "已清理上次启动器会话遗留的临时车辆方案。",
    "Select a supported game folder before testing.": "请先选择受支持的游戏目录，再测试连接。",
    "Crash report collection could not start: %s": "无法开始收集崩溃报告：%(detail)s",
    "Closing every %s process...": "正在关闭所有 %s 进程…",
    "Could not close the started process: %s": "无法关闭已启动的进程：%(detail)s",
    "Could not stop the 0.9.22 starter cleanly: %s": "无法正常关闭 0.9.22 启动辅助程序：%(detail)s",
    "The 0.9.22 starter stop helper returned exit code %s.": "0.9.22 启动辅助程序返回关闭退出码 %s。",
    "Close the game, worker and LAN room before maintenance.": "请先关闭游戏、模拟端和局域网房间，再进行维护。",
    "Select the supported 0.9.22 game folder first.": "请先选择受支持的 0.9.22 游戏目录。",
    "Launcher maintenance failed: %s": "启动器维护失败：%(detail)s",
    "Could not create the Bot lineup profile: %s": "无法新建 BOT 阵容方案：%(detail)s",
    "Bot tactics editor: %s": "BOT 战术编辑器：%(detail)s",
    "Create or select a Bot lineup profile before editing.": "请先创建或选择 BOT 阵容方案，再编辑。",
    "Select a saved Bot lineup profile before deleting it.": "请先选择已保存的 BOT 阵容方案，再删除。",
    "Could not delete the Bot lineup profile: %s": "无法删除 BOT 阵容方案：%(detail)s",
    "Vehicle profiles are available for the 0.9.22 client.": "车辆方案适用于 0.9.22 客户端。",
    "Vehicle data editor: %s": "车辆属性修改器：%(detail)s",
    "Could not create the vehicle profile: %s": "无法创建车辆方案：%(detail)s",
    "Created vehicle profile '%s'.": "已创建车辆方案「%s」。",
    "Create or select a vehicle profile before editing.": "请先创建或选择车辆方案，再编辑。",
    "Select a saved vehicle profile before deleting it.": "请先选择已保存的车辆方案，再删除。",
    "Vehicle profile deletion was cancelled.": "已取消删除车辆方案。",
    "Could not delete the vehicle profile: %s": "无法删除车辆方案：%(detail)s",
    "Deleted vehicle profile '%s'.": "已删除车辆方案「%s」。",
    "Close World of Tanks before repairing or resetting offline data.": "请先关闭坦克世界，再修复或重置离线数据。",
    "Offline data reset was cancelled.": "已取消重置离线数据。",
    "Wait for launcher maintenance to finish.": "请等待启动器完成维护。",
    "Select Online and a supported game folder first.": "请先选择联网模式和受支持的游戏目录。",
    "The selected Bot lineup is invalid: %s": "选中的 BOT 阵容无效：%(detail)s",
    "Installing the %s server data into %s...": "正在将 %s 服务器数据安装到 %s…",
    "The LAN room runs original vehicle data; no vehicle profile is shared.": "局域网房间使用原始车辆数据。",
    "The LAN room pins vehicle profile '%s' (%d package member%s); joiners receive it automatically.": "局域网房间已锁定车辆方案「%s」（含 %d 个包内文件%s），加入者会自动接收。",
    "The LAN room was not opened because its hidden simulation worker is unavailable.": "隐藏模拟端不可用，无法开启局域网房间。",
    "The LAN server could not start: %s": "无法启动局域网服务器：%(detail)s",
    "Error reporting is unavailable for this session: %s": "本次会话无法收集错误报告：%(detail)s",
    "The persistent server log boundary could not be recorded: %s": "无法记录常驻服务器的日志边界：%(detail)s",
    "Installing the %s mod into %s...": "正在将 %s 模组安装到 %s…",
    "The running LAN room keeps the vehicle data it pinned at room start; the selected profile applies when the room restarts.": "当前房间使用开房时锁定的车辆数据。重启房间后将应用本次所选方案。",
    "The running LAN room keeps the vehicle data it pinned at room start.": "当前房间使用开房时锁定的车辆数据。",
    "No launcher-owned vehicle profile is active; other installed mods are unchanged.": "当前使用原始车辆数据，已安装的其他模组保持原样。",
    "Activated single-player vehicle profile '%s' (%d package member%s).": "已启用单人车辆方案「%s」（含 %d 个包内文件%s）。",
    "The selected exact Bot lineup applies only to a server started by this Launcher; this external server keeps its own lineup.": "当前连接外部服务器，由该服务器决定 BOT 阵容。此处所选精确阵容适用于本启动器开启的房间。",
    "The compatible server at %s:%d answered.": "%s:%d 上的兼容服务器已应答。",
    "Something at %s:%d answered, but it is not the server for this client. The game was not started.": "%s:%d 有响应，但服务与此客户端不兼容。游戏未启动。",
    "%s:%d did not answer the compatible 0.9.22 protocol. The game was not started.": "%s:%d 未按兼容的 0.9.22 协议应答。游戏未启动。",
    "Warning: %s:%d did not answer. Start the game anyway and click the battle button when the host is ready.": "%s:%d 未应答。游戏将继续启动，请待房主准备好后点击战斗按钮。",
    "The launcher failed: %s": "启动器执行失败：%(detail)s",
    "Could not prepare this session's crash report: %s": "无法准备本次会话的崩溃报告：%(detail)s",
    "Could not freeze this session's diagnostic logs: %s": "无法保存本次会话的诊断日志：%(detail)s",
    "Could not remove the packaged crash dump: %s": "无法移除已打包的崩溃转储：%(detail)s",
    "The host vehicle data could not be fetched: %s": "无法获取房主的车辆数据：%(detail)s",
    "The local vehicle data could not be verified: %s": "无法校验本机车辆数据：%(detail)s",
    "The local vehicle profile could not be removed: %s": "无法移除本机车辆属性方案：%(detail)s",
    "This server does not share vehicle data; the selected vehicle profile was ignored.": "该服务器未共享车辆数据，本次按房间配置使用原始车辆数据。",
    "This server does not share vehicle data; original vehicle values stay active.": "该服务器未共享车辆数据，继续使用原始车辆属性。",
    "The LAN room runs original vehicle data, but a vehicle profile is active locally. Stop the LAN room or select 'Original vehicle values', then start again.": "房间使用原始车辆数据，本机启用了车辆方案。请关闭房间或选择「原始车辆属性」，然后重试。",
    "The host runs original vehicle data; the selected vehicle profile was ignored.": "房主使用原始车辆数据，本次按房主设置运行。",
    "The host runs original vehicle data; no vehicle profile is shared.": "房主使用原始车辆数据。",
    "Your vehicle data matches the room profile '%s'.": "你的车辆数据与房间方案「%s」一致。",
    "Your vehicle data matches the room.": "你的车辆数据与房间一致。",
    "The LAN room is pinned to the vehicle profile '%s'. Stop the LAN room and start it again after changing the vehicle profile.": "房间已锁定车辆方案「%s」。更改车辆方案后，请关闭并重开房间。",
    "The host vehicle data could not be installed: %s": "无法安装房主的车辆数据：%(detail)s",
    "Installed the host vehicle data profile '%s' (%d package member%s); original data is restored after this session.": "已安装房主的车辆方案「%s」（含 %d 个包内文件%s）。会话结束后恢复原始数据。",
    "The launcher-owned LAN server uses a different game or visibility setting, or different Bot roster rules. Stop it before starting this session.": "现有局域网服务器使用不同的客户端、可见性设置或 BOT 阵容规则。请先关闭服务器，再开始本次会话。",
    "Reusing the launcher-owned %s LAN server.": "正在复用本启动器开启的 %s 局域网服务器。",
    "This mode needs a fresh launcher-owned server, but a compatible server already uses port %d. Close it first.": "此模式需要启动新服务器。端口 %d 已有兼容服务器，请先关闭它。",
    "Bot tactics: %s": "BOT 战术：%s",
    "Custom Bot tactics require a launcher-owned server; stop the external server first.": "自定义 BOT 战术需要由此启动器创建服务器。请先关闭外部服务器。",
    "The exact Bot lineup or vehicle exclusions need a fresh launcher-owned server. Stop the compatible server already using port %d first.": "精确阵容或车辆排除设置需要开启新服务器。请先关闭占用端口 %d 的兼容服务器。",
    "A compatible %s LAN server is already running; using it.": "已有兼容的 %s 局域网服务器正在运行，将使用该服务器。",
    "Another program uses port %d and does not speak the %s LAN protocol. Close it before starting the game.": "端口 %d 被不支持 %s 局域网协议的程序占用。请先关闭该程序，再启动游戏。",
    "This session's server log could not be isolated: %s": "无法隔离本次会话的服务器日志：%(detail)s",
    "Starting the %s LAN server...": "正在启动 %s 局域网服务器…",
    "Server log: %s": "服务器日志：%s",
    "The LAN server did not answer the %s protocol on port %d.": "局域网服务器未按 %s 协议在端口 %d 应答。",
    "The LAN server listens on port %d.": "局域网服务器正在监听端口 %d。",
    "Other players join with %s:%d": "其他玩家可用 %s:%d 加入。",
    "Stopping the LAN room worker because its server closed.": "局域网服务器已关闭，正在关闭房间模拟端。",
    "The LAN server stopped with exit code %s.": "局域网服务器已退出，退出码为 %s。",
    "Starting the hidden simulation worker...": "正在启动隐藏模拟端…",
    "The worker starter log boundary could not be recorded: %s": "无法记录模拟端启动日志边界：%(detail)s",
    "Hidden worker resources: the client's own paths.xml.": "隐藏模拟端使用客户端的 paths.xml。",
    "The hidden simulation worker is ready.": "隐藏模拟端已就绪。",
    "The hidden simulation worker did not become ready.": "隐藏模拟端未能就绪。",
    "The hidden simulation worker stopped with exit code %s.": "隐藏模拟端已退出，退出码为 %s。",
    "The LAN room simulation worker stopped with exit code %s. The room is unavailable; stop it and start a new room.": "房间模拟端已退出，退出码为 %s。请关闭并重新开启局域网房间。",
    "Stopping the hidden simulation worker...": "正在关闭隐藏模拟端…",
    "The hidden simulation worker did not stop in time.": "等待隐藏模拟端退出超时。",
    "The game stopped with exit code %s.": "游戏已退出，退出码为 %s。",
    "The hidden simulation worker stopped with exit code %s; the game was closed.": "隐藏模拟端已退出，退出码为 %s，游戏已关闭。",
    "The hidden simulation worker exited normally with code %s.": "隐藏模拟端已正常退出，退出码为 %s。",
    "The game closed.": "游戏已关闭。",
    "Waiting %d seconds in case the game restarts itself...": "等待 %d 秒，检查游戏是否会自动重启…",
    "The game started another process; the server stays up.": "游戏已启动另一个进程，服务器继续运行。",
    "Stopping the LAN server...": "正在关闭局域网服务器…",
    "A World of Tanks process did not finish closing; vehicle cleanup will retry at the next launcher start.": "有坦克世界进程仍在运行。下次启动启动器时将重试清理车辆数据。",
    "Removed the temporary vehicle profile; original vehicle data is active again.": "已移除临时车辆方案，并恢复原始车辆数据。",
    "Could not restore original vehicle data: %s": "无法恢复原始车辆数据：%(detail)s",
    "Finish the current launcher maintenance before closing.": "请等待启动器完成维护，再关闭窗口。",
    "Closing the game and its offline processes...": "正在关闭游戏及其离线进程…",
    "Testing %s:%d...": "正在测试 %s:%d 的连接…",
    "The compatible server at %s answered.": "%s 上的兼容服务器已应答。",
    "Something at %s answered, but it is not the server for this client.": "%s 有响应，但服务与此客户端不兼容。",
    "No answer from %s. Check that the host started the battle and that its firewall allows TCP %d.": "%s 暂无应答。请确认房主已开启战斗，且防火墙允许 TCP 端口 %d。",
    "A compatible server already listens on %s. Start game will use it.": "已有兼容服务器在 %s 监听，启动游戏时将使用它。",
    "Another program listens on %s. Close it before you host here.": "%s 被其他程序占用。请关闭该程序，再开启房间。",
    "Nothing listens on %s yet. Start game runs the server there.": "%s 尚无服务监听。启动游戏时将在此地址开启服务器。",
    "Starting %s...": "正在启动 %s…",
    "Installed %d %s mod paths": "已安装 %d 个 %s 模组路径。",
    "Wrote %s": "已写入 %s。",
    "[worker] %s": "[模拟端] %s",
    "Bundled 0.9.22 payload: %s.": "随包 0.9.22 模组：%s。",
    "Installed 0.9.22 payload before installation: %s.": "安装前的 0.9.22 模组：%s。",
    "Installed 0.9.22 payload after installation: %s.": "安装后的 0.9.22 模组：%s。",
    "The bundled diagnostic build identity is unavailable; installation will continue and will not be treated as current on the next launch.": "无法获取随包构建标识。安装会继续，下次启动时将重新核验。",
    "Install decision: keep the installed 0.9.22 payload; the build identity and package-owned files are current.": "已安装的 0.9.22 模组及构建标识均为当前版本。",
    "Install decision: install the bundled 0.9.22 payload.": "将安装随包的 0.9.22 模组。",
    "Install decision: reinstall the bundled 0.9.22 payload.": "将重新安装随包的 0.9.22 模组。",
    "Install decision: forced reinstall the bundled 0.9.22 payload.": "将强制重新安装随包的 0.9.22 模组。",
    "The mod was installed, but its update marker could not be saved.": "模组已安装，更新标识保存失败。",
    "The isolated 0.9.22 client preferences redirect is already up to date.": "0.9.22 离线设置隔离已是当前版本。",
    "Updated the isolated 0.9.22 client preferences redirect.": "已更新 0.9.22 离线设置隔离。",
    "Created the isolated 0.9.22 client preferences redirect.": "已为 0.9.22 创建独立离线设置。",
    "Quarantined invalid config.json as %s": "已将无效的 config.json 隔离为 %s。",
    "Startup repair kept the saved endpoint, named saves and isolated client preferences; obsolete defaults follow the one-time replacement policy.": "启动修复保留了已保存的服务器地址、命名存档和独立客户端设置。过时的默认数据按一次性替换规则更新。",
    "Replaced the old %s": "已替换旧的 %s。",
    "Deleted all offline saves and rebuilt the default save.": "已清空所有离线存档并重建默认存档。",
    "Reset offline client preferences; new defaults are created on next start.": "已重置离线客户端设置，下次启动时将生成默认设置。",
    "Factory reset completed; all project data, replays and reports were removed.": "已恢复出厂设置并清除离线项目数据、录像和报告。",
    "Reset %d fully unlocked saves to current equipment defaults.": "已将 %d 份全解锁存档恢复为当前的默认装备配置。",
    "Enter the address of the PC that hosts the battle.": "请输入房主电脑的联机地址。",
    "The server address is invalid.": "服务器地址无效。",
    "The server port must be a number.": "服务器端口必须为数字。",
    "The server port must be 1-65535.": "服务器端口必须在 1 到 65535 之间。",
    "Tanks per team must be a whole number from 1 to 15.": "每队车辆数必须是 1 到 15 之间的整数。",
    "Tanks per team must be a number from 1 to 15.": "每队车辆数必须是 1 到 15 之间的数字。",
    "Tanks per team must be 1-15.": "每队车辆数必须在 1 到 15 之间。",
}

# Formatted status strings also arrive from core and the launcher backend.
# Recognize only complete, known templates. Captured values are displayed
# literally, with explicit error-detail slots localized separately.
_FIELD = re.compile(r"%%|%(?:\(detail\))?[-+ #0]*\d*(?:\.\d+)?[dsfrgx]")
_FRAGMENT = {"d": r"[-+]?\d+", "f": r"[-+]?\d+(?:\.\d+)?", "x": r"[0-9A-Fa-f]+"}


def _format_parts(template):
    parts = []
    position = 0
    for field in _FIELD.finditer(template):
        preceding = template[position:field.start()]
        if field.group() == "%%":
            parts.append((preceding + "%", ""))
        else:
            parts.append((preceding, field.group()))
        position = field.end()
    return parts, template[position:]


class ActivityText:
    def __init__(self, labels):
        self.labels = dict(labels, **_ACTIVITY_ZH)
        self.formats = defaultdict(list)
        for source, translation in self.labels.items():
            fields, tail = _format_parts(source)
            if not any(field for _, field in fields):
                continue
            translated, end = _format_parts(translation)
            if (sum(bool(field) for _, field in fields) !=
                    sum(bool(field) for _, field in translated)):
                continue
            prefix = source.partition(" ")[0]
            if "%" in prefix:
                prefix = ""
            pattern = "".join(re.escape(literal) +
                              ("(" + _FRAGMENT.get(field[-1], r".*?") + ")" if field else "")
                              for literal, field in fields) + re.escape(tail)
            self.formats[prefix].append((re.compile(pattern, re.DOTALL), translated, end))

    def chinese(self, message):
        return self._lookup(message, True) or message

    def failure(self, message, language):
        known = self._lookup(message, True)
        if language == "zh":
            return known or "操作未完成，详情见诊断日志。"
        return message if known is not None else "The operation could not be completed. See the diagnostic logs for details."

    def _lookup(self, message, allow_detail):
        if message in self.labels:
            return self.labels[message]
        prefix = message.partition(" ")[0]
        rules = (*self.formats.get(prefix, ()), *self.formats.get("", ())) if prefix else self.formats.get("", ())
        for pattern, fields, tail in rules:
            match = pattern.fullmatch(message)
            if match is None:
                continue
            values = iter(match.groups())
            result = []
            for literal, field in fields:
                result.append(literal)
                if field:
                    value = next(values)
                    if field == "%(detail)s":
                        value = self._lookup(value, False) if allow_detail else None
                        value = value or "详情见诊断日志"
                    result.append(value)
            return "".join(result) + tail
        return None
