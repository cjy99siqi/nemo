# -*- coding: utf-8 -*-
"""油液监测报告工具 (OilLab)

单文件 tkinter 桌面程序，代码结构与 vib_analyzer 对齐：
    常量（APP_DIR / STATE_FILE / DB_FILE）→ 规则表 → 文件名解析 → SQLite 缓存
    → 扫描线程 → 主界面（左侧 项目/文件夹/压缩包树 + 右侧 明细表 + 趋势图）→ 报告导出

依赖：openpyxl、python-docx、matplotlib（均为可选降级：缺 matplotlib 只影响趋势图，
缺 python-docx 只影响 Word 报告）。
"""
import os
import sys
import io
import re
import csv
import json
import math
import hashlib
import sqlite3
import threading
import queue
import traceback
import zipfile
import shutil
import datetime as dt
from datetime import datetime, date

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# 路径与常量（打包后以 exe 所在目录为准）
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = os.path.join(APP_DIR, "gui_state.json")
DB_FILE = os.path.join(APP_DIR, "oil_cache.db")
DB_SCHEMA_VERSION = 3
PARSE_VERSION = 8          # 解析规则版本：升级后首次启动自动全量重解析，避免沿用旧缓存

# 宾泉项目历史磨损浓度（内嵌，随程序走，不依赖外部 Excel）
BINQUAN_HISTORY = {
    "1#": [("2026.1", 0.10, 0.50), ("2026.2", 0.05, 0.19), ("2026.3", 0.26, 0.23), ("2026.4", 0.69, 0.33), ("2026.5", 0.76, 0.32), ("2026.6", 0.68, 0.35), ("2026.7", 0.69, 0.34), ("2026.8", 0.03, 0.20), ("2026.9", 0.01, 0.05)],
    "2#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 1.45, 0.05), ("2026.5", 3.20, 0.02), ("2026.6", 2.84, 0.02), ("2026.7", 1.55, 0.04), ("2026.8", 1.49, 0.03), ("2026.9", 0.96, 0.09)],
    "3#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "4#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "5#": [("2026.1", 1.90, 0.03), ("2026.2", 2.02, 0.02), ("2026.3", 1.87, 0.01), ("2026.4", 1.84, 0.01), ("2026.5", 1.74, 0.01), ("2026.6", 1.97, 0.02), ("2026.7", 1.71, 0.06), ("2026.8", 1.85, 0.49), ("2026.9", 1.51, 0.01)],
    "6#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "7#": [("2026.1", 0.03, 0.05), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "8#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "9#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 1.88, 0.66), ("2026.4", 2.96, 1.16), ("2026.5", 3.05, 1.07), ("2026.6", 3.13, 1.20), ("2026.7", 1.39, 0.76), ("2026.8", 2.91, 0.77), ("2026.9", 1.15, 0.36)],
    "10#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.02), ("2026.3", 0.03, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "11#": [("2026.1", 0.04, 0.01), ("2026.2", 0.04, 0.01), ("2026.3", 0.05, 0.01), ("2026.4", 0.08, 0.01), ("2026.5", 0.11, 0.03), ("2026.6", 0.11, 0.01), ("2026.7", 0.02, 0.01), ("2026.8", 0.02, 0.01), ("2026.9", 0.01, 0.01)],
    "12#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "13#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.04, 0.08), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "14#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.02), ("2026.5", 0.01, 0.03), ("2026.6", 0.01, 0.06), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.02)],
    "15#": [("2026.1", 0.01, 0.01), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "16#": [("2026.1", 3.52, 0.71), ("2026.2", 2.95, 0.99), ("2026.3", 2.59, 1.20), ("2026.4", 4.51, 1.42), ("2026.5", 4.59, 0.91), ("2026.6", 4.55, 0.65), ("2026.7", 3.50, 0.42), ("2026.8", 2.69, 0.32), ("2026.9", 4.32, 0.34)],
    "17#": [("2026.1", 0.02, 0.04), ("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.7", 0.01, 0.01), ("2026.8", 0.01, 0.01), ("2026.9", 0.01, 0.01)],
    "18#": [("2026.1", 0.17, 0.17), ("2026.2", 0.23, 0.20), ("2026.3", 0.39, 0.01), ("2026.4", 0.69, 0.33), ("2026.5", 0.10, 0.41), ("2026.6", 0.14, 0.07), ("2026.7", 0.11, 0.11), ("2026.8", 0.04, 0.04), ("2026.9", 0.01, 0.01)],
}

ZIP_CACHE_DIR = os.path.join(APP_DIR, "zip_cache")
REPORT_DIR = os.path.join(APP_DIR, "reports")
THRESHOLD_FILE = os.path.join(APP_DIR, "thresholds.json")

UI_FONT = "Microsoft YaHei UI"
COLOR_BG = "#f4f7fb"
# 岱海一标营盘梁项目历史磨损浓度（内嵌）
YINGPAN_HISTORY = {
    "1#": [("2026.2", 0.11, 0.26), ("2026.3", 0.13, 0.33), ("2026.4", 0.01, 0.01), ("2026.5", 0.04, 0.07), ("2026.6", 0.03, 0.04), ("2026.8", 0.00, 0.00)],
    "2#": [("2026.2", 0.01, 0.01), ("2026.3", 2.75, 1.37), ("2026.4", 0.17, 0.36), ("2026.5", 0.02, 0.01), ("2026.6", 0.01, 0.00)],
    "3#": [("2026.2", 0.02, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.02, 0.01), ("2026.6", 0.01, 0.00)],
    "4#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.02, 0.00), ("2026.8", 0.00, 0.00)],
    "5#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "6#": [("2026.2", 0.04, 0.07), ("2026.3", 0.03, 0.04), ("2026.4", 2.86, 1.08), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00)],
    "7#": [("2026.2", 0.27, 0.02), ("2026.3", 0.15, 0.02), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.03, 0.00), ("2026.8", 0.00, 0.00)],
    "8#": [("2026.2", 0.04, 0.06), ("2026.3", 0.04, 0.05), ("2026.4", 0.09, 0.04), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "9#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.34, 0.42), ("2026.5", 0.04, 0.12), ("2026.6", 0.02, 0.05)],
    "10#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.02, 0.07), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "11#": [("2026.2", 0.72, 2.05), ("2026.3", 0.39, 1.10), ("2026.4", 0.01, 0.01), ("2026.5", 0.55, 1.14), ("2026.6", 0.15, 0.29), ("2026.8", 0.00, 0.00)],
    "12#": [("2026.2", 0.38, 0.01), ("2026.3", 0.20, 0.01), ("2026.4", 2.23, 3.76), ("2026.5", 0.10, 0.09), ("2026.6", 0.05, 0.02), ("2026.8", 0.00, 0.00)],
    "14#": [("2026.2", 0.06, 0.09), ("2026.3", 0.06, 0.25), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.01), ("2026.8", 0.00, 0.00)],
    "16#": [("2026.2", 0.04, 0.10), ("2026.3", 0.04, 0.12), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "17#": [("2026.2", 0.01, 0.03), ("2026.3", 0.55, 0.95), ("2026.4", 0.02, 0.08), ("2026.5", 0.02, 0.02), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "18#": [("2026.3", 0.04, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.08, 0.01), ("2026.6", 0.04, 0.00), ("2026.8", 0.00, 0.00)],
    "19#": [("2026.2", 0.02, 0.01), ("2026.3", 0.02, 0.01), ("2026.4", 0.16, 0.25), ("2026.5", 0.03, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "20#": [("2026.3", 0.05, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.08, 0.01), ("2026.6", 0.06, 0.01), ("2026.8", 0.00, 0.00)],
    "21#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.02, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "22#": [("2026.2", 0.02, 0.05), ("2026.3", 0.02, 0.08), ("2026.4", 0.01, 0.03), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "23#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.02), ("2026.8", 0.00, 0.00)],
    "24#": [("2026.2", 0.08, 0.06), ("2026.3", 0.12, 0.10), ("2026.4", 0.01, 0.01), ("2026.5", 0.10, 0.08), ("2026.6", 0.03, 0.03), ("2026.8", 0.00, 0.00)],
    "25#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "26#": [("2026.2", 8.48, 5.40), ("2026.3", 6.92, 8.59), ("2026.4", 0.01, 0.01), ("2026.5", 5.48, 10.50), ("2026.6", 1.67, 3.19), ("2026.8", 0.00, 0.00)],
    "27#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "28#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.29, 0.07), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "29#": [("2026.2", 0.91, 1.23), ("2026.3", 1.35, 1.84), ("2026.4", 0.01, 0.01), ("2026.5", 0.35, 0.43), ("2026.6", 0.07, 0.09), ("2026.8", 0.00, 0.00)],
    "30#": [("2026.2", 0.01, 0.01), ("2026.3", 0.02, 0.01), ("2026.4", 0.02, 0.02), ("2026.5", 0.56, 0.70), ("2026.6", 0.27, 0.34), ("2026.8", 0.00, 0.00)],
    "31#": [("2026.2", 0.10, 0.14), ("2026.3", 0.27, 0.43), ("2026.4", 0.01, 0.01), ("2026.5", 0.03, 0.01), ("2026.6", 3.16, 3.61), ("2026.8", 0.00, 0.00)],
    "32#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "33#": [("2026.2", 0.07, 0.04), ("2026.3", 0.14, 0.13), ("2026.4", 1.32, 0.09), ("2026.5", 0.06, 0.02), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "34#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00)],
    "35#": [("2026.2", 0.01, 0.01), ("2026.3", 0.02, 0.01), ("2026.4", 5.77, 2.20), ("2026.5", 0.02, 0.04), ("2026.6", 0.01, 0.02), ("2026.8", 0.00, 0.00)],
    "36#": [("2026.3", 0.02, 0.01), ("2026.4", 0.03, 0.01), ("2026.5", 0.07, 0.06), ("2026.6", 0.04, 0.03), ("2026.8", 0.00, 0.00)],
    "37#": [("2026.2", 3.55, 2.48), ("2026.3", 4.00, 3.33), ("2026.4", 0.01, 0.01), ("2026.5", 3.26, 3.53), ("2026.6", 0.84, 0.95), ("2026.8", 0.00, 0.00)],
    "38#": [("2026.2", 0.04, 0.01), ("2026.3", 0.04, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.09, 0.19), ("2026.6", 0.03, 0.08), ("2026.8", 0.00, 0.00)],
    "39#": [("2026.2", 0.01, 0.02), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "40#": [("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.01), ("2026.8", 0.00, 0.00)],
    "41#": [("2026.2", 2.35, 0.02), ("2026.3", 0.89, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 3.13, 0.01), ("2026.6", 0.11, 0.02), ("2026.8", 0.00, 0.00)],
    "42#": [("2026.2", 2.71, 0.67), ("2026.3", 4.43, 1.59), ("2026.4", 0.16, 0.01), ("2026.5", 2.10, 0.14), ("2026.6", 0.61, 0.07)],
    "43#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "44#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "45#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "46#": [("2026.2", 0.01, 0.05), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "47#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.15), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "48#": [("2026.2", 0.01, 0.04), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "49#": [("2026.2", 0.05, 0.28), ("2026.3", 0.05, 0.34), ("2026.4", 0.01, 0.01), ("2026.5", 0.02, 0.05), ("2026.6", 0.01, 0.01), ("2026.8", 0.00, 0.00)],
    "50#": [("2026.2", 0.01, 0.02), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.02, 0.04), ("2026.6", 0.01, 0.01), ("2026.8", 0.00, 0.00)],
    "51#": [("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "52#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.39, 0.62), ("2026.8", 0.00, 0.00)],
    "54#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.05, 0.01), ("2026.6", 0.02, 0.00), ("2026.8", 0.00, 0.00)],
    "55#": [("2026.2", 2.37, 0.05), ("2026.3", 2.54, 0.03), ("2026.4", 0.28, 0.31), ("2026.5", 5.56, 0.01), ("2026.6", 2.28, 0.00), ("2026.8", 0.00, 0.00)],
    "56#": [("2026.2", 0.10, 0.02), ("2026.3", 0.03, 0.08), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "57#": [("2026.2", 0.02, 0.04), ("2026.3", 0.02, 0.05), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "58#": [("2026.2", 0.01, 0.04), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "59#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.20, 0.74), ("2026.5", 0.01, 0.02), ("2026.6", 0.00, 0.00)],
    "60#": [("2026.2", 0.32, 0.51), ("2026.3", 0.42, 0.65), ("2026.4", 0.28, 0.03), ("2026.5", 0.05, 0.01), ("2026.6", 0.02, 0.00), ("2026.8", 0.00, 0.00)],
    "61#": [("2026.2", 0.36, 0.53), ("2026.3", 0.15, 0.23), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "62#": [("2026.2", 0.19, 0.23), ("2026.3", 0.35, 0.53), ("2026.4", 0.01, 0.01), ("2026.5", 0.09, 0.11), ("2026.6", 0.02, 0.03), ("2026.8", 0.00, 0.00)],
    "63#": [("2026.2", 0.04, 0.01), ("2026.3", 0.06, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.51, 0.67), ("2026.6", 0.18, 0.24), ("2026.8", 0.00, 0.00)],
    "64#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "65#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.72, 0.78), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "66#": [("2026.2", 0.08, 0.01), ("2026.3", 0.07, 0.01), ("2026.4", 0.04, 0.02), ("2026.5", 0.02, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "67#": [("2026.2", 0.02, 0.01), ("2026.3", 0.02, 0.01), ("2026.4", 0.01, 0.01), ("2026.5", 0.05, 0.01), ("2026.6", 0.03, 0.00), ("2026.8", 0.00, 0.00)],
    "68#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.20, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "69#": [("2026.2", 0.04, 0.04), ("2026.3", 0.08, 0.20), ("2026.4", 0.01, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "70#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.13, 0.01), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00)],
    "71#": [("2026.2", 0.02, 0.01), ("2026.3", 0.06, 0.01), ("2026.4", 0.08, 0.03), ("2026.5", 0.12, 0.01), ("2026.6", 0.03, 0.00), ("2026.8", 0.00, 0.00)],
    "72#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.21, 0.15), ("2026.5", 0.01, 0.01), ("2026.6", 0.00, 0.00), ("2026.8", 0.00, 0.00)],
    "73#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 0.09, 0.15), ("2026.5", 0.01, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
    "74#": [("2026.2", 0.01, 0.01), ("2026.3", 0.01, 0.01), ("2026.4", 2.57, 0.01), ("2026.5", 0.02, 0.02), ("2026.6", 0.01, 0.01)],
    "75#": [("2026.2", 0.11, 0.11), ("2026.3", 0.11, 0.08), ("2026.4", 0.01, 0.01), ("2026.5", 0.02, 0.01), ("2026.6", 0.01, 0.00), ("2026.8", 0.00, 0.00)],
}

COLOR_HEAD = "#1f3a5f"
COLOR_ACCENT = "#2f6ea5"
COLOR_LINE = "#dde5ef"
COLOR_MUTED = "#6b7a8c"
COLOR_ALERT = "#c00000"
COLOR_WARN = "#b26b00"
COLOR_OK = "#1e7145"

EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".csv"}
MAX_PREVIEW_ROWS = 3000
MAX_ZIP_DEPTH = 4

# ---------------------------------------------------------------------------
# 参数规则表：组 / 键 / 中文名 / 单位 / 别名 / 方向 / 关注值 / 异常值
# ---------------------------------------------------------------------------
GROUP_NAMES = {
    "wear": "磨损元素",
    "clean": "清洁度",
    "water": "水分",
    "acid": "酸值",
    "base": "碱值",
    "vis": "粘度",
    "other": "其他",
}

PARAMS = {}
_ALIAS_INDEX = {}


def _add_param(key, name, group, unit="", aliases=(), direction=None, warn=None, alert=None):
    PARAMS[key] = {
        "key": key, "name": name, "group": group, "unit": unit,
        "aliases": tuple(aliases), "direction": direction, "warn": warn, "alert": alert,
    }


def _norm(text):
    """表头归一化：全角转半角、去空白、统一符号。"""
    if text is None:
        return ""
    s = str(text).strip().lower()
    table = str.maketrans({"（": "(", "）": ")", "：": ":", "℃": "°c", "μ": "u", "µ": "u",
                           "³": "3", "²": "2", "　": "", " ": "", "\t": ""})
    s = s.translate(table)
    return s


def _variants(header):
    """把一个表头拆成若干可比较的候选写法。"""
    n = _norm(header)
    if not n:
        return []
    out = [n, n.replace("(", "").replace(")", ""), re.sub(r"\([^)]*\)", "", n)]
    for v in list(out):
        for suffix in ("含量", "浓度", "元素含量", "元素", "数值", "结果", "值"):
            if v.endswith(suffix) and len(v) > len(suffix):
                out.append(v[:-len(suffix)])
    for _ in range(3):
        for v in list(out):
            nv = re.sub(r"(ppm|mg/kg|mgkoh/g|mm2/s|cst|mg/l|ug/g|%|级|个/ml|°c|g/cm3)$", "", v)
            if nv and nv != v:
                out.append(nv)
    for v in list(out):
        for prefix in ("检测", "分析", "化验", "测量", "测试"):
            if v.startswith(prefix) and len(v) > len(prefix):
                out.append(v[len(prefix):])
    seen, res = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            res.append(v)
    return res


_WEAR = [
    ("Fe", "铁", 120), ("Cu", "铜", 30), ("Al", "铝", 25), ("Cr", "铬", 10),
    ("Pb", "铅", 15), ("Sn", "锡", 12), ("Si", "硅", 25), ("Na", "钠", 20),
    ("K", "钾", 15), ("Ni", "镍", 10), ("Ti", "钛", 10), ("Ag", "银", 5),
    ("V", "钒", 5), ("Cd", "镉", 2), ("Sb", "锑", 5), ("Mn", "锰", 12),
    ("Ca", "钙", None), ("Mg", "镁", None), ("Zn", "锌", None), ("P", "磷", None),
    ("Mo", "钼", None), ("B", "硼", None), ("Ba", "钡", None),
]

for _sym, _cn, _lim in _WEAR:
    _add_param(
        "wear_%s" % _sym, "%s(%s)" % (_cn, _sym), "wear", "ppm",
        (_sym, _cn, "%s含量" % _cn, "%s含量" % _sym),
        "max" if _lim else None,
        round(_lim * 0.7, 2) if _lim else None,
        float(_lim) if _lim else None,
    )

_add_param("clean_nas", "清洁度 NAS", "clean", "级",
           ("nas", "nas等级", "nas1638", "清洁度nas", "清洁度等级"), "max", 10, 11)
_add_param("clean_iso", "清洁度 ISO 4406", "clean", "级",
           ("iso", "iso4406", "iso4406等级", "清洁度iso", "清洁度代码"), "max", 17, 19)
_add_param("clean_pq", "PQ 指数", "clean", "",
           ("pq", "pq值", "pq指数", "铁磁性颗粒指数"), "max", 100, 200)
_add_param("clean_particles", "颗粒计数", "clean", "个/mL",
           ("颗粒", "颗粒数", "颗粒计数", "颗粒物", "计数"), "max", 200000, 500000)

_add_param("water_pct", "水分", "water", "%",
           ("水分", "含水率", "水含量", "含水量", "水分含量"), "max", 0.1, 0.2)
_add_param("water_ppm", "水分(ppm)", "water", "ppm",
           ("水分ppm", "含水ppm", "微量水分", "水ppm"), "max", 300, 500)
_add_param("water_aw", "水分 AW", "water", "",
           ("水分aw", "湿度aw", "aw", "水活度", "水分活度"), "max", 80, 90)

_add_param("acid_tan", "酸值 TAN", "acid", "mgKOH/g",
           ("酸值", "总酸值", "总酸", "tan", "酸值tan", "中和值"), "max", 1.5, 2.0)
_add_param("acid_delta", "酸值变化量", "acid", "mgKOH/g",
           ("酸值变化", "酸值增量", "δtan"), "max", 0.5, 1.0)
_add_param("base_tbn", "碱值 TBN", "base", "mgKOH/g",
           ("碱值", "总碱值", "总碱", "tbn", "碱值tbn"), "min", 3.0, 1.5)

_add_param("vis_40", "运动粘度(40℃)", "vis", "mm²/s",
           ("粘度", "黏度", "运动粘度", "运动黏度", "v40", "kv40", "粘度40", "40℃粘度"))
_add_param("vis_100", "运动粘度(100℃)", "vis", "mm²/s",
           ("粘度100", "v100", "kv100", "100℃粘度"))
_add_param("vis_index", "粘度指数", "vis", "",
           ("粘度指数", "黏度指数", "vi", "vi值"), "min", 90, 80)

_add_param("flash_point", "闪点", "other", "℃",
           ("闪点", "开口闪点", "闭口闪点"), "min", 180, 160)
_add_param("pour_point", "倾点", "other", "℃", ("倾点", "凝点"))
_add_param("color", "色度", "other", "", ("色度", "颜色", "色号"))
_add_param("density", "密度", "other", "g/cm³", ("密度",))
_add_param("foam", "泡沫特性", "other", "mL", ("泡沫", "泡沫特性", "抗泡"))
_add_param("demuls", "抗乳化性", "other", "min", ("抗乳化", "破乳化", "乳化时间", "分水时间"))
_add_param("oxidation", "氧化值", "other", "", ("氧化", "氧化值"))
_add_param("nitration", "硝化值", "other", "", ("硝化",))

for _p in PARAMS.values():
    for _a in _p["aliases"]:
        _ALIAS_INDEX.setdefault(_norm(_a), _p["key"])

META_KEYS = {
    "device": ("设备名称", "设备", "机组", "设备编号", "机器名称", "装置", "设备名", "unit", "machine"),
    "point": ("取样点", "取样部位", "取样位置", "润滑点", "部位", "测点"),
    "oil": ("油品", "油品牌号", "润滑油牌号", "牌号", "油种", "油品名称", "用油", "grade"),
    "date": ("取样日期", "采样日期", "取样时间", "采样时间", "检测日期", "日期", "date"),
    "sample_no": ("样品编号", "样品号", "样号", "报告编号", "编号"),
}
META_LABEL = {"device": "设备", "point": "取样点", "oil": "油品", "date": "取样日期",
              "sample_no": "样品编号"}


def identify_param(header):
    """表头 → 参数键；识别不了返回 None。"""
    for v in _variants(header):
        hit = _ALIAS_INDEX.get(v)
        if hit:
            return hit
    n = _norm(header)
    if not n:
        return None
    if any(k in n for k in ("清洁度", "颗粒计数", "污染度")):
        if "nas" in n:
            return "clean_nas"
        if "iso" in n or "4406" in n:
            return "clean_iso"
        if "pq" in n:
            return "clean_pq"
        return "clean_nas"
    if "pq" in n and ("指数" in n or "值" in n):
        return "clean_pq"
    if any(k in n for k in ("水分", "含水", "水含量")):
        return "water_ppm" if ("ppm" in n or "mg/kg" in n) else "water_pct"
    if any(k in n for k in ("总酸值", "酸值", "中和值")) or n in ("tan", "tan值"):
        return "acid_tan"
    if any(k in n for k in ("总碱值", "碱值")) or n in ("tbn", "tbn值"):
        return "base_tbn"
    if "粘度" in n or "黏度" in n:
        if "100" in n:
            return "vis_100"
        if "指数" in n:
            return "vis_index"
        return "vis_40"
    if "闪点" in n:
        return "flash_point"
    if "倾点" in n or "凝点" in n:
        return "pour_point"
    if "色度" in n or "色号" in n:
        return "color"
    if "密度" in n:
        return "density"
    if "泡沫" in n:
        return "foam"
    if "乳化" in n:
        return "demuls"
    if "氧化" in n:
        return "oxidation"
    if "硝化" in n:
        return "nitration"
    for sym, cn, _lim in _WEAR:
        for token in (sym.lower(), cn):
            if token and n.endswith(token):
                prefix = n[:-len(token)]
                if prefix in ("磨损", "元素", "磨损元素", "光谱", "光谱分析", "金属", "金属元素", "污染物"):
                    return "wear_%s" % sym
    return None


def identify_meta(header):
    """表头 → 元数据列（设备/取样点/油品/日期/样品编号）。"""
    n = _norm(header)
    if not n:
        return None
    for key, aliases in META_KEYS.items():
        if n in {_norm(a) for a in aliases}:
            return key
    for key, aliases in META_KEYS.items():
        for a in aliases:
            an = _norm(a)
            if len(an) >= 2 and (n.startswith(an) or n.endswith(an)):
                if key == "device" and any(x in n for x in ("运行", "时间", "小时", "编号")):
                    continue
                return key
    return None


def unit_from_header(header, default=""):
    s = str(header or "")
    m = re.search(r"[（(]\s*([^)）]+?)\s*[)）]", s)
    if m:
        u = m.group(1).strip()
        if re.fullmatch(r"\d+\s*℃?", u):
            return default
        if u in ("℃", "°C", "°c"):
            return "℃"
        return u
    return default


_THRESHOLD_OVERRIDE = {}


def load_threshold_overrides():
    """thresholds.json：{"wear_Fe": {"warn": 80, "alert": 120}, ...}"""
    global _THRESHOLD_OVERRIDE
    _THRESHOLD_OVERRIDE = {}
    if not os.path.isfile(THRESHOLD_FILE):
        return
    try:
        with open(THRESHOLD_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            _THRESHOLD_OVERRIDE = data
    except Exception:
        _THRESHOLD_OVERRIDE = {}


def param_limit(key):
    p = PARAMS.get(key)
    if not p:
        return None, None, None
    warn, alert, direction = p["warn"], p["alert"], p["direction"]
    ov = _THRESHOLD_OVERRIDE.get(key) or {}
    if isinstance(ov, dict):
        warn = ov.get("warn", warn)
        alert = ov.get("alert", alert)
        direction = ov.get("direction", direction)
    return warn, alert, direction


def judge(key, value):
    if value is None or key not in PARAMS:
        return "待定"
    warn, alert, direction = param_limit(key)
    if direction is None or alert is None:
        return "待定"
    if direction == "max":
        if value >= alert:
            return "异常"
        if warn is not None and value >= warn:
            return "关注"
        return "正常"
    if value <= alert:
        return "异常"
    if warn is not None and value <= warn:
        return "关注"
    return "正常"


def limit_text(key):
    p = PARAMS.get(key)
    if not p:
        return "—"
    warn, alert, direction = param_limit(key)
    if direction is None or alert is None:
        return "—"
    unit = " " + p["unit"] if p["unit"] else ""
    return "%s %g%s" % ("≤" if direction == "max" else "≥", alert, unit)


def param_name(key):
    p = PARAMS.get(key)
    return p["name"] if p else key


def param_unit(key):
    p = PARAMS.get(key)
    return p["unit"] if p else ""


def group_name(key):
    return GROUP_NAMES.get(key, key)


# ---------------------------------------------------------------------------
# 日期 / 数值 / 文件名解析
# ---------------------------------------------------------------------------
_DATE_RE = (
    re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})"),
    re.compile(r"^(20\d{2})(\d{2})(\d{2})$"),
)
DATE_IN_NAME = re.compile(r"20\d{2}\s*[-_.年]?\s*\d{1,2}\s*[-_.月]?\s*\d{1,2}\s*日?")


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return ("%g" % v)
    return str(v).strip()


def parse_date(value):
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float)):
        if 20000 <= float(value) <= 60000:
            base = dt.date(1899, 12, 30)
            return (base + dt.timedelta(days=int(value))).isoformat()
        return ""
    s = cell_text(value)
    for pat in _DATE_RE:
        m = pat.search(s)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                return ""
    return ""


_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_value(value):
    if value is None:
        return None, ""
    if isinstance(value, bool):
        return None, cell_text(value)
    if isinstance(value, (int, float)):
        return float(value), cell_text(value)
    if isinstance(value, (datetime, date)):
        return None, ""
    s = cell_text(value)
    if not s:
        return None, ""
    compact = s.replace(",", "").replace("，", "").replace(" ", "")
    if compact.lower() in {"-", "--", "—", "/", "nd", "n.d.", "未检出", "无", "待检", "null"}:
        return None, s
    m = _NUM_RE.search(compact)
    if not m:
        return None, s
    try:
        return float(m.group()), s
    except ValueError:
        return None, s


GENERIC_WORDS = (
    "光谱", "磨损", "元素", "清洁度", "nas", "iso", "水分", "酸值", "碱值", "粘度", "黏度",
    "检测", "化验", "报告", "数据", "结果", "汇总", "台账", "分析", "监测", "油液", "列表",
    "取样", "采样", "样品", "季度", "月份", "月报", "sheet", "data", "result", "report",
)
GENERIC_FOLDERS = {
    "子目录", "子文件夹", "附件", "文件", "文档", "资料", "新建文件夹", "其他", "原始记录",
    "检测报告", "检测数据", "化验单", "excel", "表格", "归档", "备份", "临时", "root",
}
# 这些目录名不适合当项目名，向上找一级
GENERIC_PROJECTS = GENERIC_FOLDERS | {
    "油液", "油品", "油液数据", "油液监测", "油品数据", "监测数据", "在线监测",
    "shuifen", "mosun", "qingjiedu", "niandu", "data", "csv",
}


def project_label(main_dir):
    """给扫描根目录取一个像样的项目名：油液 → 上一级（如 H8项目2609月数据）。"""
    path = os.path.normpath(main_dir or "")
    name = os.path.basename(path)
    low = name.lower()
    if (low in GENERIC_PROJECTS or low.endswith(".zip")
            or unit_number(name) is not None):
        parent = os.path.basename(os.path.dirname(path))
        if parent:
            name = parent
    return name or "项目"


def is_wear_csv(vpath):
    """磨损文件：磨损.csv / mosun.csv，以及 Oil…csv 这种含磨粒列的合并文件。"""
    name = vpath.split("/")[-1].lower()
    return name.endswith(("磨损.csv", "mosun.csv")) or name.startswith("oil")


def clean_device(stem):
    s = DATE_IN_NAME.sub(" ", stem)
    s = re.sub(r"[()（）\[\]【】]", " ", s)
    for word in GENERIC_WORDS:
        s = re.sub(re.escape(word), " ", s, flags=re.I)
    s = re.sub(r"[_\-\s.]+", " ", s).strip(" _-")
    return s.strip()


UNIT_PATTERN = re.compile(r"(?:#\s*(\d+)|(\d+)\s*#)")


def unit_number(text):
    """从 youye_#10_xxx.zip / #10 / 26# / 10号 里取出机组号。"""
    m = UNIT_PATTERN.search(str(text or ""))
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def looks_like_unit_name(name):
    """机组目录/压缩包：26#、#10、H01-6.25MW、WTG01 之类。"""
    if unit_number(name) is not None:
        return True
    stem = os.path.splitext(str(name or ""))[0]
    return bool(re.fullmatch(r"[A-Za-z]{1,4}\d{1,3}([-_][A-Za-z0-9.]+)*", stem))


def unit_label(name):
    """把 youye_#10_280887679.zip / 26#_382799743 / #01 统一显示成「10#」「26#」「1#」。"""
    num = unit_number(name)
    return "%d#" % num if num is not None else str(name or "")


def guess_device(vpath):
    parts = vpath.split("/")
    # 常见在线监测导出：youye_#4_280741513.zip / youye_26#_382799743.zip → 4# / 26#
    for seg in reversed(parts):
        num = unit_number(seg)
        if num is not None:
            return "%d#" % num
    # H01-6.25MW / WTG01 这类用父目录当机组名
    for seg in reversed(parts[:-1]):
        if looks_like_unit_name(seg):
            return seg
    stem = os.path.splitext(parts[-1])[0]
    cleaned = clean_device(stem)
    if cleaned and not re.fullmatch(r"(xlsx|xls|csv)", cleaned, re.I):
        return cleaned
    for seg in reversed(parts[:-1]):
        s = os.path.splitext(seg)[0]
        if s.lower() in GENERIC_FOLDERS:
            continue
        if DATE_IN_NAME.fullmatch(s) or re.fullmatch(r"\d{4}[-_.]?\d{1,2}月?", s):
            continue
        c = clean_device(s)
        if c and not re.fullmatch(r"\d{4}", c) and re.search(r"[A-Za-z\u4e00-\u9fff]", c):
            return c
    return "未标注设备"


def guess_date(vpath):
    m = DATE_IN_NAME.search(vpath)
    return parse_date(m.group()) if m else ""

# ---------------------------------------------------------------------------
# Excel / CSV 读取与四种版式解析
#   1) wide       一行一个样品，多列分别是不同参数
#   2) long       参数名 / 结果 两列
#   3) transposed 参数在行、日期在列
#   4) single     文件名或工作表名就是参数
# ---------------------------------------------------------------------------
PARAM_LABELS = {"参数", "项目", "检测项目", "分析项目", "参数名称", "项目名称", "检测参数"}
VALUE_LABELS = {"结果", "检测结果", "数值", "值", "测定值", "分析结果", "含量"}
UNIT_LABELS = {"单位", "计量单位"}
UNIT_ROW_RE = re.compile(
    r"(ppm|mg/kg|mgkoh/g|mm2/s|mm²/s|cst|%|级|个/ml|°c|℃|g/cm3|ml|min|s)$", re.I)


def load_sheets(path):
    """读取工作簿，返回 [(工作表名, 二维行列表)]。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        raw = None
        for enc in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                with open(path, "r", encoding=enc) as fp:
                    raw = fp.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            with open(path, "r", encoding="utf-8", errors="replace") as fp:
                raw = fp.read()
        rows = [row for row in csv.reader(io.StringIO(raw))]
        return [(os.path.splitext(os.path.basename(path))[0], trim_rows(rows))]
    if ext == ".xls":
        raise ValueError("旧版 .xls 需另存为 .xlsx 后再导入")
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            rows = [[c.value for c in row] for row in ws.iter_rows(max_row=20000, max_col=120)]
            rows = trim_rows(rows)
            if rows:
                sheets.append((ws.title, rows))
    finally:
        wb.close()
    return sheets


def trim_rows(rows):
    rows = [r for r in rows[:20000] if any(cell_text(c) for c in r[:120])]
    if not rows:
        return []
    width = max(max([i + 1 for i, c in enumerate(r[:120]) if cell_text(c)] or [0]) for r in rows)
    return [(list(r) + [None] * width)[:width] for r in rows]


def meta_from_rows(rows, limit=30):
    meta = {}
    for row in rows[:limit]:
        for i, cell in enumerate(row):
            text = cell_text(cell)
            if not text or len(text) > 80:
                continue
            parts = re.split(r"[:：]", text, maxsplit=1)
            key = identify_meta(parts[0].strip() if parts else "")
            if not key:
                continue
            if len(parts) == 2 and parts[1].strip():
                meta.setdefault(key, parts[1].strip())
                continue
            if len(parts[0]) > 10:
                continue
            for nxt in row[i + 1:i + 3]:
                t = cell_text(nxt)
                if not t:
                    continue
                if identify_param(t) or identify_meta(t) or _norm(t) in (
                        PARAM_LABELS | VALUE_LABELS | UNIT_LABELS):
                    break
                meta.setdefault(key, t)
                break
    return meta


def row_score(row):
    score = 0
    for cell in row:
        n = _norm(cell)
        if n in PARAM_LABELS or n in VALUE_LABELS:
            score += 4
        elif n in UNIT_LABELS:
            score += 2
        elif identify_param(cell):
            score += 2
        elif identify_meta(cell):
            score += 2
    return score


def find_header(rows):
    best, best_idx = 0, None
    for idx, row in enumerate(rows[:25]):
        s = row_score(row)
        if s > best:
            best, best_idx = s, idx
    if best_idx is None:
        return None
    return best_idx if best >= 1 else None


def column_header(rows, r, c):
    own = cell_text(rows[r][c]) if c < len(rows[r]) else ""
    if identify_param(own):
        return own
    nxt = cell_text(rows[r + 1][c]) if r + 1 < len(rows) and c < len(rows[r + 1]) else ""
    if nxt and identify_param(nxt):
        return nxt
    return own or nxt


def looks_like_unit_row(row, param_cols):
    units = 0
    for c in param_cols:
        t = cell_text(row[c]) if c < len(row) else ""
        if t and UNIT_ROW_RE.fullmatch(t.strip()):
            units += 1
    return units >= max(2, len(param_cols) // 2)


def is_summary_row(row):
    joined = "".join(cell_text(c) for c in row).strip()
    return bool(re.match(r"^(合计|总计|平均|均值|最大|最小|备注|说明|结论)", joined))


def transposed_date_cols(rows):
    if len(rows) < 3:
        return None
    head = rows[0]
    date_cols = [c for c in range(1, len(head)) if parse_date(head[c])]
    if not date_cols:
        return None
    param_rows = sum(1 for r in rows[1:16] if r and identify_param(r[0]))
    if param_rows >= 2 and not identify_param(head[0]):
        return date_cols
    return None


def make_record(vpath, sheet, meta, param, value, raw, header):
    return {
        "vpath": vpath,
        "sheet": sheet,
        "device": meta.get("device", ""),
        "point": meta.get("point", ""),
        "oil": meta.get("oil", ""),
        "date": meta.get("date", ""),
        "sample_no": meta.get("sample_no", ""),
        "param": param,
        "value": value,
        "raw": raw,
        "unit": unit_from_header(header, param_unit(param)),
    }


def parse_sheet(sheet_name, rows, vpath, meta_extra=None):
    if not rows:
        return []
    meta = dict(meta_extra or {})
    meta.update(meta_from_rows(rows))
    date_cols = transposed_date_cols(rows)
    if date_cols:
        return parse_transposed(rows, 1, sheet_name, vpath, meta, rows[0], date_cols)
    header_idx = find_header(rows)
    if header_idx is None:
        return parse_fallback(rows, sheet_name, vpath, meta)
    out = parse_matrix(rows, header_idx, sheet_name, vpath, meta)
    return out if out else parse_fallback(rows, sheet_name, vpath, meta)


def parse_matrix(rows, header_idx, sheet_name, vpath, meta):
    header = rows[header_idx]
    param_cols, meta_cols = {}, {}
    for c, cell in enumerate(header):
        p = identify_param(cell) or identify_param(column_header(rows, header_idx, c))
        if p:
            param_cols[c] = p
            continue
        m = identify_meta(cell)
        if m:
            meta_cols[c] = m

    data_start = header_idx + 1
    if data_start < len(rows) and looks_like_unit_row(rows[data_start], param_cols):
        data_start += 1

    name_col = value_col = None
    for c, cell in enumerate(header):
        n = _norm(cell)
        if n in PARAM_LABELS:
            name_col = c
        elif n in VALUE_LABELS:
            value_col = c
    if name_col is not None and value_col is not None:
        return parse_long(rows, data_start, name_col, value_col, sheet_name, vpath, meta, header, meta_cols)

    if 0 in param_cols and len(param_cols) == 1:
        dates = [c for c in range(len(header)) if c != 0 and parse_date(header[c])]
        if len(dates) >= 2:
            return parse_transposed(rows, data_start, sheet_name, vpath, meta, header, dates)

    if not param_cols:
        return []

    out = []
    for r in range(data_start, len(rows)):
        row = rows[r]
        if is_summary_row(row):
            continue
        row_meta = dict(meta)
        for c, key in meta_cols.items():
            text = cell_text(row[c]) if c < len(row) else ""
            if not text:
                continue
            if key == "date":
                d = parse_date(row[c])
                if d:
                    row_meta["date"] = d
            elif key in ("device", "point", "oil", "sample_no"):
                row_meta[key] = text
        if not row_meta.get("date"):
            for cell in row:
                d = parse_date(cell)
                if d:
                    row_meta["date"] = d
                    break
        if not row_meta.get("device"):
            continue
        for c, p in param_cols.items():
            if c >= len(row):
                continue
            value, raw = parse_value(row[c])
            if value is None and not raw:
                continue
            out.append(make_record(vpath, sheet_name, row_meta, p, value, raw, header[c]))
    return out


def parse_long(rows, data_start, name_col, value_col, sheet_name, vpath, meta, header, meta_cols=None):
    unit_col = None
    for c, cell in enumerate(header):
        if _norm(cell) in (UNIT_LABELS | {"unit"}):
            unit_col = c
    out = []
    for r in range(data_start, len(rows)):
        row = rows[r]
        if is_summary_row(row):
            continue
        p = identify_param(row[name_col]) if name_col < len(row) else None
        if not p:
            continue
        value, raw = parse_value(row[value_col] if value_col < len(row) else None)
        if value is None and not raw:
            continue
        row_meta = dict(meta)
        for c, key in (meta_cols or {}).items():
            if c in (name_col, value_col) or c >= len(row):
                continue
            text = cell_text(row[c])
            if not text:
                continue
            if key == "date":
                d = parse_date(row[c])
                if d:
                    row_meta["date"] = d
            elif key in ("device", "point", "oil", "sample_no"):
                row_meta[key] = text
        if not row_meta.get("date"):
            for cell in row:
                d = parse_date(cell)
                if d:
                    row_meta["date"] = d
                    break
        rec = make_record(vpath, sheet_name, row_meta, p, value, raw, header[name_col])
        if unit_col is not None and unit_col < len(row) and cell_text(row[unit_col]):
            rec["unit"] = cell_text(row[unit_col])
        out.append(rec)
    return out


def parse_transposed(rows, data_start, sheet_name, vpath, meta, header, date_cols):
    out = []
    for c in date_cols:
        d = parse_date(header[c])
        for r in range(data_start, len(rows)):
            row = rows[r]
            p = identify_param(row[0]) if row else None
            if not p:
                continue
            value, raw = parse_value(row[c] if c < len(row) else None)
            if value is None and not raw:
                continue
            row_meta = dict(meta)
            if d:
                row_meta["date"] = d
            out.append(make_record(vpath, sheet_name, row_meta, p, value, raw, header[0]))
    return out


def parse_fallback(rows, sheet_name, vpath, meta):
    """兜底：文件名/工作表名即参数名，抓取每行的数字。"""
    candidates = [sheet_name, os.path.splitext(os.path.basename(vpath))[0]]
    p = None
    for c in candidates:
        p = identify_param(c)
        if p:
            break
    if not p:
        return []
    out = []
    for row in rows:
        if is_summary_row(row):
            continue
        d = ""
        for cell in row:
            d = parse_date(cell)
            if d:
                break
        numbers = []
        for cell in row:
            v, raw = parse_value(cell)
            if v is not None:
                numbers.append((v, raw, cell))
        if not numbers:
            continue
        v, raw, cell = numbers[0]
        row_meta = dict(meta)
        if d:
            row_meta["date"] = d
        out.append(make_record(vpath, sheet_name, row_meta, p, v, raw, cell))
    return out


SENSOR_TIME_HINTS = ("时间", "time", "timestamp", "datetime")
SENSOR_SKIP_HINTS = ("传感器温度", "上电时间", "上电时长", "总增长")
ISO_HEADER_RE = re.compile(r"^iso\s*(\d+)\s*$", re.I)
NAS_HEADER_RE = re.compile(r"^nas", re.I)
PARTICLE_HEADER_RE = re.compile(r"([≥>]?\s*\d+)\s*-\s*(\d+)\s*微米范围微粒数\s*\((铁磁性|非铁磁性)\)")
PARTICLE_OPEN_RE = re.compile(r"([≥>]\s*\d+)\s*微米范围微粒数\s*\((铁磁性|非铁磁性)\)")


def register_sensor_param(name, group="other", unit=""):
    """在线监测里不认识的通道，按名称动态注册为参数（不判定，只展示与画趋势）。"""
    key = "sensor_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    if key not in PARAMS:
        PARAMS[key] = {"key": key, "name": name, "group": group, "unit": unit,
                       "aliases": (), "direction": None, "warn": None, "alert": None}
    return key


def looks_like_sensor_series(rows):
    """在线监测导出的时序 CSV：有“时间”列（带时分秒）、行数多、没有设备列。"""
    if len(rows) < 30:
        return False
    header = [cell_text(c) for c in rows[0]]
    if any(identify_meta(h) == "device" for h in header):
        return False
    time_col = None
    for i, h in enumerate(header):
        if "时间" in h or h.strip().lower() in ("time", "timestamp", "datetime"):
            time_col = i
            break
    if time_col is None:
        return False
    hits = 0
    for row in rows[1:8]:
        if time_col < len(row) and re.search(r"\d{1,2}:\d{2}", cell_text(row[time_col])):
            hits += 1
    return hits >= 3


def _sensor_record(vpath, sheet_name, meta, param, value, raw):
    rec = make_record(vpath, sheet_name, meta, param, value, raw, "")
    rec["unit"] = PARAMS[param]["unit"]
    return rec


def parse_sensor_series(rows, sheet_name, vpath, meta):
    """把 5 分钟一条的在线监测数据聚合为「每设备每参数一条」记录。

    - ISO / NAS 取监测时段内最差一级；
    - 微粒数取最大值；
    - 水分、粘度、密度等取均值。
    数据点数量放在 raw 里（如“均值(327点)”），报告里可追溯。
    """
    header = [cell_text(c) for c in rows[0]]
    time_col = None
    for i, h in enumerate(header):
        if "时间" in h or h.strip().lower() in ("time", "timestamp", "datetime"):
            time_col = i
            break
    if time_col is None:
        return []
    cols = [(c, h) for c, h in enumerate(header)
            if c != time_col and h and not any(k in h for k in SENSOR_SKIP_HINTS)]
    if not cols:
        return []
    series = {c: [] for c, _ in cols}
    dates = []
    for row in rows[1:]:
        t = cell_text(row[time_col]) if time_col < len(row) else ""
        d = parse_date(t)
        if d:
            dates.append(d)
        for c, _h in cols:
            if c < len(row):
                v, _raw = parse_value(row[c])
                if v is not None:
                    series[c].append(v)
    if not dates:
        return []
    meta = dict(meta)
    meta["date"] = max(dates)

    def mean(vals):
        return sum(vals) / len(vals)

    iso_vals, nas_vals, out = [], [], []
    for c, h in cols:
        vals = series[c]
        if not vals:
            continue
        n = _norm(h)
        if ISO_HEADER_RE.match(n):
            iso_vals.extend(vals)
            continue
        if NAS_HEADER_RE.match(n):
            nas_vals.extend([v for v in vals if v >= 0])
            continue
        if n.endswith("aw") or ("湿度" in n and "水分" in n):
            out.append(_sensor_record(vpath, sheet_name, meta, "water_aw",
                                      round(mean(vals), 1), "均值(%d点)" % len(vals)))
            continue
        if n == "ppm" or ("水分" in n and "ppm" in n):
            out.append(_sensor_record(vpath, sheet_name, meta, "water_ppm",
                                      round(mean(vals), 1), "均值(%d点)" % len(vals)))
            continue
        if "vt40" in n:
            out.append(_sensor_record(vpath, sheet_name, meta, "vis_40",
                                      round(mean(vals), 2), "均值(%d点)" % len(vals)))
            continue
        if "密度" in n:
            out.append(_sensor_record(vpath, sheet_name, meta, "density",
                                      round(mean(vals), 3), "均值(%d点)" % len(vals)))
            continue
        name, group, unit = h, "other", ""
        m = PARTICLE_HEADER_RE.search(h) or PARTICLE_OPEN_RE.search(h)
        if m:
            if m.re is PARTICLE_OPEN_RE:
                rng = m.group(1).replace(" ", "")
                ferro = m.group(2)
                name = "%sμm %s颗粒数" % (rng, "铁磁" if ferro == "铁磁性" else "非铁磁")
            else:
                name = "%s-%sμm %s颗粒数" % (m.group(1), m.group(2),
                                            "铁磁" if m.group(3) == "铁磁性" else "非铁磁")
            group, unit = "wear", "个"
            value, raw = float(max(vals)), "最大(%d点)" % len(vals)
        elif "介电" in n:
            value, raw = round(mean(vals), 2), "均值(%d点)" % len(vals)
        elif "粘度" in n:
            group = "vis"
            value, raw = round(mean(vals), 2), "均值(%d点)" % len(vals)
        else:
            value, raw = round(mean(vals), 3), "均值(%d点)" % len(vals)
        param = register_sensor_param(name, group, unit)
        out.append(_sensor_record(vpath, sheet_name, meta, param, value, raw))

    if iso_vals:
        out.append(_sensor_record(vpath, sheet_name, meta, "clean_iso",
                                  float(max(iso_vals)), "最大(ISO 代码)"))
    if nas_vals:
        out.append(_sensor_record(vpath, sheet_name, meta, "clean_nas",
                                  float(max(nas_vals)), "最大(NAS)"))
    return out


def parse_workbook(path, vpath):
    """解析一个工作簿，返回 (记录列表, 工作表名列表, 错误信息)。"""
    records, sheet_names = [], []
    try:
        sheets = load_sheets(path)
    except Exception as exc:  # noqa: BLE001
        return [], [], str(exc)
    meta_extra = {"device": guess_device(vpath), "date": guess_date(vpath)}
    seen = set()
    for sheet_name, rows in sheets:
        sheet_names.append(sheet_name)
        try:
            if looks_like_sensor_series(rows):
                recs = parse_sensor_series(rows, sheet_name, vpath, meta_extra)
            else:
                recs = parse_sheet(sheet_name, rows, vpath, meta_extra)
        except Exception as exc:  # noqa: BLE001
            return records, sheet_names, "工作表 %s 解析失败：%s" % (sheet_name, exc)
        for rec in recs:
            if not rec.get("device"):
                rec["device"] = meta_extra["device"]
            if rec["param"] == "clean_iso":
                codes = [int(x) for x in re.findall(r"\d+", str(rec.get("raw") or ""))]
                if len(codes) >= 2:
                    rec["value"] = float(max(codes))
            key = (rec["device"], rec["point"], rec["date"], rec["param"], rec["value"])
            if key in seen:
                continue
            seen.add(key)
            rec["status"] = judge(rec["param"], rec["value"])
            records.append(rec)
    return records, sheet_names, ""

# ---------------------------------------------------------------------------
# SQLite 缓存
#   files   : 每个源文件一行（路径 / 大小 / mtime / 解析状态）
#   records : 统一后的监测记录（设备 × 日期 × 参数）
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
    vpath TEXT PRIMARY KEY, project TEXT, real_path TEXT, size INTEGER, mtime REAL,
    status TEXT, error TEXT, records INTEGER, params TEXT, sheets TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vpath TEXT, project TEXT, device TEXT, point TEXT, oil TEXT, date TEXT,
    param TEXT, group_key TEXT, name TEXT, value REAL, raw TEXT, unit TEXT, status TEXT,
    sheet TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(project);
CREATE INDEX IF NOT EXISTS idx_records_vpath ON records(vpath);
CREATE INDEX IF NOT EXISTS idx_records_device ON records(device);
CREATE INDEX IF NOT EXISTS idx_records_param ON records(param);
"""


class Store:
    def __init__(self, path=None):
        self.path = path or DB_FILE
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_records_date ON records(date)")
            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(records)").fetchall()}
            if "sheet" not in cols:  # 兼容早期缓存库
                self.conn.execute("ALTER TABLE records ADD COLUMN sheet TEXT")
            self.conn.commit()

    # ---------- 基础 ----------
    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _exec(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def reset(self):
        with self.lock:
            self.conn.executescript(
                "DROP TABLE IF EXISTS records; DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS meta;"
            )
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---------- meta ----------
    def get_meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self._exec("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))

    # ---------- 文件 ----------
    def file_info(self):
        rows = self.conn.execute("SELECT * FROM files").fetchall()
        return {r["vpath"]: dict(r) for r in rows}

    def upsert_file(self, rec):
        self._exec(
            "INSERT INTO files(vpath,project,real_path,size,mtime,status,error,records,params,sheets)"
            " VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(vpath) DO UPDATE SET"
            " project=excluded.project, real_path=excluded.real_path, size=excluded.size,"
            " mtime=excluded.mtime, status=excluded.status, error=excluded.error,"
            " records=excluded.records, params=excluded.params, sheets=excluded.sheets",
            (rec["vpath"], rec["project"], rec.get("real_path", ""), rec.get("size", 0),
             rec.get("mtime", 0), rec.get("status", "ok"), rec.get("error", ""),
             rec.get("records", 0), rec.get("params", ""), rec.get("sheets", "")),
        )

    def delete_file(self, vpath):
        self._exec("DELETE FROM records WHERE vpath=?", (vpath,))
        self._exec("DELETE FROM files WHERE vpath=?", (vpath,))

    def replace_records(self, vpath, project, rows, info):
        with self.lock:
            self.conn.execute("DELETE FROM records WHERE vpath=?", (vpath,))
            for r in rows:
                self.conn.execute(
                    "INSERT INTO records(vpath,project,device,point,oil,date,param,group_key,name,value,raw,unit,status,sheet)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (vpath, project, r["device"], r["point"], r["oil"], r["date"], r["param"],
                     PARAMS[r["param"]]["group"], PARAMS[r["param"]]["name"], r["value"],
                     r["raw"], r["unit"], r["status"], r.get("sheet", "")),
                )
            self.conn.execute(
                "INSERT INTO files(vpath,project,real_path,size,mtime,status,error,records,params,sheets)"
                " VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(vpath) DO UPDATE SET"
                " project=excluded.project, real_path=excluded.real_path, size=excluded.size,"
                " mtime=excluded.mtime, status=excluded.status, error=excluded.error,"
                " records=excluded.records, params=excluded.params, sheets=excluded.sheets",
                (vpath, project, info.get("real_path", ""), info.get("size", 0), info.get("mtime", 0),
                 info.get("status", "ok"), info.get("error", ""), len(rows),
                 ",".join(sorted({r["param"] for r in rows})), "、".join(info.get("sheets", []))),
            )
            self.conn.commit()

    # ---------- 查询 ----------
    def count(self, project=None, prefix=""):
        sql = "SELECT COUNT(*) FROM records WHERE 1=1"
        args = []
        if project:
            sql += " AND project=?"
            args.append(project)
        if prefix:
            sql += " AND (vpath=? OR vpath LIKE ?)"
            args.extend([prefix, prefix + "/%"])
        return self.conn.execute(sql, args).fetchone()[0]

    def projects(self):
        rows = self.conn.execute(
            "SELECT project, COUNT(*) AS files, SUM(records) AS recs FROM files GROUP BY project ORDER BY project"
        ).fetchall()
        out = []
        for r in rows:
            abn = self.conn.execute(
                "SELECT COUNT(*) FROM records WHERE project=? AND status='异常'", (r["project"],)
            ).fetchone()[0]
            out.append({"project": r["project"], "files": r["files"] or 0,
                        "records": r["recs"] or 0, "abnormal": abn})
        return out

    def summary(self, project=None):
        where, args = "", []
        if project:
            where, args = " WHERE project=?", [project]
        total = self.conn.execute("SELECT COUNT(*) FROM records" + where, args).fetchone()[0]
        cnt = {}
        for row in self.conn.execute("SELECT status, COUNT(*) FROM records" + where + " GROUP BY status", args):
            cnt[row[0]] = row[1]
        files = self.conn.execute("SELECT COUNT(*) FROM files" + where, args).fetchone()[0]
        errs = self.conn.execute(
            "SELECT COUNT(*) FROM files" + (where + " AND" if where else " WHERE") + " status='error'", args
        ).fetchone()[0]
        devs = self.conn.execute(
            "SELECT COUNT(DISTINCT device) FROM records" + where, args
        ).fetchone()[0]
        return {"records": total, "status": cnt, "files": files, "errors": errs, "devices": devs}

    def query(self, project=None, prefix="", device="", group="", param="", status="",
              keyword="", limit=MAX_PREVIEW_ROWS):
        sql = "SELECT * FROM records WHERE 1=1"
        args = []
        if project:
            sql += " AND project=?"
            args.append(project)
        if prefix:
            sql += " AND (vpath=? OR vpath LIKE ?)"
            args.extend([prefix, prefix + "/%"])
        if device:
            sql += " AND device=?"
            args.append(device)
        if group:
            sql += " AND group_key=?"
            args.append(group)
        if param:
            sql += " AND param=?"
            args.append(param)
        if status:
            statuses = [s for s in str(status).split(",") if s]
            if len(statuses) > 1:
                sql += " AND status IN (%s)" % ",".join("?" * len(statuses))
                args.extend(statuses)
            else:
                sql += " AND status=?"
                args.append(statuses[0])
        if keyword:
            sql += " AND (device LIKE ? OR name LIKE ? OR raw LIKE ? OR point LIKE ?)"
            like = "%" + keyword + "%"
            args.extend([like, like, like, like])
        sql += " ORDER BY LENGTH(device), device, date DESC, group_key, name LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def distinct(self, column, project=None, prefix="", keyword=""):
        sql = "SELECT DISTINCT %s FROM records WHERE 1=1" % column
        args = []
        if project:
            sql += " AND project=?"
            args.append(project)
        if prefix:
            sql += " AND (vpath=? OR vpath LIKE ?)"
            args.extend([prefix, prefix + "/%"])
        if keyword:
            sql += " AND (%s LIKE ?)" % column
            args.append("%" + keyword + "%")
        sql += " ORDER BY %s" % column
        return [r[0] for r in self.conn.execute(sql, args).fetchall()]


# ---------------------------------------------------------------------------
# 扫描：多层目录 + 压缩包（含嵌套）→ 逐个解析入缓存
# ---------------------------------------------------------------------------
class Scanner:
    def __init__(self, main_dir, progress=None):
        self.main_dir = main_dir
        self.progress = progress or (lambda text, pct: None)
        self.store = Store()
        self.entries = []

    def collect(self):
        entries = []
        if not self.main_dir or not os.path.isdir(self.main_dir):
            return entries
        try:
            tops = sorted(os.listdir(self.main_dir))
        except OSError:
            return entries
        unit_like = [n for n in tops if looks_like_unit_name(n)
                     and (n.lower().endswith(".zip") or os.path.isdir(os.path.join(self.main_dir, n)))]
        containers = [n for n in tops
                      if n.lower().endswith(".zip") and not looks_like_unit_name(n)]
        if len(unit_like) >= 2:
            return self.collect_units(unit_like, containers)
        for root, dirs, files in os.walk(self.main_dir):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, self.main_dir).replace("\\", "/")
                ext = os.path.splitext(fn)[1].lower()
                if "/" in rel:
                    project = rel.split("/")[0]
                elif ext == ".zip":
                    project = os.path.splitext(fn)[0]  # 根目录下的压缩包本身就是一个项目
                else:
                    project = project_label(self.main_dir)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if ext in EXCEL_EXT:
                    entries.append({"project": project, "vpath": rel, "real": full,
                                    "size": st.st_size, "mtime": st.st_mtime})
                elif ext == ".zip":
                    try:
                        entries.extend(self.expand_zip(full, rel, project, 0))
                    except Exception:
                        entries.append({"project": project, "vpath": rel, "real": full,
                                        "size": st.st_size, "mtime": st.st_mtime, "error": "压缩包损坏或无法解包"})
        default = project_label(self.main_dir)
        for e in entries:
            p = str(e.get("project") or "")
            if p.lower() in GENERIC_PROJECTS or unit_number(p) is not None:
                e["project"] = default
        return entries

    def collect_units(self, unit_like, containers):
        """现场导出的机组包：根目录一堆 #1/#2…zip（或文件夹）时，整体作为一个项目。

        有总包（如 营盘梁.zip）就以总包名作为项目名，并优先用总包里的数据；
        总包里没有的机组，再从根目录的散包/文件夹补齐；home、excel 之类的中间目录不显示。
        """
        entries = []
        project = None
        covered = set()
        if len(containers) == 1:
            cname = containers[0]
            project = os.path.splitext(cname)[0]
            centries = self.expand_zip(os.path.join(self.main_dir, cname), cname, project, 0)
            entries.extend(centries)
            for e in centries:
                num = unit_number(e["vpath"])
                if num is not None:
                    covered.add(num)
        if not project:
            project = project_label(self.main_dir)
        if project.lower() in GENERIC_PROJECTS:
            project = project_label(self.main_dir)
        for name in unit_like:
            num = unit_number(name)
            if num is not None and num in covered:
                continue
            full = os.path.join(self.main_dir, name)
            if os.path.isdir(full):
                entries.extend(self.walk_dir(full, project, name))
            else:
                entries.extend(self.expand_zip(full, name, project, 0))
        for e in entries:
            e["project"] = project
        return entries

    def walk_dir(self, root, project, prefix):
        entries = []
        for dirpath, dirs, files in os.walk(root):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                vpath = prefix + "/" + rel
                ext = os.path.splitext(fn)[1].lower()
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if ext in EXCEL_EXT:
                    entries.append({"project": project, "vpath": vpath, "real": full,
                                    "size": st.st_size, "mtime": st.st_mtime})
                elif ext == ".zip":
                    entries.extend(self.expand_zip(full, vpath, project, 0))
        return entries

    def expand_zip(self, zip_path, vpath, project, depth):
        if depth > MAX_ZIP_DEPTH:
            return []
        try:
            st = os.stat(zip_path)
        except OSError:
            return []
        key = hashlib.sha1(("%s|%s|%s" % (vpath, st.st_size, st.st_mtime)).encode("utf-8")).hexdigest()[:16]
        out_dir = os.path.join(ZIP_CACHE_DIR, key)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = self.fix_zip_name(info.filename, info.flag_bits).replace("\\", "/")
                    name = "/".join(seg for seg in name.split("/") if seg not in ("", ".", ".."))
                    if not name or name.startswith("__MACOSX") or "/__MACOSX/" in name:
                        continue
                    base = os.path.basename(name)
                    if base.startswith("~$") or base.startswith("._"):
                        continue
                    target = os.path.join(out_dir, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        entries = []
        for root, dirs, files in os.walk(out_dir):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, out_dir).replace("\\", "/")
                child_vpath = vpath + "/" + rel
                ext = os.path.splitext(fn)[1].lower()
                if ext in EXCEL_EXT:
                    try:
                        cst = os.stat(full)
                    except OSError:
                        continue
                    entries.append({"project": project, "vpath": child_vpath, "real": full,
                                    "size": cst.st_size, "mtime": cst.st_mtime})
                elif ext == ".zip":
                    try:
                        entries.extend(self.expand_zip(full, child_vpath, project, depth + 1))
                    except Exception:
                        pass
        return entries

    @staticmethod
    def fix_zip_name(name, flag_bits):
        """压缩包文件名解码：优先 UTF-8，其次 GBK（很多国产软件写 zip 不带 UTF-8 标记）。"""
        if flag_bits & 0x800:
            return name
        try:
            raw = name.encode("cp437")
        except UnicodeEncodeError:
            return name
        for enc in ("utf-8", "gb18030"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return name

    def run(self, force=False):
        self.progress("正在扫描目录…", 0)
        try:
            stored_version = self.store.get_meta("parse_version")
        except sqlite3.Error:
            stored_version = None
        if stored_version != str(PARSE_VERSION):
            force = True  # 解析规则升级，旧缓存作废
        entries = self.collect()
        self.entries = entries
        known = self.store.file_info()
        current = {e["vpath"] for e in entries}
        current_projects = {e["project"] for e in entries}
        # 只删除本次扫描到的项目里的旧文件；其他项目保留，树里可以同时显示多个项目
        for vpath, info in known.items():
            if vpath not in current and info.get("project") in current_projects:
                self.store.delete_file(vpath)

        changed = [e for e in entries
                   if force or (e["vpath"] not in known
                                or abs((known[e["vpath"]].get("size") or 0) - e["size"]) > 0
                                or abs((known[e["vpath"]].get("mtime") or 0) - e["mtime"]) > 1e-6)]
        stats = {"files": len(entries), "parsed": 0, "skipped": len(entries) - len(changed),
                 "failed": 0, "records": 0, "kept_projects": 0}
        existing_projects = {info.get("project") for info in known.values()}
        stats["kept_projects"] = len(existing_projects - current_projects)
        total = max(1, len(changed))
        for i, e in enumerate(changed):
            self.progress("解析 %s" % e["vpath"].split("/")[-1], int(i * 100 / total))
            if e.get("error"):
                self.store.upsert_file({"vpath": e["vpath"], "project": e["project"],
                                        "real_path": e["real"], "size": e["size"], "mtime": e["mtime"],
                                        "status": "error", "error": e["error"], "records": 0})
                stats["failed"] += 1
                continue
            records, sheets, err = parse_workbook(e["real"], e["vpath"])
            info = {"real_path": e["real"], "size": e["size"], "mtime": e["mtime"],
                    "status": "error" if err else "ok", "error": err, "sheets": sheets}
            self.store.replace_records(e["vpath"], e["project"], records, info)
            stats["parsed"] += 1
            stats["records"] += len(records)
            if err:
                stats["failed"] += 1
        self.store.set_meta("main_dir", self.main_dir)
        self.store.set_meta("scanned_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.store.set_meta("parse_version", PARSE_VERSION)
        self.progress("扫描完成", 100)
        return stats

# ---------------------------------------------------------------------------
# 磨损分析：磨粒计数 CSV → 月度磨损分析表（套用 磨损分析模板.xlsx）+ 机组汇总
#   口径与原「磨损CSV批量分析工具」一致：
#     颗粒数 = 末值 - 首值（先做单调递增修复）
#     个/天  = 颗粒数 / 监测天数
#     个/L   = 个/天 / (75 L/min × 1440 min)
#     浓度   = (7.87/0.86) × 1e9 × 球体积(40μm) × 颗粒数 / (π×7mm² × 0.64m/s × 天数)
# ---------------------------------------------------------------------------
WEAR_BIN_LABELS = [
    "40-59μm 铁磁", "60-99μm 铁磁", "100-299μm 铁磁", "300-399μm 铁磁", "≥400μm 铁磁",
    "135-149μm 非铁磁", "150-249μm 非铁磁", "250-349μm 非铁磁", "350-449μm 非铁磁", "≥450μm 非铁磁",
]
WEAR_FLOW_LPM = 75.0
WEAR_PIPE_R = 7.0 / 1000.0
WEAR_VELOCITY = 0.64
# 月度分析表格里的公式按 28 天计（与原模板一致）；要改成实际天数只改这里和公式
WEAR_PERIOD_DAYS = 28.0


def wear_template_path():
    return resource_path(os.path.join("templates", "磨损分析模板.xlsx"))


def load_wear_csv(path):
    """读取磨粒计数 CSV：第 1 列时间，去掉第 2 列（传感器上电时间），其余 10 列为累积颗粒数。"""
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", newline="", encoding=enc) as fp:
                raw = [r for r in csv.reader(fp) if r]
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV 编码无法识别：%s" % os.path.basename(path))
    header = raw[0] if raw else []
    idx = [i for i, h in enumerate(header) if "微米范围微粒数" in str(h)]
    if len(idx) < 10:
        idx = list(range(2, 12))  # 老格式：第 2 列是传感器上电时间
    idx = idx[:10]
    rows = []
    for r in raw:
        if len(r) < 3:
            continue
        vals = [r[i] if i < len(r) else "" for i in idx]
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                nums.append(v)
        rows.append([r[0]] + nums)
    return rows


def _wear_time(value):
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def analyze_wear(rows):
    """rows: load_wear_csv 的结果（首行表头）。返回统计与结论。"""
    if len(rows) < 3:
        raise ValueError("有效数据不足（少于 2 条记录）")
    data = []
    for row in rows[1:]:
        vals = []
        for v in row[1:11]:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals.append(0.0)
        data.append((_wear_time(row[0]), vals))
    # 分析前删除所有通道计数全为 0 的行；若整月全为 0 则保留原数据用于清零判断
    nonzero = [(t, v) for t, v in data if any(x != 0 for x in v)]
    data = nonzero if nonzero else data
    # 单调递增修复（传感器累计值偶发回退）
    fixed = []
    prev = None
    for t, vals in data:
        cur = vals[:] if prev is None else [max(vals[i], prev[i]) for i in range(10)]
        fixed.append((t, cur))
        prev = cur
    first = fixed[0][1]
    last = fixed[-1][1]
    sums = [max(0.0, last[i] - first[i]) for i in range(10)]

    times = [t for t, _ in fixed if t]
    t0 = min(times) if times else None
    t1 = max(times) if times else None
    # 采样天数：该机组实际首末采集日（含首尾，如 8/12–8/31 为 20 天）
    if t0 and t1:
        days = (t1.date() - t0.date()).days + 1
    else:
        days = WEAR_PERIOD_DAYS

    per_day = [int(s / days) for s in sums]
    per_l = [pd / (WEAR_FLOW_LPM * 60 * 24) for pd in per_day]
    particle_volume = (4.0 / 3.0) * math.pi * (40.0 / 2_000_000.0) ** 3
    denom = math.pi * WEAR_PIPE_R ** 2 * WEAR_VELOCITY * 3600 * 24 * days
    conc = [(7.87 / 0.86) * (1e9 * particle_volume * s / denom) if denom else 0.0 for s in sums]

    b7 = sum(conc[0:5])
    g7 = sum(conc[5:10])
    # 有颗粒但浓度极小时，显示下限按 0.01 计
    if 0 < b7 < 0.01:
        b7 = 0.01
    if 0 < g7 < 0.01:
        g7 = 0.01

    all_zero = all(s == 0 for s in sums)
    counter_zero = all(v == 0 for v in last)
    same_start_end = all(abs(first[i] - last[i]) < 1e-9 for i in range(10))

    # 报告按监测期最后一个月的月份命名（数据跨月时用结束月份）
    stamp = t1 or t0
    ym = stamp.strftime("%Y年%m月份") if stamp else "本期"
    ym_trend = stamp.strftime("%Y.%m") if stamp else ""
    if counter_zero:
        conclusion = "%s磨损数据清零，不排除传感器故障，建议参考下月数据作确定。" % ym.replace("份", "")
        color = "AACC99"
    elif same_start_end and not all_zero:
        conclusion = "%s磨损数据异常保持不变，建议检查采集设备和传感器运行状态。" % ym.replace("份", "")
        color = "AACC99"
    elif b7 < 1 and g7 < 1:
        conclusion = "%s磨损基本没有产生，单位体积油液颗粒含量和颗粒浓度均很小，设备运行正常。" % ym
        color = "AACC99"
    elif (b7 > 1 or g7 > 1) and (b7 < 20 and g7 < 15):
        conclusion = "%s小的磨损数据持续小速率产生，机组正常。" % ym
        color = "AACC99"
    elif b7 > 25 or g7 > 20:
        conclusion = ("%s机组磨粒产生浓度较高，达到报警限度，建议 2 周内检查确认，"
                      "并结合振动分析判断设备运行状态。" % ym)
        color = "FFC7CE"
    elif b7 > 20 or g7 > 15:
        conclusion = ("%s机组磨粒产生浓度较高，达到预警限度，建议 2 个月内检查确认，"
                      "并结合振动分析判断设备运行状态。" % ym)
        color = "FFFF99"
    else:
        conclusion = "%s数据待复核" % ym
        color = "AACC99"

    return {
        "rows": rows,
        "fixed": fixed,
        "sums": sums,
        "per_day": per_day,
        "per_l": per_l,
        "conc": conc,
        "b7": b7,
        "g7": g7,
        "days": days,
        "ym": ym,
        "ym_trend": ym_trend,
        "conclusion": conclusion,
        "color": color,
        "all_zero": all_zero,
        "same_start_end": same_start_end,
        "zero": counter_zero,
        "constant": same_start_end and not counter_zero,
    }


def _make_wear_chart(ws_data, col, start_row, last_row, title):
    """按原始数据列生成一张折线图（累计或增量）。"""
    from openpyxl.chart import LineChart, Reference
    from openpyxl.utils import get_column_letter

    chart = LineChart()
    chart.title = title
    chart.style = 2
    chart.width = 25.0
    chart.height = 5.2
    chart.legend = None
    chart.y_axis.title = "颗粒数"
    chart.x_axis.title = "时间"
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.x_axis.tickLblSkip = max(1, (last_row - start_row) // 8 or 1)
    data = Reference(ws_data, min_col=col, min_row=1, max_row=last_row)
    cats = Reference(ws_data, min_col=1, min_row=start_row, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    if start_row > 2:
        # 增量列第 2 行没有值（首行无前值），数据从第 3 行开始
        letter = get_column_letter(col)
        chart.series[0].val.numRef.f = "'%s'!$%s$%d:$%s$%d" % (
            ws_data.title, letter, start_row, letter, last_row)
    chart.set_categories(cats)
    return chart


def _rebuild_wear_charts(wb, ws_data, last_row):
    """按原始数据粘贴区的表头/列，重建铁磁、非铁磁两张趋势图工作表。"""
    layout = [
        ("积累趋势和增量图（铁磁）", list(range(2, 7)), list(range(13, 18)), 0),
        ("积累趋势和增量图（非铁磁）", list(range(7, 12)), list(range(18, 23)), 5),
    ]
    anchors = ["A1", "L1", "A11", "L11", "A21", "L21", "A31", "L31", "A41", "L41"]
    for sheet_name, cum_cols, inc_cols, offset in layout:
        if sheet_name not in wb.sheetnames:
            continue
        sh = wb[sheet_name]
        sh._charts = []
        for j, (cum_col, inc_col) in enumerate(zip(cum_cols, inc_cols)):
            label = WEAR_BIN_LABELS[offset + j] if offset + j < len(WEAR_BIN_LABELS) else str(j)
            sh.add_chart(_make_wear_chart(ws_data, cum_col, 2, last_row, "%s · 累计" % label),
                         anchors[j * 2])
            sh.add_chart(_make_wear_chart(ws_data, inc_col, 3, last_row, "%s · 增量" % label),
                         anchors[j * 2 + 1])


def build_wear_workbook(template, unit_name, analysis, out_path):
    """按模板生成单台机组的磨损分析工作簿。

    - 原始数据粘贴区：A 列时间与 M–V 增量列行数严格一致（删掉模板多余空行）；
    - 月度分析表格：保留模板公式，只把 B3:K3 的末行引用改成实际数据末行；
    - 两张趋势图工作表：按原始数据表头逐列重建累计/增量折线图。
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    wb = load_workbook(template)
    ws = wb["原始数据粘贴区"]
    rows = analysis["rows"]
    last_row = len(rows)

    if ws.max_row > last_row:
        ws.delete_rows(last_row + 1, ws.max_row - last_row)

    for ri, row in enumerate(rows, start=1):
        for ci, val in enumerate(row, start=1):
            ws.cell(row=ri, column=ci).value = val

    for r in range(3, last_row + 1):
        for f_col, src_col in zip(range(13, 23), range(2, 12)):
            letter = get_column_letter(src_col)
            ws.cell(row=r, column=f_col).value = "=%s%d-%s%d" % (letter, r, letter, r - 1)

    wa = wb["月度分析表格"]
    days = int(analysis.get("days") or WEAR_PERIOD_DAYS)
    for i in range(10):
        col = get_column_letter(2 + i)
        wa.cell(row=3, column=2 + i).value = (
            "=原始数据粘贴区!%s%d-原始数据粘贴区!%s2" % (col, last_row, col))
        # 模板里的 28 是采集天数，改成该机组实际天数
        wa.cell(row=4, column=2 + i).value = "=INT(%s3/%d)" % (col, days)
        wa.cell(row=6, column=2 + i).value = (
            "=(7.87/0.86)*(1000000000*((4/3)*3.14*(40/2000000)^3*%s3)"
            "/(3.14*(7/1000)^2*0.64*3600*24*%d))" % (col, days))
    wa["B7"].number_format = "0.00E+00"
    wa["G7"].number_format = "0.00E+00"
    wa["B8"] = analysis["conclusion"]
    fill = PatternFill(start_color=analysis["color"], end_color=analysis["color"], fill_type="solid")
    for c in range(2, 13):
        cell = wa.cell(row=8, column=c)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    _rebuild_wear_charts(wb, ws, last_row)

    wb.save(out_path)
    return out_path


def build_wear_summary(analyses, out_path):
    """机组磨损数值汇总.xlsx"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "汇总数据"
    ws.append(["机组编号", "年月", "B7浓度(铁磁性mg/kg)", "G7浓度(非铁磁性mg/kg)", "分析结论"])
    for cell in ws[1]:
        cell.font = Font(name=UI_FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for unit, ym, b7, g7, conclusion in analyses:
        ws.append([unit, ym,
                   round(b7, 4) if b7 is not None else "",
                   round(g7, 4) if g7 is not None else "",
                   conclusion])
    for col, width in (("A", 12), ("B", 10), ("C", 22), ("D", 24), ("E", 60)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        row[4].alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "A2"
    wb.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# 项目级油品分析报告（Word）
#   封面 → 报告总览 → 结论判断依据 → 逐台机组（月度表 + 累计/增量趋势图 + 评估/结论）
# ---------------------------------------------------------------------------
REPORT_COMPANY = "珠海市鑫世达测控技术有限公司"
REPORT_AUTHOR = "曹居易"
REPORT_REVIEWER = "王振尧"

# 报告判定阈值（按现场报告口径）：
#   铁磁 0-20 正常 / 20-25 预警 / >25 报警
#   非铁磁 0-15 正常 / 15-20 预警 / >20 报警
#   NAS <9 正常 / =9 预警 / >=10 报警
#   AW 0-80 正常 / 80-90 预警 / >90 报警
#   VT40 以 320 为基准：272~368 正常 / ≤272 或 ≥368 预警 / ≤256 或 ≥384 报警
REPORT_LIMITS = {
    "ferrous": (20.0, 25.0),
    "nonferrous": (15.0, 20.0),
}
NAS_LIMITS = (9.0, 11.0)
AW_LIMITS = (80.0, 90.0)
VT40_NOMINAL = 320.0
VT40_WARN = (272.0, 368.0)
VT40_ALARM = (256.0, 384.0)


def _csv_columns(path, start=None, end=None):
    rows = []
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", newline="", encoding=enc) as fp:
                rows = [r for r in csv.reader(fp) if r]
            break
        except UnicodeDecodeError:
            continue
    if len(rows) < 2:
        return {}
    header = [h.strip() for h in rows[0]]
    cols = {}
    for i, h in enumerate(header[1:], start=1):
        if not h:
            continue
        vals = []
        for r in rows[1:]:
            if start or end:
                t = parse_datetime_text(r[0]) if r else None
                if t is None:
                    continue
                d = t.date()
                if start and d < start:
                    continue
                if end and d > end:
                    continue
            if i < len(r):
                try:
                    vals.append(float(r[i]))
                except (TypeError, ValueError):
                    pass
        if vals:
            cols[h] = vals
    return cols


def _find_unit_file(store, project, unit, keyword):
    aliases = {"磨损": ("磨损", "mosun"), "水分": ("水分", "shuifen"),
               "清洁度": ("清洁度", "qingjiedu", "clean"), "粘度": ("粘度", "niandu", "vis")}
    tokens = aliases.get(keyword, (keyword,))
    for f in store.file_info().values():
        if f["project"] != project:
            continue
        base = f["vpath"].split("/")[-1]
        if not base.lower().endswith(".csv") or guess_device(f["vpath"]) != unit:
            continue
        low = base.lower()
        if any(tok in low for tok in tokens):
            return f
        # 「Oil宾泉风电场_#01_2026-10.csv」这类合并文件：磨损和水分在同一份 CSV 里
        if keyword in ("磨损", "水分") and low.startswith("oil"):
            return f
    return None


def _mean(values):
    return sum(values) / len(values) if values else None


def _judge_max(value, limits):
    """阈值判定：≤正常上限为正常；严格介于上限与报警线之间为预警；达到报警线即报警。"""
    if value is None:
        return "—"
    ok, warn = limits
    if value <= ok:
        return "正常"
    if value < warn:
        return "预警"
    return "报警"


def _judge_nas(value):
    if value is None:
        return "—"
    v = round(value)
    if v <= NAS_LIMITS[0]:
        return "正常"
    if v < NAS_LIMITS[1]:
        return "预警"
    return "报警"


def _judge_aw(value):
    if value is None:
        return "—"
    v = round(value, 1)
    if v <= AW_LIMITS[0]:
        return "正常"
    if v <= AW_LIMITS[1]:
        return "预警"
    return "报警"


def _judge_vt40(value):
    if value is None:
        return "—"
    v = round(value)
    warn_lo, warn_hi = VT40_WARN
    alarm_lo, alarm_hi = VT40_ALARM
    if warn_lo < v < warn_hi:
        return "正常"
    if alarm_lo < v <= warn_lo or warn_hi <= v < alarm_hi:
        return "预警"
    return "报警"


def collect_report_metrics(store, project, start=None, end=None):
    """收集报告需要的数据：每台机组 B7/G7、NAS、AW、VT40（可限定时间段）。"""
    units = sorted({guess_device(f["vpath"]) for f in store.file_info().values()
                    if f["project"] == project} or set(store.distinct("device", project or None)))
    units.sort(key=lambda d: int(re.sub(r"\D", "", d) or 0) if re.search(r"\d", d) else 9999)
    out = []
    for unit in units:
        item = {"unit": unit, "wear": None, "b7": None, "g7": None,
                "nas": None, "aw": None, "vt40": None,
                "nas_vals": [], "aw_vals": [], "ppm_vals": [], "vt_vals": []}
        wf = _find_unit_file(store, project, unit, "磨损")
        if wf:
            rows = filter_rows_by_window(load_wear_csv(wf["real_path"]), start, end)
            if len(rows) >= 3:
                item["wear"] = analyze_wear(rows)
                item["b7"] = item["wear"]["b7"]
                item["g7"] = item["wear"]["g7"]
        wf = _find_unit_file(store, project, unit, "水分")
        if wf:
            cols = _csv_columns(wf["real_path"], start, end)
            item["aw_vals"] = cols.get("水分传感器湿度") or cols.get("湿度aw") or []
            item["ppm_vals"] = cols.get("水分传感器PPM") or cols.get("PPM") or []
            item["aw"] = _mean(item["aw_vals"])
        wf = _find_unit_file(store, project, unit, "清洁度")
        if wf:
            cols = _csv_columns(wf["real_path"], start, end)
            nas = [v for v in cols.get("NAS5-15", []) if v >= 0]
            item["nas_vals"] = nas
            item["nas"] = round(_mean(nas), 1) if nas else None
        wf = _find_unit_file(store, project, unit, "粘度")
        if wf:
            cols = _csv_columns(wf["real_path"], start, end)
            item["vt_vals"] = cols.get("粘度VT40", [])
            item["vt40"] = _mean(item["vt_vals"])
        out.append(item)
    return out


def _wear_figures(analysis, unit, out_dir):
    """生成 4 张图：铁磁/非铁磁 × 累计/增量（每张 5 个粒径通道）。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    fixed = analysis["fixed"]
    times = [t for t, _ in fixed]
    series = [[vals[i] for _, vals in fixed] for i in range(10)]
    os.makedirs(out_dir, exist_ok=True)
    paths = []

    def render(indices, title, increments, filename):
        from matplotlib.dates import AutoDateLocator, DateFormatter
        from matplotlib.ticker import MaxNLocator, StrMethodFormatter

        fig = Figure(figsize=(9.0, 5.0), dpi=110)
        for k, idx in enumerate(indices):
            ax = fig.add_subplot(3, 2, k + 1)
            ys = series[idx]
            if increments:
                ys = [None] + [max(0.0, ys[i] - ys[i - 1]) for i in range(1, len(ys))]
            ax.plot(times, ys, linewidth=0.9, color=COLOR_ACCENT)
            ax.set_title(WEAR_BIN_LABELS[idx] + ("（增量）" if increments else ""),
                         fontsize=7, loc="left")
            ax.grid(True, color="#eef2f7", linewidth=0.7)
            ax.tick_params(labelsize=6, colors="#5b6b7d")
            ax.xaxis.set_major_locator(AutoDateLocator(minticks=3, maxticks=4))
            ax.xaxis.set_major_formatter(DateFormatter("%m-%d"))
            ax.tick_params(axis="x", labelrotation=30)
            # 纵坐标只显示整数，且不用 1e6 这类科学计数偏移
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
            ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
            vals = [v for v in ys if v is not None]
            if vals:
                lo, hi = min(vals), max(vals)
                if hi == lo:
                    if hi == 0:
                        ax.set_ylim(0, 1)
                    else:
                        pad = max(1.0, abs(hi) * 0.05)
                        ax.set_ylim(lo - pad, hi + pad)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
        fig.tight_layout(pad=0.8)
        path = os.path.join(out_dir, filename)
        fig.savefig(path, dpi=110, bbox_inches="tight")
        paths.append(path)
        return path

    render(range(0, 5), "铁磁性磨粒积累分级趋势图", False, "%s_铁磁累计.png" % unit)
    render(range(5, 10), "非铁磁性磨粒积累分级趋势图", False, "%s_非铁磁累计.png" % unit)
    render(range(0, 5), "铁磁性磨粒增量图", True, "%s_铁磁增量.png" % unit)
    render(range(5, 10), "非铁磁性磨粒增量图", True, "%s_非铁磁增量.png" % unit)
    return paths


def _sensor_figures(store, project, unit, out_dir, start=None, end=None):
    """水分 / 清洁度 / 粘度趋势图（各一条或两条曲线）。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    specs = [
        ("water", "水分趋势图", "水分", ("湿度", "PPM")),
        ("clean", "清洁度趋势图", "清洁度", ("NAS5-15", "NAS15-25")),
        ("vis", "粘度趋势图", "粘度", ("VT40", "粘度传感器粘度")),
    ]
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for key, title, keyword, tokens in specs:
        f = _find_unit_file(store, project, unit, keyword)
        if not f:
            continue
        times, channels = read_csv_series(f["real_path"], start, end)
        picked = []
        for token in tokens:
            for name, ts, vs in channels:
                if token in name:
                    picked.append((name, ts, vs))
                    break
        if not picked:
            continue
        if key == "clean":
            # NAS 里的 -1 是无效值，画图时剔除
            picked = [(name, ts, [None if (v is not None and v < 0) else v for v in vs])
                      for name, ts, vs in picked]
        from matplotlib.dates import AutoDateLocator, DateFormatter

        fig = Figure(figsize=(9.0, 3.0), dpi=110)
        ax = fig.add_subplot(111)
        ax2 = None
        if key == "water" and len(picked) >= 2:
            name1, ts1, vs1 = picked[0]
            name2, ts2, vs2 = picked[1]
            ax.plot(ts1, vs1, linewidth=0.9, color=COLOR_ACCENT, label=name1)
            ax2 = ax.twinx()
            ax2.plot(ts2, vs2, linewidth=0.9, color="#E8873A", label=name2)
            ax2.tick_params(labelsize=7, colors="#E8873A")
            for spine in ("top",):
                ax2.spines[spine].set_visible(False)
        else:
            for name, ts, vs in picked[:2]:
                ax.plot(ts, vs, linewidth=0.9, label=name)
        ax.grid(True, color="#eef2f7", linewidth=0.7)
        ax.tick_params(labelsize=7, colors="#5b6b7d")
        ax.xaxis.set_major_locator(AutoDateLocator(minticks=3, maxticks=5))
        ax.xaxis.set_major_formatter(DateFormatter("%m-%d"))
        ax.tick_params(axis="x", labelrotation=30)
        handles, labels = ax.get_legend_handles_labels()
        if ax2 is not None:
            h2, l2 = ax2.get_legend_handles_labels()
            handles += h2
            labels += l2
        ax.legend(handles, labels, fontsize=7, frameon=False, loc="upper right")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        fig.tight_layout(pad=0.6)
        path = os.path.join(out_dir, "%s_%s.png" % (unit, key))
        fig.savefig(path, dpi=110, bbox_inches="tight")
        paths[key] = path
    return paths


def _month_wear_table(doc, wear):
    """按模板版式画「月度磨粒分析」表（黄标题、合并 B7/G7、绿色结论行）。"""
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Cm

    table = doc.add_table(rows=0, cols=12)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    widths = [Cm(2.6)] + [Cm(1.28)] * 10 + [Cm(1.35)]
    for row in table.rows:
        for i, width in enumerate(widths):
            row.cells[i].width = width

    row = table.add_row()
    merged = row.cells[0].merge(row.cells[11])
    _docx_cell(merged, "月度磨粒分析\n(按照电动泵流量75L/min（0.64m/s）计算)",
               size=10, bold=True, align="center")
    _docx_shade(merged, "FFF2CC")

    header_row = table.add_row()
    _docx_cell(header_row.cells[0], "项目", size=6.5, bold=True, align="center")
    _docx_shade(header_row.cells[0], "DCE6F1")
    channel_names = [str(h) for h in wear["rows"][0][1:11]]
    for i, name in enumerate(channel_names, start=1):
        _docx_cell(header_row.cells[i], name, size=5, bold=True, align="center")
        _docx_shade(header_row.cells[i], "DCE6F1")
    _docx_cell(header_row.cells[11], "总计", size=6.5, bold=True, align="center")
    _docx_shade(header_row.cells[11], "DCE6F1")

    for label, values, fmt in (
            ("颗粒数", wear["sums"], "%g"),
            ("颗粒数量个/天", wear["per_day"], "%d"),
            ("颗粒数量个/L", wear["per_l"], "%.4f"),
            ("颗粒浓度mg/kg", wear["conc"], "%.2E")):
        row = table.add_row()
        _docx_cell(row.cells[0], label, size=6.5, bold=True, align="center")
        for i, value in enumerate(values, start=1):
            _docx_cell(row.cells[i], fmt % value, size=6.5, align="center")
        _docx_cell(row.cells[11], fmt % sum(values), size=6.5, align="center")

    row = table.add_row()
    _docx_cell(row.cells[0], "浓度", size=6.5, bold=True, align="center")
    ferro = row.cells[1].merge(row.cells[5])
    _docx_cell(ferro, "%.2f" % wear["b7"], size=6.5, align="center")
    nonferro = row.cells[6].merge(row.cells[10])
    _docx_cell(nonferro, "%.2f" % wear["g7"], size=6.5, align="center")
    _docx_cell(row.cells[11], "", size=6.5)

    row = table.add_row()
    _docx_cell(row.cells[0], "结论", size=7, bold=True, align="center")
    body = row.cells[1].merge(row.cells[11])
    _docx_cell(body, wear["conclusion"], size=7, align="center")
    _docx_shade(body, "AACC99")

    for row in table.rows:
        for i, width in enumerate(widths):
            row.cells[i].width = width
    _docx_table_borders(table)
    _docx_table_layout(table)
    _docx_row_heights(table, header=1.0, body=0.8, skip=1)
    return table


def _fmt_num(value, nd=2):
    return "—" if value is None else ("%.*f" % (nd, value))


def _validity_text(end):
    """监测结果有效期：统计截止日期后的一个月。"""
    if not end:
        return "本监测结果有效期为报告出具后 1 个月。"
    import calendar

    year, month = end.year, end.month + 1
    if month > 12:
        year, month = year + 1, 1
    day = min(end.day, calendar.monthrange(year, month)[1])
    return "本监测结果有效期至 %d 年 %d 月 %d 日。" % (year, month, day)


def _unit_assessment(item, start, end, cap=None):
    """按本期全部监测数据生成评估段落与诊断结论条目。

    cap 表示项目里实际存在的数据类型（磨损/水分/清洁度/粘度），
    项目本身没有的指标不提示“数据异常”。
    """
    cap = cap or {"wear": True, "water": True, "clean": True, "vis": True}
    wear = item.get("wear")
    nas_vals = item.get("nas_vals") or []
    aw_vals = item.get("aw_vals") or []
    ppm_vals = item.get("ppm_vals") or []
    vt_vals = item.get("vt_vals") or []

    if not wear and not nas_vals and not aw_vals and not vt_vals:
        return ["本月无数据存储。"], []

    paragraphs, threshold_issues, data_issues = [], [], []
    statuses = []

    # 磨损
    wear_special = None
    if cap["wear"] and wear:
        f_st = _judge_max(item["b7"], REPORT_LIMITS["ferrous"])
        nf_st = _judge_max(item["g7"], REPORT_LIMITS["nonferrous"])
        statuses += [f_st, nf_st]
        if wear.get("zero"):
            wear_special = "清零"
            paragraphs.append("通过磨损浓度数据观察到机组磨损数据清零无法判断机组运行状态，"
                              "建议检查采集设备和传感器的运行状况。")
        elif wear.get("constant"):
            wear_special = "保持不变"
            paragraphs.append("通过磨损浓度数据观察到机组磨损数据保持不变无法判断机组运行状态，"
                              "建议检查采集设备和传感器的运行状况。")
        else:
            paragraphs.append("通过磨损浓度数据和实时积累与增量数据，%s" % wear["conclusion"])
        if "预警" in (f_st, nf_st) or "报警" in (f_st, nf_st):
            threshold_issues.append(("磨损", "报警" if "报警" in (f_st, nf_st) else "预警"))
    elif cap["wear"]:
        paragraphs.append("本期未采集到磨损监测数据，无法评估磨粒浓度与增长趋势。")
        data_issues.append("磨损")

    # 清洁度
    if cap["clean"] and nas_vals:
        mean = sum(nas_vals) / len(nas_vals)
        lo, hi = min(nas_vals), max(nas_vals)
        st = _judge_nas(mean)
        statuses.append(st)
        base = ("通过清洁度趋势图可见，机组齿轮箱润滑油 NAS 等级平均值为 %.1f，"
                "整体处于 %d~%d 区间" % (mean, lo, hi))
        if st == "正常":
            paragraphs.append(base + "，处于正常范围，油液清洁度良好。")
        else:
            paragraphs.append(base + "，油液中颗粒污染物含量偏高，且存在明显波动，可能存在污染物"
                                    "持续侵入或过滤净化效果不稳定的情况，对齿轮及轴承的磨损防护构成潜在风险。")
            threshold_issues.append(("清洁度", st))
    elif cap["clean"]:
        paragraphs.append("本期未采集到清洁度监测数据。")
        data_issues.append("清洁度")

    # 水分
    if cap["water"] and aw_vals:
        aw_mean = sum(aw_vals) / len(aw_vals)
        ppm_mean = sum(ppm_vals) / len(ppm_vals) if ppm_vals else None
        st = _judge_aw(aw_mean)
        statuses.append(st)
        base = "通过水分趋势图可见，机组水分 AW 平均值为 %.1f" % aw_mean
        if ppm_mean is not None:
            base += "，水分 PPM 平均值为 %.0f" % ppm_mean
        if st == "正常":
            paragraphs.append(base + "，两项指标随时间呈波动变化，总体处于受控范围内，"
                                    "未出现明显异常偏离，机组运行状态稳定。")
        else:
            paragraphs.append(base + "，已超出正常范围，需检查密封、呼吸器及油品乳化情况。")
            threshold_issues.append(("水分", st))
    elif cap["water"]:
        paragraphs.append("本期未采集到水分监测数据。")
        data_issues.append("水分")

    # 粘度
    if cap["vis"] and vt_vals:
        mean = sum(vt_vals) / len(vt_vals)
        lo, hi = min(vt_vals), max(vt_vals)
        st = _judge_vt40(mean)
        statuses.append(st)
        base = ("通过粘度 VT40 趋势图可见，机组齿轮箱润滑油 VT40 平均值为 %.0f mm²/s，"
                "数值主要集中在 %.0f~%.0f 之间" % (mean, lo, hi))
        if st == "正常":
            paragraphs.append(base + "，处于齿轮箱常用润滑油粘度等级的合理范围内，毛刺是由流速、"
                                    "气泡、振动等引起的冲击，未出现明显劣化，润滑性能良好。")
        else:
            paragraphs.append(base + "，偏离正常区间，需结合油品化验结果确认是否混油、进水或油品劣化。")
            threshold_issues.append(("粘度", st))
    elif cap["vis"]:
        paragraphs.append("本期未采集到粘度监测数据。")
        data_issues.append("粘度")

    conclusions = []

    def add_item(name, status):
        if status == "正常":
            conclusions.append("机组%s数据正常。" % name)
        elif status == "报警":
            conclusions.append("机组%s报警，建议 2 周内检查确认。" % name)
        elif status == "预警":
            conclusions.append("机组%s预警，建议 2 个月内检查确认。" % name)
        else:
            conclusions.append("机组%s数据异常。" % name)

    if cap["wear"] and wear:
        if wear_special:
            conclusions.append("机组磨损数据%s。" % wear_special)
        else:
            if "报警" in (f_st, nf_st):
                add_item("磨损", "报警")
            elif "预警" in (f_st, nf_st):
                add_item("磨损", "预警")
            else:
                add_item("磨损", "正常")
    if cap["water"] and item.get("aw") is not None:
        add_item("水分", _judge_aw(item["aw"]))
    if cap["clean"] and item.get("nas") is not None:
        add_item("清洁度", _judge_nas(item["nas"]))
    if cap["vis"] and item.get("vt40") is not None:
        add_item("粘度", _judge_vt40(item["vt40"]))
    for name in data_issues:
        conclusions.append("机组%s数据异常。" % name)
    if not conclusions:
        conclusions.append("本月无数据存储。")
    return paragraphs, conclusions


def _assessment_table(doc, item, cap=None):
    """评估结果里的小结表：指标 / 本期均值 / 参考范围 / 结论。"""
    cap = cap or {"wear": True, "water": True, "clean": True, "vis": True}
    rows = []

    def add(name, value, ref, status):
        rows.append([name, value, ref, status])

    b7, g7 = item["b7"], item["g7"]
    add("铁磁磨粒", (_fmt_num(b7) + " mg/kg") if b7 is not None else "—", "0-20",
        _judge_max(b7, REPORT_LIMITS["ferrous"]) if b7 is not None else "—")
    add("非铁磁磨粒", (_fmt_num(g7) + " mg/kg") if g7 is not None else "—", "0-15",
        _judge_max(g7, REPORT_LIMITS["nonferrous"]) if g7 is not None else "—")
    aw = item["aw"]
    add("水分 AW", _fmt_num(aw, 1) if aw is not None else "—", "0-80",
        _judge_aw(aw) if aw is not None else "—")
    if cap["clean"]:
        nas = item["nas"]
        add("清洁度 NAS", (_fmt_num(nas, 1) + " 级") if nas is not None else "—", "≤9",
            _judge_nas(nas) if nas is not None else "—")
    if cap["vis"]:
        vt = item["vt40"]
        add("粘度 VT40", (_fmt_num(vt, 0) + " mm²/s") if vt is not None else "—", "272~368",
            _judge_vt40(vt) if vt is not None else "—")
    _docx_table(doc, ["监测指标", "本期均值", "参考范围", "结论"], rows,
                widths=[4.2, 4.4, 4.4, 3.2], size=9, align="center")


def _monthly_concentration(store, project, unit):
    """按月份汇总该机组的铁磁/非铁磁颗粒浓度（有几个月数据就返回几个点）。"""
    by_month = {}
    for f in store.file_info().values():
        if f["project"] != project or not is_wear_csv(f["vpath"]):
            continue
        if guess_device(f["vpath"]) != unit:
            continue
        try:
            rows = load_wear_csv(f["real_path"])
        except Exception:  # noqa: BLE001
            continue
        for row in rows[1:]:
            t = _wear_time(row[0])
            if not t:
                continue
            try:
                vals = [float(v) for v in row[1:11]]
            except (TypeError, ValueError):
                continue
            by_month.setdefault(t.strftime("%Y-%m"), []).append((t, vals))
    out = []
    particle_volume = (4.0 / 3.0) * math.pi * (40.0 / 2_000_000.0) ** 3
    for ym in sorted(by_month):
        data = sorted(by_month[ym])
        fixed, prev = [], None
        for _t, vals in data:
            cur = vals[:] if prev is None else [max(vals[i], prev[i]) for i in range(10)]
            fixed.append(cur)
            prev = cur
        first, last = fixed[0], fixed[-1]
        sums = [max(0.0, last[i] - first[i]) for i in range(10)]
        days = max(1, (data[-1][0].date() - data[0][0].date()).days + 1)
        denom = math.pi * WEAR_PIPE_R ** 2 * WEAR_VELOCITY * 3600 * 24 * days
        conc = [(7.87 / 0.86) * (1e9 * particle_volume * s / denom) if denom else 0.0
                for s in sums]
        out.append((ym, sum(conc[:5]), sum(conc[5:])))
    return out


def _concentration_figure(months, unit, out_dir):
    """月度颗粒浓度趋势图：铁磁 / 非铁磁两条线。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    labels = [m[0][2:].replace("-", "/") for m in months]  # 26/10
    ferro = [m[1] for m in months]
    nonferro = [m[2] for m in months]
    fig = Figure(figsize=(9.0, 3.2), dpi=110)
    ax = fig.add_subplot(111)
    ax.plot(labels, ferro, color=COLOR_ACCENT, marker="o", linewidth=1.4, label="铁磁磨粒")
    ax.plot(labels, nonferro, color="#E8873A", marker="s", linewidth=1.4, label="非铁磁磨粒")
    for x, y in zip(labels, ferro):
        ax.annotate("%.2f" % y, (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=COLOR_ACCENT)
    for x, y in zip(labels, nonferro):
        ax.annotate("%.2f" % y, (x, y), textcoords="offset points", xytext=(0, -14),
                    ha="center", fontsize=8, color="#E8873A")
    ax.set_ylabel("浓度 mg/kg", fontsize=9)
    ax.grid(True, color="#eef2f7", linewidth=0.8)
    ax.legend(fontsize=8, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(labelsize=8, colors="#5b6b7d")
    if len(labels) == 1:
        ax.set_xlim(-0.6, 0.6)
    fig.tight_layout(pad=0.8)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s_月度浓度趋势.png" % re.sub(r"[^\w.-]", "_", unit))
    fig.savefig(path, dpi=110, bbox_inches="tight")
    return path


def _docx_bottom_border(paragraph, color="1F3A5F", size=12):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _docx_table_borders(table, color="C9D4E2"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement("w:%s" % edge)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "6")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblPr.append(borders)


def _docx_table_layout(table, header=True, margins=(40, 40, 80, 80)):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for name, val in zip(("top", "bottom", "left", "right"), margins):
        el = OxmlElement("w:%s" % name)
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)
    if header and len(table.rows):
        trPr = table.rows[0]._tr.get_or_add_trPr()
        el = OxmlElement("w:tblHeader")
        el.set(qn("w:val"), "true")
        trPr.append(el)


def _add_field(paragraph, instr, size=9, color="5B6B7D"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    _docx_set_font(run, size=size, color=color)
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1)
    run._r.append(it)
    run._r.append(fld2)
    return run


def _docx_heading(doc, text, level):
    """多级标题：使用 Word 内置 Heading 1~4 样式，便于导航和自动目录。"""
    from docx.shared import Pt

    sizes = {1: 17, 2: 15, 3: 12.5, 4: 11}
    p = doc.add_paragraph(style="Heading %d" % level)
    p.paragraph_format.space_before = Pt(18 if level == 1 else (12 if level == 2 else 8))
    p.paragraph_format.space_after = Pt(10 if level == 1 else 6)
    run = p.add_run(text)
    color = COLOR_HEAD.lstrip("#").upper() if level <= 2 else "2E4A66"
    _docx_set_font(run, size=sizes.get(level, 11), bold=True, color=color)
    if level == 1:
        _docx_bottom_border(p, color="1F3A5F", size=12)
    elif level == 2:
        _docx_bottom_border(p, color="B9C6D6", size=6)
    return p


def overview_trend_text(category, special, display):
    """报告总览表“趋势分析（月度趋势）”列的文字。

    磨损数据“清零/保持不变”说明采集通道可能失效，属于数据异常，
    不能像正常数据那样显示“平稳”（结论列仍按原文写“清零/保持不变”，样式灰色）。
    """
    if category in ("铁磁磨粒", "非铁磁磨粒") and special:
        return "异常"
    return "平稳" if display else "—"


_HIST_CACHE = {}


def _load_history_xlsx(name):
    """从 templates/<name> 读取历史浓度（月份、铁磁、非铁磁）。"""
    if name in _HIST_CACHE:
        return _HIST_CACHE[name]
    data = {}
    path = os.path.join(APP_DIR, "templates", name)
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            rows = []
            for r in ws.iter_rows(values_only=True):
                month = None
                for v in r:
                    if isinstance(v, str) and re.fullmatch(r"20\d\d\.\d+", v.strip()):
                        month = v.strip()
                        break
                nums = [v for v in r if isinstance(v, (int, float)) and 0 <= v < 1000]
                if not month or len(nums) < 2 or month == "2025.12":
                    continue
                rows.append((month, nums[0], nums[1]))
            if rows:
                data[ws.title] = sorted(rows, key=lambda x: tuple(map(int, x[0].split("."))))
    except Exception:
        data = {}
    _HIST_CACHE[name] = data
    return data


def load_report_config(project, config_dir=None):
    """按项目名匹配 templates/*_报告配置.json，返回配置 dict；无匹配返回 None。

    匹配顺序：① 配置里的 project 字段与实际项目名互相包含；② 文件名前缀
    （如 营盘梁_报告配置.json → 营盘梁）出现在项目名里。
    读取用 utf-8-sig，容忍记事本另存产生的 BOM；坏文件跳过不抛异常。
    """
    config_dir = config_dir or os.path.join(APP_DIR, "templates")
    if not os.path.isdir(config_dir):
        return None
    proj = str(project or "")
    for name in sorted(os.listdir(config_dir)):
        if not name.lower().endswith(".json") or "报告配置" not in name:
            continue
        path = os.path.join(config_dir, name)
        try:
            with open(path, encoding="utf-8-sig") as fp:
                cfg = json.load(fp)
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        cfg_proj = str(cfg.get("project") or "")
        stem = name.split("_报告配置")[0]
        if (cfg_proj and (cfg_proj in proj or proj in cfg_proj)) or (stem and stem in proj):
            cfg["_path"] = path
            return cfg
    return None


def report_unit_count(project, config_dir=None):
    """报告要覆盖的机组台数：优先读配置 unit_count，否则沿用历史硬编码规则。

    返回 (台数, 配置dict或None)。0 表示不补齐空机组。
    """
    cfg = load_report_config(project, config_dir)
    if cfg is not None:
        raw = cfg.get("unit_count")
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n, cfg
    proj = str(project or "")
    if "营盘梁" in proj or "岱海" in proj:
        return 75, cfg          # 历史规则，无配置文件时的兜底
    return 0, cfg


def build_analysis_report_docx(project, store, out_dir, start=None, end=None):
    """按项目生成油品分析报告（Word），可限定统计时间段。"""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    from docx.oxml.ns import qn

    entries = collect_report_metrics(store, project, start, end)
    if not entries:
        raise ValueError("没有可生成报告的机组数据")
    # 项目里实际有哪些数据类型：没有的类型不出现在总览表、也不生成章节
    cap = {
        "wear": any(e["wear"] for e in entries),
        "water": any(e["aw_vals"] for e in entries),
        "clean": any(e["nas_vals"] for e in entries),
        "vis": any(e["vt_vals"] for e in entries),
    }
    # 报告覆盖的机组台数：templates/<项目>_报告配置.json 的 unit_count 优先，
    # 没有配置则沿用历史规则（营盘梁/岱海 = 75 台）。缺数据的机组补空记录。
    _declared = report_unit_count(project)[0]
    if _declared:
        _have = {e["unit"] for e in entries}
        for _i in range(1, _declared + 1):
            _u = "%d#" % _i
            if _u in _have:
                continue
            entries.append({"unit": _u, "wear": None, "b7": None, "g7": None,
                            "nas": None, "aw": None, "vt40": None,
                            "nas_vals": [], "aw_vals": [], "ppm_vals": [], "vt_vals": []})
        entries.sort(key=lambda e: int(re.sub(r"\D", "", e["unit"]) or 0))

    today = datetime.now()
    month_text = None
    months = [e["wear"]["ym_trend"] for e in entries if e["wear"] and e["wear"].get("ym_trend")]
    if months:
        latest = max(months)  # "2026.09"
        try:
            year, month = latest.split(".")
            month_text = "%s年%s月份" % (year, month)
        except ValueError:
            month_text = None
    if not month_text:
        month_text = "%d年%02d月份" % (today.year, today.month)
    title = "风力发电机组%s油品分析报告" % month_text

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    style = doc.styles["Normal"]
    style.font.name = UI_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), UI_FONT)
    style.paragraph_format.line_spacing = 1.3
    style.paragraph_format.space_after = Pt(4)

    # 页眉 / 页脚（封面不显示）
    sec.different_first_page_header_footer = True
    sec.header_distance = Cm(1.2)
    sec.footer_distance = Cm(1.2)
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run("%s · %s" % (project, title))
    _docx_set_font(hr, size=8, color="8A99AA")
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _docx_set_font(fp.add_run("第 "), size=9, color="5B6B7D")
    _add_field(fp, "PAGE")
    _docx_set_font(fp.add_run(" 页 / 共 "), size=9, color="5B6B7D")
    _add_field(fp, "NUMPAGES")
    _docx_set_font(fp.add_run(" 页"), size=9, color="5B6B7D")

    # 封面
    period_text = ("%s 至 %s" % (start.isoformat(), end.isoformat())
                   if (start and end) else month_text)
    for _ in range(4):
        doc.add_paragraph()
    _docx_para(doc, project + "风电场", size=22, bold=True, color="1F3A5F", align="center", after=10)
    _docx_para(doc, "风力发电机组%s" % month_text, size=24, bold=True, color="0F2A46",
               align="center", after=6)
    _docx_para(doc, "油品分析报告", size=24, bold=True, color="0F2A46", align="center", after=16)
    rule = _docx_para(doc, "", size=6, after=12)
    _docx_bottom_border(rule, "C8A96A", 10)
    _docx_para(doc, "监测期间：%s" % period_text, size=11, color="5B6B7D", align="center", after=90)
    _docx_para(doc, REPORT_COMPANY, size=14, bold=True, color="1F3A5F", align="center", after=8)
    _docx_para(doc, "报告编写：" + REPORT_AUTHOR, size=11, align="center", after=4)
    _docx_para(doc, "报告审阅：" + REPORT_REVIEWER, size=11, align="center", after=4)
    _docx_para(doc, "报告日期：" + today.strftime("%Y年%m月%d日"), size=11, align="center", after=4)
    doc.add_page_break()

    # 宾泉项目：插入参考报告的一~六章（监测目的/依据/方法/工具/对象/测点）
    if "宾泉" in project:
        _docx_heading(doc, "一、监测目的", 1)
        _docx_para(doc, "风电齿轮箱在长期高负荷下运行，齿轮和轴承不可避免地产生磨损，而金属颗粒是其最直接、"
                        "最敏感的早期故障信号。通过油液中的金属磨损监测，可以在振动或温度等宏观异常出现之前"
                        "捕捉到齿面点蚀、疲劳剥落等微小缺陷，及时发现潜在隐患，避免颗粒在油液中循环造成二次磨损。"
                        "若缺乏监测，往往会导致磨损加剧直至齿轮断齿或轴承失效，造成风机停机和高昂损失。因此，"
                        "金属磨损在线监测是保障风电齿轮箱可靠性和实现预测性维护的关键。", size=10.5, after=6)
        _docx_heading(doc, "二、监测依据", 1)
        _docx_para(doc, "主要依据风电机组齿轮箱在线润滑油状态监测系统现场采集油品状态数据，对风电机组油品状态"
                        "进行三等级划分，见表 1。", size=10.5, after=6)
        _docx_para(doc, "表 1 报警等级划分", size=9, align="center", after=4)
        _rows = [["铁磁磨粒", "0-20", "20~<25", "≥25"],
                 ["非铁磁磨粒", "0-15", "15~<20", "≥20"]]
        if cap["water"]:
            _rows.append(["水分(AW)", "0-80", "80-90", ">90"])
        _docx_table(doc, ["类别", "正常", "阈值（mg/kg）\n第一限度预警", "阈值（mg/kg）\n第二限度报警"],
                    _rows, widths=[4.0, 3.4, 5.0, 5.0], size=9, align="center")
        _docx_para(doc, "", size=8, after=4)
        _docx_para(doc, "正常：机组处于正常状态，可照常运行。", size=10, after=2)
        _docx_para(doc, "预警：机组存在较明显的故障特征，机组可继续运行，现场维护人员需在 2 个月内检查确认故障，"
                        "择机进行维修措施。", size=10, after=2)
        _docx_para(doc, "报警：机组故障特征明显，故障处于劣化期，现场维护人员需在 2 周内检查确认故障，"
                        "择机进行维修措施。", size=10, after=2)
        _docx_heading(doc, "三、监测方法", 1)
        _docx_para(doc, "应用风电机组在线润滑油油品状态监测系统，在线连续采集机组关键测点的油品状态磨损信号，"
                        "实时进行信号处理分析和存储，显示机组当前状态及其历史变化过程。", size=10.5, after=6)
        _docx_heading(doc, "四、监测工具", 1)
        _docx_para(doc, "风电机组在线润滑油油品状态监测系统。", size=10.5, after=6)
        _docx_heading(doc, "五、监测对象", 1)
        _docx_para(doc, "机组基本信息见表 2。", size=10.5, after=6)
        _docx_para(doc, "表 2 机组信息", size=9, align="center", after=4)
        _docx_table(doc, ["项目", "内容"],
                    [["机组位号", "#01-#18"],
                     ["机组型号", "运达 WD200-5560 风力发电机组"],
                     ["风电齿轮箱", "在线油品监测系统 1 套"],
                     ["运行状态", "运行"],
                     ["监测周期", "在线连续监测"]],
                    widths=[5.0, 11.0], size=9, align="center")
        _docx_heading(doc, "六、测点位置", 1)
        _docx_para(doc, "机组齿轮箱润滑油油品状态监测系统安装在齿轮箱润滑油回路的关键测点，"
                        "在线采集磨粒、水分等油品状态信号。", size=10.5, after=6)
        # 一~六章正文统一 1.5 倍行距
        _started = False
        for _p in doc.paragraphs:
            _t = _p.text.strip()
            if _t.startswith("一、监测目的"):
                _started = True
                continue
            if _started and not _t.startswith(("二、", "三、", "四、", "五、", "六、")):
                _p.paragraph_format.line_spacing = 1.5
        doc.add_page_break()

    # 报告总览
    _docx_heading(doc, "报告总览", 1)
    _kinds = []
    if cap.get("wear"):
        _kinds.append("磨损")
    if cap.get("water"):
        _kinds.append("水分")
    if cap.get("clean"):
        _kinds.append("清洁度")
    if cap.get("vis"):
        _kinds.append("粘度")
    if len(_kinds) > 1:
        _kinds_text = "、".join(_kinds[:-1]) + "和" + _kinds[-1]
    else:
        _kinds_text = _kinds[0] if _kinds else "磨损"
    _overview_intro = _docx_para(doc, "通过分析%s各机组%s数据，得出以下结论：" % (month_text, _kinds_text),
                                 size=10.5, after=6)
    _overview_intro.paragraph_format.line_spacing = 1.5
    # 无数据机组、报警/预警机组汇总
    _nodata = [e["unit"] for e in entries
               if not any(e[k] is not None for k in ("b7", "g7", "nas", "aw", "vt40"))]
    _faults = []
    for e in entries:
        if not any(e[k] is not None for k in ("b7", "g7", "nas", "aw", "vt40")):
            continue
        _u = e["unit"]
        if e.get("wear"):
            _st = ("报警" if "报警" in (_judge_max(e["b7"], REPORT_LIMITS["ferrous"]),
                                        _judge_max(e["g7"], REPORT_LIMITS["nonferrous"]))
                   else ("预警" if "预警" in (_judge_max(e["b7"], REPORT_LIMITS["ferrous"]),
                                              _judge_max(e["g7"], REPORT_LIMITS["nonferrous"]))
                         else None))
            if _st:
                _faults.append("%s 磨损%s" % (_u, _st))
        if e.get("nas") is not None:
            _st = _judge_nas(e["nas"])
            if _st in ("报警", "预警"):
                _faults.append("%s 清洁度%s" % (_u, _st))
        if e.get("aw") is not None:
            _st = _judge_aw(e["aw"])
            if _st in ("报警", "预警"):
                _faults.append("%s 水分%s" % (_u, _st))
        if e.get("vt40") is not None:
            _st = _judge_vt40(e["vt40"])
            if _st in ("报警", "预警"):
                _faults.append("%s 粘度%s" % (_u, _st))
    _parts = []
    if _nodata:
        _parts.append("本月%s共%d台机组无数据存储" % ("、".join(_nodata), len(_nodata)))
    if _faults:
        _parts.append("，".join(_faults))
    if _parts:
        _sum_p = _docx_para(doc, "；".join(_parts) + "。", size=10.5, after=6)
        _sum_p.paragraph_format.line_spacing = 1.5
    headers = ["机组号", "类别", "数值", "趋势分析（月度趋势）", "结论"]
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        _docx_cell(table.rows[0].cells[i], h, size=9, bold=True, color="FFFFFF", align="center")
        _docx_shade(table.rows[0].cells[i], "1F3A5F")
    for item in entries:
        unit = item["unit"]
        has_any = any(item[k] is not None for k in ("b7", "g7", "nas", "aw", "vt40"))
        if not has_any:
            _cats = []
            if cap.get("wear"):
                _cats += ["铁磁磨粒", "非铁磁磨粒"]
            if cap.get("clean"):
                _cats.append("清洁度（NAS）")
            if cap.get("water"):
                _cats.append("水分(AW)")
            if cap.get("vis"):
                _cats.append("粘度(VT40)")
            _rows = []
            for _c in _cats:
                row = table.add_row().cells
                _rows.append(row)
                _docx_cell(row[1], _c, size=9, align="center")
                _docx_cell(row[2], "—", size=9, align="center")
                _docx_cell(row[3], "—", size=9, align="center")
                _docx_cell(row[4], "本月无数据存储。", size=9, align="center")
            if _rows:
                merged = _rows[0][0].merge(_rows[-1][0])
                _docx_cell(merged, unit, size=9, align="center")
            continue
        _wear = item.get("wear") or {}
        _special = "清零" if _wear.get("zero") else ("保持不变" if _wear.get("constant") else None)
        rows_def = [
            ("铁磁磨粒", item["b7"], _special or _judge_max(item["b7"], REPORT_LIMITS["ferrous"]),
             "%.2f" % max(item["b7"], 0.01) if item["b7"] is not None else ""),
            ("非铁磁磨粒", item["g7"], _special or _judge_max(item["g7"], REPORT_LIMITS["nonferrous"]),
             "%.2f" % max(item["g7"], 0.01) if item["g7"] is not None else ""),
            ("水分(AW)", item["aw"], _judge_aw(item["aw"]),
             "%.1f" % item["aw"] if item["aw"] is not None else ""),
        ]
        if cap["clean"]:
            rows_def.append(("清洁度（NAS）", item["nas"], _judge_nas(item["nas"]),
                             "%d" % round(item["nas"]) if item["nas"] is not None else ""))
        if cap["vis"]:
            rows_def.append(("粘度(VT40)", item["vt40"], _judge_vt40(item["vt40"]),
                             "%d" % round(item["vt40"]) if item["vt40"] is not None else ""))
        start_row = len(table.rows)
        for category, _value, conclusion, display in rows_def:
            row = table.add_row().cells
            _docx_cell(row[1], category, size=9, align="center")
            _docx_cell(row[2], display, size=9, align="center")
            # 磨损清零/保持不变：趋势列写“异常”，结论列仍是“清零/保持不变”，整行灰色
            _wear_special = bool(_special) and category in ("铁磁磨粒", "非铁磁磨粒")
            _trend = overview_trend_text(category, _special, display)
            _docx_cell(row[3], _trend, size=9, align="center",
                       color="808080" if _wear_special else None)
            if _wear_special:
                color = "808080"          # 数据清零/保持不变：结论按灰色（数据问题，非阈值报警）
            else:
                color = STATUS_COLOR.get(conclusion) if conclusion in STATUS_COLOR else None
                if conclusion in ("清零", "异常"):
                    color = "808080"
            _docx_cell(row[4], conclusion, size=9, align="center", color=color, bold=bool(color))
            if conclusion == "预警":
                _docx_shade(row[4], "FFFF99")
            elif conclusion == "报警":
                _docx_shade(row[4], "FFC7CE")
        first = table.cell(start_row, 0)
        last = table.cell(len(table.rows) - 1, 0)
        merged = first.merge(last)
        _docx_cell(merged, unit, size=9, bold=True, align="center")
    for row in table.rows:
        row.cells[0].width = Cm(1.8)
        row.cells[1].width = Cm(3.4)
        row.cells[2].width = Cm(3.0)
        row.cells[3].width = Cm(4.2)
        row.cells[4].width = Cm(3.0)
    _docx_table_borders(table)
    _docx_table_layout(table)

    # 判断依据（宾泉报告已在前面的「二、监测依据」里给出表1，不重复）
    if "宾泉" not in project:
        _docx_heading(doc, "结论判断依据", 1)
        th = ["类别", "正常", "阈值（mg/kg）\n第一限度预警", "阈值（mg/kg）\n第二限度报警"]
        trs = [
            ("铁磁磨粒", "0-20", "20~<25", "≥25"),
            ("非铁磁磨粒", "0-15", "15~<20", "≥20"),
            ("水分(AW)", "0-80", "80-90", ">90"),
        ]
        if cap["clean"]:
            trs.append(("清洁度（NAS）", "≤9", "10", "≥11"))
        if cap["vis"]:
            trs.append(("粘度(VT40)", "320", "≤272 或者 ≥368", "≤256 或者 ≥384"))
        _docx_table(doc, th, [list(r) for r in trs], widths=[4.0, 3.4, 5.0, 5.0], size=9, align="center")
        _docx_para(doc, "", size=8, after=4)
        _docx_para(doc, "正常：机组处于正常状态，可照常运行。", size=10, after=2)
        _docx_para(doc, "预警：机组存在较明显的故障特征，机组可继续运行，现场维护人员需在 2 个月内检查确认故障，择机进行维修措施。", size=10, after=2)
        _docx_para(doc, "报警：机组故障特征明显，故障处于劣化期，现场维护人员需在 2 周内检查确认故障，择机进行维修措施。", size=10, after=2)

    # 详细分析数据
    doc.add_page_break()
    _docx_heading(doc, "详细分析数据", 1)
    chart_dir = os.path.join(out_dir, "charts")
    first_unit = True
    for item in entries:
        unit = item["unit"]
        wear = item["wear"]
        if not first_unit:
            doc.add_page_break()
        first_unit = False

        if not (wear or item["nas_vals"] or item["aw_vals"] or item["vt_vals"]):
            _docx_heading(doc, "%s风机" % unit, 2)
            _docx_para(doc, "本月无数据存储。", size=11, after=6)
            continue

        _docx_heading(doc, "%s风机" % unit, 2)
        sensor_imgs = _sensor_figures(store, project, unit, chart_dir, start, end)

        if cap["wear"]:
            _docx_heading(doc, "1 机组月度磨损与颗粒浓度情况", 3)
            _docx_heading(doc, "1.1 月度磨损基本情况", 4)
            if wear:
                _month_wear_table(doc, wear)
                _docx_heading(doc, "1.2 月度颗粒浓度趋势图", 4)
                months = _monthly_concentration(store, project, unit)
                _hist_src = None
                if "旺海装" in project or "汪海庄" in project:
                    _hist_src = _load_history_xlsx("旺海装_历史浓度.xlsx")
                elif "宾泉" in project:
                    _hist_src = BINQUAN_HISTORY
                elif "营盘梁" in project:
                    _hist_src = YINGPAN_HISTORY
                if _hist_src and unit in _hist_src:
                    hist = []
                    for _m, _f, _n in _hist_src[unit]:
                        _y, _mm = _m.split(".")
                        hist.append(("%s-%02d" % (_y, int(_mm)), _f, _n))
                    have = {m for m, _f, _n in hist}
                    months = hist + [x for x in months if x[0] not in have]
                if months:
                    img = _concentration_figure(months, unit, chart_dir)
                    doc.add_picture(img, width=Cm(14.5))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                    if len(months) == 1:
                        _docx_para(doc, "注：目前仅导入本期数据，后续月份数据导入后会自动形成月度趋势。",
                                   size=8, color="7A8797", after=6)
            else:
                _docx_para(doc, "本期没有磨损数据。", size=10, after=8)

        if wear:
            paths = _wear_figures(wear, unit, chart_dir)
            _docx_heading(doc, "2 月份磨粒实时积累趋势图", 3)
            _docx_heading(doc, "2.1 铁磁性磨粒积累分级趋势图", 4)
            doc.add_picture(paths[0], width=Cm(15.8))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_heading(doc, "2.2 非铁磁性磨粒积累分级趋势图", 4)
            doc.add_picture(paths[1], width=Cm(15.8))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_heading(doc, "3 月份磨粒5min间隔颗粒实时增量图", 3)
            _docx_heading(doc, "3.1 铁磁性磨粒增量图", 4)
            doc.add_picture(paths[2], width=Cm(15.8))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_heading(doc, "3.2 非铁磁性磨粒增量图", 4)
            doc.add_picture(paths[3], width=Cm(15.8))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

        sec_no = 4 if cap["wear"] else 1
        for section_name, key in (("水分趋势图", "water"),
                                  ("清洁度趋势图", "clean"),
                                  ("粘度趋势图", "vis")):
            if not cap[key]:
                continue
            _docx_heading(doc, "%d %s" % (sec_no, section_name), 3)
            if sensor_imgs.get(key):
                doc.add_picture(sensor_imgs[key], width=Cm(15.8))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                _docx_para(doc, "本期没有该参数的监测数据。", size=9, after=6)
            sec_no += 1

        eval_paras, conclusions = _unit_assessment(item, start, end, cap)
        head = _docx_heading(doc, "%d 评估结果" % sec_no, 3)
        head.paragraph_format.line_spacing = 1.5
        p0 = _docx_para(doc, _validity_text(end), size=10.5, after=6)
        p0.paragraph_format.line_spacing = 1.5
        for para in eval_paras:
            p = _docx_para(doc, para, size=10.5, after=6)
            p.paragraph_format.line_spacing = 1.5
        h6 = _docx_heading(doc, "%d 诊断结论" % (sec_no + 1), 3)
        h6.paragraph_format.line_spacing = 1.5
        for i, text in enumerate(conclusions, start=1):
            _docx_para(doc, "(%d) %s" % (i, text), size=10.5, after=4)

    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", project)[:40]
    path = os.path.join(out_dir, "%s_%s.docx" % (safe, title))
    doc.save(path)
    try:
        import shutil
        shutil.rmtree(chart_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return path


# ---------------------------------------------------------------------------
# 报告导出：Word 监测报告 / Excel 数据明细
# ---------------------------------------------------------------------------
STATUS_COLOR = {"异常": "C00000", "关注": "B26B00", "正常": "1E7145", "待定": "666666",
                "预警": "B26B00", "报警": "C00000"}
# 表格里按阈值显示为「预警 / 报警」
STATUS_DISPLAY = {"异常": "报警", "关注": "预警", "正常": "正常", "待定": "待定"}


def _docx_set_font(run, size=None, bold=None, color=None):
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    run.font.name = UI_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), UI_FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _docx_cell(cell, text, size=9, bold=False, color=None, align="left"):
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    cell.text = ""
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    run = p.add_run(str(text if text is not None else ""))
    _docx_set_font(run, size=size, bold=bold, color=color)


def _docx_shade(cell, color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def _docx_row_heights(table, header=1.0, body=0.8, skip=0):
    """统一表格行高：表头 1.0cm，数据行 0.8cm。"""
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    from docx.shared import Cm

    for i, row in enumerate(table.rows):
        if i < skip:
            continue
        row.height = Cm(header if i == skip else body)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST


def _docx_table(doc, headers, rows, widths=None, size=9, header_bg="1F3A5F", align="center"):
    from docx.enum.table import WD_TABLE_ALIGNMENT
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        _docx_cell(table.rows[0].cells[i], h, size=size, bold=True, color="FFFFFF", align="center")
        _docx_shade(table.rows[0].cells[i], header_bg)
    for ri, row in enumerate(rows):
        cells = table.add_row().cells
        for i, val in enumerate(row):
            color = STATUS_COLOR.get(str(val)) if i == len(row) - 1 and str(val) in STATUS_COLOR else None
            _docx_cell(cells[i], val, size=size, color=color, bold=bool(color), align=align)
            if ri % 2 == 1 and not color:
                _docx_shade(cells[i], "F4F7FB")
    if widths:
        from docx.shared import Cm
        for row in table.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    _docx_table_borders(table)
    _docx_table_layout(table)
    _docx_row_heights(table)
    return table


def _docx_para(doc, text, size=10.5, bold=False, color=None, align="left", after=6):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    p = doc.add_paragraph()
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    p.paragraph_format.space_after = Pt(after)
    run = p.add_run(text)
    _docx_set_font(run, size=size, bold=bold, color=color)
    return p


def build_docx(project, records, files_info):
    """生成 Word 监测报告，返回文件路径。"""
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.oxml.ns import qn

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin = section.bottom_margin = Cm(2.0)
    style = doc.styles["Normal"]
    style.font.name = UI_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), UI_FONT)

    dates = sorted({r["date"] for r in records if r["date"]})
    devices = sorted({r["device"] for r in records})
    param_set = sorted({r["param"] for r in records})
    st = {}
    for r in records:
        st[r["status"]] = st.get(r["status"], 0) + 1

    _docx_para(doc, "油液监测报告", size=24, bold=True, align="center", after=2)
    _docx_para(doc, project, size=12, color="444444", align="center", after=14)

    info = [
        ["项目名称", project, "报告生成时间", datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["数据文件", "%d 个" % len(files_info), "监测记录", "%d 条" % len(records)],
        ["监测设备", "%d 台" % len(devices), "取样日期",
         ("%s ~ %s" % (dates[0], dates[-1])) if dates else "—"],
        ["异常 / 关注", "%d / %d 项" % (st.get("异常", 0), st.get("关注", 0)),
         "监测参数", "%d 项" % len(param_set)],
    ]
    table = doc.add_table(rows=0, cols=4)
    table.style = "Table Grid"
    for row in info:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            if i % 2 == 0:
                _docx_cell(cells[i], val, size=9.5, bold=True, align="center")
                _docx_shade(cells[i], "EAF0F7")
            else:
                _docx_cell(cells[i], val, size=9.5)
    for row in table.rows:
        row.cells[0].width = Cm(3.0)
        row.cells[1].width = Cm(6.2)
        row.cells[2].width = Cm(3.2)
        row.cells[3].width = Cm(5.6)

    doc.add_paragraph()
    _docx_para(doc, "一、监测结论", size=14, bold=True, after=6)
    total = len(records) or 1
    judged = st.get("正常", 0) + st.get("关注", 0) + st.get("异常", 0)
    rate = (st.get("正常", 0) + st.get("关注", 0)) / judged * 100 if judged else 0.0
    _docx_para(doc, "本期共汇总 %d 个数据文件、%d 条监测记录，覆盖 %d 台设备、%d 项监测参数。"
                    "判定结果为：正常 %d 条、关注 %d 条、异常 %d 条、待定（无限值）%d 条；"
                    "已判定 %d 条，合格率约 %.1f%%。"
               % (len(files_info), len(records), len(devices), len(param_set),
                  st.get("正常", 0), st.get("关注", 0), st.get("异常", 0), st.get("待定", 0),
                  judged, rate))
    if st.get("异常"):
        _docx_para(doc, "共发现 %d 条超标数据，建议优先安排复检与换油评估，明细见第二部分。" % st["异常"],
                   color=STATUS_COLOR["异常"])
    elif st.get("关注"):
        _docx_para(doc, "存在 %d 条接近限值的数据，建议缩短取样周期并关注趋势变化。" % st["关注"],
                   color=STATUS_COLOR["关注"])
    else:
        _docx_para(doc, "各项监测指标均处于参考限值以内，运行状态良好。", color=STATUS_COLOR["正常"])

    groups = {}
    for r in records:
        groups[r["group_key"]] = groups.get(r["group_key"], 0) + 1
    if groups:
        _docx_para(doc, "参数组覆盖情况", size=11, bold=True, after=4)
        rows = [[group_name(g), n, len({r["param"] for r in records if r["group_key"] == g})]
                for g, n in sorted(groups.items(), key=lambda kv: -kv[1])]
        _docx_table(doc, ["参数组", "记录数", "参数项数"], rows, widths=[6.0, 4.0, 4.0])

    doc.add_paragraph()
    _docx_para(doc, "二、异常 / 关注明细", size=14, bold=True, after=6)
    flagged = [r for r in records if r["status"] in ("异常", "关注")]
    flagged.sort(key=lambda r: (r["status"] != "异常", r["device"], r["date"]))
    if flagged:
        rows = [[r["device"], r["date"] or "—", r["name"],
                 "" if r["value"] is None else "%g" % r["value"], r["unit"],
                 limit_text(r["param"]), r["status"]] for r in flagged]
        _docx_table(doc, ["设备", "取样日期", "参数", "数值", "单位", "参考限值", "结论"], rows,
                    widths=[3.2, 2.4, 3.4, 2.2, 1.8, 2.8, 1.6])
    else:
        _docx_para(doc, "无异常或关注项。", size=10)

    doc.add_paragraph()
    _docx_para(doc, "三、分设备监测明细", size=14, bold=True, after=6)
    by_device = {}
    for r in records:
        by_device.setdefault(r["device"], []).append(r)
    for device in sorted(by_device):
        recs = sorted(by_device[device], key=lambda r: (r["date"], r["group_key"], r["name"]))
        n_dates = len({r["date"] for r in recs if r["date"]}) or 1
        _docx_para(doc, "%s（取样 %d 次，记录 %d 条）" % (device, n_dates, len(recs)),
                   size=11.5, bold=True, after=4)
        rows = [[r["date"] or "—", r["name"], "" if r["value"] is None else "%g" % r["value"],
                 r["unit"], limit_text(r["param"]), r["status"]] for r in recs]
        _docx_table(doc, ["取样日期", "参数名称", "数值", "单位", "参考限值", "结论"], rows,
                    widths=[2.6, 4.2, 2.2, 1.8, 3.0, 1.8], size=8.5, header_bg="3B5B85")

    doc.add_paragraph()
    _docx_para(doc, "四、数据来源清单", size=14, bold=True, after=6)
    rows = []
    for f in sorted(files_info, key=lambda x: x["vpath"]):
        state = "解析失败：" + f["error"] if f.get("status") == "error" else "已识别"
        rows.append([f["vpath"].replace("/", " › "), f.get("sheets") or "—", f.get("records", 0), state])
    if rows:
        _docx_table(doc, ["文件", "工作表", "记录数", "解析状态"], rows, widths=[7.4, 3.0, 1.8, 3.8], size=8.5)

    doc.add_paragraph()
    _docx_para(doc, "五、判定说明", size=12, bold=True, after=4)
    _docx_para(doc, "参考限值按通用工业润滑油经验值设定，仅用于筛查；实际判定应结合设备类型、油品规格、"
                    "换油周期与历史趋势综合判断。可在程序目录 thresholds.json 中按参数调整限值。", size=9)

    os.makedirs(REPORT_DIR, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", project)[:40]
    out = os.path.join(REPORT_DIR, "%s_油液监测报告_%s.docx" % (safe, datetime.now().strftime("%Y%m%d_%H%M%S")))
    doc.save(out)
    return out


def build_xlsx(project, records, files_info):
    """导出 Excel 数据明细，返回文件路径。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(name=UI_FONT, bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="1F3A5F")
    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    fills = {"异常": PatternFill("solid", fgColor="FBE2E2"),
             "关注": PatternFill("solid", fgColor="FFF1D6"),
             "正常": PatternFill("solid", fgColor="E4F3EA")}

    def style_sheet(ws, widths):
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "汇总"
    ws.append(["油液监测数据汇总"])
    ws["A1"].font = Font(name=UI_FONT, bold=True, size=14)
    ws.merge_cells("A1:D1")
    st = {}
    for r in records:
        st[r["status"]] = st.get(r["status"], 0) + 1
    for k, v in [("项目名称", project),
                 ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                 ("数据文件", len(files_info)), ("监测记录", len(records)),
                 ("设备数量", len({r["device"] for r in records})),
                 ("参数数量", len({r["param"] for r in records})),
                 ("异常记录", st.get("异常", 0)), ("关注记录", st.get("关注", 0))]:
        ws.append([k, v])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 44

    ws2 = wb.create_sheet("监测数据")
    ws2.append(["设备", "取样点", "油品", "取样日期", "参数组", "参数键", "参数名称",
                "数值", "单位", "原始值", "参考限值", "结论", "数据文件", "工作表"])
    for r in records:
        ws2.append([r["device"], r["point"], r["oil"], r["date"], group_name(r["group_key"]),
                    r["param"], r["name"], r["value"], r["unit"], r["raw"],
                    limit_text(r["param"]), r["status"], r["vpath"], r["sheet"]])
    style_sheet(ws2, [16, 12, 12, 11, 10, 14, 14, 9, 8, 10, 12, 7, 42, 14])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for c in row:
            c.border = border
            c.alignment = Alignment(vertical="center")
        if row[11].value in fills:
            row[11].fill = fills[row[11].value]

    ws3 = wb.create_sheet("异常明细")
    ws3.append(["设备", "取样日期", "参数名称", "数值", "单位", "参考限值", "结论"])
    for r in records:
        if r["status"] in ("异常", "关注"):
            ws3.append([r["device"], r["date"], r["name"], r["value"], r["unit"],
                        limit_text(r["param"]), r["status"]])
    style_sheet(ws3, [16, 11, 14, 9, 8, 12, 7])
    for row in ws3.iter_rows(min_row=2, max_row=ws3.max_row):
        if row[6].value in fills:
            row[6].fill = fills[row[6].value]

    ws4 = wb.create_sheet("文件清单")
    ws4.append(["文件", "工作表", "记录数", "状态", "说明"])
    for f in sorted(files_info, key=lambda x: x["vpath"]):
        ws4.append([f["vpath"], f.get("sheets") or "", f.get("records", 0),
                    "失败" if f.get("status") == "error" else "已识别", f.get("error") or ""])
    style_sheet(ws4, [52, 24, 8, 8, 34])

    os.makedirs(REPORT_DIR, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", project)[:40]
    out = os.path.join(REPORT_DIR, "%s_监测数据_%s.xlsx" % (safe, datetime.now().strftime("%Y%m%d_%H%M%S")))
    wb.save(out)
    return out


# ---------------------------------------------------------------------------
# 演示数据：多层文件夹 + 汇总压缩包 + 包内嵌套压缩包
# ---------------------------------------------------------------------------
_INSTANCE_MUTEX = None


def focus_existing_instance():
    """只允许运行一个 OilLab；重复启动时把已有窗口调到前台并退出。"""
    global _INSTANCE_MUTEX
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "OilLab_SingleInstance")
        if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
            return False
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "OilLab · 油液监测报告工具")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def set_app_user_model_id():
    """让任务栏按 OilLab 自己的图标分组，而不是 python 图标。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OilLab.OilMonitor")
    except Exception:
        pass


def hide_console():
    """仅当控制台是双击 .py 新建的（只挂了本进程）时隐藏它。

    在 cmd / PowerShell / VSCode 终端里运行时，控制台还挂着 shell，不能隐藏，
    否则会把用户的终端窗口一起藏掉。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        arr = (ctypes.c_uint * 8)()
        count = kernel32.GetConsoleProcessList(arr, 8)
        if count <= 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def enable_dpi_awareness():
    """高分屏下让窗口按物理像素布局，文字更清晰、截图/控件尺寸一致。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _work_area(win):
    """屏幕可用区域（不含任务栏）。"""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def fit_window(win, pref_w, pref_h, min_w=None, min_h=None):
    """按屏幕可用尺寸自适应：小屏自动缩小，大屏保持舒适尺寸。"""
    win.update_idletasks()
    try:
        scale = win.winfo_fpixels("1i") / 96.0
    except Exception:
        scale = 1.0
    scale = max(0.85, min(1.1, scale))
    left, top, sw, sh = _work_area(win)
    max_w = max(800, int(sw * 0.92))
    max_h = max(560, int(sh * 0.90))
    w = min(int(pref_w * scale), max_w)
    h = min(int(pref_h * scale), max_h)
    x = left + max(0, (sw - w) // 2)
    y = top + max(0, (sh - h) // 2)
    win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    win.minsize(min(int((min_w or 900) * 0.8), max_w),
                min(int((min_h or 580) * 0.8), max_h))


def apply_app_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=(UI_FONT, 10), background=COLOR_BG, foreground="#16202c")
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Card.TFrame", background="white")
    style.configure("TLabel", background=COLOR_BG)
    style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_MUTED, font=(UI_FONT, 9))
    style.configure("Title.TLabel", background=COLOR_HEAD, foreground="white",
                    font=(UI_FONT, 15, "bold"))
    style.configure("Sub.TLabel", background=COLOR_HEAD, foreground="#c3d6ea", font=(UI_FONT, 9))
    style.configure("CardTitle.TLabel", background="white", foreground=COLOR_HEAD,
                    font=(UI_FONT, 10, "bold"))
    style.configure("Treeview", background="white", fieldbackground="white", rowheight=26,
                    borderwidth=0, font=(UI_FONT, 9))
    style.configure("Treeview.Heading", font=(UI_FONT, 9, "bold"), background="#eef3f9",
                    foreground="#43536b", relief="flat", padding=(6, 5))
    style.map("Treeview.Heading", background=[("active", "#e2ebf5")])
    style.map("Treeview", background=[("selected", "#dce9f6")], foreground=[("selected", COLOR_HEAD)])
    style.configure("TButton", padding=(10, 5))
    style.configure("Accent.TButton", background=COLOR_ACCENT, foreground="white",
                    padding=(12, 5), borderwidth=0)
    style.map("Accent.TButton", background=[("active", "#245a89"), ("disabled", "#9fb6cc")])
    style.configure("TEntry", padding=4)
    style.configure("TCombobox", padding=3)
    style.configure("Horizontal.TProgressbar", background=COLOR_ACCENT,
                    troughcolor="#e3ebf4", borderwidth=0)
    style.configure("TPanedwindow", background=COLOR_BG)
    style.configure("Sash", sashthickness=6, background=COLOR_BG)


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self.tip, text=self.text, justify="left", background="#ffffe1",
                         relief="solid", borderwidth=1, font=(UI_FONT, 9))
        label.pack(ipadx=6, ipady=3)

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------------------
# 数据分析窗口：按机组切换磨损 / 水分 / 清洁度 / 粘度等趋势
# ---------------------------------------------------------------------------
ANALYSIS_TABS = [
    ("磨损", ("磨损",), "wear", ("40-59", "铁磁")),
    ("水分", ("水分",), "water", ("PPM", "水分")),
    ("清洁度", ("清洁度",), "clean", ("ISO4", "ISO")),
    ("粘度", ("粘度",), "vis", ("VT40", "粘度")),
    ("酸值", ("酸值",), "acid", ("酸值",)),
    ("碱值", ("碱值",), "base", ("碱值",)),
]


def parse_datetime_text(value):
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def read_csv_series(path, start=None, end=None):
    """读原始时序 CSV：返回 (时间列表, [(列名, 时间列表, 数值列表), ...])。"""
    rows = []
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", newline="", encoding=enc) as fp:
                rows = [r for r in csv.reader(fp) if r]
            break
        except UnicodeDecodeError:
            continue
    if len(rows) < 3:
        return [], []
    header = [h.strip() for h in rows[0]]
    times = []
    cols = [[] for _ in header[1:]]
    for r in rows[1:]:
        t = parse_datetime_text(r[0]) if r else None
        if start or end:
            if t is None:
                continue
            d = t.date()
            if start and d < start:
                continue
            if end and d > end:
                continue
        times.append(t)
        for i in range(1, len(header)):
            v = None
            if i < len(r):
                try:
                    v = float(r[i])
                except (TypeError, ValueError):
                    v = None
            cols[i - 1].append(v)
    channels = []
    for i, values in enumerate(cols):
        if not any(v is not None for v in values):
            continue
        name = header[i + 1] if i + 1 < len(header) else "列%d" % (i + 2)
        if "上电时间" in name:
            continue
        channels.append((name, times, values))
    return times, channels


class AnalysisWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.store = app.store
        self.project = app.scope_project
        self.prefix = app.scope_prefix
        self.title("数据分析 · %s" % (self.project or "全部项目"))
        self.geometry("1120x720")
        self.minsize(900, 560)

        units = list(self.store.distinct("device", self.project or None, self.prefix))
        units.sort(key=lambda d: (0, int(re.sub(r"\D", "", d) or 0)) if re.fullmatch(r"\d+#?", d) else (1, 0))
        self.units = units

        head = ttk.Frame(self, padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text="机组编号", style="CardTitle.TLabel").pack(side="left")
        self.var_unit = tk.StringVar(value=units[0] if units else "")
        self.cmb_unit = ttk.Combobox(head, textvariable=self.var_unit, values=units,
                                     state="readonly", width=10)
        self.cmb_unit.pack(side="left", padx=(6, 16))
        self.cmb_unit.bind("<<ComboboxSelected>>", lambda e: self.rebuild(reset_range=True))

        ttk.Label(head, text="起始日期", style="CardTitle.TLabel").pack(side="left")
        self.var_start = tk.StringVar(value="")
        self.cmb_start = ttk.Combobox(head, textvariable=self.var_start, values=[],
                                      state="readonly", width=12)
        self.cmb_start.pack(side="left", padx=(6, 12))
        ttk.Label(head, text="结束日期", style="CardTitle.TLabel").pack(side="left")
        self.var_end = tk.StringVar(value="")
        self.cmb_end = ttk.Combobox(head, textvariable=self.var_end, values=[],
                                    state="readonly", width=12)
        self.cmb_end.pack(side="left", padx=(6, 8))
        self.btn_reset_range = ttk.Button(head, text="重置", command=self.reset_range)
        self.btn_reset_range.pack(side="left")
        for w in (self.cmb_start, self.cmb_end):
            w.bind("<<ComboboxSelected>>", lambda e: self.redraw_all())
        ttk.Label(head, text="（每个标签一张趋势图，可切换通道；日期范围内数据才参与绘制）",
                  style="Muted.TLabel").pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tabs = []
        self.rebuild()

    def rebuild(self, reset_range=False):
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self.tabs = []
        unit = self.var_unit.get()
        if reset_range:
            self.var_start.set("")
            self.var_end.set("")
        if not unit:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text="无数据")
            ttk.Label(frame, text="没有可分析的机组").pack(pady=40)
            self._set_date_options([])
            return
        built = 0
        for title, keywords, group, prefer in ANALYSIS_TABS:
            if self.build_tab(title, keywords, group, prefer, unit):
                built += 1
        dates = sorted({t.date().isoformat() for tab in self.tabs for ch in tab["channels"]
                        for t in ch[1] if t is not None})
        self._set_date_options(dates)
        if not built:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text="无数据")
            ttk.Label(frame, text="该机组没有可分析的数据文件").pack(pady=40)
        self.redraw_all()

    def _set_date_options(self, dates):
        self.date_options = dates
        self.cmb_start.config(values=dates)
        self.cmb_end.config(values=dates)
        if not dates:
            self.var_start.set("")
            self.var_end.set("")
            return
        if self.var_start.get() not in dates:
            self.var_start.set(dates[0])
        if self.var_end.get() not in dates:
            self.var_end.set(dates[-1])
        if self.var_start.get() > self.var_end.get():
            self.var_start.set(dates[0])
            self.var_end.set(dates[-1])

    def reset_range(self):
        dates = getattr(self, "date_options", [])
        if not dates:
            return
        self.var_start.set(dates[0])
        self.var_end.set(dates[-1])
        self.redraw_all()

    @staticmethod
    def _date_bound(text):
        try:
            return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    def redraw_all(self):
        for tab in getattr(self, "tabs", []):
            self.redraw_tab(tab)

    def redraw_tab(self, tab):
        channel = tab["var"].get()
        data = next((c for c in tab["channels"] if c[0] == channel), tab["channels"][0])
        self.draw(tab["fig"], tab["ax"], tab["canvas"], tab["unit"], tab["title"], data)

    def _find_raw_file(self, unit, keywords):
        for f in self.store.file_info().values():
            if f["project"] != self.project:
                continue
            base = f["vpath"].split("/")[-1]
            if not any(k in base for k in keywords):
                continue
            if guess_device(f["vpath"]) != unit:
                continue
            real = f.get("real_path") or ""
            if base.lower().endswith(".csv") and os.path.isfile(real):
                return f
        return None

    def _agg_channels(self, unit, group):
        rows = self.store.query(project=self.project, prefix=self.prefix, device=unit,
                                group=group, limit=5000)
        if not rows:
            return []
        by_param = {}
        for r in rows:
            by_param.setdefault(r["param"], {"name": r["name"], "pts": []})
            by_param[r["param"]]["pts"].append((parse_datetime_text(r["date"]), r["value"]))
        out = []
        for _key, info in by_param.items():
            pts = sorted(info["pts"], key=lambda p: (p[0] is None, p[0] or 0))
            times = [p[0] for p in pts]
            values = [p[1] for p in pts]
            if any(v is not None for v in values):
                out.append((info["name"], times, values))
        return out

    def build_tab(self, title, keywords, group, prefer, unit):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        raw = self._find_raw_file(unit, keywords)
        if raw:
            times, channels = read_csv_series(raw["real_path"])
        else:
            channels = self._agg_channels(unit, group)
            times = channels[0][1] if channels else []
        if not channels:
            return False

        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text=title)
        bar = ttk.Frame(frame, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="通道", style="CardTitle.TLabel").pack(side="left")
        names = [c[0] for c in channels]
        default = names[0]
        for token in prefer:
            hit = next((n for n in names if token in n), None)
            if hit:
                default = hit
                break
        var_ch = tk.StringVar(value=default)
        cmb = ttk.Combobox(bar, textvariable=var_ch, values=names, state="readonly", width=30)
        cmb.pack(side="left", padx=(6, 12))

        fig = Figure(figsize=(9, 4.2), dpi=100, facecolor="white")
        ax = fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 6))
        tab = {"fig": fig, "ax": ax, "canvas": canvas, "channels": channels,
               "var": var_ch, "title": title, "unit": unit}
        self.tabs.append(tab)

        cmb.bind("<<ComboboxSelected>>", lambda e, t=tab: self.redraw_tab(t))
        return True

    def draw(self, fig, ax, canvas, unit, category, data):
        name, times, values = data
        start = self._date_bound(self.var_start.get())
        end = self._date_bound(self.var_end.get())
        if start and end and start > end:
            start, end = end, start
        ax.clear()
        xs, labels = [], []
        use_time = any(t is not None for t in times)
        for i, (t, v) in enumerate(zip(times, values)):
            if v is None:
                continue
            if t is not None:
                d = t.date()
                if start and d < start:
                    continue
                if end and d > end:
                    continue
            xs.append(t if (use_time and t is not None) else i)
            labels.append(v)
        if not xs:
            ax.text(0.5, 0.5, "该日期范围内没有数据", ha="center", va="center",
                    transform=ax.transAxes, color="#8fa0b4")
            canvas.draw_idle()
            return
        ax.plot(xs, labels, color=COLOR_ACCENT, linewidth=1.3, marker="o", markersize=2.5)
        ax.set_title("%s · %s趋势 · %s" % (unit, category, name), fontsize=11,
                     color=COLOR_HEAD, loc="left")
        if start and end:
            ax.text(0.99, 1.03, "%s ~ %s" % (start.isoformat(), end.isoformat()),
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=8, color="#8fa0b4")
        ax.set_xlabel("数据时间" if use_time else "采样点", fontsize=9)
        ax.set_ylabel(name, fontsize=9)
        ax.grid(True, color="#e6edf5", linewidth=0.8)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.tick_params(colors="#5b6b7d", labelsize=8)
        if use_time:
            try:
                from matplotlib.dates import AutoDateLocator, DateFormatter
                ax.xaxis.set_major_locator(AutoDateLocator(minticks=4, maxticks=10))
                ax.xaxis.set_major_formatter(DateFormatter("%m-%d %H:%M"))
                fig.autofmt_xdate(rotation=0, ha="center")
            except Exception:
                pass
        fig.tight_layout(pad=1.1)
        canvas.draw_idle()


# ---------------------------------------------------------------------------
# 报告时间段选择
# ---------------------------------------------------------------------------
def parse_ymd(text):
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def filter_rows_by_window(rows, start=None, end=None):
    """rows[0] 是表头，其余按第 1 列时间过滤（含首尾两天）。"""
    if not start and not end:
        return rows
    out = [rows[0]] if rows else []
    for row in rows[1:]:
        t = parse_datetime_text(row[0]) if row else None
        if t is None:
            continue
        d = t.date()
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(row)
    return out


class PeriodDialog(tk.Toplevel):
    def __init__(self, master, start, end):
        super().__init__(master)
        self.title("选择报告时间段")
        self.resizable(False, False)
        self.result = None
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="起始日期").grid(row=0, column=0, sticky="w")
        self.var_start = tk.StringVar(value=start)
        ttk.Entry(body, textvariable=self.var_start, width=14).grid(row=0, column=1, padx=(6, 16))
        ttk.Label(body, text="结束日期").grid(row=0, column=2, sticky="w")
        self.var_end = tk.StringVar(value=end)
        ttk.Entry(body, textvariable=self.var_end, width=14).grid(row=0, column=3, padx=6)
        ttk.Label(body, text="格式 YYYY-MM-DD，含首尾两天；只统计该时间段内的数据",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 12))
        btns = ttk.Frame(body)
        btns.grid(row=2, column=0, columnspan=4, sticky="e")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="生成报告", style="Accent.TButton",
                   command=self.on_ok).pack(side="right")
        self.bind("<Return>", lambda e: self.on_ok())
        self.transient(master)
        self.grab_set()
        master.wait_window(self)

    def on_ok(self):
        start = parse_ymd(self.var_start.get())
        end = parse_ymd(self.var_end.get())
        if not start or not end:
            messagebox.showerror("日期格式", "请按 YYYY-MM-DD 填写起止日期", parent=self)
            return
        if start > end:
            start, end = end, start
        self.result = (start, end)
        self.destroy()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class OilGUI:
    def __init__(self, root):
        self.root = root
        root.title("OilLab · 油液监测报告工具")
        load_threshold_overrides()
        fit_window(root, 1120, 720, 940, 580)

        self.store = Store()
        self.main_dir = ""
        self.scope_project = ""
        self.scope_prefix = ""
        self.queue = queue.Queue()
        self.scanning = False
        self.rows = []
        self.sort_col = "date"
        self.sort_desc = True
        self.chart_device = ""
        self.chart_param = ""
        self._suppress_select = False
        self._group_map = {}
        self._param_map = {}
        self._chart_param_map = {}
        self._state = self.read_state()
        self._load_dynamic_params()

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_status()
        self._build_body()
        self._bind_keys()
        self.apply_state()
        self.root.after(350, self._fit_sash)

        self.refresh_all()
        if self.main_dir and os.path.isdir(self.main_dir):
            self.root.after(200, lambda: self.rescan(force=False))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_dynamic_params(self):
        """缓存里已有的在线监测动态参数，启动时重新注册，保证名称/单位不丢。"""
        try:
            rows = self.store.conn.execute(
                "SELECT DISTINCT param, name, group_key, unit FROM records").fetchall()
        except sqlite3.Error:
            return
        for r in rows:
            key = r["param"]
            if key not in PARAMS:
                PARAMS[key] = {"key": key, "name": r["name"] or key, "group": r["group_key"] or "other",
                               "unit": r["unit"] or "", "aliases": (), "direction": None,
                               "warn": None, "alert": None}

    # ---------------- 状态 ----------------
    def read_state(self):
        if not os.path.isfile(STATE_FILE):
            return {}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def apply_state(self):
        st = self._state
        self.main_dir = st.get("main_dir", "") if os.path.isdir(st.get("main_dir", "")) else ""
        if self.main_dir:
            self._set_dir_label(self.main_dir)
        geo = st.get("geometry")
        if geo:
            self._restore_geometry(geo)
        self.chart_device = st.get("chart_device", "")
        self.chart_param = st.get("chart_param", "")
        for key, var in (("filter_device", self.var_device), ("filter_group", self.var_group),
                         ("filter_param", self.var_param)):
            if st.get(key):
                var.set(st[key])
        self.var_status.set("异常/关注")  # 表格默认只看报警/预警
        if st.get("filter_keyword"):
            self.var_keyword.set(st["filter_keyword"])
        try:
            self.root.after(400, lambda: self._fit_sash(st.get("sash")))
        except Exception:
            pass

    def _restore_geometry(self, geo):
        """只恢复窗口位置；尺寸始终按当前屏幕自适应，避免旧的大尺寸把窗口撑出屏幕。"""
        try:
            m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", str(geo))
            if not m:
                return
            x, y = int(m.group(3)), int(m.group(4))
            left, top, sw, sh = _work_area(self.root)
            w, h = self.root.winfo_width(), self.root.winfo_height()
            x = max(left, min(x, left + sw - w))
            y = max(top, min(y, top + sh - h))
            self.root.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    def _fit_sash(self, pos=None):
        """左侧树宽度随窗口自适应，小屏不会把右侧挤没。"""
        try:
            width = self.root.winfo_width()
            p = int(pos if pos is not None else (self._state.get("sash") or 330))
            p = max(220, min(p, max(240, int(width * 0.34))))
            self.paned.sashpos(0, p)
        except Exception:
            pass

    def save_state(self):
        data = {
            "main_dir": self.main_dir,
            "geometry": self.root.geometry(),
            "sash": self.paned.sashpos(0),
            "chart_device": self.chart_device,
            "chart_param": self.chart_param,
            "filter_device": self.var_device.get(),
            "filter_group": self.var_group.get(),
            "filter_param": self.var_param.get(),
            "filter_status": self.var_status.get(),
            "filter_keyword": self.var_keyword.get(),
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _set_dir_label(self, path):
        path = path or ""
        if not path:
            self.dir_label.config(text="尚未选择数据目录")
            return
        parts = path.replace("\\", "/").split("/")
        short = "/".join(parts[-3:]) if len(parts) > 3 else path
        if len(short) > 56:
            short = "…" + short[-53:]
        self.dir_label.config(text=short)
        if hasattr(self, "dir_tip"):
            self.dir_tip.text = path

    # ---------------- 布局 ----------------
    def _build_header(self):
        head = tk.Frame(self.root, bg=COLOR_HEAD, height=52)
        head.grid(row=0, column=0, sticky="ew")
        head.pack_propagate(False)
        tk.Label(head, text="OilLab", bg=COLOR_HEAD, fg="white",
                 font=(UI_FONT, 15, "bold")).pack(side="left", padx=(16, 6), pady=8)
        tk.Label(head, text="油液监测报告工具", bg=COLOR_HEAD, fg="#e8f1fa",
                 font=(UI_FONT, 12)).pack(side="left", pady=12)
        tk.Label(head, text="多项目 · 多层目录 · 压缩包统一识别 · 趋势 · 报告",
                 bg=COLOR_HEAD, fg="#a9c4e0", font=(UI_FONT, 9)).pack(side="left", padx=14, pady=14)
        tk.Label(head, text="v1.0", bg=COLOR_HEAD, fg="#8fb0d0",
                 font=(UI_FONT, 9)).pack(side="right", padx=16)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.grid(row=1, column=0, sticky="ew")
        self.btn_dir = ttk.Button(bar, text="选择数据目录", style="Accent.TButton", command=self.choose_dir)
        self.btn_dir.pack(side="left")
        self.btn_rescan = ttk.Button(bar, text="重新扫描", command=lambda: self.rescan(force=True))
        self.btn_rescan.pack(side="left", padx=(8, 0))
        self.btn_clear = ttk.Button(bar, text="清空缓存", command=self.clear_cache)
        self.btn_clear.pack(side="left", padx=(8, 0))
        self.btn_analysis = ttk.Button(bar, text="数据分析", command=self.open_analysis)
        self.btn_analysis.pack(side="left", padx=(8, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=12, pady=2)
        self.btn_wear = ttk.Button(bar, text="报告", command=self.export_wear)
        self.btn_wear.pack(side="left", padx=(8, 0))
        self.btn_reports = ttk.Button(bar, text="报告目录", command=self.open_reports)
        self.btn_reports.pack(side="left", padx=(8, 0))

        self.dir_label = ttk.Label(bar, text="尚未选择数据目录", style="Muted.TLabel")
        self.dir_label.pack(side="right")
        self.dir_tip = ToolTip(self.dir_label, "当前数据目录")
        for widget, tip in ((self.btn_dir, "选择项目顶层目录：每个一级子文件夹就是一个项目"),
                            (self.btn_rescan, "重新扫描目录，按文件修改时间增量解析"),
                            (self.btn_clear, "清空解析缓存与压缩包临时目录"),
                            (self.btn_analysis, "按机组查看磨损/水分/清洁度/粘度等趋势"),
                            (self.btn_wear, "选择起止日期，生成该时间段的分析报告")):
            ToolTip(widget, tip)

    def _build_body(self):
        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 8))

        left = ttk.Frame(self.paned, style="Card.TFrame", width=330)
        self.paned.add(left, weight=1)
        head = ttk.Frame(left, style="Card.TFrame", padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text="项目 / 文件", style="CardTitle.TLabel").pack(side="left")
        self.tree_count = ttk.Label(head, text="", style="Muted.TLabel")
        self.tree_count.pack(side="right")

        tree_wrap = ttk.Frame(left, style="Card.TFrame")
        tree_wrap.pack(fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self.tree = ttk.Treeview(tree_wrap, columns=("records", "abn"), show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="项目 / 文件夹 / 文件")
        self.tree.heading("records", text="记录")
        self.tree.heading("abn", text="异常")
        self.tree.column("#0", width=230, minwidth=140)
        self.tree.column("records", width=52, anchor="center", stretch=False)
        self.tree.column("abn", width=46, anchor="center", stretch=False)
        self.tree.tag_configure("project", font=(UI_FONT, 9, "bold"), foreground=COLOR_HEAD)
        self.tree.tag_configure("zip", foreground="#8a5a12")
        self.tree.tag_configure("file", foreground="#33475c")
        self.tree.tag_configure("error", foreground=COLOR_ALERT)
        self.tree.tag_configure("empty", foreground=COLOR_MUTED)
        ysb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=3)

        # 筛选栏
        filt = ttk.Frame(right, style="Card.TFrame", padding=(10, 8))
        filt.pack(fill="x", pady=(0, 8))
        row1 = ttk.Frame(filt, style="Card.TFrame")
        row1.pack(fill="x")
        row2 = ttk.Frame(filt, style="Card.TFrame")
        row2.pack(fill="x", pady=(6, 0))
        self.var_device = tk.StringVar(value="全部机组")
        self.var_group = tk.StringVar(value="全部参数组")
        self.var_param = tk.StringVar(value="全部参数")
        self.var_status = tk.StringVar(value="异常/关注")
        self.var_keyword = tk.StringVar(value="")

        ttk.Label(row1, text="机组编号", style="CardTitle.TLabel").pack(side="left")
        self.cmb_device = ttk.Combobox(row1, textvariable=self.var_device, width=15, state="readonly",
                                       values=["全部机组"])
        self.cmb_device.pack(side="left", padx=(4, 12))
        ttk.Label(row1, text="参数组", style="CardTitle.TLabel").pack(side="left")
        self.cmb_group = ttk.Combobox(row1, textvariable=self.var_group, width=10, state="readonly",
                                      values=["全部参数组"])
        self.cmb_group.pack(side="left", padx=(4, 12))
        ttk.Label(row1, text="参数", style="CardTitle.TLabel").pack(side="left")
        self.cmb_param = ttk.Combobox(row1, textvariable=self.var_param, width=15, state="readonly",
                                      values=["全部参数"])
        self.cmb_param.pack(side="left", padx=(4, 12))
        ttk.Label(row1, text="状态", style="CardTitle.TLabel").pack(side="left")
        self.cmb_status = ttk.Combobox(row1, textvariable=self.var_status, width=10, state="readonly",
                                       values=["异常/关注", "异常", "关注", "正常", "待定", "全部"])
        self.cmb_status.pack(side="left", padx=(4, 0))

        ttk.Label(row2, text="关键词", style="CardTitle.TLabel").pack(side="left")
        entry = ttk.Entry(row2, textvariable=self.var_keyword, width=30)
        entry.pack(side="left", padx=(4, 8))
        ttk.Button(row2, text="重置筛选", command=self.reset_filters).pack(side="left")
        self.filter_hint = ttk.Label(row2, text="", style="Muted.TLabel")
        self.filter_hint.pack(side="right")

        for widget in (self.cmb_device, self.cmb_group, self.cmb_param, self.cmb_status):
            widget.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        entry.bind("<Return>", lambda e: self.refresh_table())

        # 表格 + 趋势图
        self.vpaned = ttk.PanedWindow(right, orient="vertical")
        self.vpaned.pack(fill="both", expand=True)

        table_card = ttk.Frame(self.vpaned, style="Card.TFrame")
        self.vpaned.add(table_card, weight=2)
        thead = ttk.Frame(table_card, style="Card.TFrame", padding=(10, 6))
        thead.pack(fill="x")
        ttk.Label(thead, text="监测数据", style="CardTitle.TLabel").pack(side="left")
        self.table_info = ttk.Label(thead, text="", style="Muted.TLabel")
        self.table_info.pack(side="left", padx=10)

        table_wrap = ttk.Frame(table_card, style="Card.TFrame")
        table_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        cols = ("device", "date", "name", "value", "unit", "limit", "status")
        self.table = ttk.Treeview(table_wrap, columns=cols, show="headings", selectmode="browse", height=8)
        headers = [("device", "机组编号", 150, "center"), ("date", "数据时间", 120, "center"),
                   ("name", "参数", 150, "center"),
                   ("value", "数值", 80, "center"), ("unit", "单位", 68, "center"),
                   ("limit", "参考限值", 112, "center"), ("status", "结论", 62, "center")]
        for key, text, width, anchor in headers:
            self.table.heading(key, text=text, command=lambda c=key: self.sort_table(c))
            self.table.column(key, width=width, anchor=anchor, stretch=(key in ("device", "name")))
        self.table.tag_configure("异常", foreground=COLOR_ALERT)
        self.table.tag_configure("关注", foreground=COLOR_WARN)
        self.table.tag_configure("正常", foreground="#1f3a4f")
        self.table.tag_configure("待定", foreground=COLOR_MUTED)
        self.table.tag_configure("zebra", background="#f7fafd")
        ysb2 = ttk.Scrollbar(table_wrap, orient="vertical", command=self.table.yview)
        xsb2 = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ysb2.set, xscrollcommand=xsb2.set)
        ysb2.pack(side="right", fill="y")
        xsb2.pack(side="bottom", fill="x")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.on_row_select)
        self.table.bind("<Double-1>", self.on_row_double)

        chart_card = ttk.Frame(self.vpaned, style="Card.TFrame")
        self.vpaned.add(chart_card, weight=3)
        chead = ttk.Frame(chart_card, style="Card.TFrame", padding=(10, 6))
        chead.pack(fill="x")
        ttk.Label(chead, text="趋势", style="CardTitle.TLabel").pack(side="left")
        self.var_chart_device = tk.StringVar(value="")
        self.var_chart_param = tk.StringVar(value="")
        self.cmb_chart_device = ttk.Combobox(chead, textvariable=self.var_chart_device, width=16,
                                             state="readonly", values=[])
        self.cmb_chart_device.pack(side="left", padx=(8, 4))
        self.cmb_chart_param = ttk.Combobox(chead, textvariable=self.var_chart_param, width=18,
                                            state="readonly", values=[])
        self.cmb_chart_param.pack(side="left", padx=(0, 6))
        self.var_show_limits = tk.BooleanVar(value=True)
        ttk.Checkbutton(chead, text="限值线", variable=self.var_show_limits,
                        command=self.draw_trend).pack(side="left")
        ttk.Label(chead, text="点击明细行可切换设备/参数", style="Muted.TLabel").pack(side="right")
        self.cmb_chart_device.bind("<<ComboboxSelected>>", lambda e: self.on_chart_combo())
        self.cmb_chart_param.bind("<<ComboboxSelected>>", lambda e: self.draw_trend())

        self.chart_holder = ttk.Frame(chart_card, style="Card.TFrame")
        self.chart_holder.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.canvas = None
        self._init_chart()

        self.root.after(500, lambda: self.vpaned.sashpos(0, 330))

    def _init_chart(self):
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            self.fig = Figure(figsize=(9, 2.2), dpi=100, facecolor="white")
            self.ax = self.fig.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_holder)
            self.canvas.get_tk_widget().configure(background="white")
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self.chart_ready = True
        except Exception as exc:  # noqa: BLE001
            self.chart_ready = False
            ttk.Label(self.chart_holder, text="趋势图不可用（未安装 matplotlib）：\n%s" % exc,
                      style="Muted.TLabel", justify="left").pack(anchor="w", padx=12, pady=12)

    def _build_status(self):
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.grid(row=3, column=0, sticky="ew")
        self.status_label = ttk.Label(bar, text="就绪", style="Muted.TLabel")
        self.status_label.pack(side="left")
        self.progress = ttk.Progressbar(bar, length=180, mode="determinate")
        self.progress.pack(side="left", padx=12)
        self.summary_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.summary_label.pack(side="right")

    def _bind_keys(self):
        self.root.bind("<F5>", lambda e: self.rescan(force=True))
        self.root.bind("<Control-o>", lambda e: self.choose_dir())

    # ---------------- 数据刷新 ----------------
    def refresh_all(self):
        self.refresh_tree()
        self.refresh_filter_values()
        self.refresh_table()
        self.refresh_summary()

    def refresh_summary(self):
        info = self.store.projects()
        total_files = sum(p["files"] for p in info)
        total_recs = sum(p["records"] for p in info)
        abn = sum(p["abnormal"] for p in info)
        self.tree_count.config(text="%d 个项目" % len(info))
        self.summary_label.config(
            text="项目 %d  ·  文件 %d  ·  记录 %d  ·  异常 %d" % (len(info), total_files, total_recs, abn))

    def refresh_tree(self):
        self._suppress_select = True
        self.tree.delete(*self.tree.get_children())
        projects = self.store.projects()
        files = list(self.store.file_info().values())
        if not projects:
            self.tree.insert("", "end", iid="__empty__", text="暂无数据，请选择目录或导入演示数据",
                             tags=("empty",))
            self._suppress_select = False
            return
        by_project = {}
        for f in files:
            by_project.setdefault(f["project"], []).append(f)
        for p in projects:
            name = p["project"]
            pid = "P::" + name
            self.tree.insert("", "end", iid=pid, text=unit_label(name), open=True, tags=("project",),
                             values=(p["records"], p["abnormal"] or ""))
            nodes = {}
            for f in sorted(by_project.get(name, []), key=lambda x: x["vpath"]):
                parts = f["vpath"].split("/")
                # 项目名已经作为根节点：跳过路径里同名的第一层（根目录压缩包会多一个 .zip）
                if len(parts) > 1 and (parts[0] == name or parts[0].lower() == (name + ".zip").lower()):
                    parts = parts[1:]
                    base = name + "/"
                else:
                    base = ""
                parent = pid
                path = base.rstrip("/")
                for i, seg in enumerate(parts):
                    path = (path + "/" + seg) if path else seg
                    last = i == len(parts) - 1
                    nid = "N::" + name + "::" + path
                    if nid in nodes:
                        parent = nid
                        continue
                    if last:
                        tag = "error" if f.get("status") == "error" else "file"
                        self.tree.insert(parent, "end", iid=nid, text=seg, tags=(tag,),
                                         values=(f["records"], ""))
                    else:
                        tag = "zip" if seg.lower().endswith(".zip") else "folder"
                        self.tree.insert(parent, "end", iid=nid, text=unit_label(seg),
                                         tags=(tag,), values=("", ""))
                    nodes[nid] = True
                    parent = nid
        self._collapse_duplicate_nodes("")
        self._sort_tree("")
        self._suppress_select = False
        # 汇总各级节点的记录数
        self._aggregate_tree(pid=None)

    def _collapse_duplicate_nodes(self, item):
        """压平“10号/10号.zip”这类重复层级，以及 home/excel 这类无意义包装层。"""
        for child in self.tree.get_children(item):
            self._collapse_duplicate_nodes(child)
        children = self.tree.get_children(item)
        if item and len(children) == 1:
            child = children[0]
            if "file" in self.tree.item(child, "tags"):
                return
            child_text = self.tree.item(child, "text")
            same_name = child_text == self.tree.item(item, "text")
            wrapper = child_text.lower() in ("home", "excel")
            if same_name or wrapper:
                for grand in self.tree.get_children(child):
                    self.tree.move(grand, item, "end")
                self.tree.delete(child)

    def _sort_tree(self, item):
        """机组节点按号码从小到大排（1、4、5、7、8、10、11、12）。"""
        def key(child):
            text = self.tree.item(child, "text")
            m = re.fullmatch(r"(\d+)#", text)
            if m:
                return (0, int(m.group(1)), text)
            return (1, 0, text.lower())

        for child in sorted(self.tree.get_children(item), key=key):
            self.tree.move(child, item, "end")
        for child in self.tree.get_children(item):
            self._sort_tree(child)

    def _aggregate_tree(self, pid=None):
        def walk(item, is_project=False):
            recs = 0
            abn = 0
            if not is_project:
                own_r = self.tree.set(item, "records")
                own_a = self.tree.set(item, "abn")
                try:
                    recs = int(own_r) if str(own_r).strip() else 0
                except ValueError:
                    recs = 0
                try:
                    abn = int(own_a) if str(own_a).strip() else 0
                except ValueError:
                    abn = 0
            for child in self.tree.get_children(item):
                c_recs, c_abn = walk(child)
                recs += c_recs
                abn += c_abn
            self.tree.set(item, "records", recs if recs else "")
            self.tree.set(item, "abn", abn if abn else "")
            return recs, abn
        for item in self.tree.get_children():
            walk(item, is_project=item.startswith("P::"))

    def refresh_filter_values(self):
        project = self.scope_project or None
        prefix = self.scope_prefix
        devices = self.store.distinct("device", project, prefix)
        devices.sort(key=lambda d: (0, int(re.sub(r"\D", "", d) or 0)) if re.fullmatch(r"\d+#?", d) else (1, 0))
        self.cmb_device.config(values=["全部机组"] + devices)
        if self.var_device.get() not in ["全部机组"] + devices:
            self.var_device.set("全部机组")
        groups = sorted({r[0] for r in self.store.conn.execute(
            "SELECT DISTINCT group_key FROM records WHERE 1=1" + (" AND project=?" if project else ""),
            ([project] if project else []))})
        group_labels = ["全部参数组"] + [group_name(g) for g in groups]
        self.cmb_group.config(values=group_labels)
        self._group_map = {group_name(g): g for g in groups}
        if self.var_group.get() not in group_labels:
            self.var_group.set("全部参数组")
        params = self.store.conn.execute(
            "SELECT DISTINCT param, name FROM records WHERE 1=1" + (" AND project=?" if project else "") +
            " ORDER BY name", ([project] if project else [])).fetchall()
        self._param_map = {r["name"]: r["param"] for r in params}
        param_labels = ["全部参数"] + [r["name"] for r in params]
        self.cmb_param.config(values=param_labels)
        if self.var_param.get() not in param_labels:
            self.var_param.set("全部参数")
        if self.chart_device and self.chart_device not in devices:
            self.chart_device = ""
        self.cmb_chart_device.config(values=devices)
        self.var_chart_device.set(self.chart_device if self.chart_device else (devices[0] if devices else ""))
        self.refresh_chart_params()
        scope = self.scope_prefix or self.scope_project or "全部项目"
        self.filter_hint.config(text="范围：%s" % scope)

    def refresh_chart_params(self):
        device = self.var_chart_device.get()
        project = self.scope_project or None
        rows = self.store.conn.execute(
            "SELECT DISTINCT param, name FROM records WHERE 1=1" + (" AND project=?" if project else "") +
            (" AND device=?" if device else "") + " ORDER BY name",
            ([project] if project else []) + ([device] if device else [])).fetchall()
        values = [r["name"] for r in rows]
        self._chart_param_map = {r["name"]: r["param"] for r in rows}
        self.cmb_chart_param.config(values=values)
        if self.chart_param:
            for k, v in self._chart_param_map.items():
                if v == self.chart_param:
                    self.var_chart_param.set(k)
                    return
        if values:
            self.var_chart_param.set(values[0])
            self.chart_param = self._chart_param_map[values[0]]
        else:
            self.var_chart_param.set("")

    def current_filters(self):
        status = self.var_status.get()
        group_label = self.var_group.get()
        param_label = self.var_param.get()
        device = self.var_device.get()
        if status == "异常/关注":
            status_value = "异常,关注"
        elif status in ("异常", "关注", "正常", "待定"):
            status_value = status
        else:
            status_value = ""
        return {
            "project": self.scope_project,
            "prefix": self.scope_prefix,
            "device": "" if device in ("", "全部机组") else device,
            "group": self._group_map.get(group_label, ""),
            "param": self._param_map.get(param_label, ""),
            "status": status_value,
            "keyword": self.var_keyword.get().strip(),
        }

    def refresh_table(self):
        filters = self.current_filters()
        self.rows = self.store.query(limit=MAX_PREVIEW_ROWS, **filters)
        # ISO 4406 的报警不在监测数据表里展示
        self.rows = [r for r in self.rows if r["param"] != "clean_iso"]
        self.rows = self._sorted_rows(self.rows)
        self.render_rows()
        if not self.rows:
            total = self.store.count(project=self.scope_project or None, prefix=self.scope_prefix)
            if total:
                self.table_info.config(
                    text="当前筛选（%s）没有数据；该项目共 %d 条记录，把「状态」改成「全部」即可查看"
                         % (self.var_status.get(), total))
        self.refresh_chart_params()
        self.draw_trend()

    def _sorted_rows(self, rows):
        key = self.sort_col
        mapping = {"device": "device", "date": "date", "name": "name",
                   "value": "value", "unit": "unit", "limit": "param", "status": "status"}
        field = mapping.get(key, "device")

        def sort_key(r):
            v = r.get(field)
            if field == "device":
                num = re.sub(r"\D", "", str(v or ""))
                return (0, int(num or 0), str(v))
            if field == "value":
                return (v is None, v if v is not None else 0)
            return (v is None, str(v))

        try:
            rows = sorted(rows, key=sort_key, reverse=self.sort_desc)
        except Exception:
            rows = rows
        return rows

    def render_rows(self):
        self._suppress_select = True
        self.table.delete(*self.table.get_children())
        for i, r in enumerate(self.rows):
            tags = [r["status"]]
            if i % 2 == 1:
                tags.append("zebra")
            self.table.insert("", "end", iid=str(r["id"]), tags=tuple(tags), values=(
                r["device"], r["date"], r["name"],
                "" if r["value"] is None else ("%g" % r["value"]), r["unit"],
                limit_text(r["param"]), STATUS_DISPLAY.get(r["status"], r["status"]),
            ))
        self._suppress_select = False
        self.table_info.config(text="共 %d 条%s" % (
            len(self.rows), "（仅显示前 %d 条）" % MAX_PREVIEW_ROWS if len(self.rows) >= MAX_PREVIEW_ROWS else ""))

    def refresh_status_text(self):
        self.status_label.config(text="就绪")

    # ---------------- 事件 ----------------
    def on_tree_select(self, _event=None):
        if self._suppress_select:
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == "__empty__":
            return
        if iid.startswith("P::"):
            self.scope_project = iid[3:]
            self.scope_prefix = ""
        else:
            parts = iid[3:].split("::", 1)
            self.scope_project = parts[0]
            self.scope_prefix = parts[1] if len(parts) > 1 else ""
        self.var_device.set("全部机组")
        self.var_group.set("全部参数组")
        self.var_param.set("全部参数")
        self.refresh_filter_values()
        self.refresh_table()
        self.refresh_summary()

    def on_row_select(self, _event=None):
        if self._suppress_select:
            return
        sel = self.table.selection()
        if not sel:
            return
        row = self._row_by_id(sel[0])
        if not row:
            return
        self.chart_device = row["device"]
        self.chart_param = row["param"]
        self.var_chart_device.set(row["device"])
        self.refresh_chart_params()
        for label, key in self._chart_param_map.items():
            if key == row["param"]:
                self.var_chart_param.set(label)
                break
        self.draw_trend()

    def on_row_double(self, _event=None):
        sel = self.table.selection()
        if not sel:
            return
        row = self._row_by_id(sel[0])
        if not row:
            return
        messagebox.showinfo("数据来源",
                            "文件：%s\n工作表：%s\n设备：%s\n参数：%s\n原始值：%s"
                            % (row["vpath"], row["sheet"], row["device"], row["name"], row["raw"]))

    def _row_by_id(self, iid):
        for r in self.rows:
            if str(r["id"]) == str(iid):
                return r
        return None

    def sort_table(self, col):
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            self.sort_desc = True
        self.rows = self._sorted_rows(self.rows)
        self.render_rows()
        for key in ("device", "date", "name", "value", "unit", "limit", "status"):
            text = {"device": "机组编号", "date": "数据时间", "name": "参数",
                    "value": "数值", "unit": "单位", "limit": "参考限值", "status": "结论"}[key]
            if key == col:
                text += " ▼" if self.sort_desc else " ▲"
            self.table.heading(key, text=text)

    def on_chart_combo(self):
        self.chart_device = self.var_chart_device.get()
        self.refresh_chart_params()
        self.draw_trend()

    def reset_filters(self):
        self.var_device.set("全部机组")
        self.var_group.set("全部参数组")
        self.var_param.set("全部参数")
        self.var_status.set("异常/关注")
        self.var_keyword.set("")
        self.refresh_table()

    # ---------------- 趋势图 ----------------
    def draw_trend(self):
        if not getattr(self, "chart_ready", False):
            return
        self.ax.clear()
        device = self.var_chart_device.get()
        param_label = self.var_chart_param.get()
        param = self._chart_param_map.get(param_label, "") if hasattr(self, "_chart_param_map") else ""
        if not device or not param:
            self._chart_placeholder("请选择机组与参数")
            return
        rows = self.store.query(project=self.scope_project, prefix=self.scope_prefix,
                                device=device, param=param, limit=5000)
        if not rows:
            self._chart_placeholder("该设备没有「%s」的历史数据" % param_label)
            return
        from matplotlib.dates import AutoDateLocator, DateFormatter
        by_date = {}
        for r in rows:
            if not r["date"] or r["value"] is None:
                continue
            by_date.setdefault(r["date"], []).append(r["value"])
        if not by_date:
            self._chart_placeholder("没有可绘制的数值")
            return
        dates = sorted(by_date)
        xs = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
        ys = [sum(by_date[d]) / len(by_date[d]) for d in dates]

        self.ax.plot(xs, ys, color=COLOR_ACCENT, linewidth=1.6, marker="o", markersize=5,
                     markerfacecolor="white", markeredgewidth=1.4, zorder=3, label=param_label)
        warn, alert, direction = param_limit(param)
        if self.var_show_limits.get():
            if alert is not None and direction:
                self.ax.axhline(alert, color=COLOR_ALERT, linestyle="--", linewidth=1.2, alpha=0.85,
                                label="异常限值 %g" % alert)
            if warn is not None and direction:
                self.ax.axhline(warn, color=COLOR_WARN, linestyle=":", linewidth=1.2, alpha=0.85,
                                label="关注限值 %g" % warn)

        for x, y in zip(xs, ys):
            st = judge(param, y)
            if st == "异常":
                self.ax.plot([x], [y], marker="o", markersize=9, markerfacecolor=COLOR_ALERT,
                             markeredgecolor="white", zorder=5)
                self.ax.annotate("%g" % y, (x, y), textcoords="offset points", xytext=(0, 9),
                                 ha="center", fontsize=8, color=COLOR_ALERT)
            elif st == "关注":
                self.ax.plot([x], [y], marker="o", markersize=8, markerfacecolor=COLOR_WARN,
                             markeredgecolor="white", zorder=5)

        unit = param_unit(param)
        self.ax.set_title("%s · %s%s" % (device, param_name(param), ("（%s）" % unit) if unit else ""),
                          fontsize=11, color=COLOR_HEAD, loc="left")
        self.ax.grid(True, color="#e6edf5", linewidth=0.8)
        self.ax.set_axisbelow(True)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            self.ax.spines[spine].set_color("#c8d5e3")
        self.ax.tick_params(colors="#5b6b7d", labelsize=8)
        # 纵坐标不显示 1e7 偏移；计数类数据只显示整数刻度
        from matplotlib.ticker import MaxNLocator, StrMethodFormatter
        self.ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        vals = [abs(v) for v in ys if v is not None]
        if vals and (max(vals) >= 100 or all(abs(v - round(v)) < 1e-9 for v in ys)):
            self.ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
            self.ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        else:
            self.ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
        locator = AutoDateLocator(minticks=3, maxticks=8)
        self.ax.xaxis.set_major_locator(locator)
        self.ax.xaxis.set_major_formatter(DateFormatter("%y-%m-%d"))
        if len(xs) == 1:
            self.ax.set_xlim(xs[0] - dt.timedelta(days=3), xs[0] + dt.timedelta(days=3))
        if len(xs) <= 12 or self.var_show_limits.get():
            self.ax.legend(fontsize=8, frameon=False, loc="upper right")
        try:
            self.fig.autofmt_xdate(rotation=0, ha="center")
        except Exception:
            pass
        self.fig.tight_layout(pad=1.1)
        self.canvas.draw_idle()

    def _chart_placeholder(self, text):
        self.ax.clear()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in ("top", "right", "left", "bottom"):
            self.ax.spines[spine].set_visible(False)
        self.ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=10, color="#8fa0b4",
                     transform=self.ax.transAxes)
        self.canvas.draw_idle()

    # ---------------- 扫描 ----------------
    def choose_dir(self):
        d = filedialog.askdirectory(title="选择项目顶层目录（每个子文件夹 = 一个项目）")
        if not d:
            return
        self.main_dir = d
        self._set_dir_label(d)
        self.scope_project = ""
        self.scope_prefix = ""
        # 选目录＝重新导入，强制重解析，避免“文件没变化→全部跳过”的误解
        self.rescan(force=True)

    def rescan(self, force=False):
        if self.scanning or not self.main_dir:
            if not self.main_dir:
                messagebox.showinfo("提示", "请先选择数据目录")
            return
        self.scanning = True
        self.progress["value"] = 0
        self.status_label.config(text="准备扫描…")
        for b in (self.btn_dir, self.btn_rescan, self.btn_clear, self.btn_analysis):
            b.state(["disabled"])
        main_dir = self.main_dir

        def worker():
            try:
                scanner = Scanner(main_dir, progress=lambda text, pct: self.queue.put(("progress", text, pct)))
                stats = scanner.run(force=force)
                self.queue.put(("done", stats))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(120, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    self.status_label.config(text=msg[1])
                    self.progress["value"] = msg[2]
                elif kind == "done":
                    stats = msg[1]
                    self.scanning = False
                    self.progress["value"] = 100
                    line = ("扫描完成：更新 %d 个文件，跳过 %d 个（未变化），失败 %d 个；本次新增记录 %d 条"
                            % (stats["parsed"], stats["skipped"], stats["failed"], stats["records"]))
                    if stats.get("kept_projects"):
                        line += "；保留其他 %d 个项目" % stats["kept_projects"]
                    self.status_label.config(text=line)
                    for b in (self.btn_dir, self.btn_rescan, self.btn_clear, self.btn_analysis):
                        b.state(["!disabled"])
                    self.refresh_all()
                    # 没有任何预警/报警时，自动切到「全部」，避免刚导入看到空表
                    if not self.rows and self.var_status.get() == "异常/关注":
                        if self.store.count(project=self.scope_project or None,
                                            prefix=self.scope_prefix):
                            self.var_status.set("全部")
                            self.refresh_table()
                    return
                elif kind == "error":
                    self.scanning = False
                    for b in (self.btn_dir, self.btn_rescan, self.btn_clear, self.btn_analysis):
                        b.state(["!disabled"])
                    self.status_label.config(text="扫描失败")
                    messagebox.showerror("扫描失败", msg[1])
                    return
        except queue.Empty:
            pass
        if self.scanning:
            self.root.after(120, self._poll_queue)

    def clear_cache(self):
        if not messagebox.askyesno("清空缓存", "将删除解析缓存与压缩包临时文件，之后会重新扫描。\n确定继续？"):
            return
        self.store.reset()
        if os.path.isdir(ZIP_CACHE_DIR):
            shutil.rmtree(ZIP_CACHE_DIR, ignore_errors=True)
        self.scope_project = ""
        self.scope_prefix = ""
        self.refresh_all()
        if self.main_dir:
            self.rescan(force=True)
        else:
            self.status_label.config(text="缓存已清空")

    # ---------------- 报告 ----------------
    def _report_context(self):
        filters = self.current_filters()
        records = self.store.query(limit=200000, **filters)
        project = self.scope_project or "全部项目"
        if self.scope_prefix:
            project = "%s（%s）" % (project, self.scope_prefix.split("/")[-1])
        files = [f for f in self.store.file_info().values()
                 if (not self.scope_project or f["project"] == self.scope_project)
                 and (not self.scope_prefix or f["vpath"] == self.scope_prefix
                      or f["vpath"].startswith(self.scope_prefix + "/"))]
        records.sort(key=lambda r: (r["device"], r["date"], r["group_key"], r["name"]))
        return project, records, files

    def export_word(self):
        project, records, files = self._report_context()
        if not records:
            messagebox.showinfo("提示", "当前范围内没有数据，无法生成报告")
            return
        try:
            path = build_docx(project, records, files)
        except ImportError:
            messagebox.showerror("缺少依赖", "生成 Word 报告需要 python-docx：pip install python-docx")
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("生成失败", str(exc))
            return
        if messagebox.askyesno("生成成功", "报告已生成：\n%s\n\n是否打开？" % path):
            try:
                os.startfile(path)  # noqa: S606
            except Exception:
                pass

    def export_excel(self):
        project, records, files = self._report_context()
        if not records:
            messagebox.showinfo("提示", "当前范围内没有数据，无法导出")
            return
        try:
            path = build_xlsx(project, records, files)
        except ImportError:
            messagebox.showerror("缺少依赖", "导出 Excel 需要 openpyxl：pip install openpyxl")
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc))
            return
        if messagebox.askyesno("导出成功", "明细已导出：\n%s\n\n是否打开？" % path):
            try:
                os.startfile(path)  # noqa: S606
            except Exception:
                pass

    def open_analysis(self):
        if not self.store.projects():
            messagebox.showinfo("提示", "还没有数据，请先选择数据目录并扫描")
            return
        win = getattr(self, "_analysis_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_set()
                    return
            except tk.TclError:
                pass
        self._analysis_win = AnalysisWindow(self.root, self)

    def export_wear(self):
        """生成报告：先选统计时间段，再按该时段计算并输出 Excel + Word。"""
        projects = [p["project"] for p in self.store.projects()]
        if not projects:
            messagebox.showinfo("提示", "还没有数据，请先选择数据目录并扫描")
            return
        project = self.scope_project
        if not project:
            if len(projects) == 1:
                project = projects[0]
            else:
                messagebox.showinfo("提示", "请先在左侧选择一个项目，再点「报告」")
                return
        files = [f for f in self.store.file_info().values()
                 if f["project"] == project and is_wear_csv(f["vpath"])]
        if not files:
            messagebox.showinfo("提示", "项目「%s」里没有找到磨损数据（磨损.csv / mosun.csv / Oil…csv）" % project)
            return

        template = wear_template_path()
        if not os.path.isfile(template):
            template = filedialog.askopenfilename(title="选择磨损分析模板（副本磨损分析数据模板.xlsx）",
                                                  filetypes=[("Excel 文件", "*.xlsx")])
            if not template:
                return

        def device_no(f):
            num = unit_number(f["vpath"])
            return (num if num is not None else 999, f["vpath"])

        files.sort(key=device_no)

        # 默认时间段 = 磨损数据的首末日期
        dates = []
        for f in files:
            real = f.get("real_path") or ""
            if not os.path.isfile(real):
                continue
            try:
                rows_probe = load_wear_csv(real)
            except Exception:  # noqa: BLE001
                continue
            for idx in (1, -1):
                if len(rows_probe) > idx:
                    t = parse_datetime_text(rows_probe[idx][0])
                    if t:
                        dates.append(t.date())
        today = datetime.now().strftime("%Y-%m-%d")
        default_start = min(dates).isoformat() if dates else today
        default_end = max(dates).isoformat() if dates else today

        dlg = PeriodDialog(self.root, default_start, default_end)
        if not dlg.result:
            return
        start_date, end_date = dlg.result
        period_text = "%s ~ %s" % (start_date.isoformat(), end_date.isoformat())

        safe = re.sub(r'[\\/:*?"<>|]+', "_", project)[:40]
        out_dir = os.path.join(REPORT_DIR, "报告_%s_%s-%s_%s" % (
            safe, start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"),
            datetime.now().strftime("%H%M%S")))
        os.makedirs(out_dir, exist_ok=True)

        summary, failures = [], []
        self.progress["value"] = 0
        for i, f in enumerate(files, start=1):
            self.status_label.config(text="报告：%s（%d/%d）" % (f["vpath"].split("/")[-2:][0], i, len(files)))
            self.progress["value"] = int((i - 1) * 100 / len(files))
            self.root.update_idletasks()
            try:
                real = f.get("real_path") or ""
                if not os.path.isfile(real):
                    raise ValueError("源文件不存在，请重新扫描")
                rows = filter_rows_by_window(load_wear_csv(real), start_date, end_date)
                if len(rows) < 3:
                    raise ValueError("该时间段内没有数据")
                analysis = analyze_wear(rows)
                unit = guess_device(f["vpath"])
                num = re.sub(r"\D", "", unit) or unit
                name = "磨损分析_机组%s_%s.xlsx" % (num, analysis["ym_trend"].replace(".", ""))
                build_wear_workbook(template, unit, analysis, os.path.join(out_dir, name))
                summary.append((num, analysis["ym_trend"], analysis["b7"], analysis["g7"],
                                analysis["conclusion"]))
            except Exception as exc:  # noqa: BLE001
                failures.append("%s：%s" % (f["vpath"], exc))

        self.progress["value"] = 100
        report_path = None
        if summary:
            build_wear_summary(summary, os.path.join(out_dir, "机组磨损数值汇总.xlsx"))
            try:
                self.status_label.config(text="正在生成报告文档…")
                self.root.update_idletasks()
                report_path = build_analysis_report_docx(project, self.store, out_dir,
                                                         start_date, end_date)
            except Exception as exc:  # noqa: BLE001
                failures.append("Word 报告：%s" % exc)
        self.status_label.config(text="报告完成：成功 %d 台，失败 %d 台" % (len(summary), len(failures)))

        msg = "统计时间段：%s\n\n已生成 %d 台机组的磨损分析工作簿与汇总表：\n%s" % (
            period_text, len(summary), out_dir)
        if report_path:
            msg += "\n\n报告文档：\n%s" % os.path.basename(report_path)
        if failures:
            msg += "\n\n失败 %d 个：\n%s" % (len(failures), "\n".join(failures[:6]))
        if summary and messagebox.askyesno("报告完成", msg + "\n\n是否打开输出目录？"):
            try:
                os.startfile(out_dir)  # noqa: S606
            except Exception:
                pass
        elif not summary:
            messagebox.showwarning("报告", msg)

    def open_reports(self):
        os.makedirs(REPORT_DIR, exist_ok=True)
        try:
            os.startfile(REPORT_DIR)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("报告目录", REPORT_DIR)

    # ---------------- 关闭 ----------------
    def on_close(self):
        self.save_state()
        self.store.close()
        self.root.destroy()


def resource_path(name):
    base = getattr(sys, "_MEIPASS", APP_DIR)
    return os.path.join(base, name)


def run_wear_cli(src_dir, out_dir=None, start=None, end=None):
    """命令行批量报告：--wear <数据目录> [输出目录] [起始 YYYY-MM-DD] [结束 YYYY-MM-DD]。"""
    load_threshold_overrides()
    if not os.path.isdir(src_dir):
        raise SystemExit("数据目录不存在：%s" % src_dir)
    start_date = parse_ymd(start) if start else None
    end_date = parse_ymd(end) if end else None
    scanner = Scanner(src_dir)
    stats = scanner.run(force=False)
    store = scanner.store
    projects = [p["project"] for p in store.projects()]
    if not projects:
        raise SystemExit("没有扫描到数据：%s" % src_dir)
    out_root = out_dir or os.path.join(REPORT_DIR, "报告_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_root, exist_ok=True)
    template = wear_template_path()
    if not os.path.isfile(template):
        raise SystemExit("找不到磨损分析模板：%s" % template)
    total = 0
    for project in projects:
        files = [f for f in store.file_info().values()
                 if f["project"] == project and is_wear_csv(f["vpath"])]
        if not files:
            continue
        safe = re.sub(r'[\\/:*?"<>|]+', "_", project)[:40]
        sub = os.path.join(out_root, safe)
        os.makedirs(sub, exist_ok=True)
        summary = []
        files.sort(key=lambda f: unit_number(f["vpath"]) if unit_number(f["vpath"]) is not None else 999)
        for f in files:
            rows = filter_rows_by_window(load_wear_csv(f["real_path"]), start_date, end_date)
            if len(rows) < 3:
                continue
            analysis = analyze_wear(rows)
            unit = guess_device(f["vpath"])
            num = re.sub(r"\D", "", unit) or unit
            build_wear_workbook(template, unit, analysis,
                                os.path.join(sub, "磨损分析_机组%s_%s.xlsx"
                                             % (num, analysis["ym_trend"].replace(".", ""))))
            summary.append((num, analysis["ym_trend"], analysis["b7"], analysis["g7"],
                            analysis["conclusion"]))
            total += 1
        if summary:
            build_wear_summary(summary, os.path.join(sub, "机组磨损数值汇总.xlsx"))
            try:
                build_analysis_report_docx(project, store, sub, start_date, end_date)
            except Exception as exc:  # noqa: BLE001
                print("报告生成失败：%s" % exc)
    return total, out_root


def main():
    enable_dpi_awareness()
    argv = sys.argv[1:]
    if argv and argv[0] in ("--wear", "-w"):
        src = argv[1] if len(argv) > 1 else APP_DIR
        out = argv[2] if len(argv) > 2 else None
        start = argv[3] if len(argv) > 3 else None
        end = argv[4] if len(argv) > 4 else None
        try:
            total, folder = run_wear_cli(src, out, start, end)
            print("报告生成完成：%d 台，输出 %s" % (total, folder))
        except SystemExit as exc:
            print(exc)
            raise
        return None
    set_app_user_model_id()
    hide_console()
    if focus_existing_instance():
        return None
    load_threshold_overrides()
    root = tk.Tk()
    icon = resource_path("app.ico")
    if os.path.isfile(icon):
        try:
            root.iconbitmap(default=icon)
        except Exception:
            pass
    apply_app_theme(root)
    app = OilGUI(root)
    root.mainloop()
    return app


if __name__ == "__main__":
    main()
