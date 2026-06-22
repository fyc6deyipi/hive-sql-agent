# Hive SQL 优化智能体

封装为 API 的 Hive on MR/Tez 慢任务诊断与优化智能体。部署在千帆 AppBuilder（工作流 + 知识库 + qwen-code）。

## 目录
```
hive-sql-agent/
├── README.md                                # 本文档
├── DEPLOY.md                                # 千帆部署完整步骤
├── knowledge/
│   └── hive_mr_tez_optimization.md          # 知识库（上传到千帆 RAG）
├── prompts/
│   ├── system_prompt.md                     # LLM 节点系统提示词
│   └── user_prompt_template.md              # 用户提示词模板（含变量占位）
├── schema/
│   └── api_schema.md                        # API 入参 schema 说明
└── examples/
    ├── request_example.json                 # 请求示例
    └── response_example.json                # 响应示例
```

## 快速链路
1. 阅读 `DEPLOY.md` → 在千帆建工作流 + 上传知识库
2. 节点 1 入参对齐 `schema/api_schema.md`
3. 节点 4 LLM 系统提示词粘贴 `prompts/system_prompt.md`
4. 用 `examples/request_example.json` 调试，期望响应结构对齐 `examples/response_example.json`
5. 发布为 API

## 设计要点
- **单 LLM 调用**：诊断 + 改写 + Markdown 报告一次性结构化输出，省 token、降延迟
- **RAG 知识库**：按 `##` 标题切片，覆盖倾斜/Join/分区/小文件/反模式 9 大类
- **JSON + Markdown 双输出**：`json` 给下游系统消费，`markdown_report` 给开发同学阅读
- **可回归**：响应里每个 issue 含 evidence，方便人工复核与积累测试集
