# 固定确认提示音

- 文件：`question-pending.wav`。
- 文本：有问题待确认，请及时处理。
- 制作：维护时使用 macOS 系统 `say` 的 Tingting 中文音色离线生成一次。
- 格式：WAV，单声道、16-bit PCM、22050 Hz，约 2.92 秒，132772 字节。
- SHA256：`9fe477010873a1155d7d7305a830f812f20f9a5ec8d5878c88b1d5d6aaa516f6`，播放器固定核对；重新录制须同步摘要与验证。

此文件是随 Skill 分发的固定资源，不是每次提问的临时产物。提问、安装和升级时均不合成音频；由 Agent 按[提醒规则](../references/question-notification.md)调用本地播放器。生成时未发送业务文本或凭据到外部服务。
