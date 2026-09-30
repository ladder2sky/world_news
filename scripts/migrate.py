"""
数据库迁移工具
用于未来数据库schema变更时的数据迁移
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "news.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"

def get_current_schema_version(db_path: Path) -> int:
    """
    获取当前数据库schema版本
    
    Args:
        db_path: 数据库路径
    
    Returns:
        版本号，不存在返回0
    """
    if not db_path.exists():
        return 0
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 检查是否存在version表
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        
        if not cursor.fetchone():
            # 创建版本表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
            conn.commit()
            version = 0
        else:
            cursor.execute("SELECT MAX(version) FROM schema_version")
            version = cursor.fetchone()[0] or 0
        
        conn.close()
        return version
        
    except Exception as e:
        logger.error(f"Failed to get schema version: {e}")
        return 0

def apply_schema(db_path: Path, schema_path: Path) -> bool:
    """
    应用schema脚本
    
    Args:
        db_path: 数据库路径
        schema_path: schema文件路径
    
    Returns:
        是否成功
    """
    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 执行schema脚本
        cursor.executescript(schema_sql)
        
        # 记录版本
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """)
        
        # 简单版本管理：基于时间戳
        version = int(datetime.now().timestamp())
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
            (version, "Applied schema.sql")
        )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Schema applied successfully (version: {version})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to apply schema: {e}")
        return False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据库迁移工具')
    parser.add_argument('--apply', action='store_true', help='应用当前schema')
    parser.add_argument('--check', action='store_true', help='检查当前版本')
    parser.add_argument('--force', action='store_true', help='强制重新应用schema（会重建数据库）')
    
    args = parser.parse_args()
    
    if args.force:
        if DB_PATH.exists():
            DB_PATH.unlink()
            logger.warning(f"Deleted existing database: {DB_PATH}")
        apply_schema(DB_PATH, SCHEMA_PATH)
    
    elif args.apply:
        if not DB_PATH.exists():
            logger.info("Database not found, creating new one...")
            apply_schema(DB_PATH, SCHEMA_PATH)
        else:
            apply_schema(DB_PATH, SCHEMA_PATH)
    
    elif args.check:
        version = get_current_schema_version(DB_PATH)
        logger.info(f"Current schema version: {version}")
    
    else:
        # 默认检查并提示
        version = get_current_schema_version(DB_PATH)
        logger.info(f"Current schema version: {version}")
        logger.info("Use --apply to apply schema changes")
        logger.info("Use --force to rebuild database (WARNING: data loss)")

if __name__ == '__main__':
    main()
