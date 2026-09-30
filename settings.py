"""
全局配置文件
"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# 数据库
DB_PATH = BASE_DIR / "database" / "news.db"

# AI配置
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:1234")
AI_MODEL_LIGHT = os.getenv("AI_MODEL_LIGHT", "unsloth/gemma-4-26b-a4b-it")
AI_MODEL_MAIN = os.getenv("AI_MODEL_MAIN", "unsloth/gemma-4-26b-a4b-it")
AI_TOP_N = int(os.getenv("AI_TOP_N", "20"))
AI_SCREEN_N = int(os.getenv("AI_SCREEN_N", "50"))

# 抓取配置
NEWS_AGE_HOURS = int(os.getenv("NEWS_AGE_HOURS", "24"))         # 只抓取24小时内新闻
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))       # 请求超时(秒)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))                # 最大重试次数
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "1"))                # 初始重试延迟(秒)

# 评分阈值
SCORE_THRESHOLD_TOP = int(os.getenv("SCORE_THRESHOLD_TOP", "70"))  # Top新闻最低分数

# TTS配置
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_OUTPUT_DIR = BASE_DIR / "output_data" / "audio"

# 日志配置
LOG_DIR = BASE_DIR / "logs"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SYSTEM_LOG = LOG_DIR / "system.log"
ERROR_LOG = LOG_DIR / "errors.log"

# 运行模式
RUN_MODE = os.getenv("RUN_MODE", "full")

# RSS源配置文件
RSS_SOURCES_FILE = BASE_DIR / "config" / "rss_sources.json"

# AI Prompt配置文件
AI_PROMPTS_FILE = BASE_DIR / "config" / "ai_prompts.json"

# 输出目录
OUTPUT_DATA_DIR = BASE_DIR / "output_data"
OUTPUT_DIR = OUTPUT_DATA_DIR

# 备份目录
BACKUP_DIR = BASE_DIR / "backups"

# 确保目录存在
def ensure_directories():
    """确保所有需要的目录存在"""
    for directory in [LOG_DIR, OUTPUT_DATA_DIR, TTS_OUTPUT_DIR, BACKUP_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
