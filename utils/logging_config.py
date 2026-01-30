"""
统一日志配置模块
所有模块导入此模块即可使用日志系统

功能：
- 避免多个模块 logging.basicConfig() 冲突
- 集中管理日志配置
- 支持环境变量配置
- 支持控制台 + 文件双输出
- 为第三方库降低日志级别
- 导入即自动初始化

使用方法：
    # 方式1：直接使用全局 logger（推荐）
    from utils.logging_config import logger
    logger.info("这是一条日志")
    
    # 方式2：获取自定义名称的 logger
    from utils.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("这是一条日志")

环境变量配置：
    LOG_LEVEL: 全局日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL，默认 INFO）
    CONSOLE_LOG_LEVEL: 控制台日志级别（默认与 LOG_LEVEL 相同）
    FILE_LOG_LEVEL: 文件日志级别（默认与 LOG_LEVEL 相同）
    LOG_FILE: 日志文件路径（可选，不设置则只输出到控制台）

Author: Claude Code
Date: 2026-01-27
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# =====================================================
# 日志配置（从环境变量读取）
# =====================================================

# 日志级别配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
CONSOLE_LOG_LEVEL = os.getenv('CONSOLE_LOG_LEVEL', LOG_LEVEL).upper()
FILE_LOG_LEVEL = os.getenv('FILE_LOG_LEVEL', LOG_LEVEL).upper()

# 日志文件配置（可选）
LOG_FILE = os.getenv('LOG_FILE')  # 不设置则只输出到控制台

# 日志文件轮转配置
MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(100 * 1024 * 1024)))  # 默认100MB
BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '5'))  # 默认保留5个备份

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# =====================================================
# 自动初始化日志系统
# =====================================================

def _init_logging():
    """初始化日志系统（模块加载时自动调用）"""
    
    # 日志级别映射
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 设置为最低级别，由 handler 控制
    
    # 清除现有的 handler（避免重复）
    root_logger.handlers.clear()
    
    # 日志格式化器
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    
    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level_map.get(CONSOLE_LOG_LEVEL, logging.INFO))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 文件 handler（如果配置了日志文件）
    if LOG_FILE:
        # 确保日志目录存在
        log_path = Path(LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(level_map.get(FILE_LOG_LEVEL, logging.INFO))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 为第三方库设置日志级别，避免输出过多信息
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('websocket').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('hyperliquid').setLevel(logging.INFO)
    
    # 记录初始化信息
    init_logger = logging.getLogger('utils.logging_config')
    init_logger.info(f"日志系统已初始化 - 控制台级别: {CONSOLE_LOG_LEVEL}, 文件级别: {FILE_LOG_LEVEL}")
    if LOG_FILE:
        init_logger.info(f"日志文件: {LOG_FILE} (最大 {MAX_BYTES/(1024*1024):.0f}MB, 保留 {BACKUP_COUNT} 个备份)")


# 模块加载时自动初始化
_init_logging()

# =====================================================
# 导出接口
# =====================================================

# 导出全局 logger 供直接使用（推荐）
logger = logging.getLogger('app')


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger（可选，用于需要区分模块的场景）
    
    Args:
        name: logger 名称（通常使用 __name__）
    
    Returns:
        logging.Logger 实例
    
    Example:
        logger = get_logger(__name__)
        logger.info("这是一条信息日志")
    
    Note:
        大多数情况下直接使用全局 logger 即可：
        from utils.logging_config import logger
    """
    return logging.getLogger(name)
