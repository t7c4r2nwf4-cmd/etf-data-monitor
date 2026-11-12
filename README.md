# ETF 数据监控 · 588940 / 513650 / SPX

无需证券账户或 API Key；GitHub Actions 在云端采集公开行情、保存按时间戳标识的快照。所有行情均可能延迟，不能保证交易所级实时性。

### 使用入口

- [Actions 自动采集与测试](https://github.com/t7c4r2nwf4-cmd/etf-data-monitor/actions)
- [原始数据 JSON](https://raw.githubusercontent.com/t7c4r2nwf4-cmd/etf-data-monitor/main/docs/latest.json)（首次采集成功后才生成）
- [报价网页源码](https://github.com/t7c4r2nwf4-cmd/etf-data-monitor/blob/main/docs/index.html)（首次成功后生成）
- 若想看独立网页，在 Settings → Pages → Deploy from a branch → main /docs 启用 GitHub Pages；网页通常位于 https://t7c4r2nwf4-cmd.github.io/etf-data-monitor/

### 自动任务（北京时间）

GitHub 采集：08:35、08:45；13:35、13:45；14:15、14:25、14:45；15:15、16:15。北京时间 = UTC + 8。GitHub Actions 计划任务可能延迟、跳过或受到额度限制，所以严格核对 `collected_at` 和 `quote_time`，过期的行情不作为当前交易依据。

**ChatGPT 原有 09:00、14:00、14:30 推送任务目前不变。** 不会把机器启发式预测混入旧的 ChatGPT 历史命中率。下一步需要验证 ChatGPT 定时任务能否稳定访问本公开数据地址，然后再接线；公网源无法读取时应明确说“数据不足”。

### 采集细节

- 588940、513650：东方财富公共行情，失败后尝试腾讯；原始报价时间和来源随价格一起记录。东方财富日 K 用于收盘后结算。
- SPX：Yahoo 历史日 K，排除尚未正式收盘的盘中日 K；ES、VIX、美债收益率代理 ^TNX、美元/人民币、半导体指数等来自 Yahoo 免费接口。美国指数和期货不是同一锚点，不能直接用 ES 的日K涨幅充当“今晚SPX预期”。
- **513650 的 IOPV：当前未找到足够可信、可证明时间同步的免费字段；故 `iopv=null`、`premium_pct=null`。** 不提供伪精确折溢价，也不将“推荐”假装成“模拟成交”。
- SPX/588940 两个时点的机器预测由独立启发式模型从首次运行起保存到 `data/predictions.jsonl`；`data/outcomes.jsonl` 仅在具备正式收盘记录时增加结算。其强度值**不是历史校准胜率**。
- 模拟做T统计需有可信 IOPV、同期成交参考价、完整买卖闭环与成本，否则保持0笔。总持仓中的50%长期底仓不动。

### 怎么检查是否成功

1. Actions → ETF market snapshot → 查看最近一次运行状态是否绿色成功。
2. 打开 `docs/latest.json` 检查 `health`、`quotes`、`us`、`errors` 及原始时间戳。
3. 免费接口若被限流，可能产生仅有部分数据的 JSON；成功运行不等于所有行情有效。
4. 若需要即时手动验证：Actions → ETF market snapshot → Run workflow（必须由仓库拥有者点击）。
5. 如工作流最后提交时报权限不足：Settings → Actions → General → Workflow permissions → Read and write permissions。

**安全：** 不接入券商账户、不放交易密码、不做自动下单。Public 仓库仅存公开行情与机器模拟记录，禁止上传持仓或私密 API 密钥。