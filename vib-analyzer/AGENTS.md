# VibSpec（风电机组振动分析）

tkinter 单文件桌面程序：批量读采集器 CSV，算特征指标入库做趋势，谱图上标轴承/齿轮特征频率，套 Word 模板出月度报告。
**动手前先读 `项目说明.md`**（架构地图 + 真实函数名/行号 + 12 条已知坑）。

## 关键路径
- 主程序：`振动分析.py`（约 8248 行，UTF-8 无 BOM；`SpectrumWindow` 一个类 3400+ 行）
- 模板填充：`tpl_fill.py`（410 行）
- **机型/轴承数据全外置**：`数据\机型库.json`（各项目自己的齿轮比、齿数、测点→轴承）+ `数据\轴承库.json`（132 条轴承倍数）。代码里 `BEARING_LIB` 是空壳，没有任何内置机型数字
- 数据生成：`tools\build_libs.py`（读现场 xls，重建上面两个 JSON；`--dry-run` 只看统计）
- 齿轮判读规则：`齿轮啮合图谱经验.md`（18 个现场案例 → 边带间隔定位 / 严重度 / 行星级规则）
- 交接文档：`项目说明.md`；测试：`tests/`

## 常用命令
```powershell
pip install -r requirements.txt
python 振动分析.py                       # 带控制台，便于看 traceback
python tools\build_libs.py --dry-run     # 重新生成前的统计
python tests\test_machine_lib.py         # 机型库 + 各项目齿轮比（42 项断言）
python tests\test_csv_read.py            # CSV 格式容错：单列/多列/时间轴/非数值（8 项断言）
python tests\test_gear_sideband.py       # 齿轮边带识别、判读卡、故障模式（29 项断言）
python tests\test_time_cursor.py         # 时域时间游标：A/B、方向键、Δt/1÷Δt、1T…5T（28 项断言）
python tests\test_zoom_out.py            # 「缩小」逐级生效，不是一次回全图（11 项断言）
python tests\test_clear_cache.py         # 清空缓存：按项目+年月日选择性删除（11 项断言）
python tests\test_zip_scan.py            # 压缩包扫描：正常/截断可救/全坏/认不出测点（6 项断言）
python tests\test_tree_missing_points.py # 树形图：无数据测点灰字占位、机型名不同名不占位（14 项断言）
python tests\test_abnormal_filter.py     # 量级异常（传感器饱和）拒收 + 清理条件（6 项断言）
python tests\test_peak_labels.py         # 峰值标注：频率 1 位小数（4 项断言）
python tests\test_marks_per_plot.py      # 标注显隐按谱图独立（8 项断言）
python tests\test_autocorr_label.py      # 自相关标频：谱峰定支 + 多周期细化（7 项断言）
python tests\test_dirs_dedupe.py         # 项目目录父子去重 + 行去重（10 项断言）
python tests\test_reject_cache.py        # 被拒收文件缓存，不重复计算（10 项断言）
python tests\test_fault_persistence.py   # 报告判读：阈值标定 + 复现才算警告（11 项断言）
python tests\test_fault_exclusions.py    # 判读交叉排除：转频/啮合重合、弱证据（20 项断言）
python tests\test_golden_cases.py        # 齿轮经验文档案例的黄金回归（19 项断言）
python tests\test_rms_box.py             # 谱图左上角通频/基频 RMS 框（13 项断言）
python tests\test_refine_smooth.py       # 框选细化用 blit，拖拽不整图重绘（6 项断言）
python tests\test_review_table.py        # 判读复核表导出（18 项断言）
python tests\test_report_appendix.py     # ≥3 个月报告自动附复核表附录（18 项断言）
python tests\test_single_window.py       # 主程序单实例 + 图谱分析单窗口（12 项断言）
python tests\test_time_period_source.py  # 时域 1T…5T 周期来源 + 起点选周期段（13 项断言）
python tests\test_freq_diff.py           # 频差 A/B 吸附与 Δf（11 项断言）
python tests\test_annot_reset.py         # 换数据不带上一份基频/标线（7 项断言）
python tests\test_bearing_import.py      # 轴承库校验（含对原表反算 420 个频率）
python tests\test_bearing_family.py      # 轴承阶次谐波族匹配（11 项断言）
python tests\test_bearing_lib.py         # 轴承库加载容错（14 项断言）
python tests\test_bearing_dialog.py      # 轴承对话框（需图形环境）
```

## 硬性约定
1. **`启动振动分析.bat` 是 GBK 编码**（58 字节）。用 UTF-8 另存会让 cmd 找不到脚本、双击闪退。改它必须存成 GBK/ANSI。
2. 源码统一 **UTF-8 无 BOM**；读写 JSON 一律显式 `encoding="utf-8-sig"`（容忍 BOM）。
3. **改倍数/齿轮比不要改代码**：改 `数据\轴承库.json`、`数据\机型库.json`，或重跑 `tools\build_libs.py`；临时改动用界面「自定义倍数」和「机型」下拉。
4. **任何机型数字都不许写进代码**：齿轮比、齿数、测点→轴承映射、项目名关键字一律进 `数据\机型库.json`。新增项目＝在那里面加一条（`projects` 写项目名关键字）。
5. **改计算口径必须 bump `VDI_VERSION`**，否则旧 SQLite 缓存照旧、新算法不生效；改表结构才动 `DB_SCHEMA_VERSION`。
6. **滤波必须走 `design_band`（真实 fs/2）**，不要把 `fs/2.56` 当 Nyquist。
7. `数据\` 里的 xlsx/xls **运行时不读**，只有 `tools\build_libs.py` 生成 JSON 时读一次；改了表要重跑工具才生效。
8. 单文件 8000+ 行、短变量名（`v_*`、`_r`、`_p`）在多个闭包里重复，改前全文搜索。

## 改代码时优先看
`项目说明.md §3 代码结构地图`（解析/指标/谱图/轴承/齿轮/GUI/报告）与 `§6 已知坑`（`fs/2.56`、`VDI_VERSION`、中文字体、`logs/vib_error.log`）。
