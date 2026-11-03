# VibSpec（风电机组振动分析）

tkinter 单文件桌面程序：批量读采集器 CSV，算特征指标入库做趋势，谱图上标轴承/齿轮特征频率，套 Word 模板出月度报告。
**动手前先读 `项目说明.md`**（架构地图 + 真实函数名/行号 + 12 条已知坑）。

## 关键路径
- 主程序：`振动分析.py`（约 8248 行，UTF-8 无 BOM；`SpectrumWindow` 一个类 3400+ 行）
- 模板填充：`tpl_fill.py`（410 行）
- 轴承库：内置 `BEARING_LIB`，**外部覆盖用 `数据\轴承库.json`**（模板见 `数据\轴承库.example.json`）
- 交接文档：`项目说明.md`；测试：`tests/`

## 常用命令
```powershell
pip install -r requirements.txt
python 振动分析.py                       # 带控制台，便于看 traceback
python tests\test_bearing_lib.py         # 轴承库加载（14 项断言）
python tests\test_bearing_dialog.py      # 轴承对话框（需图形环境）
```

## 硬性约定
1. **`启动振动分析.bat` 是 GBK 编码**（58 字节）。用 UTF-8 另存会让 cmd 找不到脚本、双击闪退。改它必须存成 GBK/ANSI。
2. 源码统一 **UTF-8 无 BOM**；读写 JSON 一律显式 `encoding="utf-8-sig"`（容忍 BOM）。
3. **改倍数不要改代码**：优先 `数据\轴承库.json`（同名整体覆盖、新名追加）；临时改动用界面「自定义倍数」（齿轮/轴承两个对话框都有）。
4. **改计算口径必须 bump `VDI_VERSION`**，否则旧 SQLite 缓存照旧、新算法不生效；改表结构才动 `DB_SCHEMA_VERSION`。
5. **滤波必须走 `design_band`（真实 fs/2）**，不要把 `fs/2.56` 当 Nyquist。
6. `数据\` 里的 xlsx/xls 是机组参数资料，**运行时不读**，别以为改了会生效。
7. 单文件 8000+ 行、短变量名（`v_*`、`_r`、`_p`）在多个闭包里重复，改前全文搜索。

## 改代码时优先看
`项目说明.md §3 代码结构地图`（解析/指标/谱图/轴承/齿轮/GUI/报告）与 `§6 已知坑`（`fs/2.56`、`VDI_VERSION`、中文字体、死代码 `export_excel`/`build_report_docx`）。
