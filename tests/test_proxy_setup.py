"""setup_proxy_env 行为:从环境变量保留代理给国外站点,清空给国内站点。"""

import os
from unittest.mock import patch

from monitor import setup_proxy_env


def test_extracts_http_and_https_proxies():
    """从 HTTP_PROXY / HTTPS_PROXY 提取并返回字典。"""
    # clear=True 隔离机器真实代理环境,避免测试结果依赖运行机器的 shell 代理变量
    env = {'HTTP_PROXY': 'http://127.0.0.1:7890', 'HTTPS_PROXY': 'http://127.0.0.1:7890'}
    with patch.dict(os.environ, env, clear=True):
        orig = setup_proxy_env()
    assert orig == {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}


def test_lowercase_variants_also_picked_up():
    """http_proxy(小写)也算。"""
    env = {'http_proxy': 'http://lower:7890', 'https_proxy': 'http://lower:7890'}
    with patch.dict(os.environ, env, clear=True):
        orig = setup_proxy_env()
    assert orig['http'] == 'http://lower:7890'


def test_no_proxy_returns_empty():
    """无任何代理变量时返回空 dict,后续 fetch_vix 也能直连尝试。"""
    proxy_vars = ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy']
    env_clean = {k: v for k, v in os.environ.items() if k not in proxy_vars}
    with patch.dict(os.environ, env_clean, clear=True):
        orig = setup_proxy_env()
    assert orig == {}


def test_clears_proxy_env_for_domestic_sources():
    """执行后环境变量里所有代理变量应被清空(给国内 akshare 直连)。"""
    env = {'HTTP_PROXY': 'http://x', 'http_proxy': 'http://x', 'ALL_PROXY': 'socks5://y'}
    with patch.dict(os.environ, env, clear=False):
        setup_proxy_env()
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
            assert k not in os.environ
        assert os.environ.get('NO_PROXY') == '*'


def test_returns_filtered_dict_no_none_values():
    """返回的 dict 不含 None 值(只放真有代理的协议)。"""
    # 完全清空环境,只留 HTTP_PROXY,避免机器现有 http_proxy 渗入
    with patch.dict(os.environ, {'HTTP_PROXY': 'http://x'}, clear=True):
        orig = setup_proxy_env()
    assert orig == {'http': 'http://x'}
