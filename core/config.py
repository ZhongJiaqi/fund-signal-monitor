"""监控配置加载 — 零依赖。

基金列表不硬编码进源码:优先读真实 config.json(gitignored),
缺失时回退 committed 的 config.example.json,让 clone 后未配置也能跑通示例 + 测试。
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / 'config.json'
EXAMPLE_PATH = _ROOT / 'config.example.json'


def load_config(real_path: Path = CONFIG_PATH, example_path: Path = EXAMPLE_PATH) -> dict:
    """读监控配置 dict:优先真实 config.json,缺失回退 config.example.json。"""
    path = real_path if Path(real_path).exists() else example_path
    with open(path, encoding='utf-8') as f:
        return json.load(f)
