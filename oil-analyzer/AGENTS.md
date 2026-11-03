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
```

## 硬性约定
1. **编码**：源码/README/bat 都是 **UTF-8 无 BOM**。用 PowerShell 读文件要显式 `-Encoding UTF8`，否则中文变乱码。
2. **不要用 UTF-8 重存 `.bat`**：cmd 按 936 代码页解析，重存会导致启动失败（本项目 bat 带 `chcp 65001`，改动需实测）。
3. **报告台数**走 `templates/<项目>_报告配置.json` 的 `unit_count`，无配置才回落到历史规则（营盘梁/岱海=75）。改台数不要改代码。
4. **改计算口径必须同步改版本号**：`PARSE_VERSION` 变化会触发全量重解析；`DB_SCHEMA_VERSION` 只管表结构。
5. **两套限值并存**：界面用 `PARAMS`（ppm/级），Word 报告用 `REPORT_LIMITS`（mg/kg）。改限值必须两处一起改，否则会出现"界面正常、报告预警"。
6. 运行产物（`oil_cache.db`、`gui_state.json`、`reports/`）不进仓库。
7. 提交前跑一遍 `python tests\test_report_config.py`。

## 改代码时优先看
`项目说明.md §3 代码结构地图`（GUI 三大区、解析、缓存、报告链路）与 `§6 已知坑`（时间段过滤静默丢行、Excel 合并单元格锚点、公式不算值等）。
