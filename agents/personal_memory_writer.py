"""
个人关系记忆写入器
记录用户（陈宇函）与他人、事物的关系信息
通过source_description提供上下文，让Graphiti自然理解主体
"""

import hashlib
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from loguru import logger

from graphiti_core.nodes import EpisodeType
from core.wechat_graphiti_client import WeChatGraphitiClient


class PersonalMemoryWriter:
    """个人关系记忆写入器"""

    def __init__(self, user_name: str = "陈宇函", user_alias: str = "肥猫"):
        """
        初始化写入器

        Args:
            user_name: 用户真实姓名（可从配置读取）
            user_alias: 用户别名（可从配置读取）
        """
        self.client = WeChatGraphitiClient()
        self.user_name = user_name
        self.user_alias = user_alias
        self._initialized = False

    async def initialize(self):
        """初始化写入器"""
        if not self._initialized:
            await self.client.initialize()
            self._initialized = True
            logger.info(f"PersonalMemoryWriter initialized for {self.user_name} ({self.user_alias})")

    async def close(self):
        """关闭写入器"""
        if self._initialized:
            await self.client.close()
            self._initialized = False
            logger.info("PersonalMemoryWriter closed")

    def _generate_memory_id(self, content: str) -> str:
        """
        生成记忆唯一ID

        Args:
            content: 记忆内容

        Returns:
            str: MD5哈希ID
        """
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    async def write_memory(
        self,
        content: str,
        memory_type: str = "relationship",
        source: str = "llm_conversation"
    ) -> Dict[str, Any]:
        """
        写入单条记忆到Graphiti

        Args:
            content: 记忆内容（保持用户原始输入，可以包含"我"）
            memory_type: relationship|preference|event|fact
            source: 来源描述

        Returns:
            {"success": bool, "message": str, "memory_id": str}
        """
        try:
            if not self._initialized:
                await self.initialize()

            # 验证内容
            if not content or not content.strip():
                return {
                    "success": False,
                    "message": "记忆内容不能为空"
                }

            # 生成唯一ID
            memory_id = self._generate_memory_id(content)

            # 构建source_description，提供用户上下文
            # Graphiti会通过这个上下文理解"我"指的是谁
            source_desc = f"Personal {memory_type} from {self.user_name} ({self.user_alias}) via {source}"

            # 使用Graphiti存储（内容保持原样，不修改）
            await self.client.graphiti.add_episode(
                name=f"Personal {memory_type.capitalize()}",
                episode_body=content,  # 保持原始内容
                source_description=source_desc,  # 上下文在这里
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,  # 使用枚举类型
                group_id="personal_memories"  # 新的group_id
            )

            logger.info(f"✅ 成功写入个人记忆 [{memory_type}]: {content[:50]}...")

            return {
                "success": True,
                "message": "记忆已成功存入知识图谱",
                "memory_id": memory_id
            }

        except Exception as e:
            logger.error(f"❌ 写入记忆失败: {e}")
            return {
                "success": False,
                "message": f"写入失败: {str(e)}"
            }


# 全局实例
_writer: Optional[PersonalMemoryWriter] = None


async def write_personal_memory(
    content: str,
    memory_type: str = "relationship",
    source: str = "chat"
) -> Dict[str, Any]:
    """
    全局函数：写入个人记忆

    Args:
        content: 记忆内容
        memory_type: relationship|preference|event|fact
        source: 来源描述

    Returns:
        写入结果字典
    """
    global _writer

    if _writer is None:
        _writer = PersonalMemoryWriter()
        await _writer.initialize()

    return await _writer.write_memory(content, memory_type, source)


async def close_writer():
    """关闭写入器"""
    global _writer
    if _writer:
        await _writer.close()
        _writer = None