import time
from datetime import datetime, timedelta

from utils.config import env, SCHEDULER_WEEKDAY_CHECK_INTERVAL, SCHEDULER_TIME_CHECK_INTERVAL, SCHEDULER_EXECUTION_WINDOW_MINUTES, SCHEDULER_POST_EXECUTION_WAIT_SECONDS
from utils.logging_config import logger

def scheduled_task(start_time=None, duration=None, weekdays=None):
    """
    定时调度装饰器
    (以下三种调度方式任选其一，其他参数按需配置)

    :param start_time: 启动时间，格式为 'HH:MM'
    :param duration: 多长时间调度一次（秒）
    :param weekdays: 指定周几执行，格式为整数列表 [0,1,2,3,4,5,6]，0表示周一，6表示周日
                     如 [1,3,5] 表示周二、周四、周六执行
                     如果不指定，则每天都执行
                     
    调度方式说明：
    1. 周几的几点执行：提供 start_time 和 weekdays 参数
    2. 每天的几点执行：只提供 start_time 参数 
    3. 每隔 N 秒执行一次：只提供 duration 参数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            if env == 'local':
                logger.info('开发环境，直接启动（放弃定时调度）')
                func(*args, **kwargs)
                return
            logger.info('程序启动，等待调度中...')
            while True:
                # 定时调度
                if start_time:
                    # 获取当前时间和调度时间范围
                    today_now = datetime.now()
                    
                    # 检查是否指定了周几，如果指定了，则检查当前是否是指定的周几
                    if weekdays is not None:
                        # 获取当前是周几 (0表示周一，6表示周日)
                        current_weekday = today_now.weekday()  # 0-6 对应周一至周日
                        if current_weekday not in weekdays:
                            # 不是指定的周几，等待一段时间再检查
                            time.sleep(SCHEDULER_WEEKDAY_CHECK_INTERVAL)
                            continue
                        else:
                            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                            logger.info(f'今天是{weekday_names[current_weekday]}，符合调度计划 {weekdays}')    
                    
                    # 解析调度时间
                    start_hour, start_minute = map(int, start_time.split(':'))
                    start = today_now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
                    end = start + timedelta(minutes=SCHEDULER_EXECUTION_WINDOW_MINUTES)

                    # 如果当前时间在调度时间范围内，执行任务
                    if start <= today_now < end:
                        logger.info('激活调度')
                        func(*args, **kwargs)
                        logger.info('调度结束')

                        # 等待下一个周期
                        time.sleep(SCHEDULER_POST_EXECUTION_WAIT_SECONDS)
                    else:
                        # 不在执行时间范围内，等待一段时间再检查
                        time.sleep(SCHEDULER_TIME_CHECK_INTERVAL)
                else:
                    logger.info('激活调度')
                    func(*args, **kwargs)
                    logger.info('调度结束')
                    time.sleep(duration)
        return wrapper
    return decorator