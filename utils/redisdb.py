import redis
from typing import Optional

from utils.config import redis_password, redis_host
from utils.logging_config import logger


def redis_cli() -> redis.Redis:
    """
    创建并返回Redis客户端连接
    """
    # 安全日志：使用掩码记录密码配置状态
    logger.info(f"Redis认证: {'已配置' if redis_password else '未配置'}")
    
    # 创建连接池配置
    pool_kwargs = {
        'host': redis_host,
        'port': 6379,
        'db': 0,
    }
    
    # 只有当密码存在时才添加
    if redis_password:
        pool_kwargs['password'] = redis_password
    
    # 创建连接池
    pool = redis.ConnectionPool(**pool_kwargs)
    
    # 创建Redis客户端
    client = redis.Redis(connection_pool=pool)
    
    # 测试连接
    try:
        client.ping()
        logger.info("Redis 连接成功")
    except redis.AuthenticationError:
        logger.error("Redis 认证失败，请检查密码")
        raise
    except redis.ConnectionError:
        logger.error("Redis 连接失败，请检查 Redis 是否运行")
        raise
    
    return client