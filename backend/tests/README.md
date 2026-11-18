# 归档与冷热分层测试

`test_archive.py` 对真实运行栈（PostgreSQL + Redis + API + worker）做端到端验证，
不使用 mock。每个用例前 `reset_data()` 重建 600 行账单夹具并清空归档/批次表，
因此可重复、可乱序执行。

## 运行前提

先启动 db、redis、API；测试会自行拉起和销毁 worker 子进程
（崩溃恢复用例需要控制 worker 生命周期）。

```bash
pip install -r requirements-dev.txt
# 已按 docker-compose 或本地方式启动 API（默认 http://127.0.0.1:19240）
# 先停掉常驻 worker，避免与测试自管 worker 抢队列
export DATABASE_URL=... REDIS_URL=... JWT_SECRET=... ARTIFACTS_DIR=/tmp/artifacts
pytest tests/test_archive.py -v
```

## 覆盖的关键场景

| 用例 | 验证点 |
|---|---|
| full_dataset_read_unchanged | 归档前后视图总量、总金额不变，原 SQL 读冷热全量 |
| pending_invoice_stays_hot | 搬运瞬间恢复待结算的账单 skipped 并留在热库 |
| concurrent_amount_update | 版本乐观锁：旧版本 409、新版本成功，不丢更新 |
| edit_during_archive | 搬运过程中改账，更新不丢、无重复无丢失 |
| worker_restart_mid_archive | 杀掉 worker 后续跑，不重复搬账、不漏账、留痕无重复 |
| overlapping_archive_ranges | 两次范围重叠，已在冷库的账单不二次搬运 |
| reader_role_and_limits | viewer 只读 403、分页上限 200、operator 不可归档 |
| invoice_create_and_limited_queries | 新增入热库、重号 409、受限查询 |
| failed_job_retry_is_idempotent | 注入失败后断点重试，无重复、无丢失 |
