#!/usr/bin/env python3
"""
剪贴板管理器启动器 (.pyw = 无终端窗口)
=========================================
双击此文件即可直接启动，不会弹出命令行窗口。
"""

import os
import sys

# 确保能找到同目录下的主程序
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 直接导入并运行主程序
from clipboard_manager import main

if __name__ == "__main__":
    main()
