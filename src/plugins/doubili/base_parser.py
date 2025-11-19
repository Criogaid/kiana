"""
视频解析器基类模块

提供统一的接口和数据结构，用于不同视频平台的解析器实现。
遵循NoneBot2插件架构最佳实践，使用抽象基类定义标准接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO

from httpx import AsyncClient
from nonebot import logger

# 类型别名定义（Python 3.12+ 使用 type 关键字）
type MediaType = str  # "video" 或 "images"
type ParseResultType = "ParseResult | str"  # 成功返回ParseResult，失败返回错误字符串


@dataclass
class ParseResult:
    """统一的视频/图片解析结果数据结构

    属性:
        title: 媒体标题或描述
        author: 作者/UP主名称
        media_urls: 媒体URL列表（视频为单元素列表，图片为多元素列表）
        media_type: 媒体类型 ("video" 或 "images")
        cover_url: 封面图URL（可选）
    """

    title: str
    author: str
    media_urls: list[str]
    media_type: MediaType
    cover_url: str = ""


class BaseVideoParser(ABC):
    """视频解析器抽象基类

    所有平台解析器（B站、抖音、小红书）都应继承此类，并实现抽象方法。
    提供统一的接口和公共工具方法，遵循依赖倒置原则。

    设计原则：
    - 单一职责：每个解析器只负责一个平台的解析
    - 接口隔离：通过抽象方法强制实现必要的接口
    - 依赖倒置：高层模块依赖抽象，不依赖具体实现
    """

    def __init__(self, client: AsyncClient):
        """初始化解析器

        Args:
            client: 共享的HTTP客户端实例，用于复用连接池
        """
        self.client = client
        self.headers: dict[str, str] = {}
        self._setup_headers()

    def _setup_headers(self) -> None:
        """设置默认请求头

        子类可以重写此方法设置平台特定的请求头
        """
        self.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    @abstractmethod
    async def extract_id(self, message: str) -> str:
        """从消息文本中提取视频/笔记ID

        Args:
            message: 用户发送的完整消息文本

        Returns:
            提取到的ID字符串，如果提取失败返回空字符串
        """
        pass

    @abstractmethod
    async def parse(self, video_id: str) -> ParseResultType:
        """解析视频/笔记信息

        Args:
            video_id: 从extract_id获取的视频/笔记ID

        Returns:
            ParseResult: 解析成功返回ParseResult对象
            str: 解析失败返回错误信息字符串
        """
        pass

    async def download_media(self, url: str, timeout: float = 30.0) -> BytesIO | None:
        """下载媒体内容（视频或图片）

        Args:
            url: 媒体URL
            timeout: 下载超时时间（秒）

        Returns:
            BytesIO: 下载成功返回BytesIO对象
            None: 下载失败返回None
        """
        try:
            response = await self.client.get(url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
            return BytesIO(response.content)
        except Exception as e:
            logger.warning(f"下载媒体失败 {url}: {e}")
            return None

    async def get_redirect_url(self, url: str) -> str:
        """获取重定向后的最终URL

        Args:
            url: 原始URL（可能是短链接）

        Returns:
            重定向后的最终URL
        """
        try:
            response = await self.client.get(url, headers=self.headers, follow_redirects=True)
            return str(response.url)
        except Exception as e:
            logger.warning(f"获取重定向URL失败 {url}: {e}")
            return url
