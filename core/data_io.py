"""IO 层:代理 setup / retry / akshare 取数 / 缓存 / 状态 / 交易日历 / .env / 日志。"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, TypeVar

import requests

from core.config import load_config


# ===== 路径常量 =====

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / 'state.json'
LOG_PATH = ROOT / 'run.log'
ENV_PATH = ROOT / '.env'


# ===== 代理环境 =====

# 原始代理变量(给 Yahoo 用)。setup_proxy_env() 填充。
_ORIG_PROXIES: dict[str, str] = {}


def setup_proxy_env() -> dict[str, str]:
    """记录原代理(给 Yahoo 用),然后清空环境变量(给 akshare 国内站点直连)。

    返回 `{'http': ..., 'https': ...}` 只含真有值的协议,空 dict 表示无代理。
    同时把结果写入模块级 `_ORIG_PROXIES`,fetch_vix_latest 直接读它。

    幂等:多次调用结果一致。**main() 必须在任何 fetch_* 之前调用一次。**
    """
    orig = {
        'http': os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY'),
        'https': os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY'),
    }
    orig = {k: v for k, v in orig.items() if v}
    for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
               'ALL_PROXY', 'all_proxy'):
        os.environ.pop(_k, None)
    os.environ.setdefault('NO_PROXY', '*')

    global _ORIG_PROXIES
    _ORIG_PROXIES = orig
    return orig


def get_orig_proxies() -> dict[str, str]:
    """给 notify/runner 模块用的访问器,避免直接读模块级变量造成隐式依赖。"""
    return _ORIG_PROXIES


# ===== retry =====

T = TypeVar('T')

FETCH_MAX_ATTEMPTS = 3
FETCH_BASE_DELAY = 2.0


def with_retry(
    fn: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> T:
    """指数退避重试:第 i 次失败后 sleep base_delay * 2**(i-1),最后一次失败直接抛。

    用法:`with_retry(lambda: fetch_xxx(arg), max_attempts=3)`
    base_delay=0 时跳过 sleep(单测用)。
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts and base_delay > 0:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


# ===== 数据集定义 =====

@dataclass(frozen=True)
class Asset:
    fund_code: str       # 基金代码
    fund_name: str       # 基金简称


def _assets_from_config(cfg: dict, key: str) -> list[Asset]:
    """把 config 里的基金条目构建成 Asset 列表(纯函数,无 IO)。"""
    return [Asset(fund_code=a['fund_code'], fund_name=a['fund_name']) for a in cfg.get(key, [])]


# 基金列表来自 config.json(gitignored)/ config.example.json(committed),不硬编码。
#   dividend_assets:累计净值 + MA120/MA250 三档信号
#   shortma_assets :单位净值 + MA20 单档信号(高波动品种,不显示份数)
_config = load_config()
ASSETS: list[Asset] = _assets_from_config(_config, 'dividend_assets')
SHORTMA_ASSETS: list[Asset] = _assets_from_config(_config, 'shortma_assets')


# ===== 取数 =====

def fetch_fund_cumulative_nav(fund_code: str):
    """基金累计净值历史(分红还原,适合算 MA 信号)。带 3 次指数退避重试。"""
    def _fetch():
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator='累计净值走势')
        df = df[['净值日期', '累计净值']].copy()
        df.columns = ['date', 'close']
        df['date'] = df['date'].apply(
            lambda d: d if isinstance(d, date) else datetime.strptime(str(d)[:10], '%Y-%m-%d').date()
        )
        df['close'] = df['close'].astype(float)
        df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
        return df

    return with_retry(_fetch, max_attempts=FETCH_MAX_ATTEMPTS, base_delay=FETCH_BASE_DELAY)


def fetch_fund_unit_nav(fund_code: str):
    """基金单位净值历史(MA20 短线信号用,与累计净值口径区分)。带 3 次指数退避重试。

    返回 DataFrame, 列: date(date), close(float)。"close" 字段沿用旧名,实际是单位净值。
    """
    def _fetch():
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator='单位净值走势')
        df = df[['净值日期', '单位净值']].copy()
        df.columns = ['date', 'close']
        df['date'] = df['date'].apply(
            lambda d: d if isinstance(d, date) else datetime.strptime(str(d)[:10], '%Y-%m-%d').date()
        )
        df['close'] = df['close'].astype(float)
        df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
        return df

    return with_retry(_fetch, max_attempts=FETCH_MAX_ATTEMPTS, base_delay=FETCH_BASE_DELAY)


def fetch_ndx():
    """NDX 日线(新浪美股指数),带重试。"""
    def _fetch():
        import akshare as ak
        df = ak.index_us_stock_sina(symbol='.NDX')
        df = df[['date', 'close']].copy()
        df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
        return df

    return with_retry(_fetch, max_attempts=FETCH_MAX_ATTEMPTS, base_delay=FETCH_BASE_DELAY)


def _fetch_vix_yahoo() -> float:
    """主源:Yahoo Finance ^VIX 5 日历史的最后一个非 null close。"""
    r = requests.get(
        'https://query1.finance.yahoo.com/v8/finance/chart/^VIX?range=5d&interval=1d',
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=10,
        proxies=_ORIG_PROXIES or None,
    )
    if r.status_code != 200:
        raise RuntimeError(f'yahoo vix http {r.status_code}')
    closes = r.json()['chart']['result'][0]['indicators']['quote'][0]['close']
    for v in reversed(closes):
        if v is not None:
            return float(v)
    raise RuntimeError('yahoo vix all-null')


def _fetch_vix_cboe() -> float:
    """备源:CBOE 官方延迟报价 JSON,直接给当前价。

    CBOE 在国外但通常和 Yahoo 不同时挂(不同 CDN),作为 fallback 有意义。
    """
    r = requests.get(
        'https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json',
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=10,
        proxies=_ORIG_PROXIES or None,
    )
    if r.status_code != 200:
        raise RuntimeError(f'cboe vix http {r.status_code}')
    data = r.json().get('data', {})
    val = data.get('close') if data.get('close') else data.get('current_price')
    if val is None:
        raise RuntimeError('cboe vix no price')
    return float(val)


def fetch_vix_latest() -> Optional[float]:
    """VIX 双源:Yahoo 主(3 次重试)→ 失败 → CBOE 备(2 次重试)→ 仍失败返回 None。"""
    try:
        return with_retry(_fetch_vix_yahoo, max_attempts=FETCH_MAX_ATTEMPTS, base_delay=FETCH_BASE_DELAY)
    except Exception:
        pass
    try:
        return with_retry(_fetch_vix_cboe, max_attempts=2, base_delay=FETCH_BASE_DELAY)
    except Exception:
        return None


# ===== 缓存 =====

def cache_path(asset: Asset) -> Path:
    """累计净值缓存路径(红利低波用)。"""
    return ROOT / f'nav_history_{asset.fund_code}.csv'


def unit_cache_path(asset: Asset) -> Path:
    """单位净值缓存路径(短线 MA20 用,文件名加 _unit 与累计净值区分)。"""
    return ROOT / f'nav_history_{asset.fund_code}_unit.csv'


def save_history(asset: Asset, df) -> None:
    df.to_csv(cache_path(asset), index=False)


def save_unit_history(asset: Asset, df) -> None:
    df.to_csv(unit_cache_path(asset), index=False)


# ===== 状态 =====

# ===== state.json schema 版本与迁移 =====

CURRENT_SCHEMA_VERSION = 2


def _migrate_state_v1_to_v2(state: dict) -> dict:
    """v1 → v2 信号编号重排:

    - v1.signal_3 (MA250) → v2.signal_1
    - v1.signal_1 (MA120 -6%) → v2.signal_2
    - v1.signal_2 (MA120 -12%) → v2.signal_3

    signals dict 与 signal_meta dict 同步 rename。返回**新** dict,不修改入参。
    """
    rename_map = {'signal_1': 'signal_2', 'signal_2': 'signal_3', 'signal_3': 'signal_1'}

    new_state = dict(state)
    new_assets = {}
    for code, asset in state.get('assets', {}).items():
        new_asset = dict(asset)
        old_signals = asset.get('signals', {}) or {}
        new_asset['signals'] = {
            new_key: old_signals.get(old_key, False)
            for old_key, new_key in rename_map.items()
        }
        old_meta = asset.get('signal_meta', {}) or {}
        new_meta = {
            rename_map[old_key]: dict(meta)
            for old_key, meta in old_meta.items()
            if old_key in rename_map
        }
        new_asset['signal_meta'] = new_meta
        new_assets[code] = new_asset
    new_state['assets'] = new_assets
    new_state['schema_version'] = CURRENT_SCHEMA_VERSION
    return new_state


def load_state() -> dict:
    """读 state.json。若是 v1 schema,自动迁移到 v2 + 备份 + 写回。"""
    if not STATE_PATH.exists():
        return {'last_run': None, 'assets': {}}
    raw = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    if raw.get('schema_version') == CURRENT_SCHEMA_VERSION:
        return raw

    # v1 → v2 迁移
    import shutil
    ts = int(datetime.now().timestamp())
    backup = STATE_PATH.parent / f'state.json.bak.before-schema-v2.{ts}'
    shutil.copy(STATE_PATH, backup)
    migrated = _migrate_state_v1_to_v2(raw)
    STATE_PATH.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )
    return migrated


def save_state(state: dict) -> None:
    state['schema_version'] = CURRENT_SCHEMA_VERSION
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )


# ===== 交易日 =====

def load_trading_calendar() -> "set[date]":
    """加载 A 股交易日历(akshare),带重试。失败抛异常,调用方决定降级策略。"""
    def _fetch() -> "set[date]":
        import akshare as ak
        cal = ak.tool_trade_date_hist_sina()
        return set(cal['trade_date'].tolist())

    return with_retry(_fetch, max_attempts=FETCH_MAX_ATTEMPTS, base_delay=FETCH_BASE_DELAY)


def is_a_share_trading_day(d: date, calendar: "set[date] | None" = None) -> bool:
    """calendar 传入时直接判定,不传则现拉一次(兼容旧调用)。"""
    cal = calendar if calendar is not None else load_trading_calendar()
    return d in cal


# ===== 交易日历缓存(1 周失效)=====

CALENDAR_CACHE_PATH = ROOT / 'trading_calendar.json'
CALENDAR_CACHE_MAX_AGE_DAYS = 7


def _read_calendar_cache() -> Optional[tuple[datetime, "set[date]"]]:
    """读缓存。返回 (fetched_at, dates);文件不存在/损坏 → None。"""
    if not CALENDAR_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CALENDAR_CACHE_PATH.read_text(encoding='utf-8'))
        fetched_at = datetime.fromisoformat(payload['fetched_at'])
        dates = {date.fromisoformat(s) for s in payload['dates']}
        return fetched_at, dates
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _write_calendar_cache(dates: "set[date]") -> None:
    payload = {
        'fetched_at': datetime.now().isoformat(),
        'dates': sorted(d.isoformat() for d in dates),
    }
    CALENDAR_CACHE_PATH.write_text(json.dumps(payload), encoding='utf-8')


def load_trading_calendar_cached() -> "set[date]":
    """带缓存的交易日历加载:

    - 缓存存在且 < MAX_AGE_DAYS → 直接返回缓存
    - 缓存不存在 / 过期 / 损坏 → 调 load_trading_calendar() 重拉 + 写盘
    - 重拉失败但缓存仍可读(即使过期)→ 用过期缓存,不抛
    - 重拉失败且无缓存 → 抛原异常
    """
    cached = _read_calendar_cache()
    now = datetime.now()
    fresh = cached and (now - cached[0]) <= timedelta(days=CALENDAR_CACHE_MAX_AGE_DAYS)

    if fresh:
        return cached[1]

    try:
        dates = load_trading_calendar()
        _write_calendar_cache(dates)
        return dates
    except Exception:
        if cached is not None:
            return cached[1]
        raise


# ===== .env 简单解析 =====

def load_env() -> dict[str, str]:
    """读 .env 简单解析:KEY=VALUE 一行一对,忽略空行与 '#' 开头。"""
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ===== 日志 =====

def get_logger() -> logging.Logger:
    """单例 logger,文件 + stdout 双写。"""
    logger = logging.getLogger('dividend_monitor')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    fh = logging.FileHandler(LOG_PATH, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger
