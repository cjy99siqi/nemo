# -*- coding: utf-8 -*-
"""打包 VibSpec 为 Windows 可分发目录（PyInstaller，onedir）。

产物：
    发布\\VibSpec\\VibSpec.exe                主程序
    发布\\VibSpec\\数据\\...                  机型库/轴承库/模板（可直接改）
    发布\\VibSpec\\转速堆叠谱\\转速堆叠谱.exe  转速堆叠工具（主程序右键调用）
运行：
    python tools\\build_exe.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(ROOT, "发布", "VibSpec")


def run(cmd):
    print("\n>>>", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit("打包失败：%s" % " ".join(cmd))


def build_main():
    run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--onedir", "--name", "VibSpec",
        "--add-data", os.path.join("数据", "机型库.json") + ";数据",
        "--add-data", os.path.join("数据", "轴承库.json") + ";数据",
        "--add-data", os.path.join("数据", "模板") + ";数据/模板",
        "--hidden-import", "tpl_fill",
        "--hidden-import", "docx",
        "--hidden-import", "tkcalendar",
        "--hidden-import", "matplotlib.backends.backend_tkagg",
        "振动分析.py",
    ])


def build_tool():
    run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--onedir", "--name", "转速堆叠谱",
        "--add-data", "振动分析.py;.",
        "--add-data", os.path.join("数据", "机型库.json") + ";数据",
        "--add-data", os.path.join("数据", "轴承库.json") + ";数据",
        "--add-data", os.path.join("tools", "转速堆叠谱.ico") + ";.",
        "--add-data", os.path.join("tools", "转速堆叠谱.png") + ";.",
        "--hidden-import", "pandas",
        "--hidden-import", "tkcalendar",
        "--hidden-import", "scipy.signal",
        "--hidden-import", "docx",
        "--hidden-import", "matplotlib.backends.backend_tkagg",
        os.path.join("tools", "转速堆叠谱.py"),
    ])


def assemble():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    # 主程序
    src_main = os.path.join(DIST, "VibSpec")
    for name in os.listdir(src_main):
        s = os.path.join(src_main, name)
        d = os.path.join(OUT, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    # 数据（json + 模板）；xls/xlsx 运行时不读，不打包
    data_out = os.path.join(OUT, "数据")
    os.makedirs(data_out, exist_ok=True)
    for f in ("机型库.json", "轴承库.json"):
        shutil.copy2(os.path.join(ROOT, "数据", f), os.path.join(data_out, f))
    tpl_src = os.path.join(ROOT, "数据", "模板")
    if os.path.isdir(tpl_src):
        shutil.copytree(tpl_src, os.path.join(data_out, "模板"))
    os.makedirs(os.path.join(OUT, "输出"), exist_ok=True)
    # 工具
    tool_out = os.path.join(OUT, "转速堆叠谱")
    shutil.copytree(os.path.join(DIST, "转速堆叠谱"), tool_out)
    # PyInstaller 6 把 add-data 放进 _internal；工具的 _load_app 按“exe 同目录”找源码/图标，
    # 所以这里把 振动分析.py 和图标再复制一份到 exe 旁边
    shutil.copy2(os.path.join(ROOT, "振动分析.py"), tool_out)
    for _f in ("转速堆叠谱.ico", "转速堆叠谱.png"):
        shutil.copy2(os.path.join(ROOT, "tools", _f), tool_out)
    tool_data = os.path.join(tool_out, "数据")
    os.makedirs(tool_data, exist_ok=True)
    for f in ("机型库.json", "轴承库.json"):
        shutil.copy2(os.path.join(ROOT, "数据", f), os.path.join(tool_data, f))
    # 说明
    with open(os.path.join(OUT, "使用说明.txt"), "w", encoding="utf-8") as fh:
        fh.write("VibSpec 使用说明\n"
                 "1. 双击 VibSpec.exe 启动；首次打开会让你选项目目录。\n"
                 "2. 机型/轴承参数在 数据\\机型库.json、数据\\轴承库.json，可直接改。\n"
                 "3. 报告模板在 数据\\模板\\，换模板直接替换 docx 文件。\n"
                 "4. 转速堆叠谱由主程序趋势图右键“查看转速堆叠谱…”自动调用，\n"
                 "   也可以直接双击 转速堆叠谱\\转速堆叠谱.exe 独立运行。\n"
                 "5. 输出文件在 输出\\ 目录。\n"
                 "6. 不要删除 _internal 目录，否则程序无法启动。\n")


def main():
    print("root:", ROOT)
    build_main()
    build_tool()
    assemble()
    print("\n完成：", OUT)


if __name__ == "__main__":
    main()
