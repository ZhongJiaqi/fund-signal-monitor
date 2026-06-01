"""科技通道卡片 `build_shortma_card_md` 渲染契约 — 锁定基金列内"板块标签"格式不变量。

板块标签格式:`` `{code}` [{sector}]{fund_name} ``(板块用半角方括号包裹,后紧贴基金名);
sector 为空时退化为 `` `{code}` {fund_name} ``。
"""

from datetime import date

from core.cards import build_shortma_card_md
from core.data_io import Asset


def _safe_result(close=2.0, ma20=1.95):
    """构造一只"MA20 之上"的安全基金 result(无任何 fired_* 事件)。"""
    return {
        'fund_code': '999999', 'fund_name': '占位',
        'asof': '2026-05-29', 'close': close, 'ma20': ma20,
        'signal': False,
        'fired_first': False, 'fired_new_low': False, 'fired_still_active': False,
        'signal_meta': {}, 'errors': [],
    }


def _fired_result(close=1.85, ma20=1.95):
    """构造一只首次跌破 MA20 的 result(fired_first=True)。"""
    return {
        'fund_code': '999998', 'fund_name': '占位',
        'asof': '2026-05-29', 'close': close, 'ma20': ma20,
        'signal': True,
        'fired_first': True, 'fired_new_low': False, 'fired_still_active': False,
        'signal_meta': {'lowest_close': close, 'activated_at': '2026-06-01'},
        'errors': [],
    }


# ===== sector 标签格式 =====

def test_card_includes_sector_tag_in_fund_cell():
    """有 sector → 基金列必须出现 `[{sector}]` 紧贴基金名。"""
    asset = Asset(fund_code='025833', fund_name='天弘中证电网设备主题指数发起C', sector='电网设备')
    md = build_shortma_card_md(date(2026, 6, 1), [(asset, _safe_result())], asof='2026-05-29')
    assert '`025833` [电网设备]天弘中证电网设备主题指数发起C' in md


def test_card_omits_sector_when_empty():
    """sector 为空字符串 → 退化为旧格式,不显示空方括号。"""
    asset = Asset(fund_code='159915', fund_name='创业板ETF', sector='')
    md = build_shortma_card_md(date(2026, 6, 1), [(asset, _safe_result())], asof='2026-05-29')
    assert '`159915` 创业板ETF' in md
    assert '[]' not in md, '空 sector 不应渲染出空方括号'


def test_card_omits_sector_when_default_param_missing():
    """Asset 不传 sector → default '' → 不渲染方括号(向后兼容旧 config.json)。"""
    asset = Asset(fund_code='159915', fund_name='创业板ETF')
    md = build_shortma_card_md(date(2026, 6, 1), [(asset, _safe_result())], asof='2026-05-29')
    assert '[]' not in md
    assert '`159915` 创业板ETF' in md


def test_card_mixed_sector_and_no_sector():
    """同一张卡片混合 有/无 sector → 各自按自己的格式渲染,互不影响。"""
    a_with = Asset(fund_code='025833', fund_name='电网基金', sector='电网设备')
    a_without = Asset(fund_code='159915', fund_name='创业板ETF')
    md = build_shortma_card_md(
        date(2026, 6, 1),
        [(a_with, _safe_result()), (a_without, _safe_result())],
        asof='2026-05-29',
    )
    assert '`025833` [电网设备]电网基金' in md
    assert '`159915` 创业板ETF' in md


# ===== 表格结构契约 =====

def test_card_header_unchanged_no_extra_column():
    """加 sector 标签**不是**新增独立列,表头仍是 3 列。"""
    asset = Asset(fund_code='025833', fund_name='电网基金', sector='电网设备')
    md = build_shortma_card_md(date(2026, 6, 1), [(asset, _safe_result())], asof='2026-05-29')
    # 表头精确匹配旧 3 列
    assert '| 基金 | 距 MA20 | 状态 |' in md
    assert '|---|---|---|' in md
    # 没有引入"板块"作为表头列
    assert '| 板块 |' not in md


def test_card_sector_appears_on_correct_row_only():
    """sector 仅渲染在对应行,不污染其他行。"""
    a1 = Asset(fund_code='025833', fund_name='电网基金', sector='电网设备')
    a2 = Asset(fund_code='002112', fund_name='德邦基金', sector='CPO')
    md = build_shortma_card_md(
        date(2026, 6, 1),
        [(a1, _safe_result()), (a2, _safe_result())],
        asof='2026-05-29',
    )
    # 电网设备 / CPO 各自只出现 1 次(在自己的行),不串行
    assert md.count('电网设备') == 1
    assert md.count('CPO') == 1


def test_card_fired_row_still_carries_sector_tag():
    """触发(fired_first)的行,板块标签同样保留(状态列内容不影响基金列格式)。"""
    asset = Asset(fund_code='002112', fund_name='德邦鑫星混合C', sector='CPO')
    md = build_shortma_card_md(date(2026, 6, 1), [(asset, _fired_result())], asof='2026-05-29')
    assert '`002112` [CPO]德邦鑫星混合C' in md
    # 触发态 emoji + 文案在状态列正常出现
    assert '🔴' in md
    assert '首次跌破 MA20' in md
