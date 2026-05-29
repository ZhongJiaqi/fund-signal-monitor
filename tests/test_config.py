"""配置加载(core.config.load_config)测试。

开源脱敏:基金列表不再硬编码进源码,改为从 config.json(gitignored)读;
缺失时回退 committed 的 config.example.json,让 clone 后未配置也能跑通示例 + 测试。
"""

import json
from pathlib import Path

from core.config import load_config
from core.data_io import Asset, _assets_from_config

ROOT = Path(__file__).resolve().parent.parent


def test_load_config_prefers_real_config_when_present(tmp_path):
    real = tmp_path / 'config.json'
    real.write_text(json.dumps(
        {'dividend_assets': [{'fund_code': '111111', 'fund_name': '真实基金'}], 'shortma_assets': []}
    ), encoding='utf-8')
    example = tmp_path / 'config.example.json'
    example.write_text(json.dumps(
        {'dividend_assets': [{'fund_code': '999999', 'fund_name': '示例基金'}], 'shortma_assets': []}
    ), encoding='utf-8')

    cfg = load_config(real_path=real, example_path=example)

    assert cfg['dividend_assets'][0]['fund_code'] == '111111'


def test_load_config_falls_back_to_example_when_real_missing(tmp_path):
    example = tmp_path / 'config.example.json'
    example.write_text(json.dumps(
        {'dividend_assets': [{'fund_code': '510300', 'fund_name': '沪深300ETF（示例）'}], 'shortma_assets': []}
    ), encoding='utf-8')

    cfg = load_config(real_path=tmp_path / 'does_not_exist.json', example_path=example)

    assert cfg['dividend_assets'][0]['fund_code'] == '510300'


def test_committed_example_config_is_valid():
    """committed 的 config.example.json 必须存在、可解析、两个列表齐全、字段完整。"""
    example = json.loads((ROOT / 'config.example.json').read_text(encoding='utf-8'))

    assert isinstance(example.get('dividend_assets'), list) and len(example['dividend_assets']) >= 1
    assert isinstance(example.get('shortma_assets'), list) and len(example['shortma_assets']) >= 1
    for group in ('dividend_assets', 'shortma_assets'):
        for a in example[group]:
            assert 'fund_code' in a and 'fund_name' in a


def test_assets_from_config_builds_frozen_assets():
    cfg = {'dividend_assets': [{'fund_code': '510300', 'fund_name': '沪深300ETF'}]}

    assets = _assets_from_config(cfg, 'dividend_assets')

    assert assets == [Asset(fund_code='510300', fund_name='沪深300ETF')]


def test_assets_from_config_missing_key_returns_empty():
    assert _assets_from_config({}, 'dividend_assets') == []
