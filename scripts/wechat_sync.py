#!/usr/bin/env python3
"""
微信数据同步脚本
将JSON格式的微信聊天数据转换为Graphiti Episodes并存储到Neo4j
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger
from tqdm import tqdm

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.wechat_processor import WeChatDataProcessor, process_wechat_data
from core.wechat_models import WeChatEpisode, EpisodeGenerationResult
from config.settings import settings


class WeChatSyncScript:
    """微信数据同步脚本主类"""
    
    def __init__(self, data_path: str = None):
        if data_path:
            # 如果提供的是相对路径，基于项目根目录解析
            if not Path(data_path).is_absolute():
                self.data_path = PROJECT_ROOT / data_path
            else:
                self.data_path = Path(data_path)
        else:
            # 使用绝对路径，基于项目根目录 - 微信数据根目录
            self.data_path = PROJECT_ROOT / "local_data" / "wechat"
        
        self.processed_files_path = PROJECT_ROOT / "local_data" / "wechat" / "processed_wechat_files.txt"
        self.processor = WeChatDataProcessor()
        
        # 确保目录存在
        self.data_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"微信数据同步脚本初始化完成，微信数据根目录: {self.data_path}")
        logger.info(f"项目根目录: {PROJECT_ROOT}")
        logger.info(f"绝对数据路径: {self.data_path.absolute()}")
        logger.info(f"目录是否存在: {self.data_path.exists()}")
    
    async def sync_all(self, force: bool = False) -> EpisodeGenerationResult:
        """同步指定文件夹的所有JSON文件"""
        logger.info(f"开始{'强制' if force else '增量'}同步微信数据")
        logger.info(f"处理目录: {self.data_path}")
        
        try:
            # 直接处理指定目录下的JSON文件
            return await self._sync_folder(self.data_path, force)
            
        except Exception as e:
            logger.error(f"同步过程中发生错误: {e}")
            return EpisodeGenerationResult(
                success=False,
                errors=[str(e)]
            )
    
    async def _sync_folder(self, folder_path: Path, force: bool = False) -> EpisodeGenerationResult:
        """同步文件夹中的所有JSON文件"""
        try:
            # 获取文件夹中的所有JSON文件
            json_files = list(folder_path.glob("*.json"))
            logger.info(f"发现 {len(json_files)} 个JSON文件")
            
            if not force:
                # 增量同步：过滤已处理的文件
                processed_files = self._get_processed_files()
                original_count = len(json_files)
                json_files = [f for f in json_files if f.name not in processed_files]
                logger.info(f"过滤后剩余 {len(json_files)} 个未处理文件 (原有 {original_count} 个)")
            
            if not json_files:
                logger.info("没有需要处理的文件")
                return EpisodeGenerationResult(success=True, total_episodes=0)
            
            # 显示即将处理的文件
            logger.info(f"即将处理的文件: {', '.join([f.name for f in json_files])}")
            
            # 初始化Graphiti客户端
            await self.processor.client.initialize()
            
            # 处理指定的文件列表，显示进度条
            with tqdm(total=len(json_files), desc="处理JSON文件", unit="文件") as pbar:
                processed_count = 0
                
                def file_processed_callback(filename: str):
                    """每处理完一个文件的回调函数"""
                    nonlocal processed_count
                    processed_count += 1
                    pbar.update(1)
                    pbar.set_description(f"已处理 {processed_count}/{len(json_files)} 个文件")
                    # 立即记录已处理的文件
                    self._mark_file_processed(filename)
                
                # 处理指定的文件列表
                episodes, processed_files = await self.processor.process_specific_files(json_files, file_processed_callback)
                
                if not episodes:
                    logger.warning("没有Episode需要存储")
                    result = EpisodeGenerationResult(
                        success=True,
                        total_episodes=0,
                        episodes_by_type={},
                        processed_files=processed_files
                    )
                else:
                    # 批量存储到Neo4j
                    logger.info(f"开始存储 {len(episodes)} 个Episode到Neo4j")
                    result = await self.processor.client.add_graphiti_episodes_bulk(episodes)
                    
                    if result.success:
                        logger.info(f"成功存储 {result.total_episodes} 个Episode到Neo4j")
                        result.processed_files = processed_files
                    else:
                        logger.error(f"存储Episode失败: {result.errors}")
                        # 存储失败时，需要从txt文件中移除已记录的文件（因为它们实际没有成功存储）
                        result.processed_files = []
                        logger.warning("因存储失败，需要重新处理这些文件")
            
            # 处理结果
            if result.success:
                logger.info(f"✅ 成功处理 {len(result.processed_files)} 个文件，生成 {result.total_episodes} 个Episode")
            else:
                logger.error(f"❌ 处理失败：{result.errors}")
            
            return result
            
        except Exception as e:
            logger.error(f"处理文件夹失败: {e}")
            return EpisodeGenerationResult(
                success=False,
                errors=[str(e)]
            )
    
    async def validate_files(self) -> Dict[str, Any]:
        """验证JSON文件格式"""
        logger.info("开始验证JSON文件格式")
        
        json_files = list(self.data_path.glob("**/*.json"))
        validation_results = {
            "total_files": len(json_files),
            "valid_files": [],
            "invalid_files": [],
            "errors": []
        }
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 基本格式验证
                if self._validate_json_format(data):
                    validation_results["valid_files"].append(str(json_file))
                    logger.debug(f"文件格式正确: {json_file}")
                else:
                    validation_results["invalid_files"].append(str(json_file))
                    logger.warning(f"文件格式不正确: {json_file}")
                    
            except Exception as e:
                validation_results["invalid_files"].append(str(json_file))
                validation_results["errors"].append(f"{json_file}: {str(e)}")
                logger.error(f"文件验证失败 {json_file}: {e}")
        
        logger.info(f"验证完成：{validation_results['total_files']} 个文件中有 {len(validation_results['valid_files'])} 个格式正确")
        return validation_results
    
    def get_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        json_files = list(self.data_path.glob("**/*.json"))
        processed_files = self._get_processed_files()
        
        status = {
            "data_path": str(self.data_path),
            "total_files": len(json_files),
            "processed_files": len(processed_files),
            "unprocessed_files": len(json_files) - len(processed_files),
            "processed_file_list": list(processed_files),
            "unprocessed_file_list": [str(f) for f in json_files if f.name not in processed_files]
        }
        
        return status
    
    def _get_processed_files(self) -> set:
        """获取已处理的文件列表"""
        if not self.processed_files_path.exists():
            return set()
        
        try:
            with open(self.processed_files_path, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        except Exception as e:
            logger.warning(f"读取已处理文件列表失败: {e}")
            return set()
    
    def _mark_file_processed(self, filename: str):
        """标记单个文件为已处理"""
        try:
            # 检查是否已经记录过
            processed_files = self._get_processed_files()
            if filename not in processed_files:
                with open(self.processed_files_path, 'a', encoding='utf-8') as f:
                    f.write(f"{filename}\n")
                logger.debug(f"标记文件 {filename} 为已处理")
        except Exception as e:
            logger.error(f"标记文件 {filename} 为已处理失败: {e}")
    
    def _mark_files_processed(self, file_paths: List[str]):
        """标记多个文件为已处理"""
        try:
            processed_files = self._get_processed_files()
            new_files = []
            
            for file_path in file_paths:
                # 提取文件名
                filename = Path(file_path).name
                if filename not in processed_files:
                    new_files.append(filename)
            
            if new_files:
                with open(self.processed_files_path, 'a', encoding='utf-8') as f:
                    for filename in new_files:
                        f.write(f"{filename}\n")
                logger.debug(f"标记 {len(new_files)} 个新文件为已处理")
        except Exception as e:
            logger.error(f"标记文件处理状态失败: {e}")
    
    def _validate_json_format(self, data: Any) -> bool:
        """验证JSON格式是否正确"""
        try:
            # 检查是否是列表（聊天消息格式）
            if isinstance(data, list):
                # 验证消息格式
                for message in data:
                    if not isinstance(message, dict):
                        return False
                    if "sender" not in message:
                        return False
                return True
            
            # 检查是否是字典（结构化格式）
            elif isinstance(data, dict):
                # 可以添加更多验证逻辑
                return True
            
            return False
            
        except Exception:
            return False
    
    def _count_episodes_by_type(self, episodes: List[WeChatEpisode]) -> Dict[str, int]:
        """按类型统计Episode数量"""
        counts = {}
        for episode in episodes:
            episode_type = episode.episode_type.value
            counts[episode_type] = counts.get(episode_type, 0) + 1
        return counts
    
    async def cleanup(self):
        """清理资源"""
        await self.processor.close()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="微信数据同步脚本")
    parser.add_argument("command", choices=["sync", "force", "validate", "status"], 
                       help="执行的命令")
    parser.add_argument("--data-path", type=str,
                       help="要处理的数据目录路径，例如: local_data/wechat/group", default="local_data/wechat/person")
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="日志级别")
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level=args.log_level)
    
    # 初始化同步脚本
    sync_script = WeChatSyncScript(args.data_path)
    
    try:
        if args.command == "sync":
            # 增量同步
            result = await sync_script.sync_all(force=False)
            if result.success:
                print(f"✅ 增量同步成功：处理了 {len(result.processed_files)} 个文件，生成 {result.total_episodes} 个Episode")
                if result.episodes_by_type:
                    print("Episode类型分布：")
                    for episode_type, count in result.episodes_by_type.items():
                        print(f"  - {episode_type}: {count}")
            else:
                print(f"❌ 增量同步失败：{result.errors}")
                sys.exit(1)
        
        elif args.command == "force":
            # 强制同步
            result = await sync_script.sync_all(force=True)
            if result.success:
                print(f"✅ 强制同步成功：处理了 {len(result.processed_files)} 个文件，生成 {result.total_episodes} 个Episode")
                if result.episodes_by_type:
                    print("Episode类型分布：")
                    for episode_type, count in result.episodes_by_type.items():
                        print(f"  - {episode_type}: {count}")
            else:
                print(f"❌ 强制同步失败：{result.errors}")
                sys.exit(1)
        
        elif args.command == "validate":
            # 验证文件格式
            validation_results = await sync_script.validate_files()
            print(f"📋 文件格式验证结果：")
            print(f"  总文件数: {validation_results['total_files']}")
            print(f"  有效文件: {len(validation_results['valid_files'])}")
            print(f"  无效文件: {len(validation_results['invalid_files'])}")
            
            if validation_results['invalid_files']:
                print("\n❌ 无效文件列表：")
                for invalid_file in validation_results['invalid_files']:
                    print(f"  - {invalid_file}")
            
            if validation_results['errors']:
                print("\n⚠️  错误详情：")
                for error in validation_results['errors']:
                    print(f"  - {error}")
        
        elif args.command == "status":
            # 查看状态
            status = sync_script.get_status()
            print(f"📊 同步状态：")
            print(f"  数据目录: {status['data_path']}")
            print(f"  总文件数: {status['total_files']}")
            print(f"  已处理文件: {status['processed_files']}")
            print(f"  未处理文件: {status['unprocessed_files']}")
            
            if status['unprocessed_files'] > 0:
                print("\n📝 未处理文件列表：")
                for unprocessed_file in status['unprocessed_file_list']:
                    print(f"  - {unprocessed_file}")
            
            if status['processed_files'] > 0:
                print(f"\n✅ 已处理文件: {status['processed_files']} 个")
    
    except KeyboardInterrupt:
        print("\n⏹️  用户中断操作")
        sys.exit(1)
    except Exception as e:
        logger.error(f"脚本执行失败: {e}")
        print(f"❌ 脚本执行失败: {e}")
        sys.exit(1)
    finally:
        # 清理资源
        await sync_script.cleanup()


if __name__ == "__main__":
    asyncio.run(main())