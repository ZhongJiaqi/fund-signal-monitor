"""信号判断纯函数 — 无 IO,完全可单测。

包含:MA / 价格类信号 / VIX 信号 / 首次触发对比 / 事件分类(first/new_low/still_active)
/ 下一档阈值定位 / 激活持续交易日数。
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence


# ===== MA =====

def ma(closes: Sequence[float], window: int) -> Optional[float]:
    """简单移动平均:取最后 `window` 个 close 的算术平均。数据不足返回 None。"""
    if len(closes) < window or window <= 0:
        return None
    tail = closes[-window:]
    return sum(tail) / window


# ===== 信号阈值常量(2026-05-28 重编号:从浅到深) =====

# 信号一:净值 < MA250(原信号三)— 最浅,最早触发
# 信号二:净值 < MA120 × (1 - 6%)(原信号一)
# 信号三:净值 < MA120 × (1 - 12%)(原信号二)— 最深
SIGNAL_2_DROP = 0.06   # 净值 < MA120 × (1 - 6%) → 信号二
SIGNAL_3_DROP = 0.12   # 净值 < MA120 × (1 - 12%) → 信号三
VIX_THRESHOLD = 30.0   # NDX 通道:VIX 超过 30 触发恐慌加仓信号


# ===== 信号评估 =====

def evaluate_vix_signal(vix: Optional[float]) -> Optional[bool]:
    """VIX > 30 → True;VIX ≤ 30 → False;None 时 → None(未取到)。"""
    if vix is None:
        return None
    return vix > VIX_THRESHOLD


def evaluate_ma20_signal(close: Optional[float], ma20: Optional[float]) -> Optional[bool]:
    """短线 MA20 信号:close < MA20 → True 激活。任一为 None → None。

    严格小于(与信号三 close < MA250 一致),阈值附近反复触发就是反复入场机会,
    符合用户对 F3 失活宽限带"不做"的拍板决策。
    """
    if close is None or ma20 is None:
        return None
    return close < ma20


def evaluate_signals(
    close: Optional[float],
    ma120: Optional[float],
    ma250: Optional[float],
) -> dict:
    """3 个价格类信号(2026-05-28 重编号,全用严格小于 <)。

    - signal_1:净值 < MA250(最浅档,最早触发)
    - signal_2:净值 < MA120 × (1 - 6%)(中等回撤)
    - signal_3:净值 < MA120 × (1 - 12%)(深度回撤)

    True=激活,False=未激活,None=数据未取到。
    """
    if close is None or ma250 is None:
        s1 = None
    else:
        s1 = close < ma250

    if close is None or ma120 is None:
        s2 = s3 = None
    else:
        s2 = close < ma120 * (1 - SIGNAL_2_DROP)
        s3 = close < ma120 * (1 - SIGNAL_3_DROP)

    return {'signal_1': s1, 'signal_2': s2, 'signal_3': s3}


def first_triggered(prev: Optional[bool], today: Optional[bool]) -> bool:
    """今天激活、上次未激活(或未取到/未运行)→ 首次触发。

    今天未取到(None)永不提醒。
    """
    if today is not True:
        return False
    return prev is not True


def detect_signal_event(
    prev_active: Optional[bool],
    today_active: Optional[bool],
    today_close: Optional[float],
    prev_lowest: Optional[float],
) -> tuple[Optional[str], Optional[float]]:
    """检测信号事件:首次激活 / 创新低 / 持续激活 / 无事件。

    返回 (event, new_lowest):
    - event: 'first'(未激活→激活) / 'new_low'(持续+刷新最低)
             / 'still_active'(持续激活但未创新低,日常存在感汇报) / None
    - new_lowest: 该信号的最新累计净值最低值;未激活时返回 None
    """
    # 信号未激活 → reset
    if today_active is False:
        return None, None

    # 数据缺失 → 保守保留 prev_lowest,不推
    if today_active is None or today_close is None:
        return None, prev_lowest

    # today_active is True
    if prev_active is not True:
        return 'first', today_close

    # 持续激活
    if prev_lowest is None:
        # 旧 state.json 没记录,视为补登;迁移当天保持安静
        return None, today_close

    if today_close < prev_lowest:
        return 'new_low', today_close

    return 'still_active', prev_lowest


def next_threshold(
    close: Optional[float],
    ma120: Optional[float],
    ma250: Optional[float],
    signals: dict,
) -> Optional[tuple[str, float]]:
    """定位下一档会触发的信号 + 它的阈值价。

    顺序(从浅到深):signal_1 (MA250) → signal_2 (MA120 × 0.94) → signal_3 (MA120 × 0.88)。
    返回 (信号简称, 阈值价);全激活或 MA 缺失返回 None。
    """
    if not signals.get('signal_1'):
        if ma250 is None:
            return None
        return ('信号一', ma250)
    if not signals.get('signal_2'):
        if ma120 is None:
            return None
        return ('信号二', ma120 * (1 - SIGNAL_2_DROP))
    if not signals.get('signal_3'):
        if ma120 is None:
            return None
        return ('信号三', ma120 * (1 - SIGNAL_3_DROP))
    return None


def compute_active_days(
    activated_at_iso: str,
    today: date,
    trading_dates: "set[date] | frozenset[date] | None",
) -> int:
    """从激活日(ISO 字符串)到 today 之间的**交易日**数,含首尾。

    激活当天 = 第 1 天。跨周末/节假日不计入。
    边界:trading_dates 空 / 激活日晚于 today / 区间内无交易日 → 0。
    """
    parts = activated_at_iso.split('-')
    activated = date(int(parts[0]), int(parts[1]), int(parts[2]))
    if today < activated:
        return 0
    if not trading_dates:
        return 0
    return sum(1 for d in trading_dates if activated <= d <= today)


# ===== 信号显示元数据 =====

SIGNAL_LABELS = {
    'signal_1': 'MA250 加仓(净值跌破 MA250)',
    'signal_2': '常规加仓(净值跌破 MA120 6%)',
    'signal_3': '加倍加仓(净值跌破 MA120 12%)',
    'vix_30': 'VIX 突破 30(恐慌区)',
}
# 单位:份(1 份 = 1 个加仓单位,具体金额由使用者自定)
SIGNAL_SHARES = {
    'signal_1': 1,
    'signal_2': 1,
    'signal_3': 2,
}
SIGNAL_NEXT_SHARES = {'信号一': 1, '信号二': 1, '信号三': 2}
