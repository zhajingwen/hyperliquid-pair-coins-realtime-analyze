import requests
import json
import time

from utils.config import lark_webhook_url, lark_alert_email, LARK_MAX_RETRIES, LARK_REQUEST_TIMEOUT, LARK_BACKOFF_BASE
from utils.logging_config import logger

def sender(msg, url=None, title='', del_blank_row=True):
    """
    # 文本格式化官方文档
    https://open.larksuite.com/document/ukTMukTMukTM/uMDMxEjLzATMx4yMwETM?lang=zh-CN
    # 关于加粗：用Card中的Fields来实现
    加粗（文档最底部）：https://open.larksuite.com/document/common-capabilities/message-card/message-cards-content/content-module
    https://open.larksuite.com/document/common-capabilities/message-card/message-cards-content/card-structure
    https://open.larksuite.com/document/common-capabilities/message-card/message-cards-content/using-markdown-tags
    加粗：（文档最底部）：https://open.larksuite.com/document/common-capabilities/message-card/message-cards-content/embedded-non-interactive-elements/field
    :param url: webhook地址
    :param msg: 需要发送的消息
    """
    if not url:
        url = lark_webhook_url
        if not url:
            logger.error("未配置飞书Webhook URL，无法发送消息")
            return None
    msg_list = []
    for i in msg.strip().split('\n'):
        i = i.strip()
        if del_blank_row:
            if not i:
                continue
        if i:
            i_list = i.split(' ')
            msg_row = []
            for i_word in i_list:
                if '&url&' in i_word:
                    href =  i_word.split('&url&')[-1].strip()
                    link_name = i_word.split('&url&')[0].strip()
                    item_json = {
                        "tag": "a",
                        "href": href,
                        "text": link_name
                    }
                else:
                    item_json = {
                        "tag": "text",
                        "text": i_word + ' '
                    }
                msg_row.append(item_json)
        else:
            msg_row = [{"tag": "text","text": "\n"}]
        msg_list.append(msg_row)

    data = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": msg_list
                }
            }
        }
    }

    # 如果配置了告警邮箱，添加到消息中
    if lark_alert_email:
        data["email"] = lark_alert_email
    headers = {'Content-Type': 'application/json'}

    # 修复死循环: 明确重试次数、添加超时和指数退避
    max_retries = LARK_MAX_RETRIES
    for attempt in range(max_retries):
        try:
            res = requests.request(
                "POST",
                url,
                headers=headers,
                data=json.dumps(data),
                timeout=LARK_REQUEST_TIMEOUT
            )
            res.raise_for_status()  # 检查HTTP错误
            logger.info(f'lark 告警调用成功：{res.text}')
            return res.text
        except requests.exceptions.RequestException as e:
            logger.warning(f'lark 告警调用失败 (尝试 {attempt+1}/{max_retries}): {e}')
            if attempt == max_retries - 1:
                # 最后一次失败，记录错误并返回None
                logger.error(f'lark 告警最终失败: {e} | URL: {url}', exc_info=True)
                return None
            # 指数退避
            time.sleep(LARK_BACKOFF_BASE ** attempt)

    return None

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