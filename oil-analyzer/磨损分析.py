# -*- coding: utf-8 -*-
"""报告批量入口（VSCode 里直接运行本文件即可）

用法：
    1) 在 VSCode 里打开本文件，直接点运行，会提示输入数据目录（可拖文件夹路径进来）；
    2) 或在终端执行：
         python 磨损分析.py "D:\\油液数据" "D:\\输出目录" [起始 YYYY-MM-DD] [结束 YYYY-MM-DD]

数据目录可以是：
    - 一个项目文件夹（里面有 youye_#1_xxx.zip / 或者 #1、#2… 机组文件夹）；
    - 或者包含多个项目文件夹的顶层目录。

输出：每台机组一个 磨损分析_机组N_年月.xlsx（套用 templates/磨损分析模板.xlsx）
      + 机组磨损数值汇总.xlsx + 项目油品分析报告.docx
      起止日期不填时统计全部数据。
"""
import os
import sys

from oil_monitor_gui import enable_dpi_awareness, run_wear_cli


def main():
    enable_dpi_awareness()
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        src_dir = args[0].strip('"').strip("'")
        out_dir = args[1].strip('"').strip("'") if len(args) > 1 else None
        start = args[2].strip() if len(args) > 2 else None
        end = args[3].strip() if len(args) > 3 else None
    else:
        src_dir = input("数据目录（可把文件夹拖进来）：").strip().strip('"').strip("'")
        out_dir = input("输出目录（直接回车=程序目录下 reports/）：").strip().strip('"').strip("'") or None
        start = input("起始日期 YYYY-MM-DD（直接回车=全部数据）：").strip() or None
        end = input("结束日期 YYYY-MM-DD（直接回车=全部数据）：").strip() or None
    if not os.path.isdir(src_dir):
        print("目录不存在：", src_dir)
        return
    total, folder = run_wear_cli(src_dir, out_dir, start, end)
    print("报告生成完成：%d 台机组" % total)
    print("输出目录：", folder)


if __name__ == "__main__":
    main()
