"""NDX 卡片(build_ndx_card_md / build_ndx_summary_line)渲染测试。

NDX 卡片**只在 VIX 触发(fired)时推送**(runner.py 仅 `if ndx_result['fired']` 调用),
所以它永远是"已触发"卡片。2026-05-28 重设计后:去 H2 标题、3 列表格、阈值用 VIX_THRESHOLD。
VIX 长期 < 30 未触发,这段新格式代码一直没经真实推送验证 —— 这些测试把新格式钉死,
防止回退到 5/14 旧格式(带 `## H2` / 阈值 15 / "金额自定" / "不构成投资建议"等冗余)。
"""

from datetime import date

from core.cards import (
    NDX_RULE_FOOTER,
    build_ndx_card_md,
    build_ndx_summary_line,
)
from core.signals import VIX_THRESHOLD

TODAY = date(2026, 5, 28)


def _fired_ndx(close=30223.8887, vix=31.5, asof='2026-05-28', errors=None):
    """构造一个 fired NDX result(结构对齐 runner.process_ndx 的输出)。"""
    return {
        'asof': asof,
        'close': close,
        'vix': vix,
        'signal': True,
        'fired': True,
        'errors': errors or [],
    }


# ===== build_ndx_card_md(已触发卡片)=====

def test_ndx_card_has_no_h2_header():
    """重设计后去掉 `## 标题`(避免与推送 title 字面重复)。"""
    # Arrange / Act
    card = build_ndx_card_md(TODAY, _fired_ndx())

    # Assert
    assert '#' not in card
    assert card.lstrip().startswith('>')


def test_ndx_card_starts_with_asof_quote():
    card = build_ndx_card_md(TODAY, _fired_ndx(asof='2026-05-28'))

    assert card.lstrip().startswith('> 数据截至 2026-05-28')


def test_ndx_card_three_column_table():
    card = build_ndx_card_md(TODAY, _fired_ndx())

    assert '| 指标 | 数值 | 状态 |' in card
    assert '|---|---|---|' in card


def test_ndx_card_renders_close_and_vix_two_decimals():
    card = build_ndx_card_md(TODAY, _fired_ndx(close=30223.8887, vix=31.5))

    assert '`30223.89`' in card       # NDX 收盘两位小数
    assert '**`31.50`**' in card      # VIX 加粗两位小数


def test_ndx_card_uses_vix_threshold_constant_not_legacy_15():
    """阈值用 VIX_THRESHOLD 动态渲染(当前 30),不是旧格式硬编码的 15。"""
    card = build_ndx_card_md(TODAY, _fired_ndx())

    assert f'突破阈值 {VIX_THRESHOLD:.0f}' in card
    assert '15' not in card


def test_ndx_card_marks_vix_as_fired():
    """卡片只在 fired 时推 → VIX 行带 🔴 + 恐慌区文案。"""
    card = build_ndx_card_md(TODAY, _fired_ndx())

    assert '🔴 VIX' in card
    assert '恐慌区' in card


def test_ndx_card_no_legacy_cruft():
    """旧格式的冗余文案不应再出现。"""
    card = build_ndx_card_md(TODAY, _fired_ndx())

    for legacy in ('金额自定', '仅为预设规则提醒', '不构成投资建议', '阈值 15', '####'):
        assert legacy not in card, f'残留旧文案: {legacy!r}'


def test_ndx_card_footer_threshold_matches_constant():
    """规则 footer 的阈值数字必须与 VIX_THRESHOLD 一致。

    footer 当前把 30 写成字符串字面量,而表格单元格用 `{VIX_THRESHOLD:.0f}` 动态渲染。
    这条 guard 防止将来改常量时漏改 footer 导致两处不一致。
    """
    assert f'VIX > {VIX_THRESHOLD:.0f}' in NDX_RULE_FOOTER
    assert NDX_RULE_FOOTER in build_ndx_card_md(TODAY, _fired_ndx())


def test_ndx_card_missing_close_shows_placeholder():
    """红线:数据未取到一律标"未取到",不编造(NDX 行情取失败但 VIX 已触发的边界)。"""
    card = build_ndx_card_md(TODAY, _fired_ndx(close=None))

    assert '未取到' in card


# ===== build_ndx_summary_line(未触发时的 stdout 摘要)=====

def test_ndx_summary_line_basic():
    line = build_ndx_summary_line(_fired_ndx(close=30223.8887, vix=17.84, errors=[]))

    assert '30223.89' in line
    assert '17.84' in line
    assert f'阈值 {VIX_THRESHOLD:.0f}' in line
    assert '缺数' not in line


def test_ndx_summary_line_with_errors():
    line = build_ndx_summary_line(_fired_ndx(errors=['vix_fetch_failed']))

    assert '缺数' in line
    assert 'vix_fetch_failed' in line
