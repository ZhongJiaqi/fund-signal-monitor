"""Markdown 卡片构建:三个板块合并卡(2026-05-28 重设计)。

每个板块只有一种卡片,推送标题与卡片 H2 字面一致 = `{板块} · {today}`。
表格永远展示所有基金的完整状态(消除原"加仓卡 vs 状态卡"互斥导致的信息丢失)。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from core.signals import (
    SIGNAL_2_DROP,
    SIGNAL_3_DROP,
    SIGNAL_LABELS,
    SIGNAL_NEXT_SHARES,
    SIGNAL_SHARES,
    VIX_THRESHOLD,
    compute_active_days,
    next_threshold,
)


# ===== 文本工具 =====

def fmt_pct(v: Optional[float]) -> str:
    return '未取到' if v is None else f'{v * 100:.1f}%'


def fmt_num(v: Optional[float], digits: int = 2) -> str:
    return '未取到' if v is None else f'{v:.{digits}f}'


def _pct_diff(close: Optional[float], base: Optional[float]) -> str:
    if close is None or base is None:
        return '-'
    return f'{(close / base - 1) * 100:+.2f}%'


# ===== 规则文案 footer =====

DIVIDEND_RULE_FOOTER = (
    '**规则**\n'
    '\n'
    '- 信号一(净值 < MA250)1 份\n'
    '- 信号二(净值 < MA120 × (1 - 6%))1 份\n'
    '- 信号三(净值 < MA120 × (1 - 12%))2 份'
)

SHORTMA_RULE_FOOTER = '> 规则:净值 < MA20 视为短期超跌'

NDX_RULE_FOOTER = '> 规则:VIX > 30 触发恐慌加仓'


# ===== 行排序与 emoji ===

_EVENT_ORDER = {
    'first': 0,
    'new_low': 1,
    'still_active': 2,
    'near': 3,
    'inactive': 4,
    'missing': 5,
}

_KIND_EMOJI = {
    'first': '🔴',
    'new_low': '⬇️',
    'still_active': '🟢',
    'near': '🟡',
    'inactive': '⚪',
    'missing': '⚠',
}

_SIG_DEPTH = {'signal_1': 1, 'signal_2': 2, 'signal_3': 3}


def _emoji(kind: str) -> str:
    return _KIND_EMOJI.get(kind, '')


def _sig_label(sig_key: str) -> str:
    return {'signal_1': '信号一', 'signal_2': '信号二', 'signal_3': '信号三'}.get(sig_key, sig_key)


def _dividend_event_kind(r: dict) -> str:
    """判定红利低波单只基金当前主事件类型,用于排序 + emoji + 文案。"""
    if r.get('fired_first'):
        return 'first'
    if r.get('fired_new_low'):
        return 'new_low'
    if r.get('fired_still_active'):
        return 'still_active'
    close, ma120, ma250 = r.get('close'), r.get('ma120'), r.get('ma250')
    sigs = r.get('signals') or {}
    if close is None:
        return 'missing'
    nt = next_threshold(close, ma120, ma250, sigs)
    if nt is not None:
        _, price = nt
        drop_pct = (1 - price / close) * 100
        if 0 <= drop_pct < 1:
            return 'near'
    return 'inactive'


def _shortma_event_kind(r: dict) -> str:
    if r.get('fired_first'):
        return 'first'
    if r.get('fired_new_low'):
        return 'new_low'
    if r.get('fired_still_active'):
        return 'still_active'
    close, ma20 = r.get('close'), r.get('ma20')
    if close is None or ma20 is None:
        return 'missing'
    if close >= ma20:
        gap = (close / ma20 - 1) * 100
        if gap < 1:
            return 'near'
    return 'inactive'


# ===== 状态列文案渲染 =====

def _render_dividend_state_cell(r: dict, trading_dates: "set[date] | None", today: date) -> str:
    cal = trading_dates if trading_dates is not None else set()
    close = r.get('close')
    ma120 = r.get('ma120')
    ma250 = r.get('ma250')
    sigs = r.get('signals') or {}
    meta = r.get('signal_meta') or {}

    kind = _dividend_event_kind(r)
    emoji = _emoji(kind)

    if kind == 'first':
        sig_keys = sorted(r.get('fired_first') or [], key=lambda k: _SIG_DEPTH.get(k, 99))
        sig_key = sig_keys[-1]
        return f'{emoji} **{_sig_label(sig_key)}首次激活**'

    if kind == 'new_low':
        sig_keys = sorted(r.get('fired_new_low') or [], key=lambda k: _SIG_DEPTH.get(k, 99))
        sig_key = sig_keys[-1]
        m = meta.get(sig_key) or {}
        days = None
        activated_at = m.get('activated_at')
        if activated_at:
            d = compute_active_days(activated_at, today, cal)
            days = d if d > 0 else None
        days_str = f' · 已激活 {days} 天' if days else ''
        return f'{emoji} **{_sig_label(sig_key)}探底新低**{days_str}'

    if kind == 'still_active':
        sig_keys = sorted(r.get('fired_still_active') or [], key=lambda k: _SIG_DEPTH.get(k, 99))
        sig_key = sig_keys[-1]
        m = meta.get(sig_key) or {}
        days = None
        activated_at = m.get('activated_at')
        if activated_at:
            d = compute_active_days(activated_at, today, cal)
            days = d if d > 0 else None
        days_str = f'**第 {days} 天**' if days else '中'
        nt = next_threshold(close, ma120, ma250, sigs)
        next_str = ''
        if nt is not None and close is not None:
            label, price = nt
            drop = (1 - price / close) * 100
            next_str = f' · 再跌 {drop:.1f}% 触发{label}'
        return f'{emoji} {_sig_label(sig_key)}激活{days_str}{next_str}'

    if kind == 'near':
        nt = next_threshold(close, ma120, ma250, sigs)
        if nt is not None and close is not None:
            label, price = nt
            drop = (1 - price / close) * 100
            return f'{emoji} 临近{label} · 距阈值 +{drop:.2f}%'
        return f'{emoji} 临近'

    if kind == 'inactive':
        nt = next_threshold(close, ma120, ma250, sigs)
        if nt is not None and close is not None:
            label, price = nt
            drop = (1 - price / close) * 100
            return f'{emoji} 未激活 · 距{label} +{drop:.2f}%'
        return f'{emoji} 未激活'

    return f'{emoji} 数据缺失'


def _render_shortma_state_cell(r: dict, trading_dates: "set[date] | None", today: date) -> str:
    cal = trading_dates if trading_dates is not None else set()
    close = r.get('close')
    ma20 = r.get('ma20')
    meta = r.get('signal_meta') or {}

    kind = _shortma_event_kind(r)
    emoji = _emoji(kind)

    if kind == 'first':
        return f'{emoji} **首次跌破 MA20**'

    if kind == 'new_low':
        days = None
        activated_at = meta.get('activated_at')
        if activated_at:
            d = compute_active_days(activated_at, today, cal)
            days = d if d > 0 else None
        days_str = f' · 已激活 {days} 天' if days else ''
        return f'{emoji} **MA20 探底新低**{days_str}'

    if kind == 'still_active':
        days = None
        activated_at = meta.get('activated_at')
        if activated_at:
            d = compute_active_days(activated_at, today, cal)
            days = d if d > 0 else None
        days_str = f'**第 {days} 天**' if days else '中'
        return f'{emoji} 跌破 MA20 {days_str}'

    if kind == 'near':
        if close is not None and ma20 is not None:
            gap = (close / ma20 - 1) * 100
            return f'{emoji} 临近 MA20 · 高 +{gap:.2f}%'
        return f'{emoji} 临近'

    if kind == 'inactive':
        if close is not None and ma20 is not None:
            gap = (close / ma20 - 1) * 100
            return f'{emoji} MA20 之上 +{gap:.2f}%'
        return f'{emoji} 未激活'

    return f'{emoji} 数据缺失'


# ===== 卡片构建 =====

def _sort_results(results: list[tuple], kind_fn) -> list[tuple]:
    """按事件优先级排序(触发的在前)。同优先级按 fund_code 字典序。"""
    return sorted(results, key=lambda ar: (_EVENT_ORDER.get(kind_fn(ar[1]), 99), ar[0].fund_code))


def build_dividend_card_md(
    today: date,
    results: list[tuple],
    asof,
    trading_dates: "set[date] | None" = None,
) -> str:
    sorted_results = _sort_results(results, _dividend_event_kind)
    body = [
        f'> 数据截至 {asof}',
        '',
        '| 基金 | 距 MA120 | 距 MA250 | 状态 |',
        '|---|---|---|---|',
    ]
    for asset, r in sorted_results:
        close = r.get('close')
        state_cell = _render_dividend_state_cell(r, trading_dates, today)
        body.append(
            f'| `{asset.fund_code}` {asset.fund_name} '
            f'| `{_pct_diff(close, r.get("ma120"))}` '
            f'| `{_pct_diff(close, r.get("ma250"))}` '
            f'| {state_cell} |'
        )
        if r.get('errors'):
            body.append(f'> ⚠ `{asset.fund_code}` 缺数据:{", ".join(r["errors"])}')
    body.append('')
    body.append(DIVIDEND_RULE_FOOTER)
    return '\n'.join(body)


def build_shortma_card_md(
    today: date,
    results: list[tuple],
    asof,
    trading_dates: "set[date] | None" = None,
) -> str:
    sorted_results = _sort_results(results, _shortma_event_kind)
    body = [
        f'> 数据截至 {asof}',
        '',
        '| 基金 | 距 MA20 | 状态 |',
        '|---|---|---|',
    ]
    for asset, r in sorted_results:
        close = r.get('close')
        state_cell = _render_shortma_state_cell(r, trading_dates, today)
        sector_tag = f'[{asset.sector}]' if asset.sector else ''
        body.append(
            f'| `{asset.fund_code}` {sector_tag}{asset.fund_name} '
            f'| `{_pct_diff(close, r.get("ma20"))}` '
            f'| {state_cell} |'
        )
        if r.get('errors'):
            body.append(f'> ⚠ `{asset.fund_code}` 缺数据:{", ".join(r["errors"])}')
    body.append('')
    body.append(SHORTMA_RULE_FOOTER)
    return '\n'.join(body)


def build_ndx_card_md(today: date, r: dict) -> str:
    asof = r.get('asof')
    vix = r.get('vix')
    close = r.get('close')
    body = [
        f'> 数据截至 {asof}',
        '',
        '| 指标 | 数值 | 状态 |',
        '|---|---|---|',
        f'| NDX 收盘 | `{fmt_num(close, 2)}` | — |',
        f'| 🔴 VIX | **`{fmt_num(vix, 2)}`** | 突破阈值 {VIX_THRESHOLD:.0f},恐慌区 |',
        '',
        NDX_RULE_FOOTER,
    ]
    return '\n'.join(body)


def build_ndx_summary_line(r: dict) -> str:
    err = f' | 缺数: {",".join(r["errors"])}' if r['errors'] else ''
    return (
        f'  NDX(纳斯达克 100): 收盘 {fmt_num(r.get("close"), 2)} | '
        f'VIX {fmt_num(r.get("vix"), 2)} (阈值 {VIX_THRESHOLD:.0f}){err}'
    )


# ===== 飞书云文档 XML 渲染(2026-06-12 起 ServerChan v2 切到飞书云文档) =====

import re as _re


def _xml_escape(s: str) -> str:
    """转义 XML 文本内容(不动标签):& < > 三个字符。"""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _md_state_to_xml(md: str) -> str:
    """状态文字(markdown,含 **xxx**)转 XML 安全格式:先转义 + ** 转 <b>。"""
    safe = _xml_escape(md)
    return _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)


def build_combined_xml(
    today: date,
    dividend_results: list,
    shortma_results: list,
    overseas_results: list,
    trading_dates: "set[date] | None" = None,
) -> str:
    """构造飞书云文档完整 XML(用于 lark-cli docs +update overwrite)。

    布局:title + blockquote(数据截至) + 3 个 h2 section,每段 = table(显式列宽)
    + 规则段。设计依据见 [[project-fund-signal-monitor-feishu-doc-migration]] (2026-06-12)。
    """
    div_sorted = _sort_results(dividend_results, _dividend_event_kind)
    sho_sorted = _sort_results(shortma_results, _shortma_event_kind)
    osv_sorted = _sort_results(overseas_results, _shortma_event_kind)

    out: list[str] = []
    out.append('<title>📊 基金信号</title>')
    out.append('')
    out.append(f'<blockquote><p>数据截至 {today} · 每个 A 股交易日 10:00 北京自动更新</p></blockquote>')
    out.append('')
    out.append('<hr/>')
    out.append('')

    # ===== 红利低波 (4 列:基金 / 距 MA120 / 距 MA250 / 状态) =====
    out.append('<h2>红利低波</h2>')
    out.append('')
    out.append('<table>')
    out.append('<colgroup><col width="400"/><col width="90"/><col width="90"/><col width="220"/></colgroup>')
    out.append('<thead><tr>'
               '<th background-color="light-gray">基金</th>'
               '<th background-color="light-gray">距 MA120</th>'
               '<th background-color="light-gray">距 MA250</th>'
               '<th background-color="light-gray">状态</th>'
               '</tr></thead>')
    out.append('<tbody>')
    for asset, r in div_sorted:
        ma120_pos = _pct_diff(r.get('close'), r.get('ma120'))
        ma250_pos = _pct_diff(r.get('close'), r.get('ma250'))
        state = _md_state_to_xml(_render_dividend_state_cell(r, trading_dates, today))
        name = _xml_escape(asset.fund_name)
        out.append(
            f'<tr><td><code>{asset.fund_code}</code> {name}</td>'
            f'<td>{ma120_pos}</td><td>{ma250_pos}</td><td>{state}</td></tr>'
        )
    out.append('</tbody>')
    out.append('</table>')
    out.append('')
    out.append('<p><b>规则</b></p>')
    out.append('<ul>')
    out.append('<li>信号一(净值 &lt; MA250):加仓 1 份</li>')
    out.append('<li>信号二(净值 &lt; MA120 × 0.94):加仓 1 份</li>')
    out.append('<li>信号三(净值 &lt; MA120 × 0.88):加仓 2 份</li>')
    out.append('</ul>')
    out.append('')
    out.append('<hr/>')
    out.append('')

    # ===== 科技-国内 (4 列:基金 / 板块 / 距 MA20 / 状态) =====
    out.append('<h2>科技-国内</h2>')
    out.append('')
    out.append('<table>')
    out.append('<colgroup><col width="350"/><col width="100"/><col width="80"/><col width="220"/></colgroup>')
    out.append('<thead><tr>'
               '<th background-color="light-gray">基金</th>'
               '<th background-color="light-gray">板块</th>'
               '<th background-color="light-gray">距 MA20</th>'
               '<th background-color="light-gray">状态</th>'
               '</tr></thead>')
    out.append('<tbody>')
    for asset, r in sho_sorted:
        gap = _pct_diff(r.get('close'), r.get('ma20'))
        sector = _xml_escape(getattr(asset, 'sector', '') or '')
        state = _md_state_to_xml(_render_shortma_state_cell(r, trading_dates, today))
        name = _xml_escape(asset.fund_name)
        out.append(
            f'<tr><td><code>{asset.fund_code}</code> {name}</td>'
            f'<td>{sector}</td><td>{gap}</td><td>{state}</td></tr>'
        )
    out.append('</tbody>')
    out.append('</table>')
    out.append('')
    out.append('<p><b>规则</b>:净值 &lt; MA20 视为短期超跌 · 有事件才推送</p>')
    out.append('')
    out.append('<hr/>')
    out.append('')

    # ===== 科技-海外 (3 列:基金 / 距 MA20 / 状态) =====
    out.append('<h2>科技-海外</h2>')
    out.append('')
    out.append('<table>')
    out.append('<colgroup><col width="420"/><col width="90"/><col width="220"/></colgroup>')
    out.append('<thead><tr>'
               '<th background-color="light-gray">基金</th>'
               '<th background-color="light-gray">距 MA20</th>'
               '<th background-color="light-gray">状态</th>'
               '</tr></thead>')
    out.append('<tbody>')
    for asset, r in osv_sorted:
        gap = _pct_diff(r.get('close'), r.get('ma20'))
        state = _md_state_to_xml(_render_shortma_state_cell(r, trading_dates, today))
        name = _xml_escape(asset.fund_name)
        out.append(
            f'<tr><td><code>{asset.fund_code}</code> {name}</td>'
            f'<td>{gap}</td><td>{state}</td></tr>'
        )
    out.append('</tbody>')
    out.append('</table>')
    out.append('')
    out.append('<p><b>规则</b>:净值 &lt; MA20 视为短期超跌 · 每日固定播报(无事件也推一份)</p>')

    return '\n'.join(out)


def build_feishu_summary_lines(
    dividend_results: list,
    shortma_results: list,
    overseas_results: list,
) -> list[str]:
    """飞书摘要卡片用的 3 行通道速览(markdown 加粗 + emoji 计数)。"""
    def _count(results, kind_fn) -> dict:
        c = {'first': 0, 'new_low': 0, 'still_active': 0, 'near': 0, 'inactive': 0}
        for _, r in results:
            k = kind_fn(r)
            if k in c:
                c[k] += 1
        return c

    def _line(channel: str, c: dict) -> str:
        parts = []
        if c['first']:
            parts.append(f'{c["first"]}🔴')
        if c['new_low']:
            parts.append(f'{c["new_low"]}⬇️')
        if c['still_active']:
            parts.append(f'{c["still_active"]}🟢')
        if c['near']:
            parts.append(f'{c["near"]}🟡')
        if c['inactive']:
            parts.append(f'{c["inactive"]}⚪')
        return f'**{channel}** · {" ".join(parts) if parts else "—"}'

    return [
        _line('红利低波', _count(dividend_results, _dividend_event_kind)),
        _line('科技-国内', _count(shortma_results, _shortma_event_kind)),
        _line('科技-海外', _count(overseas_results, _shortma_event_kind)),
    ]
