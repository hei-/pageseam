# Privacy Policy

English | 简体中文 below

## Data collected

This plugin does not collect any user data for itself. It has no analytics, telemetry or tracking.

## How data flows

- When a tool runs, the plugin sends the selected file and the API key to the **PageSeam service URL that you configure** in the plugin credentials. Nothing is sent to the plugin author or to any other third party.
- PageSeam is self-hosted: you deploy and operate it, so the files stay on infrastructure you control.

## Storage and retention

- The plugin does not store file contents. It fetches the results and immediately deletes the job and its files on the service.
- Results that are never fetched (for example after a timeout) are deleted by the service automatically when its retention time expires (60 minutes by default).
- The service URL and API key are stored by Dify as plugin credentials.

## Logging

The plugin does not log file contents or credentials. Error messages may include the service URL and the HTTP status returned by the service.

## Third-party sharing

None. Data is only exchanged between Dify and the PageSeam service you configure.

---

# 隐私说明

- **收集的数据**：插件本身不收集任何用户数据，没有统计、遥测或跟踪。
- **数据流向**：调用工具时，插件把选中的文件和 API Key 发送到你在插件凭据中配置的 PageSeam 服务地址，不发送给插件作者或任何第三方。PageSeam 由你自己部署和运维，文件留在你自己的服务器上。
- **存储和保留**：插件不保存文件内容；取回结果后立即删除服务端的任务和文件。没有取回的结果（比如等待超时）在服务端保留时间（默认 60 分钟）到期后自动删除。服务地址和 API Key 由 Dify 作为插件凭据保存。
- **日志**：插件不记录文件内容和凭据。出错信息中可能包含服务地址和服务返回的 HTTP 状态码。
- **第三方共享**：无。数据只在 Dify 和你配置的 PageSeam 服务之间传输。
