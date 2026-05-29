"""state.json v1 → v2 schema 迁移测试。

v1:assets.{code}.signals = {signal_1: MA120-6%, signal_2: MA120-12%, signal_3: MA250}
v2:assets.{code}.signals = {signal_1: MA250, signal_2: MA120-6%, signal_3: MA250-12%}

迁移规则:
- v1.signal_3 → v2.signal_1(MA250)
- v1.signal_1 → v2.signal_2(MA120-6%)
- v1.signal_2 → v2.signal_3(MA120-12%)
- signal_meta 内同步 rename
"""

import json
from pathlib import Path

import pytest

from core.data_io import (
    CURRENT_SCHEMA_VERSION,
    _migrate_state_v1_to_v2,
    load_state,
)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    p = tmp_path / 'state.json'
    monkeypatch.setattr('core.data_io.STATE_PATH', p)
    return p


def _v1_state_sample() -> dict:
    """模拟 5/28 之前 state.json 的真实形态(510300 信号三激活)。"""
    return {
        'last_run': '2026-05-27T11:00:04',
        'assets': {
            '510300': {
                'asof': '2026-05-26',
                'close': 1.928,
                'ma120': 1.9577625,
                'ma250': 1.9650139999999998,
                'signals': {'signal_1': False, 'signal_2': False, 'signal_3': True},
                'signal_meta': {
                    'signal_3': {'lowest_close': 1.919, 'activated_at': '2026-05-14'}
                },
                'errors': [],
            },
            '510500': {
                'signals': {'signal_1': False, 'signal_2': False, 'signal_3': False},
                'signal_meta': {},
                'errors': [],
            },
        },
        'ndx': {'signal': False, 'errors': []},
    }


def test_migrate_swaps_signal_keys_correctly():
    v1 = _v1_state_sample()
    v2 = _migrate_state_v1_to_v2(v1)

    # 510300 v1.signal_3=True (MA250) → v2.signal_1=True
    assert v2['assets']['510300']['signals'] == {
        'signal_1': True,   # 原 signal_3 (MA250)
        'signal_2': False,  # 原 signal_1 (MA120-6%)
        'signal_3': False,  # 原 signal_2 (MA120-12%)
    }


def test_migrate_renames_signal_meta_keys():
    v1 = _v1_state_sample()
    v2 = _migrate_state_v1_to_v2(v1)

    meta = v2['assets']['510300']['signal_meta']
    assert 'signal_1' in meta
    assert 'signal_3' not in meta
    assert meta['signal_1']['lowest_close'] == 1.919
    assert meta['signal_1']['activated_at'] == '2026-05-14'


def test_migrate_writes_schema_version():
    v1 = _v1_state_sample()
    v2 = _migrate_state_v1_to_v2(v1)
    assert v2.get('schema_version') == 2


def test_migrate_preserves_non_signal_fields():
    """asof / close / ma120 / ma250 / errors / last_run / ndx 等不变。"""
    v1 = _v1_state_sample()
    v2 = _migrate_state_v1_to_v2(v1)
    assert v2['last_run'] == '2026-05-27T11:00:04'
    assert v2['assets']['510300']['asof'] == '2026-05-26'
    assert v2['assets']['510300']['close'] == 1.928
    assert v2['ndx']['signal'] is False


def test_migrate_handles_asset_with_no_meta():
    """510500 signal_meta 空 → 保持空(不报错)。"""
    v1 = _v1_state_sample()
    v2 = _migrate_state_v1_to_v2(v1)
    assert v2['assets']['510500']['signal_meta'] == {}


def test_migrate_with_signal_1_and_signal_2_also_active():
    """信号 1+2 同时激活(老编号)→ 应该变成新编号 2+3。"""
    v1 = {
        'assets': {
            'X': {
                'signals': {'signal_1': True, 'signal_2': True, 'signal_3': False},
                'signal_meta': {
                    'signal_1': {'lowest_close': 1.5, 'activated_at': '2026-04-01'},
                    'signal_2': {'lowest_close': 1.4, 'activated_at': '2026-04-10'},
                },
            }
        }
    }
    v2 = _migrate_state_v1_to_v2(v1)
    sigs = v2['assets']['X']['signals']
    assert sigs == {'signal_1': False, 'signal_2': True, 'signal_3': True}
    meta = v2['assets']['X']['signal_meta']
    assert meta['signal_2']['lowest_close'] == 1.5    # 原 signal_1
    assert meta['signal_3']['lowest_close'] == 1.4    # 原 signal_2
    assert 'signal_1' not in meta


def test_load_state_auto_migrates_v1(state_path, monkeypatch, tmp_path):
    """load_state 检测到无 schema_version → 自动迁移 + 备份 + 写回。"""
    v1 = _v1_state_sample()
    state_path.write_text(json.dumps(v1), encoding='utf-8')

    loaded = load_state()

    # 返回的 state 是 v2
    assert loaded.get('schema_version') == 2
    assert loaded['assets']['510300']['signals']['signal_1'] is True
    assert 'signal_1' in loaded['assets']['510300']['signal_meta']

    # 写盘也是 v2
    on_disk = json.loads(state_path.read_text())
    assert on_disk.get('schema_version') == 2

    # 备份文件应存在
    backups = list(state_path.parent.glob('state.json.bak.before-schema-v2.*'))
    assert len(backups) == 1


def test_load_state_no_double_migration(state_path):
    """已是 v2 schema → 直接返回,不重复迁移。"""
    v2 = {
        'schema_version': 2,
        'assets': {
            '510300': {
                'signals': {'signal_1': True, 'signal_2': False, 'signal_3': False},
                'signal_meta': {'signal_1': {'lowest_close': 1.919, 'activated_at': '2026-05-14'}},
            }
        },
    }
    state_path.write_text(json.dumps(v2), encoding='utf-8')

    loaded = load_state()
    assert loaded == v2

    # 不应该生成新备份
    backups = list(state_path.parent.glob('state.json.bak.before-schema-v2.*'))
    assert len(backups) == 0


def test_load_state_empty_file_no_migration(state_path):
    """state.json 不存在 → load_state 返回 fresh state,无迁移。"""
    # state_path 不存在
    loaded = load_state()
    assert 'last_run' in loaded
    assert loaded['assets'] == {}


def test_current_schema_version_is_2():
    """常量 sanity check。"""
    assert CURRENT_SCHEMA_VERSION == 2
