# OilLab（油液监测报告工具）

tkinter 单文件桌面程序，用于油液监测数据的批量入库、趋势查看与月度 Word 报告生成。
**动手前先读 `项目说明.md`**（架构地图 + 真实函数名/行号 + 18 条已知坑）。

## 关键路径
- 主程序：`oil_monitor_gui.py`（约 5042 行，UTF-8 无 BOM）
- 独立脚本：`磨损分析.py`
- 模板与配置：`templates/`（`*_报告配置.json` 现在会被读取）
- 交接文档：`项目说明.md`；测试：`tests/`

## 常用命令
```powershell
pip install -r requirements.txt
python oil_monitor_gui.py            # 带控制台，便于看 traceback
python tests\test_report_config.py   # 报告配置/台数逻辑
python tests\test_wear_limits.py     # 磨粒阈值口径
python tests\test_params_limits.py   # 磨粒参数与 PARAMS 限值
python tests\test_time_parse.py      # 时间解析（不补零/中文格式）
python tests\test_wear_records.py    # 磨粒 b7/g7 入库
```

## 硬性约定
1. **编码**：源码/README/bat 都是 **UTF-8 无 BOM**。用 PowerShell 读文件要显式 `-Encoding UTF8`，否则中文变乱码。
2. **不要用 UTF-8 重存 `.bat`**：cmd 按 936 代码页解析，重存会导致启动失败（本项目 bat 带 `chcp 65001`，改动需实测）。
3. **报告台数**走 `templates/<项目>_报告配置.json` 的 `unit_count`，无配置才回落到历史规则（营盘梁/岱海=75）。改台数不要改代码。
4. **改计算口径必须同步改版本号**：`PARSE_VERSION` 变化会触发全量重解析；`DB_SCHEMA_VERSION` 只管表结构。
5. **限值分两类，别混**：`PARAMS`（:232 起）是元素/理化指标（Fe 是 ppm，限值 84/120）；`REPORT_LIMITS`（:222，已上移到参数注册之前）是磨粒浓度 mg/kg（铁磁 20/25、非铁磁 15/20）。三处共用它：报告表格 `_judge_max`、磨损结论 `wear_verdict()`、界面参数 `wear_ferrous`/`wear_nonferrous`——改阈值只改 `REPORT_LIMITS` 一处。
6. **时间解析统一走 `parse_datetime_text`**：`_wear_time` 只是它的别名，不要另写副本。解析失败计入 `PARSE_STATS["unparsed"]`（扫描结束显示在状态栏）；`analyze_wear` 的 `days_estimated=True` 表示用了 28 天兜底，浓度口径是估算值。
7. **磨粒记录在扫描时入库**：`Scanner.run` 对磨损 CSV 追加 `wear_records()` 产出的 `wear_ferrous`/`wear_nonferrous` 两条记录，数值与报告同源。当前 `PARSE_VERSION = 9`——改动这条链路时要继续 +1，否则老库不会重算。
8. 运行产物（`oil_cache.db`、`gui_state.json`、`reports/`）不进仓库。
9. 提交前跑 `tests\` 下五个测试：`test_report_config.py`、`test_wear_limits.py`、`test_params_limits.py`、`test_time_parse.py`、`test_wear_records.py`。

## 改代码时优先看
`项目说明.md §3 代码结构地图`（GUI 三大区、解析、缓存、报告链路）与 `§6 已知坑`（时间段过滤静默丢行、Excel 合并单元格锚点、公式不算值等）。
