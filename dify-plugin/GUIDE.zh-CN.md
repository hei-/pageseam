# PageSeam 插件详细说明

[English](GUIDE.md) | 简体中文

[插件说明](readme/README_zh_Hans.md)背后的细节：分段规则、签名、开发注意事项。不打进插件包。

## `chunks`：为什么不用通用分块器

Dify 自带的「通用分块器」（General Chunker）只按分隔符切分，不会把短段落合并：页码标记会单独成为一个分段，正文分段里没有页码，内容也很零碎（样例 10 页被切成 63 段）。

`chunks` 按页切分，规则如下：

- 段落合并到不超过「分段最大字数」（默认 800），标题开始新的分段，分段不跨页。
- 表格转成 `| 单元格 | 单元格 |` 格式的纯文本。HTML 标签会占用经济模式关键词索引的名额。
- 表格按「表格最大字数」（`table_max_chars`，默认 0，即与分段最大字数相同）分段：不超过的表格整张放进一个分段；超长的表格按行切开，**每段都带表头**，检索到任何一段都知道各列的含义。
- 问题经常要整表回答（合计、一共几项）时，把表格最大字数填 2000–3000：中小表格整张一段，超大表格仍按行切开，分段长度始终有上限。小于分段最大字数时按分段最大字数算。
- 跨页表格（服务端已合并）单独成段，标注起止页，如「【合同 · 第 1–2 页】」。
- 每段以「【文档名 · 第 N 页 · 所在章节】」开头。文档名是去掉扩展名的文件名：知识库检索交给模型的只有分段内容，没有文件名，同一手册的新旧版本、几份格式相同的合同，不标注时模型分不清哪段出自哪份。不需要时关掉「分段标注文档名」（`chunk_doc_name`）。

样例被切成 15 段，检索到任何一段都能引用页码。在知识流水线中，把 `chunks` 直接接到「知识库」节点即可（`index_chunk_variable_selector: [解析节点, chunks]`）。

## 签名

Dify 默认只允许安装 Marketplace 签名过的插件（`FORCE_VERIFYING_SIGNATURE=true`）。安装本地打包的插件有两种做法：

- **用自己的密钥签名（推荐）**：`dify signature generate -f mykey` 生成密钥对，`dify signature sign dify-plugin.difypkg -p mykey.private.pem -c community` 签名（授权类别标为 community，不冒用官方类别）；把公钥放到插件守护进程能读到的目录，设置 `THIRD_PARTY_SIGNATURE_VERIFICATION_ENABLED=true` 和 `THIRD_PARTY_SIGNATURE_VERIFICATION_PUBLIC_KEYS=<公钥路径>`，重建 `plugin_daemon` 容器。私钥不要提交。
- 关闭校验（`FORCE_VERIFYING_SIGNATURE=false`）：所有未签名插件都能装，只适合测试环境。

> 开启第三方签名校验前要先放好公钥文件。公钥文件不存在时，守护进程会校验失败，**所有插件**（包括官方插件）都装不上。

## 开发注意事项

- **每个工具文件里只能有一个 `Tool` 子类**：SDK 按模块命名空间查找 `Tool` 的子类。`from utils.tool_base import DocParserTool` 会把基类也带进命名空间，插件启动时报 `Multiple subclasses of Tool`。正确写法是 `from utils import tool_base`，然后继承 `tool_base.DocParserTool`。
- **每个参数都必须有 `human_description`**：少写一个参数的 `human_description`，插件启动时就会报 `Error loading tool configuration`。
- **修改代码后重新打包上传即可升级**：版本号不变也可以，包的内容变了，唯一标识（checksum）就会变，已配置的凭据保留。

## 文件结构

```
dify-plugin/
├── manifest.yaml
├── main.py                    # 单次调用上限 600 秒
├── provider/pageseam.{yaml,py}   # 凭据和校验
├── tools/                     # 三个工具
├── utils/
│   ├── client.py              # 提交、轮询（2 秒起，最长间隔 10 秒）、429 重试、下载、删除
│   ├── tool_base.py           # 读取参数、输出结果；取回结果后立即删除服务端任务
│   └── chunking.py            # 按页分段
├── readme/README_zh_Hans.md   # 中文说明（Marketplace 对简体中文用户显示）
└── tests/test_chunking.py     # 分段规则的单元测试（不打进插件包）
```

分段规则改动后运行单元测试（只依赖标准库）：

```bash
cd dify-plugin && python3 -m unittest discover tests
```
