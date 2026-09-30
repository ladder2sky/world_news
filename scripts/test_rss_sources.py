"""
RSS源测试脚本
用于验证所有RSS源是否可访问
"""
import json
import time
from pathlib import Path

import feedparser
import requests
from loguru import logger

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
SOURCES_FILE = PROJECT_ROOT / "config" / "rss_sources.json"

def test_rss_source(name: str, url: str, timeout: int = 10) -> dict:
    """
    测试单个RSS源
    
    Args:
        name: 来源名称
        url: RSS URL
        timeout: 请求超时时间(秒)
    
    Returns:
        测试结果字典
    """
    result = {
        'name': name,
        'url': url,
        'status': 'unknown',
        'status_code': None,
        'response_time': None,
        'entry_count': 0,
        'error': None
    }
    
    try:
        logger.info(f"Testing: {name} ({url})")
        
        start_time = time.time()
        
        # 发起请求
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (News Collector Bot)'
        })
        
        result['status_code'] = response.status_code
        result['response_time'] = round(time.time() - start_time, 2)
        
        if response.status_code != 200:
            result['status'] = 'failed'
            result['error'] = f"HTTP {response.status_code}"
            logger.error(f"  [FAIL] {name}: HTTP {response.status_code}")
            return result
        
        # 解析RSS
        feed = feedparser.parse(response.content)
        
        if feed.bozo and not feed.entries:
            result['status'] = 'parse_error'
            result['error'] = 'RSS parse error'
            logger.warning(f"  [WARN] {name}: Parse error")
            return result
        
        entry_count = len(feed.entries)
        result['entry_count'] = entry_count
        result['status'] = 'ok'
        
        logger.success(f"  [OK] {name}: {entry_count} entries ({result['response_time']}s)")
        
        return result
        
    except requests.exceptions.Timeout:
        result['status'] = 'timeout'
        result['error'] = 'Request timeout'
        logger.error(f"  [FAIL] {name}: Timeout")
        return result
    except requests.exceptions.ConnectionError as e:
        result['status'] = 'connection_error'
        result['error'] = str(e)
        logger.error(f"  [FAIL] {name}: Connection error")
        return result
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        logger.error(f"  [FAIL] {name}: {e}")
        return result

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("RSS Source Testing")
    logger.info("=" * 60)
    
    # 加载配置
    try:
        with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load sources config: {e}")
        return
    
    sources = config.get('sources', [])
    logger.info(f"Testing {len(sources)} RSS sources...\n")
    
    # 测试所有源
    results = []
    total_time = 0
    
    for source in sources:
        start = time.time()
        result = test_rss_source(
            name=source['name'],
            url=source['url']
        )
        results.append(result)
        total_time += result['response_time'] or 0
        time.sleep(0.5)  # 避免请求过快
    
    # 统计结果
    ok_count = sum(1 for r in results if r['status'] == 'ok')
    fail_count = len(results) - ok_count
    
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    logger.info(f"Total: {len(results)} sources")
    logger.info(f"OK: {ok_count}")
    logger.info(f"Failed: {fail_count}")
    logger.info(f"Total time: {total_time:.2f}s")
    
    # 输出失败列表
    if fail_count > 0:
        logger.warning("\nFailed sources:")
        for r in results:
            if r['status'] != 'ok':
                logger.warning(f"  - {r['name']}: {r['error']}")
    
    # 保存结果
    output_file = PROJECT_ROOT / "scripts" / "test_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"\nResults saved to: {output_file}")

if __name__ == '__main__':
    main()
