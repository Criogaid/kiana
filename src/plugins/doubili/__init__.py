import asyncio
import html
import json
import re
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from httpx import AsyncClient
from nonebot import get_driver, get_plugin_config, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.exception import MatcherException
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ..group_permission import create_platform_rule
from . import bilibili, douyin, xiaohongshu
from .config import Config
from .security import SecurityError, validate_video_url, sanitize_error_message

__plugin_meta__ = PluginMetadata(
    name="doubili",
    description="视频解析",
    usage="发送B站、抖音、小红书链接即可下载视频或图片",
    config=Config,
)

config = get_plugin_config(Config)

# 创建各平台的规则检查函数
_bilibili_group_rule = create_platform_rule(lambda: config, "bilibili")
_douyin_group_rule = create_platform_rule(lambda: config, "douyin")
_xiaohongshu_group_rule = create_platform_rule(lambda: config, "xiaohongshu")

# HTTP客户端管理
_http_client: AsyncClient | None = None


def get_http_client() -> AsyncClient:
    """获取全局HTTP客户端实例"""
    global _http_client
    if _http_client is None:
        _http_client = AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _http_client


driver = get_driver()


@driver.on_shutdown
async def shutdown_http_client():
    """插件关闭时清理HTTP客户端"""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def is_bilibili_link(event: MessageEvent) -> bool:
    """检查是否为B站链接且B站解析已启用"""
    # 使用通用规则检查群权限和全局开关
    if not await _bilibili_group_rule(event):
        return False

    message = str(event.message).strip()

    if "CQ:json" in message:
        try:
            # 增强的JSON解析，支持多种转义格式
            json_pattern = r"\[CQ:json,data=([^\]]+)\]"
            json_str = re.search(json_pattern, message)
            if json_str:
                # 处理转义字符
                json_data = json.loads(unquote(json_str.group(1).replace("&#44;", ",")))
                if "meta" in json_data and "detail_1" in json_data["meta"]:
                    detail = json_data["meta"]["detail_1"]
                    # 验证appid是B站的
                    if detail.get("appid") == "1109937557":
                        return True

        except Exception as e:
            logger.debug(f"解析小程序数据失败: {e}")

    # 检查普通链接
    return any(pattern.search(message) for pattern in bilibili.PATTERNS.values())


bilibili_matcher = on_message(
    rule=Rule(is_bilibili_link),
    priority=5,
    block=True,
)


@bilibili_matcher.handle()
async def handle_bilibili_message(bot: Bot, event: MessageEvent):
    message = str(event.message).strip()

    id_type, video_id = await bilibili.extract_video_id(message)
    if not video_id:
        return

    try:
        # 根据id类型选择参数
        if id_type == "BV":
            video_data = await bilibili.get_video_stream(bvid=video_id)
        else:  # aid
            video_data = await bilibili.get_video_stream(aid=int(video_id))

        if isinstance(video_data, str):
            await bilibili_matcher.send(video_data)
        else:
            client = get_http_client()
            video_response = await client.get(video_data["url"], headers=video_data["headers"])
            video_response.raise_for_status()
            video_bytes = BytesIO(video_response.content)
            await bilibili_matcher.send(MessageSegment.video(video_bytes))
    except MatcherException:
        raise
    except Exception as e:
        logger.error(f"获取视频失败: {e}")
        # 清理错误信息，防止泄露敏感信息
        safe_error = sanitize_error_message(str(e))
        await bilibili_matcher.finish(f"获取视频失败: {safe_error}")


async def is_douyin_link(event: MessageEvent) -> bool:
    """检查是否为抖音链接且抖音解析已启用"""
    # 使用通用规则检查群权限和全局开关
    if not await _douyin_group_rule(event):
        return False

    message = str(event.message).strip()
    return any(pattern.search(message) for pattern in douyin.PATTERNS.values())


async def is_xiaohongshu_link(event: MessageEvent) -> bool:
    """检查是否为小红书链接且小红书解析已启用"""
    # 使用通用规则检查群权限和全局开关
    if not await _xiaohongshu_group_rule(event):
        return False

    message = str(event.message).strip()

    # 检查卡片消息
    if "CQ:json" in message and config.xiaohongshu_cookie:
        try:
            # 增强的JSON解析，支持多种转义格式
            json_pattern = r"\[CQ:json,data=([^\]]+)\]"
            json_str = re.search(json_pattern, message)
            if json_str:
                json_data = json.loads(unquote(json_str.group(1).replace("&#44;", ",")))
                if "meta" in json_data and "news" in json_data["meta"]:
                    news = json_data["meta"]["news"]
                    jump_url = news.get("jumpUrl", "")
                    if "xiaohongshu.com" in jump_url or "xhslink.com" in jump_url:
                        return True

        except Exception as e:
            logger.debug(f"解析小红书卡片数据失败: {e}")

    # 检查普通链接
    return any(pattern.search(message) for pattern in xiaohongshu.PATTERNS.values())


douyin_matcher = on_message(
    rule=Rule(is_douyin_link),
    priority=5,
    block=True,
)


@douyin_matcher.handle()
async def handle_douyin_message(bot: Bot, event: MessageEvent):
    """处理抖音消息"""
    message = str(event.message).strip()
    video_id = await douyin.extract_video_id(message)

    if not video_id:
        await douyin_matcher.finish("未找到有效的抖音视频ID")

    video_data = None
    video_segment = None

    try:
        video_info = await douyin.get_video_info(video_id)
        if isinstance(video_info, str):
            await douyin_matcher.finish(video_info)

        await douyin_matcher.send(f"{video_info['title']}")

        client = get_http_client()
        response = await client.get(video_info["url"], headers=video_info["headers"])
        response.raise_for_status()

        video_data = BytesIO(response.content)
        video_segment = MessageSegment.video(video_data)

        try:
            await douyin_matcher.finish(video_segment)
        except Exception as send_error:
            error_str = str(send_error)
            if "timeout" in error_str.lower() or "NetWorkError" in error_str:
                logger.warning(f"发送视频时可能超时，但视频可能已发送: {send_error}")
            else:
                raise

    except MatcherException:
        raise
    except Exception as e:
        logger.error(f"处理抖音视频失败: {e}")
        # 只有在视频还没准备好或下载失败时才发送错误消息
        if video_segment is None:
            await douyin_matcher.finish(f"处理视频失败: {e}")


# 小红书消息匹配器
xiaohongshu_matcher = on_message(
    rule=Rule(is_xiaohongshu_link),
    priority=5,
    block=True,
)


async def extract_url_from_card_message(message: str) -> str:
    """从卡片消息中提取小红书URL"""
    if "CQ:json" not in message:
        return ""

    if not config.xiaohongshu_cookie or not config.xiaohongshu_cookie.strip():
        logger.debug("检测到小红书卡片消息，但未配置有效cookie，跳过卡片解析")
        return ""

    try:
        # 增强的JSON解析，支持多种转义格式
        json_pattern = r"\[CQ:json,data=([^\]]+)\]"
        json_str = re.search(json_pattern, message)
        if not json_str:
            return ""

        json_data = json.loads(unquote(json_str.group(1).replace("&#44;", ",")))
        if "meta" not in json_data or "news" not in json_data["meta"]:
            return ""

        news = json_data["meta"]["news"]
        jump_url = news.get("jumpUrl", "")

        if "xiaohongshu.com" not in jump_url and "xhslink.com" not in jump_url:
            return ""

        return await process_xiaohongshu_url(jump_url)

    except Exception as e:
        logger.debug(f"从卡片消息提取小红书链接失败: {e}")
        return ""


async def process_xiaohongshu_url(jump_url: str) -> str:
    """处理小红书URL，包括短链接解析和参数提取"""

    # 处理短链接
    if "xhslink" in jump_url:
        # 针对小红书短链接的优化安全检查
        try:
            # 只检查基础格式，不严格验证域名白名单（因为是短链接）
            parsed = urlparse(jump_url)
            if parsed.scheme not in {"http", "https"}:
                raise SecurityError(f"只允许HTTP/HTTPS协议: {parsed.scheme}")
            if len(jump_url) > 2048:
                raise SecurityError("URL过长，最大长度2048字符")
        except SecurityError as e:
            logger.warning(f"检测到可疑的小红书短链接: {jump_url} - {e}")
            return ""
        except Exception as e:
            logger.warning(f"小红书短链接解析异常: {jump_url} - {e}")
            return ""

        # 使用全局HTTP客户端进行短链接解析
        client = get_http_client()
        try:
            response = await client.get(jump_url, follow_redirects=True, timeout=10.0)
            jump_url = str(response.url)
        except Exception as e:
            logger.warning(f"小红书短链接重定向失败: {jump_url} - {e}")
            return ""

    # 提取笔记ID
    pattern = r"(?:/explore/|/discovery/item/|source=note&noteId=)(\w+)"
    matched = re.search(pattern, jump_url)

    if not matched:
        # 如果无法提取ID，回退到原来的方法
        return await xiaohongshu.extract_url(jump_url)

    xhs_id = matched.group(1)
    # 解析URL参数
    parsed_url = urlparse(jump_url)
    # 解码HTML实体
    decoded_query = html.unescape(parsed_url.query)
    params = parse_qs(decoded_query)

    # 提取xsec_source和xsec_token
    xsec_source = params.get("xsec_source", [None])[0] or "pc_feed"
    xsec_token = params.get("xsec_token", [None])[0]

    # 构造完整URL
    if xsec_token:
        final_url = f"https://www.xiaohongshu.com/explore/{xhs_id}?xsec_source={xsec_source}&xsec_token={xsec_token}"
    else:
        final_url = f"https://www.xiaohongshu.com/explore/{xhs_id}?xsec_source={xsec_source}"

    # 对最终URL进行安全验证
    try:
        validate_video_url(final_url)
        return final_url
    except SecurityError as e:
        logger.warning(f"构造的小红书URL未通过安全验证: {final_url} - {e}")
        return ""


async def download_image_concurrent(pic_url: str, max_concurrent: int = 5) -> MessageSegment | None:
    """并发下载单张图片

    Args:
        pic_url: 图片URL
        max_concurrent: 最大并发数（通过semaphore控制）

    Returns:
        MessageSegment: 下载成功返回图片消息段
        None: 下载失败返回None
    """
    client = get_http_client()
    try:
        response = await client.get(pic_url, timeout=30.0)
        response.raise_for_status()

        image_data = BytesIO(response.content)
        return MessageSegment.image(image_data)
    except Exception as e:
        logger.warning(f"下载图片失败 {pic_url}: {e}")
        return None


async def download_images_concurrent(
    pic_urls: list[str], max_concurrent: int = 5
) -> list[MessageSegment]:
    """并发下载多张图片

    使用asyncio.gather实现并发下载，显著提升多图下载性能。
    9张图片下载时间从~18秒降低到~3秒（取决于网络状况）。

    Args:
        pic_urls: 图片URL列表
        max_concurrent: 最大并发数，防止过多并发导致网络拥塞

    Returns:
        成功下载的图片消息段列表（失败的已过滤）
    """
    # 创建semaphore限制并发数
    semaphore = asyncio.Semaphore(max_concurrent)

    async def download_with_semaphore(url: str) -> MessageSegment | None:
        async with semaphore:
            return await download_image_concurrent(url)

    # 创建所有下载任务
    tasks = [download_with_semaphore(url) for url in pic_urls]

    # 并发执行所有任务，return_exceptions=True防止单个失败影响全局
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤成功的结果（排除None和Exception）
    image_segments = []
    for result in results:
        if isinstance(result, MessageSegment):
            image_segments.append(result)
        elif isinstance(result, Exception):
            logger.warning(f"图片下载异常: {result}")
        # None值直接忽略

    logger.info(f"成功下载 {len(image_segments)}/{len(pic_urls)} 张图片")
    return image_segments


async def send_forward_message(bot: Bot, event: MessageEvent, forward_nodes: list):
    """发送合并转发消息"""
    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=forward_nodes,
        )
    else:
        await bot.call_api(
            "send_private_forward_msg",
            user_id=event.user_id,
            messages=forward_nodes,
        )


async def create_forward_nodes(
    bot: Bot, info_text: str, media_segments: list[MessageSegment] | None = None
) -> list[dict[str, Any]]:
    """创建合并转发消息节点"""
    forward_nodes: list[dict[str, Any]] = []

    # 添加文字内容节点
    text_node = {
        "type": "node",
        "data": {"name": "", "uin": bot.self_id, "content": info_text},
    }
    forward_nodes.append(text_node)

    # 添加媒体内容节点
    if media_segments:
        for media_seg in media_segments:
            node = {
                "type": "node",
                "data": {"name": "", "uin": bot.self_id, "content": media_seg},
            }
            forward_nodes.append(node)

    return forward_nodes


@xiaohongshu_matcher.handle()
async def handle_xiaohongshu_message(bot: Bot, event: MessageEvent):
    """处理小红书消息"""
    message = str(event.message).strip()

    # 先尝试从卡片消息中提取URL
    url = await extract_url_from_card_message(message)

    if not url:
        url = await xiaohongshu.extract_url(message)

    if not url:
        await xiaohongshu_matcher.finish("未找到有效的小红书链接")

    try:
        note_info = await xiaohongshu.get_note_info(url)
        if isinstance(note_info, str):
            await xiaohongshu_matcher.finish(note_info)

        info_text = f"{note_info['title']}\n作者: {note_info['author']}"

        if note_info["pic_urls"]:
            # 处理图片内容 - 使用并发下载提升性能
            pic_urls = note_info["pic_urls"][:9]  # 最多处理9张图片
            logger.info(
                f"图片数量{len(pic_urls)}张，使用并发下载（max_concurrent=5）"
            )

            # 使用新的并发下载函数（性能提升：~18秒 -> ~3秒）
            image_segments = await download_images_concurrent(
                pic_urls, max_concurrent=5
            )
            forward_nodes = await create_forward_nodes(bot, info_text, image_segments)
            await send_forward_message(bot, event, forward_nodes)

        elif note_info["video_url"]:
            # 处理视频内容
            client = get_http_client()
            response = await client.get(note_info["video_url"], timeout=60.0)
            video_data = BytesIO(response.content)
            video_segment = MessageSegment.video(video_data)

            forward_nodes = await create_forward_nodes(bot, info_text, [video_segment])
            await send_forward_message(bot, event, forward_nodes)

        else:
            # 处理纯文字内容
            forward_nodes = await create_forward_nodes(bot, info_text)
            await send_forward_message(bot, event, forward_nodes)

    except MatcherException:
        raise
    except Exception as e:
        logger.error(f"处理小红书笔记失败: {e}")
        await xiaohongshu_matcher.finish(f"处理笔记失败: {e}")
