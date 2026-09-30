"""
每日全球新闻智能采集与分析系统
主入口程序
"""
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

# 配置日志
def setup_logging():
    """设置日志配置"""
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # 移除默认handler
    logger.remove()
    
    # 控制台输出
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 系统日志文件
    logger.add(
        logs_dir / "system.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        encoding="utf-8"
    )
    
    # 错误日志文件
    logger.add(
        logs_dir / "errors.log",
        rotation="1 day",
        retention="30 days",
        level="ERROR",
        encoding="utf-8"
    )

setup_logging()

import settings
from database.database import DatabaseManager
from collector.rss_reader import RSSReader
from ai.analyzer import NewsAnalyzer
from output.csv_generator import CSVGenerator
from output.report_builder import ReportBuilder
from tts.script_generator import ScriptGenerator

def load_sources_from_json(db: DatabaseManager):
    """
    从JSON配置文件加载新闻源到数据库（JSON是唯一真源：JSON中存在=enabled，JSON中已删除的源自动置为disabled）
    
    Args:
        db: 数据库管理器
    """
    sources_file = settings.RSS_SOURCES_FILE
    logger.info(f"Loading RSS sources from {sources_file}")
    
    try:
        with open(sources_file, 'r', encoding='utf-8') as f:
            sources_data = json.load(f)
        
        json_names = {s['name'] for s in sources_data.get('sources', [])}
        
        count = 0
        for source in sources_data.get('sources', []):
            name = source['name']
            url = source['url']
            category = source.get('category', 'Other')
            enabled = bool(source.get('enabled', True))
            
            if db.upsert_source(name, url, category, enabled=enabled):
                count += 1
        
        if json_names:
            disabled = db.disable_sources_not_in(json_names)
            if disabled:
                logger.info(f"Disabled {disabled} sources missing from JSON config")
        
        logger.info(f"Loaded {count} RSS sources to database")
        
    except Exception as e:
        logger.error(f"Failed to load RSS sources: {e}")
        raise

def run_news_collection(run_type: str = "full"):
    """
    执行新闻采集流程
    
    Args:
        run_type: 运行类型 (full/incremental/manual)
    """
    start_time = time.time()
    logger.info(f"=" * 60)
    logger.info(f"Daily News Collection Started - {run_type} mode")
    logger.info(f"=" * 60)
    
    # 使用数据库上下文管理器
    with DatabaseManager() as db:
        # 1. 初始化数据库
        logger.info("Initializing database...")
        db.initialize_schema()
        
        # 2. 加载RSS源配置
        load_sources_from_json(db)
        
        # 3. 获取启用的源
        sources = db.get_enabled_sources()
        sources_list = [
            {'name': s['name'], 'url': s['url'], 'category': s['category']}
            for s in sources
        ]
        
        logger.info(f"Processing {len(sources_list)} RSS sources...")
        
        # 4. 创建运行记录
        run_id = db.create_run_record(run_type, len(sources_list))
        
        try:
            # 5. RSS抓取
            logger.info("-" * 40)
            logger.info("Phase 1: RSS Collection")
            logger.info("-" * 40)
            
            reader = RSSReader()
            result = reader.fetch_all_feeds(sources_list)
            
            news_list = result['news']
            stats = result['stats']
            
            logger.info(f"Collected {len(news_list)} news items")
            logger.info(f"Sources: {stats['success']} success, {stats['failed']} failed")
            
            # 更新源状态
            for source in sources_list:
                # 简化处理，实际应该跟踪每个源的状态
                pass
            
            # 6. 保存到数据库
            logger.info("-" * 40)
            logger.info("Phase 2: Data Storage")
            logger.info("-" * 40)
            
            insert_stats = db.bulk_insert_news(news_list)
            logger.info(f"New: {insert_stats['new']}, Duplicated: {insert_stats['duplicated']}")
            
            # 更新运行记录
            db.update_run_record(
                run_id,
                news_fetched=len(news_list),
                news_new=insert_stats['new'],
                news_duplicated=insert_stats['duplicated']
            )
            
            # 7. AI分析（如果可用）
            logger.info("-" * 40)
            logger.info("Phase 3: AI Analysis")
            logger.info("-" * 40)
            
            analyzer = NewsAnalyzer()
            ai_processed = 0
            
            if analyzer.check_service():
                # 获取未处理的新闻
                unprocessed = db.get_unprocessed_news(limit=settings.AI_SCREEN_N)
                
                if unprocessed:
                    # 转换为字典列表
                    news_dicts = [dict(row) for row in unprocessed]
                    
                    # 批量分析
                    analyzed_news = analyzer.batch_analyze(news_dicts)
                    
                    # 更新数据库
                    for news in analyzed_news:
                        db.update_news_analysis(
                            news_id=news['id'],
                            category=news.get('category', 'Other'),
                            country=','.join(news.get('countries', ['Global'])),
                            ai_summary=news.get('ai_summary', ''),
                            importance_score=news.get('score', 0),
                            event_id=news.get('event_id', '')
                        )
                        ai_processed += 1
                    
                    logger.info(f"AI analyzed {ai_processed} news items")
                    
                    # 更新运行记录
                    db.update_run_record(run_id, ai_processed=ai_processed)
                else:
                    logger.info("No unprocessed news found")
            else:
                logger.warning("Ollama service not available, skipping AI analysis")
                logger.info("Start Ollama and re-run with --analyze-only flag")
            
            # 8. 生成报告
            logger.info("-" * 40)
            logger.info("Phase 4: Report Generation")
            logger.info("-" * 40)
            
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            # 获取已处理的新闻
            processed_news = db.get_top_news(count=settings.AI_TOP_N * 2)
            
            if processed_news:
                news_dicts = [dict(row) for row in processed_news]
                
                # CSV报告
                csv_gen = CSVGenerator()
                csv_path = csv_gen.generate_daily_csv(news_dicts, today_str)
                logger.info(f"CSV report: {csv_path}")
                
                # 文本摘要
                report_builder = ReportBuilder()
                summary_path = report_builder.build_summary_text(news_dicts, today_str)
                logger.info(f"Summary report: {summary_path}")
                
                # TTS脚本
                script_gen = ScriptGenerator()
                script_path = script_gen.generate_script(news_dicts, max_count=10, date_str=today_str)
                logger.info(f"TTS script: {script_path}")
            else:
                logger.warning("No processed news available for reports")
            
            # 9. 完成运行记录
            duration = time.time() - start_time
            db.complete_run_record(run_id, duration, "success")
            
            logger.info("=" * 60)
            logger.info(f"Collection Complete!")
            logger.info(f"Duration: {duration:.2f} seconds")
            logger.info(f"News collected: {len(news_list)}")
            logger.info(f"New news: {insert_stats['new']}")
            logger.info(f"AI processed: {ai_processed}")
            logger.info("=" * 60)
            
        except Exception as e:
            duration = time.time() - start_time
            db.complete_run_record(run_id, duration, "failed", str(e))
            logger.error(f"Collection failed: {e}")
            raise

def generate_reports_from_db(db: DatabaseManager) -> dict:
    """
    从数据库读取已分析（is_processed=1）的新闻生成 CSV / 文本摘要 / TTS 播报脚本。

    供 --analyze-only 跑完之后使用，也可独立被 --reports-only / --resummarize 调用。
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    processed_news = db.get_top_news(count=settings.AI_TOP_N * 2)

    result = {'csv': None, 'summary': None, 'script': None, 'count': 0}
    if not processed_news:
        logger.warning("No processed (AI-analyzed) news available for reports — run --analyze-only first.")
        return result

    news_dicts = [dict(row) for row in processed_news]
    result['count'] = len(news_dicts)

    csv_gen = CSVGenerator()
    result['csv'] = csv_gen.generate_daily_csv(news_dicts, today_str)
    logger.info(f"CSV report: {result['csv']}")

    report_builder = ReportBuilder()
    result['summary'] = report_builder.build_summary_text(news_dicts, today_str)
    logger.info(f"Summary report: {result['summary']}")

    script_gen = ScriptGenerator()
    result['script'] = script_gen.generate_script(news_dicts, max_count=10, date_str=today_str)
    logger.info(f"TTS script: {result['script']}")

    return result


def run_resummarize(db: DatabaseManager, limit: int = 500, force_all: bool = False) -> int:
    """
    重跑摘要：对 DB 里不合格的 ai_summary 重新调用本地 LLM 生成中文摘要。
    - 分类 / 打分 / event_id 一律不动（省 token）
    - 如果 force_all=True：忽略不合格判定，对所有 is_processed=1 的新闻重算摘要
    """
    from ai.analyzer import _chinese_char_ratio  # 复用 analyzer 的汉字比例判定

    analyzer = NewsAnalyzer()
    if not analyzer.check_service():
        logger.error("LLM service not available — abort resummarize.")
        return 0

    constraints = analyzer.prompt_manager.get_summary_constraints()
    min_chars = int(constraints.get('min_chars', 100))
    min_zh = 0.45

    # --- 1. 捞候选项 ---
    if force_all:
        cursor = db.connection.execute(
            """SELECT * FROM news
               WHERE is_processed = 1
               ORDER BY importance_score DESC, published_time DESC
               LIMIT ?""",
            (int(limit),)
        )
        raw_rows = cursor.fetchall()
    else:
        raw_rows = db.get_news_needing_resummary(min_chars=min_chars, limit=limit)

    # --- 2. Python 侧精筛：汉字比例 或 长度 双失败的才重跑 ---
    if force_all:
        target_rows = list(raw_rows)
    else:
        target_rows = []
        for r in raw_rows:
            cur = (r['ai_summary'] or '').strip()
            bad_len = (not cur) or len(cur) < min_chars
            bad_zh = _chinese_char_ratio(cur) < min_zh
            if bad_len or bad_zh:
                target_rows.append(r)

    if not target_rows:
        logger.success("No news needs resummarize — all ai_summary look good.")
        return 0

    logger.info(f"Resummarizing {len(target_rows)} items (force_all={force_all})...")
    news_dicts = [dict(r) for r in target_rows]
    updated = analyzer.resummarize_batch(news_dicts)

    written = 0
    for news in updated:
        db.update_news_summary_only(news_id=news['id'], ai_summary=news.get('ai_summary', ''))
        written += 1
    logger.success(f"Resummarize done: updated {written} ai_summary fields")
    return written


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description='每日全球新闻智能采集与分析系统'
    )
    parser.add_argument(
        '--type', '-t',
        choices=['full', 'incremental', 'manual'],
        default='full',
        help='运行类型 (default: full)'
    )
    parser.add_argument(
        '--analyze-only', '-a',
        action='store_true',
        help='仅执行AI分析，不采集新新闻（分析完自动生成3份报告）'
    )
    parser.add_argument(
        '--reports-only', '-r',
        action='store_true',
        help='不采集、不分析，只根据DB里已分析完的新闻重新生成CSV/摘要/TTS脚本'
    )
    parser.add_argument(
        '--resummarize',
        action='store_true',
        help='只重跑摘要：对 ai_summary 不合格（过短/英文）的新闻重生成，不改分类/打分，最后自动出报告'
    )
    parser.add_argument(
        '--resummarize-all',
        action='store_true',
        help='（慎用）对 DB 里全部已分析的新闻强制重算摘要；用于刚改完 prompt 想一次性把旧摘要全换掉'
    )
    parser.add_argument(
        '--test-sources',
        action='store_true',
        help='测试RSS源可用性'
    )

    args = parser.parse_args()

    try:
        if args.test_sources:
            from database.database import DatabaseManager
            with DatabaseManager() as db:
                db.initialize_schema()
                load_sources_from_json(db)
                sources = db.get_enabled_sources()

            logger.info(f"Testing {len(sources)} RSS sources...")
            reader = RSSReader()

            for source in sources:
                try:
                    feed = reader.fetch_feed(source['url'])
                    if feed:
                        logger.success(f"[OK] {source['name']}: {len(feed.entries)} entries")
                    else:
                        logger.warning(f"[WARN] {source['name']}: No entries")
                except Exception as e:
                    logger.error(f"[FAIL] {source['name']}: {e}")

        elif args.reports_only and not (args.resummarize or args.resummarize_all):
            from database.database import DatabaseManager
            with DatabaseManager() as db:
                db.initialize_schema()
                load_sources_from_json(db)
                out = generate_reports_from_db(db)
            logger.success(f"Reports generated from DB ({out['count']} items)")

        elif args.resummarize or args.resummarize_all:
            from database.database import DatabaseManager
            with DatabaseManager() as db:
                db.initialize_schema()
                load_sources_from_json(db)
                run_resummarize(db, limit=5000, force_all=bool(args.resummarize_all))
                logger.info("-" * 40)
                logger.info("Phase 4: Report Generation (post resummarize)")
                logger.info("-" * 40)
                out = generate_reports_from_db(db)
            logger.success(f"Resummarize flow complete — reports refreshed ({out['count']} items)")

        elif args.analyze_only:
            from database.database import DatabaseManager
            with DatabaseManager() as db:
                db.initialize_schema()
                load_sources_from_json(db)

                unprocessed = db.get_unprocessed_news(limit=settings.AI_SCREEN_N)
                if unprocessed:
                    analyzer = NewsAnalyzer()
                    if analyzer.check_service():
                        news_dicts = [dict(row) for row in unprocessed]
                        analyzed = analyzer.batch_analyze(news_dicts)

                        for news in analyzed:
                            db.update_news_analysis(
                                news_id=news['id'],
                                category=news.get('category', 'Other'),
                                country=','.join(news.get('countries', ['Global'])),
                                ai_summary=news.get('ai_summary', ''),
                                importance_score=news.get('score', 0),
                                event_id=news.get('event_id', '')
                            )
                        logger.success(f"AI analyzed {len(analyzed)} news items")
                    else:
                        logger.error("LLM service not available (check LM Studio / Ollama is up + model loaded)")
                else:
                    logger.info("No unprocessed news found, skipping AI analysis")

                logger.info("-" * 40)
                logger.info("Phase 4: Report Generation")
                logger.info("-" * 40)
                out = generate_reports_from_db(db)

        else:
            run_news_collection(args.type)
    
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
