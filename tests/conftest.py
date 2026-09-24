# -*- coding: utf-8 -*-
"""标记 tests 目录为包，并提供 src 路径注入。"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
