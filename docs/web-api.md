# 本地网页 HTTP 合同 v1

单 Uvicorn worker、一个长期 Runtime、一个串行分析线程。默认真实 DeepSeek（live），仅显式启动参数可选择 offline 测试模式，不会自动降级为模拟模型。SQLite schema 1 保存网页元数据，原预算账本是唯一费用来源。等待队列默认 8；满时 429。同一会话仅一个未终结任务。

API 使用 HttpOnly / SameSite=Strict 随机 owner Cookie；不开放 CORS。Host 必须匹配配置的 loopback 地址，变更请求要求匹配 Origin 和 application/json；开发 Origin 为 http://127.0.0.1:5173。请求体上限 16 KiB。

| 方法 / 路径 | 请求与返回 |
| --- | --- |
| GET /api/health | 模式、资产就绪、预算周期、预设问题；live 预算仅公开 stopped，offline 保留模拟账本诊断统计 |
| POST /api/sessions | `{}` → 会话 |
| GET /api/sessions | 当前 owner 的会话列表 |
| GET /api/sessions/{id} | 会话、轮次任务（问题、核验回答、证据入口）、usage；会话与各任务分别聚合 |
| POST /api/sessions/{id}/turns | `{text: string(1..4000), idempotency_key: string(16..80, 字母数字及-_ )}` → 202 任务；同键同内容返回原任务，同键不同内容 409 |
| GET /api/jobs/{id}?after_seq=0 | 任务、usage 及 seq 大于 after_seq 的事件；终态后停止轮询 |
| POST /api/jobs/{id}/cancel | `{}` → 202 cancelling 或已有终态；排队取消保持会话，运行取消回收整个会话 |
| POST /api/sessions/{id}/close | `{}` → 202 closing 或 closed；close_failed 可再次调用 |
| POST /api/sessions/{id}/delete | `{}` → 200 `{id, deleted:true}`；校验 owner、停止任务并等待工作线程退出后，事务硬删除该对话及 jobs/events/evidence。关闭失败或超时返回 409，保留记录供重试；跨 owner/不存在返回 404 |
| GET /api/sessions/{id}/turns/{turn_id}/evidence/{evidence_id} | owner/session/turn 绑定的公开快照；不匹配一律 404 |

状态：queued → running → succeeded / failed / timed_out / budget_stopped / interrupted；running → cancelling → cancelled / close_failed。排队可直接 cancelled。只有 succeeded 含宿主 reference_checked_candidate 非空回答。终态在同一锁/事务中提交，取消先获锁则迟到结果不能发布。所有错误只公开分类、中文说明和任务编号，不返回异常路径或内部日志。

唯一键 (session_id, idempotency_key)，接受请求时原子保存 turn/job 身份及问题，再入队。刷新仅 GET。重启将活动任务记为 interrupted，全部旧会话只读；不自动重发。证据从已核验的四类选择及对应公开工具字段制作，按轮次持久保存。

状态目录 APP_STATE_DIR/web/{offline|live}/{period}。period 仅本地启动参数设置，当前默认 live-main、预算 4.90 元；旧 default 网络失败账本保留，不覆盖/清零旧周期，也不自动换周期。预算绑定 mode、period、limit；配置不匹配、账本缺失/损坏/锁残留时阻止执行。恢复未知预留会停止共享预算。操作系统文件锁防止同一周期多进程。

历史删除为数据库实际删除，不是隐藏或软删除；刷新、重启不会恢复。删除不会修改其他对话、共享预算账本或运行时审计日志，也不会清除未知费用。后台关闭失败时不得谎报删除成功。页面确认后执行，成功后清理当前选择、输入和证据视图；删除历史记录不会切换或清空正在查看的其他对话。

前端仅访问 /api 和自己的构建资源；Markdown 禁用 HTML、图片和非 http(s) 链接。Python 仅挂载 web/dist，不挂载 state 或 assets。服务只在 127.0.0.1 监听。

## 结果呈现与导出

### 用量与预计成本

`usage` 仅从通过 owner 校验的任务 turn_id 对应账本记录生成，不接受客户端指定任意账本或范围。字段为 mode、estimated_cny、pending_reserved_cny、request_count、settled_requests、pending_requests、input_tokens、output_tokens、cache_hit_tokens、updated_at、basis。`updated_at` 是本次读取时间，非最后一次消费时间；basis 为 `recorded_usage_local_tariff`。提交任务响应也包含此投影。

live 的 token 来自模型返回的已记录 raw_usage；费用沿用账本本地单价估算，并非服务商最终账单。没有实际用量的请求单独保留预留金额，不编造消费为零。offline 真实用量为零，模拟账本不能计入真实成本。当前对话汇总只覆盖该对话，运行期间随任务轮询刷新；终态后刷新/重开历史读取最新记录。历史删除不删除费用账本。全局账本仍仅保留在后端，没有新增管理员网页或向普通用户公开全局金额。

health.capabilities 返回五类已支持能力及准确示例；选择入口和点击示例只改变输入框，发送才创建任务。冻结预测公开字段限于 expected_qualified_count、predicted_count、missing_count、mean_p、prediction_coverage，范围为 V6 frozen_t0_replay。

每个任务 evidence 列表含源自宿主已核验选择的 fact DTO。图表只使用这些字段，不解析自由文本：兼容的 M03 rate 可绘制百分比条形图；player_count 可绘制分群规模图；规则支持度/置信度/提升度进入表格。差值使用已核验 compare_results，缺失值不补零。每行都关联本轮 opaque evidence ID，可打开同源完整证据。长原文可展开，文本不改写；无结构化事实时直接展示核验原文。

复制/Markdown 下载由前端读取当前 owner 的已完成任务公开证据组成，只导出这一轮的原文、模式、模拟数据标识、任务及证据引用。无需新增文件或任意路径下载 API。原始日志和运行配置不进入 DTO。关闭证据抽屉恢复触发按钮焦点；小屏宽表在独立容器横向滚动。
