#!/usr/bin/env python3
"""
Health Check Script
Comprehensive health check for all system components.
"""

import asyncio
import sys
from datetime import datetime
from typing import Dict, Any, List
from loguru import logger

from config.settings import get_settings
from config.logging import setup_logging
from core.graphiti_client import GraphitiClient
from core.notion_client import NotionExtractor
from utils.embedding_utils import get_embedding_service


class HealthChecker:
    """
    Comprehensive health checker for all system components.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.results = {}
        
    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks."""
        logger.info("Starting comprehensive health check...")
        
        checks = [
            ("Configuration", self.check_configuration),
            ("Neo4j Database", self.check_neo4j),
            ("Notion API", self.check_notion_api),
            ("Embedding Service", self.check_embedding_service),
            ("Graph Data Integrity", self.check_graph_integrity),
            ("System Resources", self.check_system_resources),
        ]
        
        for check_name, check_func in checks:
            try:
                logger.info(f"Running {check_name} check...")
                result = await check_func()
                self.results[check_name] = result
                
                status = "" if result["healthy"] else ""
                logger.info(f"{status} {check_name}: {result['message']}")
                
            except Exception as e:
                logger.exception(f"Error in {check_name} check: {e}")
                self.results[check_name] = {
                    "healthy": False,
                    "message": f"Check failed with exception: {str(e)}",
                    "error": str(e)
                }
        
        # Overall health assessment
        overall_healthy = all(result["healthy"] for result in self.results.values())
        
        self.results["overall"] = {
            "healthy": overall_healthy,
            "timestamp": datetime.now().isoformat(),
            "total_checks": len(checks),
            "passed_checks": sum(1 for r in self.results.values() if r["healthy"]),
            "failed_checks": sum(1 for r in self.results.values() if not r["healthy"])
        }
        
        return self.results
    
    async def check_configuration(self) -> Dict[str, Any]:
        """Check configuration settings."""
        try:
            issues = []
            
            # Check required settings
            if not self.settings.notion_token:
                issues.append("Notion token not set")
            
            if not self.settings.neo4j_password:
                issues.append("Neo4j password not set")
            
            if not self.settings.gemini_api_key:
                issues.append("Gemini API key not set")
            
            # Check URLs
            if not self.settings.neo4j_uri.startswith(("neo4j://", "bolt://")):
                issues.append("Invalid Neo4j URI format")
            
            # Check numeric settings
            if self.settings.sync_interval_minutes < 1:
                issues.append("Sync interval too low")
            
            if self.settings.notion_rate_limit_per_second < 1:
                issues.append("Rate limit too low")
            
            healthy = len(issues) == 0
            message = "Configuration valid" if healthy else f"Issues found: {', '.join(issues)}"
            
            return {
                "healthy": healthy,
                "message": message,
                "issues": issues,
                "settings_checked": [
                    "notion_token", "neo4j_password", "gemini_api_key",
                    "neo4j_uri", "sync_interval_minutes", "notion_rate_limit_per_second"
                ]
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Configuration check failed: {str(e)}",
                "error": str(e)
            }
    
    async def check_neo4j(self) -> Dict[str, Any]:
        """Check Neo4j database connectivity and status."""
        graph_client = None
        try:
            graph_client = GraphitiClient(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_username,
                neo4j_password=self.settings.neo4j_password
            )
            
            await graph_client.initialize()
            
            # Test basic connectivity
            query = "RETURN 1 as test"
            result = await graph_client._graphiti.driver.execute_query(query)
            
            if not result.records:
                return {
                    "healthy": False,
                    "message": "Neo4j connection failed - no response"
                }
            
            # Check database info
            db_info_query = "CALL dbms.components()"
            db_info = await graph_client._graphiti.driver.execute_query(db_info_query)
            
            # Check constraints and indices
            constraints_query = "SHOW CONSTRAINTS"
            constraints = await graph_client._graphiti.driver.execute_query(constraints_query)
            
            indices_query = "SHOW INDEXES"
            indices = await graph_client._graphiti.driver.execute_query(indices_query)
            
            # Check data counts
            stats = await graph_client.get_graph_stats()
            
            return {
                "healthy": True,
                "message": f"Neo4j connected - {stats.total_pages} pages, {stats.total_relationships} relationships",
                "database_info": {
                    "components": len(db_info.records),
                    "constraints": len(constraints.records),
                    "indices": len(indices.records),
                    "pages": stats.total_pages,
                    "relationships": stats.total_relationships
                }
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Neo4j check failed: {str(e)}",
                "error": str(e)
            }
        finally:
            if graph_client:
                await graph_client.close()
    
    async def check_notion_api(self) -> Dict[str, Any]:
        """Check Notion API connectivity and permissions."""
        try:
            notion_client = NotionExtractor(
                api_key=self.settings.notion_token,
                rate_limit_per_second=self.settings.notion_rate_limit_per_second
            )
            
            # Test basic connectivity
            healthy = await notion_client.health_check()
            
            if not healthy:
                return {
                    "healthy": False,
                    "message": "Notion API health check failed"
                }
            
            # Test permissions by trying to search
            try:
                # Get a small sample of pages to test read permissions
                pages = await notion_client.get_all_pages_metadata()
                page_count = len(pages[:5])  # Just check first 5 for speed
                
                # Test database access
                databases = await notion_client.get_databases()
                db_count = len(databases)
                
                return {
                    "healthy": True,
                    "message": f"Notion API connected - access to {page_count} pages, {db_count} databases",
                    "api_info": {
                        "pages_accessible": page_count > 0,
                        "databases_accessible": db_count > 0,
                        "sample_page_count": page_count,
                        "database_count": db_count
                    }
                }
                
            except Exception as e:
                return {
                    "healthy": False,
                    "message": f"Notion API permission error: {str(e)}",
                    "error": str(e)
                }
                
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Notion API check failed: {str(e)}",
                "error": str(e)
            }
    
    async def check_embedding_service(self) -> Dict[str, Any]:
        """Check embedding service (Gemini) connectivity."""
        try:
            embedding_service = get_embedding_service()
            
            # Test health check
            healthy = await embedding_service.health_check()
            
            if not healthy:
                return {
                    "healthy": False,
                    "message": "Embedding service health check failed"
                }
            
            # Test embedding generation
            test_embedding = await embedding_service.generate_embedding("test embedding")
            
            if not test_embedding:
                return {
                    "healthy": False,
                    "message": "Failed to generate test embedding"
                }
            
            # Verify embedding properties
            expected_dim = self.settings.gemini_dimension
            actual_dim = len(test_embedding)
            
            if actual_dim != expected_dim:
                return {
                    "healthy": False,
                    "message": f"Embedding dimension mismatch: expected {expected_dim}, got {actual_dim}"
                }
            
            return {
                "healthy": True,
                "message": f"Embedding service connected - {actual_dim}D vectors",
                "embedding_info": {
                    "model": self.settings.gemini_model,
                    "dimension": actual_dim,
                    "test_embedding_generated": True
                }
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Embedding service check failed: {str(e)}",
                "error": str(e)
            }
    
    async def check_graph_integrity(self) -> Dict[str, Any]:
        """Check graph data integrity."""
        graph_client = None
        try:
            graph_client = GraphitiClient(
                neo4j_uri=self.settings.neo4j_uri,
                neo4j_user=self.settings.neo4j_username,
                neo4j_password=self.settings.neo4j_password
            )
            
            await graph_client.initialize()
            
            # Get integrity validation from the graph updater
            from sync_service.graph_updater import GraphUpdater
            from core.notion_client import NotionExtractor
            
            notion_client = NotionExtractor(
                api_key=self.settings.notion_token,
                rate_limit_per_second=self.settings.notion_rate_limit_per_second
            )
            
            updater = GraphUpdater(graph_client, notion_client)
            validation = await updater.validate_graph_integrity()
            
            if "error" in validation:
                return {
                    "healthy": False,
                    "message": f"Graph integrity check failed: {validation['error']}",
                    "error": validation["error"]
                }
            
            is_valid = validation.get("is_valid", False)
            issues = []
            
            if validation.get("orphaned_pages", 0) > 0:
                issues.append(f"{validation['orphaned_pages']} orphaned pages")
            
            if validation.get("broken_relationships", 0) > 0:
                issues.append(f"{validation['broken_relationships']} broken relationships")
            
            if validation.get("duplicate_pages", 0) > 0:
                issues.append(f"{validation['duplicate_pages']} duplicate pages")
            
            message = "Graph integrity validated" if is_valid else f"Issues found: {', '.join(issues)}"
            
            return {
                "healthy": is_valid,
                "message": message,
                "integrity_info": validation
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Graph integrity check failed: {str(e)}",
                "error": str(e)
            }
        finally:
            if graph_client:
                await graph_client.close()
    
    async def check_system_resources(self) -> Dict[str, Any]:
        """Check system resources and dependencies."""
        try:
            import psutil
            import os
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_usage = (disk.used / disk.total) * 100
            
            # CPU usage (average over 1 second)
            cpu_usage = psutil.cpu_percent(interval=1)
            
            # Check log directory
            log_dir = os.path.dirname(self.settings.log_file_path)
            log_dir_exists = os.path.exists(log_dir)
            
            issues = []
            if memory_usage > 90:
                issues.append(f"High memory usage: {memory_usage:.1f}%")
            
            if disk_usage > 90:
                issues.append(f"High disk usage: {disk_usage:.1f}%")
            
            if cpu_usage > 90:
                issues.append(f"High CPU usage: {cpu_usage:.1f}%")
            
            if not log_dir_exists:
                issues.append("Log directory does not exist")
            
            healthy = len(issues) == 0
            message = "System resources normal" if healthy else f"Issues: {', '.join(issues)}"
            
            return {
                "healthy": healthy,
                "message": message,
                "resource_info": {
                    "memory_usage_percent": memory_usage,
                    "disk_usage_percent": disk_usage,
                    "cpu_usage_percent": cpu_usage,
                    "log_directory_exists": log_dir_exists,
                    "total_memory_gb": round(memory.total / (1024**3), 2),
                    "available_memory_gb": round(memory.available / (1024**3), 2)
                },
                "issues": issues
            }
            
        except ImportError:
            return {
                "healthy": True,
                "message": "System resource monitoring not available (psutil not installed)",
                "resource_info": {"monitoring_available": False}
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": f"System resource check failed: {str(e)}",
                "error": str(e)
            }


def format_results(results: Dict[str, Any]) -> str:
    """Format health check results for display."""
    output = []
    output.append("=" * 60)
    output.append("CHIMERA HEALTH CHECK REPORT")
    output.append("=" * 60)
    
    overall = results.get("overall", {})
    timestamp = overall.get("timestamp", "Unknown")
    output.append(f"Timestamp: {timestamp}")
    output.append(f"Overall Status: {' HEALTHY' if overall.get('healthy') else ' UNHEALTHY'}")
    output.append(f"Checks: {overall.get('passed_checks', 0)}/{overall.get('total_checks', 0)} passed")
    output.append("")
    
    for check_name, result in results.items():
        if check_name == "overall":
            continue
            
        status = "" if result["healthy"] else ""
        output.append(f"{status} {check_name}")
        output.append(f"   {result['message']}")
        
        if "issues" in result and result["issues"]:
            output.append(f"   Issues: {', '.join(result['issues'])}")
        
        output.append("")
    
    return "\n".join(output)


async def main():
    """Main entry point."""
    setup_logging()
    
    import argparse
    parser = argparse.ArgumentParser(description="Health check script")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--check", choices=["config", "neo4j", "notion", "embedding", "integrity", "resources"], 
                       help="Run specific check only")
    
    args = parser.parse_args()
    
    health_checker = HealthChecker()
    
    try:
        if args.check:
            # Run specific check
            check_methods = {
                "config": health_checker.check_configuration,
                "neo4j": health_checker.check_neo4j,
                "notion": health_checker.check_notion_api,
                "embedding": health_checker.check_embedding_service,
                "integrity": health_checker.check_graph_integrity,
                "resources": health_checker.check_system_resources
            }
            
            result = await check_methods[args.check]()
            
            if args.json:
                import json
                print(json.dumps({args.check: result}, indent=2))
            else:
                status = "" if result["healthy"] else ""
                print(f"{status} {args.check.title()}: {result['message']}")
            
            sys.exit(0 if result["healthy"] else 1)
        else:
            # Run all checks
            results = await health_checker.run_all_checks()
            
            if args.json:
                import json
                print(json.dumps(results, indent=2))
            else:
                print(format_results(results))
            
            overall_healthy = results.get("overall", {}).get("healthy", False)
            sys.exit(0 if overall_healthy else 1)
            
    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())