# PageSeam 文档解析插件

[English](../README.md) | 简体中文

源码：https://github.com/hei-/pageseam

调用自部署的 [PageSeam](https://github.com/hei-/pageseam/blob/main/README.zh-CN.md) 服务解析 PDF、Word（doc、docx）、PPT 和图片：逐页判断是否需要 OCR，输出 Markdown（给知识库）、可搜索 PDF 或 Word。Word 里嵌入的扫描页会被识别，跨页表格合并成一张表。

**需要先部署 PageSeam 服务**（Docker，CPU 可运行）。插件只负责上传文件、取回结果；文件只发送到你配置的服务地址，不发送给第三方。

## 工具

| 工具 | 输出 |
|------|------|
| **解析文档为 Markdown**（`parse_document`） | `text`：Markdown，每页以 `<!-- page N -->` 开头<br>`chunks`：分好的知识库分段，可直接接「知识库」节点 |
| **PDF 转 Word / 可搜索 PDF**（`convert_document`） | `files`：Word 和 / 或可搜索 PDF |
| **查询任务结果**（`get_job_result`） | 前两个工具等待超时时，用 `job_id` 再取结果 |

`chunks` 按页切分，不按分隔符：每段开头标注文档名、页码和章节；表格整张保留，或按行切开、每段带表头；跨页表格合成一段。在知识流水线中把 `chunks` 直接接到「知识库」节点即可。

## 凭据

| 字段 | 说明 |
|------|------|
| 服务地址 | 例如 `http://<服务器 IP>:8000`。要能从 Dify 的 `plugin_daemon` 容器访问：用宿主机内网 IP，不要用 `localhost` |
| API Key | 服务的 API Key |

## 安装

用 [Dify 插件 CLI](https://docs.dify.ai/en/develop-plugin/getting-started/getting-started-dify-plugin) 打包（`dify plugin package ./dify-plugin`），在「插件 → 安装插件 → 本地插件」中上传。本地打包的插件需要签名，见 [GUIDE.zh-CN.md](https://github.com/hei-/pageseam/blob/main/dify-plugin/GUIDE.zh-CN.md#签名)。

分段规则、签名和开发注意事项见 [GUIDE.zh-CN.md](https://github.com/hei-/pageseam/blob/main/dify-plugin/GUIDE.zh-CN.md)。

## 许可证

[MIT](https://github.com/hei-/pageseam/blob/main/dify-plugin/LICENSE)。PageSeam 服务端是 AGPL-3.0。
