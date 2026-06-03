"""红利低波卡片 `build_dividend_card_md` 渲染契约。

dividend 卡片 4 列(基金 / 距 MA120 / 距 MA250 / 状态),状态列融合 5 种 emoji 情态:
🔴 first / ⬇️ new_low / 🟢 still_active / 🟡 near / ⚪ inactive。行按事件优先级排序。

这是三个 card builder 里最后一个加单测的(shortma / ndx 已有),用来钉死状态文案、
表头结构、行排序、百分比格式,防止重构时回退。
"""

from datetime import date

from core.cards import DIVIDEND_RULE_FOOTER, build_dividend_card_md
from core.data_io import Asset

TODAY = date(2026, 6, 3)


def _trading_dates_around(activated_iso: str, today: date) -> set:
    """构造一个交易日集合,覆盖 activated_at → today 的工作日(简化:全算交易日)。

    用于 compute_active_days 算"第 N 天"文案。真实日历跳过周末/节假日,
    这里 mock 一个连续区间够测试用。
    """
    y, m, d = (int(x) for x in activated_iso.split('-'))
    start = date(y, m, d)
    cal = set()
    cur = start
    while cur <= today:
        cal.add(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return cal


# ===== result 构造工具 =====

def _base_result(
    *,
    close=2.00,
    ma120=1.95,
    ma250=1.96,
    signals=None,
    signal_meta=None,
    fired_first=None,
    fired_new_low=None,
    fired_still_active=None,
    errors=None,
    asof='2026-06-02',
    fund_code='999999',
    fund_name='占位基金',
):
    return {
        'fund_code': fund_code,
        'fund_name': fund_name,
        'asof': asof,
        'close': close,
        'ma120': ma120,
        'ma250': ma250,
        'signals': signals or {'signal_1': False, 'signal_2': False, 'signal_3': False},
        'signal_meta': signal_meta or {},
        'fired_first': fired_first or [],
        'fired_new_low': fired_new_low or [],
        'fired_still_active': fired_still_active or [],
        'errors': errors or [],
    }


def _inactive_result():
    """⚪ 未激活,距 signal_1 (MA250) 较远(>1%)。close 高于 ma250 ~+2%。"""
    return _base_result(close=2.00, ma120=1.95, ma250=1.96)


def _near_result():
    """🟡 临近信号一:close 略高于 ma250,距阈值 <1%。"""
    return _base_result(close=1.965, ma120=1.95, ma250=1.96)


def _first_result(sig_keys=('signal_1',)):
    """🔴 首次激活信号一。"""
    signals = {'signal_1': False, 'signal_2': False, 'signal_3': False}
    for k in sig_keys:
        signals[k] = True
    return _base_result(
        close=1.95,
        ma120=1.96,
        ma250=1.97,
        signals=signals,
        fired_first=list(sig_keys),
        signal_meta={k: {'lowest_close': 1.95, 'activated_at': '2026-06-02'} for k in sig_keys},
    )


def _new_low_result():
    """⬇️ 信号一已激活,今天再创新低。"""
    return _base_result(
        close=1.90,
        ma120=1.96,
        ma250=1.97,
        signals={'signal_1': True, 'signal_2': False, 'signal_3': False},
        fired_new_low=['signal_1'],
        signal_meta={'signal_1': {'lowest_close': 1.90, 'activated_at': '2026-05-14'}},
    )


def _still_active_result():
    """🟢 信号一持续激活,close ≥ lowest 不创新低。"""
    return _base_result(
        close=1.95,
        ma120=1.97,
        ma250=1.96,
        signals={'signal_1': True, 'signal_2': False, 'signal_3': False},
        fired_still_active=['signal_1'],
        signal_meta={'signal_1': {'lowest_close': 1.90, 'activated_at': '2026-05-14'}},
    )


def _missing_result():
    """⚠ 取数失败,close=None。"""
    return _base_result(close=None, ma120=None, ma250=None, errors=['fetch_failed'])


def _render(results, today=TODAY, asof='2026-06-02', trading_dates=None):
    """简化调用:把 [(Asset, result), ...] 渲染成 md。"""
    return build_dividend_card_md(today, results, asof=asof, trading_dates=trading_dates)


def _asset(code='999999', name='占位基金'):
    return Asset(fund_code=code, fund_name=name)


# ===== 结构契约 =====

def test_card_has_no_h2_header():
    """2026-05-28 重设计后去 H2(避免与推送 title 重复)。"""
    md = _render([(_asset(), _inactive_result())])
    assert '#' not in md


def test_card_starts_with_asof_quote():
    md = _render([(_asset(), _inactive_result())], asof='2026-06-02')
    assert md.lstrip().startswith('> 数据截至 2026-06-02')


def test_card_header_four_columns():
    """表头精确 4 列:基金 / 距 MA120 / 距 MA250 / 状态。"""
    md = _render([(_asset(), _inactive_result())])
    assert '| 基金 | 距 MA120 | 距 MA250 | 状态 |' in md
    assert '|---|---|---|---|' in md


def test_card_ends_with_rule_footer():
    md = _render([(_asset(), _inactive_result())])
    assert md.rstrip().endswith(DIVIDEND_RULE_FOOTER)


def test_rule_footer_lists_three_signals():
    """规则段必须列出全部三档信号(2026-06-01 改成 markdown 列表后的契约)。"""
    assert '信号一' in DIVIDEND_RULE_FOOTER
    assert '信号二' in DIVIDEND_RULE_FOOTER
    assert '信号三' in DIVIDEND_RULE_FOOTER
    assert 'MA250' in DIVIDEND_RULE_FOOTER
    assert 'MA120' in DIVIDEND_RULE_FOOTER


def test_rule_footer_uses_markdown_list_not_br():
    """`<br>` HTML 标签 Server 酱不解析(字面显示) → 必须用 markdown 列表。"""
    assert '<br>' not in DIVIDEND_RULE_FOOTER
    assert '- 信号' in DIVIDEND_RULE_FOOTER


# ===== 百分比 / 数值格式 =====

def test_pct_diff_format_signed_two_decimals():
    """距 MA120 / 距 MA250 列必须 `+/-X.XX%` 两位小数。"""
    md = _render([(_asset(), _inactive_result())])
    # close=2.00, ma120=1.95 → +2.56%
    assert '`+2.56%`' in md
    # close=2.00, ma250=1.96 → +2.04%
    assert '`+2.04%`' in md


def test_pct_diff_missing_renders_dash():
    """close=None → 距 MA 列显示 `-`,不显示 `nan%`。"""
    md = _render([(_asset(), _missing_result())])
    assert '`-`' in md
    assert 'nan' not in md.lower()


# ===== 5 种 emoji 状态文案 =====

def test_state_first_renders_red_and_bold():
    """🔴 first → `**信号X首次激活**`,加粗。"""
    md = _render([(_asset(), _first_result(('signal_1',)))])
    assert '🔴' in md
    assert '**信号一首次激活**' in md


def test_state_first_with_multiple_signals_picks_deepest():
    """多档同时首次激活 → 显示最深档(_SIG_DEPTH 最大)。"""
    md = _render([(_asset(), _first_result(('signal_1', 'signal_2', 'signal_3')))])
    assert '**信号三首次激活**' in md
    # 浅档不能反过来出现
    assert '**信号一首次激活**' not in md


def test_state_new_low_renders_arrow_and_bold():
    """⬇️ new_low → `**信号X探底新低** · 已激活 N 天`。"""
    cal = _trading_dates_around('2026-05-14', TODAY)
    md = _render([(_asset(), _new_low_result())], trading_dates=cal)
    assert '⬇️' in md
    assert '**信号一探底新低**' in md
    assert '已激活' in md
    assert '天' in md


def test_state_still_active_renders_green_and_days_count():
    """🟢 still_active → `信号X激活**第 N 天** · 再跌 X.X% 触发信号Y`。"""
    cal = _trading_dates_around('2026-05-14', TODAY)
    md = _render([(_asset(), _still_active_result())], trading_dates=cal)
    assert '🟢' in md
    assert '信号一激活' in md
    assert '**第' in md and '天**' in md
    assert '再跌' in md
    assert '触发信号二' in md


def test_state_still_active_without_trading_dates_falls_back_to_zhong():
    """trading_dates 为空 → days=None → 文案降级为 `激活中`,不渲染"第 None 天"。"""
    md = _render([(_asset(), _still_active_result())], trading_dates=None)
    assert '信号一激活中' in md
    assert 'None' not in md


def test_state_near_renders_yellow_and_gap():
    """🟡 near → `临近信号X · 距阈值 +X.XX%`。"""
    md = _render([(_asset(), _near_result())])
    assert '🟡' in md
    assert '临近信号一' in md
    assert '距阈值 +' in md


def test_state_inactive_renders_white_and_distance():
    """⚪ inactive → `未激活 · 距信号X +X.XX%`。"""
    md = _render([(_asset(), _inactive_result())])
    assert '⚪' in md
    assert '未激活 · 距信号一' in md


def test_state_missing_renders_warning():
    """close=None → ⚠ 数据缺失。"""
    md = _render([(_asset(), _missing_result())])
    assert '⚠' in md
    assert '数据缺失' in md


# ===== 行排序优先级 =====

def test_rows_sorted_by_event_priority():
    """优先级:🔴 first → ⬇️ new_low → 🟢 still_active → 🟡 near → ⚪ inactive。"""
    rows = [
        (_asset('A_inactive', '未激活'), _inactive_result()),
        (_asset('B_still', '持续'), _still_active_result()),
        (_asset('C_first', '首次'), _first_result()),
        (_asset('D_new_low', '新低'), _new_low_result()),
        (_asset('E_near', '临近'), _near_result()),
    ]
    md = _render(rows, trading_dates=_trading_dates_around('2026-05-14', TODAY))
    # 抓表格 body 行的出现顺序(每行以 fund_code 开头)
    positions = {
        code: md.find(f'`{code}`')
        for code in ('A_inactive', 'B_still', 'C_first', 'D_new_low', 'E_near')
    }
    assert all(p > 0 for p in positions.values()), positions
    assert positions['C_first'] < positions['D_new_low']
    assert positions['D_new_low'] < positions['B_still']
    assert positions['B_still'] < positions['E_near']
    assert positions['E_near'] < positions['A_inactive']


def test_same_priority_sorted_by_fund_code():
    """同事件类型 → fund_code 字典序。"""
    rows = [
        (_asset('Z999'), _inactive_result()),
        (_asset('A001'), _inactive_result()),
        (_asset('M500'), _inactive_result()),
    ]
    md = _render(rows)
    pa = md.find('`A001`')
    pm = md.find('`M500`')
    pz = md.find('`Z999`')
    assert 0 < pa < pm < pz


# ===== errors 字段渲染 =====

def test_errors_appended_below_row():
    """result.errors 非空 → 表格下方追加 `> ⚠ {code} 缺数据: ...`。"""
    r = _inactive_result()
    r['errors'] = ['nav_fetch_failed', 'ma_compute_failed']
    md = _render([(_asset('510300', '测试基金'), r)])
    assert '> ⚠ `510300` 缺数据' in md
    assert 'nav_fetch_failed' in md
    assert 'ma_compute_failed' in md


# ===== 红线:fired_* 与 signals 一致性 =====

def test_inactive_does_not_show_active_days():
    """未激活的基金不应渲染"第 N 天"等持续激活文案。"""
    md = _render([(_asset(), _inactive_result())])
    assert '激活' not in md or '未激活' in md  # 只在 "未激活" 上下文里允许 "激活" 子串
    assert '第' not in md
    assert '探底' not in md
