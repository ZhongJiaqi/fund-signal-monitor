"""主流程编排:process_asset + process_ndx + main 串联。

main() 是 launchd 的入口,做以下事情(每日 11:00):
1. setup_proxy_env(给 Yahoo 留代理,清空给 akshare 直连)
2. SIGALRM 120s 整体超时
3. 加载交易日历 → 非交易日安静退出
4. 3 只基金各自取累计净值 + MA + 信号 + 事件分类
5. NDX/VIX 取数 + 评估
6. 落盘 state.json
7. 按 first/new_low → 加仓卡 / still_active → 状态卡 / NDX fired → NDX 卡 三路决定推送
8. fetch errors 写本地诊断 latest_alert_errors.md(不推送)
"""

from __future__ import annotations

import signal as _signal
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from core.cards import (
    build_dividend_card_md,
    build_ndx_card_md,
    build_ndx_summary_line,
    build_shortma_card_md,
    fmt_num,
    _pct_diff,
)
from core.data_io import (
    ASSETS,
    Asset,
    FETCH_MAX_ATTEMPTS,
    ROOT,
    SHORTMA_ASSETS,
    SHORTMA_OVERSEAS_ASSETS,
    fetch_fund_cumulative_nav,
    fetch_fund_unit_nav,
    fetch_ndx,
    fetch_vix_latest,
    get_logger,
    load_env,
    load_state,
    load_trading_calendar_cached,
    save_history,
    save_state,
    save_unit_history,
    setup_proxy_env,
)
from core.notify import send_macos_notification, send_serverchan
from core.signals import (
    SIGNAL_LABELS,
    evaluate_ma20_signal,
    evaluate_signals,
    evaluate_vix_signal,
    detect_signal_event,
    first_triggered,
    ma,
)


GLOBAL_TIMEOUT_SECONDS = 120


def _timeout_handler(signum, frame):
    raise TimeoutError(f'整体超时 {GLOBAL_TIMEOUT_SECONDS}s,可能某个数据源接口卡死')


def process_asset(asset: Asset, prev_asset_state: dict, log: logging.Logger) -> dict:
    """处理单只资产:拉累计净值 + 算 MA + 评信号 + 检测首次/新低事件。"""
    out: dict = {
        'fund_code': asset.fund_code,
        'asof': None,
        'close': None, 'ma120': None, 'ma250': None,
        'signals': {k: None for k in ('signal_1', 'signal_2', 'signal_3')},
        'fired_first': [],         # 首次激活的信号 keys
        'fired_new_low': [],       # 持续激活且创新低的信号 keys
        'fired_still_active': [],  # 持续激活但未创新低(日常汇报)的信号 keys
        'signal_meta': {},         # 信号元数据 {sig_key: {'lowest_close': float}}
        'errors': [],
    }

    try:
        hist = fetch_fund_cumulative_nav(asset.fund_code)
        save_history(asset, hist)
        out['asof'] = hist['date'].iloc[-1]
        out['close'] = float(hist['close'].iloc[-1])
        closes = hist['close'].astype(float).tolist()
    except Exception as e:
        log.warning(f'{asset.fund_code} 取累计净值失败: {e}')
        out['errors'].append(f'nav_fetch_failed: {e}')
        return out

    out['ma120'] = ma(closes, 120)
    out['ma250'] = ma(closes, 250)

    sigs = evaluate_signals(close=out['close'], ma120=out['ma120'], ma250=out['ma250'])
    out['signals'] = sigs

    prev_signals = (prev_asset_state or {}).get('signals', {})
    prev_meta = (prev_asset_state or {}).get('signal_meta', {})
    today_iso = datetime.now().date().isoformat()
    for sig_key, today_val in sigs.items():
        prev_sig_meta = prev_meta.get(sig_key) or {}
        prev_lowest = prev_sig_meta.get('lowest_close')
        prev_activated_at = prev_sig_meta.get('activated_at')
        event, new_lowest = detect_signal_event(
            prev_active=prev_signals.get(sig_key),
            today_active=today_val,
            today_close=out['close'],
            prev_lowest=prev_lowest,
        )
        if event == 'first':
            out['fired_first'].append(sig_key)
            new_activated_at = today_iso
        elif event == 'new_low':
            out['fired_new_low'].append(sig_key)
            new_activated_at = prev_activated_at
        elif event == 'still_active':
            out['fired_still_active'].append(sig_key)
            new_activated_at = prev_activated_at
        else:
            new_activated_at = prev_activated_at if new_lowest is not None else None
        if new_lowest is not None:
            entry = {'lowest_close': new_lowest}
            if new_activated_at:
                entry['activated_at'] = new_activated_at
            out['signal_meta'][sig_key] = entry

    return out


def process_shortma_asset(asset: Asset, prev_asset_state: dict, log: logging.Logger) -> dict:
    """处理单只短线 MA20 资产:拉单位净值 + 算 MA20 + 评信号 + 事件分类。

    state 结构与 process_asset 相似但只有 1 个信号(ma20)。signal_meta 顶层即对应 ma20。
    """
    out: dict = {
        'fund_code': asset.fund_code,
        'asof': None,
        'close': None, 'ma20': None,
        'signal': None,             # bool / None
        'fired_first': False,
        'fired_new_low': False,
        'fired_still_active': False,
        'signal_meta': {},          # {'lowest_close': float, 'activated_at': str}
        'errors': [],
    }

    try:
        hist = fetch_fund_unit_nav(asset.fund_code)
        save_unit_history(asset, hist)
        out['asof'] = hist['date'].iloc[-1]
        out['close'] = float(hist['close'].iloc[-1])
        closes = hist['close'].astype(float).tolist()
    except Exception as e:
        log.warning(f'{asset.fund_code} 取单位净值失败: {e}')
        out['errors'].append(f'unit_nav_fetch_failed: {e}')
        return out

    out['ma20'] = ma(closes, 20)
    out['signal'] = evaluate_ma20_signal(close=out['close'], ma20=out['ma20'])

    prev_signal = (prev_asset_state or {}).get('signal')
    prev_meta = (prev_asset_state or {}).get('signal_meta') or {}
    prev_lowest = prev_meta.get('lowest_close')
    prev_activated_at = prev_meta.get('activated_at')
    today_iso = datetime.now().date().isoformat()

    event, new_lowest = detect_signal_event(
        prev_active=prev_signal,
        today_active=out['signal'],
        today_close=out['close'],
        prev_lowest=prev_lowest,
    )
    if event == 'first':
        out['fired_first'] = True
        new_activated_at = today_iso
    elif event == 'new_low':
        out['fired_new_low'] = True
        new_activated_at = prev_activated_at
    elif event == 'still_active':
        out['fired_still_active'] = True
        new_activated_at = prev_activated_at
    else:
        new_activated_at = prev_activated_at if new_lowest is not None else None

    if new_lowest is not None:
        entry = {'lowest_close': new_lowest}
        if new_activated_at:
            entry['activated_at'] = new_activated_at
        out['signal_meta'] = entry

    return out


def process_ndx(prev_state: dict, log: logging.Logger) -> dict:
    """处理 NDX:取数 + 评估 VIX 信号 + 与上次状态对比。"""
    out: dict = {
        'asof': None, 'close': None, 'vix': None,
        'signal': None, 'fired': False, 'errors': [],
    }

    try:
        ndx = fetch_ndx()
        ndx.to_csv(ROOT / 'history_NDX.csv', index=False)
        out['asof'] = ndx['date'].iloc[-1]
        out['close'] = float(ndx['close'].iloc[-1])
    except Exception as e:
        log.warning(f'NDX 取行情失败: {e}')
        out['errors'].append(f'ndx_fetch_failed: {e}')

    out['vix'] = fetch_vix_latest()
    if out['vix'] is None:
        out['errors'].append('vix_fetch_failed')

    out['signal'] = evaluate_vix_signal(out['vix'])
    prev_signal = (prev_state or {}).get('signal')
    out['fired'] = first_triggered(prev_signal, out['signal'])
    return out


def main(today: Optional[date] = None, dry_run: bool = False, force: bool = False) -> int:
    """主流程入口。

    dry_run=True 时阻断 5 类副作用:Server 酱推送 / macOS 通知 / save_state /
    latest_alert_*.md 文件写入 / latest_alert_errors.md。其余照常(取数、
    history CSV 缓存、trading_calendar 缓存、run.log)。stdout 显式 [DRY-RUN]
    前缀,每通道标注"会推 / 不会推"。

    force=True 时跳过 same-day 幂等检查(手动重跑 escape hatch)。生产路径
    默认 force=False:state.last_run.date() == today 视为今日已推过,fast exit
    不重复打扰用户。配合 Cloudflare Workers 多 schedule 触发(0/5/10 2 * * 1-5
    UTC),任一时间点成功即可,后续触发被幂等吸收。
    """
    # 第一步:准备代理环境(给 Yahoo 用 _ORIG_PROXIES,清空 env 给 akshare 直连)
    setup_proxy_env()

    _signal.signal(_signal.SIGALRM, _timeout_handler)
    _signal.alarm(GLOBAL_TIMEOUT_SECONDS)

    log = get_logger()
    today = today or datetime.now().date()
    log.info(f'====== 运行开始 {today}{" [DRY-RUN]" if dry_run else ""} ======')

    if dry_run:
        print('[DRY-RUN] 不真发 / 不耗 Server 酱额度 / 不写 state.json')

    # 交易日历:一次加载(优先本地缓存,7 天失效),复用给 is_a_share_trading_day + compute_active_days
    trading_dates: "set[date]" = set()
    try:
        trading_dates = load_trading_calendar_cached()
        if today not in trading_dates:
            log.info(f'{today} 非 A 股交易日,安静退出。')
            return 0
    except Exception as e:
        log.warning(f'交易日历获取失败,继续运行: {e}')

    state = load_state()

    # 幂等检查:multi-schedule 触发时防重复推送
    # 仅 production 路径生效(dry-run 不写 state 不污染,自然幂等;force 显式绕过)
    if not dry_run and not force:
        last_run_iso = state.get('last_run', '')
        last_run_date = None
        if last_run_iso:
            try:
                last_run_date = datetime.fromisoformat(last_run_iso).date()
            except (TypeError, ValueError):
                last_run_date = None  # 数据腐败 → 视为无 last_run,放行
        if last_run_date == today:
            msg = (
                f'今日 ({today}) 已成功跑过 (last_run={last_run_iso}),'
                f'跳过推送 — multi-schedule 兜底触发吸收(--force 可强制重跑)。'
            )
            log.info(msg)
            print(msg)
            return 0

    new_assets_state = {}
    all_dividend_results: list[tuple] = []      # [(Asset, result), ...] 全部 3 只
    dividend_text_lines: list[str] = []         # 终端简短文本
    fired_short: list[str] = []                 # macOS 通知短消息

    for asset in ASSETS:
        prev = state.get('assets', {}).get(asset.fund_code, {})
        result = process_asset(asset, prev, log)
        new_assets_state[asset.fund_code] = {
            'asof': result['asof'],
            'close': result['close'],
            'ma120': result['ma120'],
            'ma250': result['ma250'],
            'signals': result['signals'],
            'signal_meta': result['signal_meta'],
            'errors': result['errors'],
        }
        all_dividend_results.append((asset, result))
        action_keys = result['fired_first'] + result['fired_new_low']
        if action_keys:
            tags = []
            for s in result['fired_first']:
                tags.append(SIGNAL_LABELS[s].split('(')[0])
            for s in result['fired_new_low']:
                tags.append(f"{SIGNAL_LABELS[s].split('(')[0]}(新低)")
            fired_short.append(f'{asset.fund_code}:' + '、'.join(tags))
        ma120_pos = _pct_diff(result.get('close'), result.get('ma120'))
        ma250_pos = _pct_diff(result.get('close'), result.get('ma250'))
        dividend_text_lines.append(
            f'  {asset.fund_code} {asset.fund_name[:20]}: 累计净值 {fmt_num(result["close"], 4)} '
            f'| MA120 {ma120_pos} | MA250 {ma250_pos}'
            + (f' | 缺数: {",".join(result["errors"])}' if result['errors'] else '')
        )

    # 短线 MA20 监控(国内科技,单位净值口径)
    new_shortma_state = {}
    all_shortma_results: list[tuple] = []
    shortma_fired_short: list[str] = []

    for asset in SHORTMA_ASSETS:
        prev = state.get('shortma_assets', {}).get(asset.fund_code, {})
        result = process_shortma_asset(asset, prev, log)
        new_shortma_state[asset.fund_code] = {
            'asof': result['asof'],
            'close': result['close'],
            'ma20': result['ma20'],
            'signal': result['signal'],
            'signal_meta': result['signal_meta'],
            'errors': result['errors'],
        }
        all_shortma_results.append((asset, result))
        if result['fired_first'] or result['fired_new_low']:
            tag = '跌破 MA20' if result['fired_first'] else 'MA20 期间新低'
            shortma_fired_short.append(f'{asset.fund_code}: {tag}')

    # 短线 MA20 监控(海外 QDII,规则同上,独立推送一张卡)
    new_overseas_state = {}
    all_overseas_results: list[tuple] = []
    overseas_fired_short: list[str] = []

    for asset in SHORTMA_OVERSEAS_ASSETS:
        prev = state.get('shortma_overseas_assets', {}).get(asset.fund_code, {})
        result = process_shortma_asset(asset, prev, log)
        new_overseas_state[asset.fund_code] = {
            'asof': result['asof'],
            'close': result['close'],
            'ma20': result['ma20'],
            'signal': result['signal'],
            'signal_meta': result['signal_meta'],
            'errors': result['errors'],
        }
        all_overseas_results.append((asset, result))
        if result['fired_first'] or result['fired_new_low']:
            tag = '跌破 MA20' if result['fired_first'] else 'MA20 期间新低'
            overseas_fired_short.append(f'{asset.fund_code}: {tag}')

    # NDX/VIX 监控
    prev_ndx = state.get('ndx', {})
    ndx_result = process_ndx(prev_ndx, log)

    state['last_run'] = datetime.now().isoformat(timespec='seconds')
    state['assets'] = new_assets_state
    state['shortma_assets'] = new_shortma_state
    state['shortma_overseas_assets'] = new_overseas_state
    state['ndx'] = {
        'asof': ndx_result['asof'],
        'close': ndx_result['close'],
        'vix': ndx_result['vix'],
        'signal': ndx_result['signal'],
        'errors': ndx_result['errors'],
    }
    if not dry_run:
        save_state(state)

    env = load_env()
    sendkey = env.get('SERVERCHAN_SENDKEY', '')

    # ----- 通道 1:红利低波(统一推送,合并卡)-----
    has_first = any(r['fired_first'] for _, r in all_dividend_results)
    has_new_low = any(r['fired_new_low'] for _, r in all_dividend_results)
    has_still_active = any(r['fired_still_active'] for _, r in all_dividend_results)
    has_any_dividend = has_first or has_new_low or has_still_active

    asofs = [r['asof'] for _, r in all_dividend_results if r.get('asof')]
    max_asof = max(asofs) if asofs else '未取到'

    if has_any_dividend:
        md = build_dividend_card_md(today, all_dividend_results, max_asof, trading_dates)
        title = f'红利低波 · {today}'
        if dry_run:
            print(f'\n[DRY-RUN] 红利低波 会推:{title}')
            print(md)
        else:
            print(md)
            (ROOT / 'latest_alert_dividend.md').write_text(md, encoding='utf-8')
            send_macos_notification(
                title=title,
                message=';'.join(fired_short) or '当前仍处于加仓窗口',
            )
            send_serverchan(sendkey, title, md, log)
    elif dry_run:
        print('\n[DRY-RUN] 红利低波 不会推(无信号事件)')

    # ----- 通道 2:科技-国内(统一推送,合并卡)-----
    shortma_has_first = any(r['fired_first'] for _, r in all_shortma_results)
    shortma_has_new_low = any(r['fired_new_low'] for _, r in all_shortma_results)
    shortma_has_still = any(r['fired_still_active'] for _, r in all_shortma_results)
    shortma_has_any = shortma_has_first or shortma_has_new_low or shortma_has_still

    shortma_asofs = [r['asof'] for _, r in all_shortma_results if r.get('asof')]
    shortma_max_asof = max(shortma_asofs) if shortma_asofs else '未取到'

    if shortma_has_any:
        md = build_shortma_card_md(today, all_shortma_results, shortma_max_asof, trading_dates)
        title = f'科技-国内 · {today}'
        if dry_run:
            print(f'\n[DRY-RUN] 科技-国内 会推:{title}')
            print(md)
        else:
            print()
            print(md)
            (ROOT / 'latest_alert_shortma.md').write_text(md, encoding='utf-8')
            send_macos_notification(
                title=title,
                message=';'.join(shortma_fired_short) or '当前仍处于跌破 MA20 窗口',
            )
            send_serverchan(sendkey, title, md, log)
    elif dry_run:
        print('\n[DRY-RUN] 科技-国内 不会推(无信号事件)')

    # ----- 通道 2.5:科技-海外(每日固定播报,与国内规则不同)-----
    # 国内 shortma 是"有事件才推",海外是"每日必推一张状态卡"(用户要求,
    # 便于每天扫一眼海外持仓的相对 MA20 位置)。只在 7 只全部取数失败时
    # 跳过推送,避免空卡片浪费 Server 酱额度。
    overseas_has_first = any(r['fired_first'] for _, r in all_overseas_results)
    overseas_has_new_low = any(r['fired_new_low'] for _, r in all_overseas_results)
    overseas_has_still = any(r['fired_still_active'] for _, r in all_overseas_results)
    overseas_has_any = overseas_has_first or overseas_has_new_low or overseas_has_still
    overseas_has_data = any(r.get('close') is not None for _, r in all_overseas_results)

    overseas_asofs = [r['asof'] for _, r in all_overseas_results if r.get('asof')]
    overseas_max_asof = max(overseas_asofs) if overseas_asofs else '未取到'

    if overseas_has_data:
        md = build_shortma_card_md(today, all_overseas_results, overseas_max_asof, trading_dates)
        title = f'科技-海外 · {today}'
        macos_msg = ';'.join(overseas_fired_short) or '每日海外科技状态汇报'
        if dry_run:
            tag = '(每日固定播报)' if not overseas_has_any else '(有事件)'
            print(f'\n[DRY-RUN] 科技-海外 会推{tag}:{title}')
            print(md)
        else:
            print()
            print(md)
            (ROOT / 'latest_alert_shortma_overseas.md').write_text(md, encoding='utf-8')
            send_macos_notification(title=title, message=macos_msg)
            send_serverchan(sendkey, title, md, log)
    elif dry_run:
        print('\n[DRY-RUN] 科技-海外 不会推(7 只全部取数失败)')

    # ----- 通道 3:纳指(VIX 触发才推)-----
    if ndx_result['fired']:
        md = build_ndx_card_md(today, ndx_result)
        title = f'纳指 · {today}'
        if dry_run:
            print(f'\n[DRY-RUN] 纳指 会推:{title}')
            print(md)
        else:
            print()
            print(md)
            (ROOT / 'latest_alert_ndx.md').write_text(md, encoding='utf-8')
            send_macos_notification(
                title=title,
                message=f'VIX {fmt_num(ndx_result["vix"], 2)} 突破 {VIX_THRESHOLD:.0f}',
            )
            send_serverchan(sendkey, title, md, log)
    elif dry_run:
        vix_v = ndx_result.get('vix')
        if vix_v is None:
            reason = 'VIX 未取到'
        else:
            reason = f'VIX {fmt_num(vix_v, 2)} < {VIX_THRESHOLD:.0f}'
        print(f'\n[DRY-RUN] 纳指 不会推({reason})')

    # ----- 无触发时终端简短状态 -----
    if (not has_any_dividend
            and not shortma_has_any
            and not overseas_has_any
            and not ndx_result['fired']):
        print(f'✅ {today} 今日无新加仓信号首次触发。')
        for line in dividend_text_lines:
            print(line)
        for asset, r in all_shortma_results:
            close = r.get('close')
            ma20 = r.get('ma20')
            pos = _pct_diff(close, ma20)
            err = f' | 缺数: {",".join(r["errors"])}' if r['errors'] else ''
            print(f'  {asset.fund_code} {asset.fund_name[:24]}: 单位净值 {fmt_num(close, 4)} | MA20 {pos}{err}')
        for asset, r in all_overseas_results:
            close = r.get('close')
            ma20 = r.get('ma20')
            pos = _pct_diff(close, ma20)
            err = f' | 缺数: {",".join(r["errors"])}' if r['errors'] else ''
            print(f'  {asset.fund_code} {asset.fund_name[:24]}: 单位净值 {fmt_num(close, 4)} | MA20 {pos}{err}')
        print(build_ndx_summary_line(ndx_result))

    # ----- 取数失败时本地诊断(不推送)-----
    fetch_errors: list[str] = []
    for asset, r in all_dividend_results:
        if r.get('errors'):
            fetch_errors.append(f'{asset.fund_code} {asset.fund_name}: {", ".join(r["errors"])}')
    for asset, r in all_shortma_results:
        if r.get('errors'):
            fetch_errors.append(f'{asset.fund_code} {asset.fund_name}: {", ".join(r["errors"])}')
    for asset, r in all_overseas_results:
        if r.get('errors'):
            fetch_errors.append(f'{asset.fund_code} {asset.fund_name}: {", ".join(r["errors"])}')
    if ndx_result.get('errors'):
        fetch_errors.append(f'NDX/VIX: {", ".join(ndx_result["errors"])}')
    if fetch_errors:
        err_md = '\n'.join([
            f'# ⚠ 取数失败诊断 · {today}',
            f'> 已尝试 {FETCH_MAX_ATTEMPTS} 次指数退避重试仍失败。**未推送 Server 酱**,仅本地记录。',
            '',
            *[f'- {line}' for line in fetch_errors],
            '',
            '排查:`tail -50 run.log`,或 REPL 直接调 `fetch_fund_cumulative_nav(code)` 看 traceback。',
        ])
        if dry_run:
            print('\n[DRY-RUN] 取数失败诊断(不写 latest_alert_errors.md):')
            print(err_md)
        else:
            (ROOT / 'latest_alert_errors.md').write_text(err_md, encoding='utf-8')
            log.warning(f'取数失败 {len(fetch_errors)} 项,已写 latest_alert_errors.md(未推送)')

    log.info('====== 运行结束 ======')
    return 0


# NDX 卡片需要 VIX_THRESHOLD,从 signals 拿
from core.signals import VIX_THRESHOLD  # noqa: E402
