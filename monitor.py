"""红利低波基金加仓信号监控 — 入口薄壳。

实际实现见 `core/` 包:
- core/signals.py  纯函数(MA / 信号 / 事件分类 / 阈值定位 / 激活天数)
- core/data_io.py  IO(代理 setup / retry / akshare 取数 / 缓存 / state.json / 交易日历 / .env / logger)
- core/notify.py   推送(macOS 通知 / Server 酱微信)
- core/cards.py    Markdown 卡片(红利低波加仓卡 / 状态卡 / NDX 加仓卡)
- core/runner.py   主流程(process_asset / process_ndx / main)

本文件保留两个职责:
1. launchd 入口(`python monitor.py`,见 plist)
2. 给测试 re-export 所有公开符号(`from monitor import xxx` 仍 work)
"""

from __future__ import annotations

import sys

# ===== Re-export for tests and backwards-compat =====

from core.signals import (  # noqa: F401
    SIGNAL_2_DROP,
    SIGNAL_3_DROP,
    SIGNAL_LABELS,
    SIGNAL_NEXT_SHARES,
    SIGNAL_SHARES,
    VIX_THRESHOLD,
    compute_active_days,
    detect_signal_event,
    evaluate_ma20_signal,
    evaluate_signals,
    evaluate_vix_signal,
    first_triggered,
    ma,
    next_threshold,
)
from core.data_io import (  # noqa: F401
    ASSETS,
    Asset,
    ENV_PATH,
    FETCH_BASE_DELAY,
    FETCH_MAX_ATTEMPTS,
    LOG_PATH,
    ROOT,
    SHORTMA_ASSETS,
    SHORTMA_OVERSEAS_ASSETS,
    STATE_PATH,
    cache_path,
    fetch_fund_cumulative_nav,
    fetch_fund_unit_nav,
    fetch_ndx,
    fetch_vix_latest,
    get_logger,
    is_a_share_trading_day,
    load_env,
    load_state,
    load_trading_calendar,
    load_trading_calendar_cached,
    save_history,
    save_state,
    save_unit_history,
    setup_proxy_env,
    unit_cache_path,
    with_retry,
)
from core.notify import (  # noqa: F401
    SERVERCHAN_QUOTA_CODES,
    send_feishu_bot,
    send_feishu_summary_card,
    send_macos_notification,
    send_serverchan,
)
from core.cards import (  # noqa: F401
    DIVIDEND_RULE_FOOTER,
    NDX_RULE_FOOTER,
    SHORTMA_RULE_FOOTER,
    build_combined_xml,
    build_dividend_card_md,
    build_feishu_summary_lines,
    build_ndx_card_md,
    build_ndx_summary_line,
    build_shortma_card_md,
    fmt_num,
    fmt_pct,
)
from core.runner import (  # noqa: F401
    GLOBAL_TIMEOUT_SECONDS,
    main,
    process_asset,
    process_ndx,
    process_shortma_asset,
)

# 测试 mock 的 hook 点 — test_serverchan 用 `monitor.requests.post`,需要在此模块可访问
import requests  # noqa: F401
import time  # noqa: F401


def _parse_args(argv: list[str] | None = None):
    import argparse
    parser = argparse.ArgumentParser(
        prog='monitor.py',
        description='基金加仓信号监控 · 三通道独立推送(红利低波 / 科技 / 纳指)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='预览模式:不真发微信/不弹通知/不写 state.json/不写 latest_alert_*.md,'
             '只在 stdout 显示会推送的内容。改推送内容前先跑这个。',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='跳过 same-day 幂等检查 — 即使 state.last_run 是今天也强制重跑(再次推送)。'
             '正常使用不需要;multi-schedule 兜底依赖默认幂等,手动重跑时偶尔用。',
    )
    return parser.parse_args(argv)


if __name__ == '__main__':
    args = _parse_args()
    try:
        sys.exit(main(dry_run=args.dry_run, force=args.force))
    except TimeoutError as e:
        get_logger().error(str(e))
        sys.exit(2)
