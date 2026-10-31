# DeepSeek 处置建议

本项目通过后端的 OpenAI 兼容接口调用 DeepSeek。模型负责根据已经完成的检测统计、聚集分析和现场补充文字编写建议；YOLO 图像识别仍在本机运行。

## 配置

1. 在 https://platform.deepseek.com/ 创建 API Key，确保账户有可用余额。
2. 打开 `backend/config/ai.local.env`，填写：

```dotenv
DECISION_PROVIDER=openai_compatible
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
OPENAI_API_KEY=在这里填写自己的API密钥
DECISION_API_TIMEOUT_SECONDS=120
```

配置项沿用兼容接口的 OPENAI 前缀，以上地址实际调用 DeepSeek。模型名依据 DeepSeek 当前官方文档，之后可自行更改。

3. 关闭程序的启动窗口，再双击 YOLOv11 启动文件。启动脚本会自动加载此配置；不要只刷新浏览器。
4. 进入任务的处置建议页，确认顶部显示 DeepSeek 和模型名称，再点击生成。已有的本地规则建议不会自动改写，需要重新生成。

`ai.local.env` 已加入 Git 忽略，不应提交或分享。不要把密钥放进网页脚本。恢复离线模式时，把 `DECISION_PROVIDER` 改回 `rules` 并重启。

## 数据与结果

点击生成会发送检测数量、类别统计、聚集区域编号、位置描述、聚集指数及输入的现场文字；不会发送原始图片、局部目标图或完整数据库。

返回结果必须符合指定 JSON 结构，引用的区域编号必须来自当前任务；输出按建议版本保存，并记录来源与模型。用户补充信息仅用于辅助，不会更改检测数量或热力图。

API Key 错误、余额不足、限流、网络超时或不合格输出会显示错误；不会将规则建议伪装成 AI 建议。失败不会覆盖上一次保存的建议。为避免自动重复计费，调用失败不自动重试，可手动再次生成。

## 验证范围

接口请求、错误处理、建议存储和任务流程使用模拟响应测试。真实连通性、账户额度、实际模型效果需要填写有效 API Key 后验证。

参考：https://api-docs.deepseek.com/zh-cn/ ，https://api-docs.deepseek.com/zh-cn/guides/json_mode/
