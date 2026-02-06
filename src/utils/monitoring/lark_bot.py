import requests
import json
import time

from src.utils.core.config import lark_alert_email, LARK_MAX_RETRIES, LARK_REQUEST_TIMEOUT, LARK_BACKOFF_BASE
from src.utils.core.logging_config import logger


def sender_colourful(url, content, title=''):
    """
    https://open.larksuite.com/document/common-capabilities/message-card/message-cards-content/using-markdown-tags
    """
    message = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": "red"
            },
            "elements": [{
                "tag": "markdown",
                "content": content,
            }]
        }
    }

    # 如果配置了告警邮箱，添加到消息中
    if lark_alert_email:
        message["email"] = lark_alert_email
    headers = {
        'Content-Type': 'application/json'
    }

    # 修复死循环: 明确重试次数、添加超时和指数退避
    max_retries = LARK_MAX_RETRIES
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(message),
                timeout=LARK_REQUEST_TIMEOUT
            )
            response.raise_for_status()  # 检查HTTP错误
            logger.info(f'lark 彩色告警调用成功：{response.text}')
            return response.text
        except requests.exceptions.RequestException as e:
            logger.warning(f'lark 彩色告警调用失败 (尝试 {attempt+1}/{max_retries}): {e}')
            if attempt == max_retries - 1:
                # 最后一次失败，记录错误并返回None
                logger.error(f'lark 彩色告警最终失败: {e} | URL: {url}', exc_info=True)
                return None
            # 指数退避
            time.sleep(LARK_BACKOFF_BASE ** attempt)

    return None