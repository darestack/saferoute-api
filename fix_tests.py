import os
import re

TEST_PROXY = "tests/test_proxy.py"
TEST_RETENTION = "tests/test_retention.py"

def fix_test_proxy():
    with open(TEST_PROXY, "r") as f:
        content = f.read()

    # Imports to update:
    content = content.replace("from app.routes.proxy import clear_route_cache", "from app.services.route_cache import clear_route_cache")
    content = content.replace("from app.routes.proxy import _cache_route, _get_cached_route, clear_route_cache", "from app.services.route_cache import _cache_route, get_cached_route as _get_cached_route, clear_route_cache")
    content = content.replace("from app.routes.proxy import _get_cached_route", "from app.services.route_cache import get_cached_route as _get_cached_route")
    content = content.replace("from app.routes.proxy import _fill_route_cache, _route_cache_fills", "from app.services.route_cache import fill_route_cache as _fill_route_cache, _route_cache_fills")
    content = content.replace("from app.routes.proxy import _fill_route_cache", "from app.services.route_cache import fill_route_cache as _fill_route_cache")
    content = content.replace("from app.routes.proxy import _route_cache_fills as fills", "from app.services.route_cache import _route_cache_fills as fills")
    
    # process_retries
    content = content.replace('patch("app.routes.proxy.admin")', 'patch("app.services.retry_processor.admin")')
    
    # route cache patches
    content = content.replace('patch("app.routes.proxy._cache_route"', 'patch("app.services.route_cache._cache_route"')
    content = content.replace('patch("app.routes.proxy._route_cache_fills"', 'patch("app.services.route_cache._route_cache_fills"')
    content = content.replace('patch("app.routes.proxy._route_cache_fills_lock"', 'patch("app.services.route_cache._route_cache_fills_lock"')

    # Fix test references to _get_cached_route / etc inside mock signatures if any
    
    with open(TEST_PROXY, "w") as f:
        f.write(content)


def fix_test_retention():
    with open(TEST_RETENTION, "r") as f:
        content = f.read()

    content = content.replace('patch("app.routes.proxy._is_circuit_breaker_open")', 'patch("app.services.circuit_breaker.is_circuit_breaker_open")')
    
    with open(TEST_RETENTION, "w") as f:
        f.write(content)


def add_clear_route_cache():
    RC_FILE = "app/services/route_cache.py"
    with open(RC_FILE, "r") as f:
        content = f.read()
    
    if "async def clear_route_cache" not in content:
        content += "\n\nasync def clear_route_cache() -> None:\n    async with _route_cache_lock:\n        _route_cache.clear()\n"
        with open(RC_FILE, "w") as f:
            f.write(content)

if __name__ == "__main__":
    add_clear_route_cache()
    fix_test_proxy()
    fix_test_retention()
    print("Fixes applied.")
