"""
Deep Research Multi-Agent System

基于Director-Worker架构的深度研究系统：
- Director: 总控智能体，负责子图采集、主题分簇、Worker调度、结果合并
- Worker: 工蜂智能体，负责簇内深挖、摘要、评分

核心特性：
- 固定参数：depth=3, max_workers=6
- 智能参数：max_pages(5-20), research_complexity
- KV Cache优化：稳定前缀 + 追加式设计
- 并发处理：6个Worker固定架构
"""

from .director import ContextEngineeringDirector
from .worker import OptimizedWorker

__all__ = [
    "ContextEngineeringDirector",
    "OptimizedWorker"
]

__version__ = "1.0.0"