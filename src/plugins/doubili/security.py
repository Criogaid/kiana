"""
安全防护模块

提供URL验证、输入检查等安全功能，防止SSRF攻击和其他安全威胁。
遵循Python安全开发最佳实践。
"""

import ipaddress
import re
from urllib.parse import urlparse

from nonebot import logger

# 允许的视频平台域名白名单
ALLOWED_DOMAINS = {
    # 主域名
    "bilibili.com",
    "douyin.com",
    "xiaohongshu.com",
    # 短链接域名
    "b23.tv",
    "bili2233.cn",
    "iesdouyin.com",
    "xhslink.com",
    # 移动域名
    "m.bilibili.com",
    "m.douyin.com",
    "www.xiaohongshu.com",
}

# 内网IP段（需要阻止）
PRIVATE_IP_RANGES = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),  # Link-local
]

# 危险协议黑名单
DANGEROUS_PROTOCOLS = {
    "file://",
    "ftp://",
    "ssh://",
    "telnet://",
    "ldap://",
    "dict://",
    "gopher://",
}


class SecurityError(Exception):
    """安全验证错误"""
    pass


def validate_video_url(url: str) -> bool:
    """验证视频URL的安全性

    检查点：
    1. 协议安全性（只允许http/https）
    2. 域名白名单验证
    3. 内网IP和私有域名防护
    4. 危险协议阻止
    5. URL长度限制

    Args:
        url: 待验证的URL

    Returns:
        bool: True表示安全，False表示存在风险

    Raises:
        SecurityError: 详细的安全错误信息
    """
    if not url:
        raise SecurityError("URL不能为空")

    # URL长度检查（防止DoS）
    if len(url) > 2048:
        raise SecurityError("URL过长，最大长度2048字符")

    # 危险协议检查
    for protocol in DANGEROUS_PROTOCOLS:
        if url.lower().startswith(protocol):
            raise SecurityError(f"不允许使用危险协议: {protocol}")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SecurityError(f"URL解析失败: {e}")

    # 协议检查
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError(f"只允许HTTP/HTTPS协议，当前协议: {parsed.scheme}")

    # 域名检查
    hostname = parsed.hostname
    if not hostname:
        raise SecurityError("无法解析主机名")

    # 检查是否在白名单中
    if hostname not in ALLOWED_DOMAINS:
        # 检查是否是子域名
        is_valid_subdomain = False
        for allowed_domain in ALLOWED_DOMAINS:
            if hostname == allowed_domain or hostname.endswith(f".{allowed_domain}"):
                is_valid_subdomain = True
                break

        if not is_valid_subdomain:
            raise SecurityError(f"域名不在白名单中: {hostname}")

    # IP地址检查（防止IP形式的URL）
    try:
        # 检查是否是IP地址
        ipaddress.ip_address(hostname)
        # 如果是IP地址，直接拒绝
        raise SecurityError(f"不允许使用IP地址: {hostname}")
    except ValueError:
        # 不是IP地址，继续检查
        pass

    # 端口检查（只允许标准端口）
    if parsed.port and parsed.port not in {80, 443}:
        raise SecurityError(f"不允许使用非标准端口: {parsed.port}")

    logger.debug(f"URL安全验证通过: {url}")
    return True


def is_internal_ip(hostname: str) -> bool:
    """检查主机名是否解析为内网IP

    Args:
        hostname: 主机名或IP地址

    Returns:
        bool: True表示是内网IP
    """
    try:
        # 如果是IP地址，直接检查
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # 如果是域名，需要解析（这里简化处理，实际应该DNS解析）
        # 对于视频平台，我们假设不会解析到内网IP
        return False

    # 检查是否是内网IP段
    for private_range in PRIVATE_IP_RANGES:
        if ip in private_range:
            return True

    return False


def sanitize_error_message(error: str, max_length: int = 200) -> str:
    """清理错误信息，防止泄露敏感信息

    Args:
        error: 原始错误信息
        max_length: 最大长度限制

    Returns:
        清理后的错误信息
    """
    if not error:
        return "未知错误"

    # 移除可能包含的敏感信息
    sanitized = str(error)

    # 移除文件路径（防止泄露系统信息）
    sanitized = re.sub(r"/[^\s]+/[^\s]+", "[PATH]", sanitized)

    # 移除IP地址
    sanitized = re.sub(r"\d+\.\d+\.\d+\.\d+", "[IP]", sanitized)

    # 移除URL中的具体路径（保留域名）
    sanitized = re.sub(r"https?://[^/]+/[^\s]*", "[URL]", sanitized)

    # 长度限制
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    return sanitized


def validate_video_id_format(video_id: str, platform: str) -> bool:
    """验证视频ID格式

    Args:
        video_id: 视频ID
        platform: 平台名称（bilibili/douyin/xiaohongshu）

    Returns:
        bool: 格式是否有效
    """
    if not video_id:
        return False

    if len(video_id) > 50:  # 合理的ID长度限制
        return False

    # 平台特定的格式验证
    if platform == "bilibili":
        # BV号或av号
        return bool(re.match(r"^(BV[1-9a-zA-Z]{10}|av\d{6,})$", video_id))

    elif platform == "douyin":
        # 抖音视频ID（通常是数字）
        return bool(re.match(r"^\d{10,20}$", video_id))

    elif platform == "xiaohongshu":
        # 小红书笔记ID（通常是字母数字组合）
        return bool(re.match(r"^[a-zA-Z0-9]{10,30}$", video_id))

    return True  # 未知平台，不严格验证


def check_link_safety(url: str) -> dict:
    """全面的链接安全检查

    Args:
        url: 待检查的URL

    Returns:
        dict: 检查结果，包含安全性和详细信息
    """
    result = {"safe": False, "reasons": [], "warnings": []}

    try:
        validate_video_url(url)
        result["safe"] = True
        result["reasons"].append("通过所有安全检查")
    except SecurityError as e:
        result["reasons"].append(str(e))
    except Exception as e:
        result["reasons"].append(f"安全检查异常: {e}")

    # 额外的安全建议
    if result["safe"]:
        result["warnings"].append("请确保URL来源可信")
        result["warnings"].append("避免点击不明链接")

    return result
