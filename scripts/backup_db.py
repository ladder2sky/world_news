"""
数据库备份脚本
"""
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "news.db"
BACKUP_DIR = PROJECT_ROOT / "backups"

def backup_database():
    """备份数据库"""
    if not DB_PATH.exists():
        logger.warning(f"Database not found: {DB_PATH}")
        return None
    
    # 创建备份目录
    BACKUP_DIR.mkdir(exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"news_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    
    try:
        shutil.copy2(str(DB_PATH), str(backup_path))
        logger.info(f"Database backed up: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise

def cleanup_old_backups(keep_days: int = 30):
    """
    清理旧备份
    
    Args:
        keep_days: 保留天数
    """
    from datetime import timedelta
    
    if not BACKUP_DIR.exists():
        return
    
    cutoff = datetime.now() - timedelta(days=keep_days)
    deleted_count = 0
    
    for backup_file in BACKUP_DIR.glob("news_*.db"):
        # 从文件名提取日期
        try:
            date_str = backup_file.stem.replace('news_', '')
            file_date = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            
            if file_date < cutoff:
                backup_file.unlink()
                deleted_count += 1
                logger.info(f"Deleted old backup: {backup_file}")
        except ValueError:
            continue
    
    logger.info(f"Cleanup complete: {deleted_count} old backups removed")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据库备份工具')
    parser.add_argument('--full', action='store_true', help='完整备份')
    parser.add_argument('--cleanup', action='store_true', help='清理旧备份')
    parser.add_argument('--keep-days', type=int, default=30, help='保留天数 (default: 30)')
    
    args = parser.parse_args()
    
    if args.full or not args.cleanup:
        backup_database()
    
    if args.cleanup:
        cleanup_old_backups(args.keep_days)

if __name__ == '__main__':
    main()
