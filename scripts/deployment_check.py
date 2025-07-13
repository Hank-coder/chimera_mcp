#!/usr/bin/env python3
"""
Deployment Readiness Check
Final verification that the system is ready for deployment.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_deployment_readiness():
    """Check if the system is ready for deployment."""
    print("🚀 Project Chimera - Deployment Readiness Check")
    print("=" * 60)
    
    checks = []
    
    # 1. Project Structure
    print("📁 Checking project structure...")
    required_dirs = ["config", "core", "sync_service", "mcp_server", "utils", "scripts", "tests"]
    missing_dirs = [d for d in required_dirs if not (project_root / d).exists()]
    
    if not missing_dirs:
        checks.append(("Project Structure", True, "All directories present"))
    else:
        checks.append(("Project Structure", False, f"Missing: {missing_dirs}"))
    
    # 2. Core Files
    print("📄 Checking core files...")
    critical_files = [
        "pyproject.toml", "README.md", ".env.example", 
        "core/models.py", "core/notion_client.py",
        "config/settings.py", "utils/embedding_utils.py"
    ]
    missing_files = [f for f in critical_files if not (project_root / f).exists()]
    
    if not missing_files:
        checks.append(("Core Files", True, "All critical files present"))
    else:
        checks.append(("Core Files", False, f"Missing: {missing_files}"))
    
    # 3. Configuration
    print("⚙️  Checking configuration...")
    try:
        from config.settings import get_settings
        settings = get_settings()
        
        # Check critical settings
        critical_settings = [
            ("App Name", settings.app_name == "personal-ai-memory"),
            ("App Version", settings.app_version == "0.1.0"),
            ("Python Version", "3.11" in str(settings)),
            ("Gemini Model", settings.gemini_model == "models/text-embedding-004"),
            ("Embedding Dimension", settings.embedding_dimension == 768)
        ]
        
        config_issues = [name for name, valid in critical_settings if not valid]
        
        if not config_issues:
            checks.append(("Configuration", True, "All settings valid"))
        else:
            checks.append(("Configuration", False, f"Issues: {config_issues}"))
            
    except Exception as e:
        checks.append(("Configuration", False, f"Error: {e}"))
    
    # 4. Dependencies
    print("📦 Checking dependencies...")
    try:
        # Test critical imports
        from core.models import NotionPageMetadata
        from core.notion_client import NotionExtractor
        from utils.embedding_utils import EmbeddingService
        from sync_service.main import SyncService
        from mcp_server.server import ChimeraMCPServer
        
        checks.append(("Dependencies", True, "All critical imports successful"))
        
    except Exception as e:
        checks.append(("Dependencies", False, f"Import error: {e}"))
    
    # 5. Data Models
    print("🗂️  Checking data models...")
    try:
        from core.models import NotionPageMetadata, NodeType
        from datetime import datetime
        
        # Test model creation
        page = NotionPageMetadata(
            notion_id="test",
            title="Test",
            type=NodeType.PAGE,
            last_edited_time=datetime.now(),
            url="https://test.com"
        )
        
        checks.append(("Data Models", True, "Model creation successful"))
        
    except Exception as e:
        checks.append(("Data Models", False, f"Model error: {e}"))
    
    # 6. Embedding System
    print("🧠 Checking embedding system...")
    try:
        from utils.embedding_utils import EmbeddingService
        
        service = EmbeddingService()
        similarity = service.calculate_similarity([1, 0, 0], [1, 0, 0])
        
        if similarity == 1.0:
            checks.append(("Embedding System", True, "Similarity calculation working"))
        else:
            checks.append(("Embedding System", False, f"Unexpected similarity: {similarity}"))
            
    except Exception as e:
        checks.append(("Embedding System", False, f"Embedding error: {e}"))
    
    # 7. API Credentials
    print("🔑 Checking API configuration...")
    try:
        from config.settings import get_settings
        settings = get_settings()
        
        credentials_status = []
        if settings.notion_token and len(settings.notion_token) > 10:
            credentials_status.append("Notion ✓")
        else:
            credentials_status.append("Notion ✗")
            
        if settings.gemini_api_key and len(settings.gemini_api_key) > 10:
            credentials_status.append("Gemini ✓")
        else:
            credentials_status.append("Gemini ✗")
            
        if settings.neo4j_password and len(settings.neo4j_password) > 3:
            credentials_status.append("Neo4j ✓")
        else:
            credentials_status.append("Neo4j ✗")
        
        all_good = all("✓" in status for status in credentials_status)
        checks.append(("API Credentials", all_good, " | ".join(credentials_status)))
        
    except Exception as e:
        checks.append(("API Credentials", False, f"Credential check error: {e}"))
    
    # Print Results
    print("\n" + "=" * 60)
    print("DEPLOYMENT READINESS RESULTS")
    print("=" * 60)
    
    passed = 0
    total = len(checks)
    
    for check_name, success, message in checks:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {check_name}: {message}")
        if success:
            passed += 1
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{total} checks passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 SYSTEM IS READY FOR DEPLOYMENT!")
        print("\nNext steps:")
        print("1. Copy .env.example to .env and update with your credentials")
        print("2. Start Neo4j database")
        print("3. Run: python scripts/setup_database.py")
        print("4. Run: python scripts/health_check.py")
        print("5. Start services:")
        print("   - Sync: python -m sync_service.main")
        print("   - MCP: python -m mcp_server.server")
        return True
    else:
        print(f"\n⚠️  {total - passed} ISSUES FOUND - Please fix before deployment")
        return False


def show_system_info():
    """Show system information."""
    print("\n" + "=" * 60)
    print("SYSTEM INFORMATION")
    print("=" * 60)
    
    try:
        from config.settings import get_settings
        settings = get_settings()
        
        print(f"Project: {settings.app_name}")
        print(f"Version: {settings.app_version}")
        print(f"Python: >=3.11")
        print(f"Environment: {settings.app_environment}")
        print(f"Package Manager: UV")
        
        print(f"\nComponents:")
        print(f"  🗄️  Graph Database: Neo4j")
        print(f"  📝 Content Source: Notion API")
        print(f"  🧠 Embeddings: Google Gemini ({settings.gemini_model})")
        print(f"  🔌 API Protocol: MCP (Model Context Protocol)")
        print(f"  📊 Data Validation: Pydantic")
        print(f"  📋 Logging: Loguru")
        
        print(f"\nServices:")
        print(f"  📚 The Archivist (Sync Service)")
        print(f"     - Interval: {settings.sync_interval_minutes} minutes")
        print(f"     - Rate limit: {settings.notion_rate_limit_per_second} req/sec")
        print(f"  🧭 The Navigator (MCP Server)")
        print(f"     - Host: {settings.mcp_server_host}")
        print(f"     - Port: {settings.mcp_server_port}")
        
        print(f"\nGraph Configuration:")
        print(f"  📏 Embedding dimension: {settings.embedding_dimension}")
        print(f"  📊 Max depth: {settings.graph_max_depth}")
        print(f"  📈 Max results: {settings.graph_max_results}")
        print(f"  🎯 Similarity threshold: {settings.similarity_threshold}")
        
    except Exception as e:
        print(f"Error displaying system info: {e}")


def main():
    """Main entry point."""
    try:
        success = check_deployment_readiness()
        show_system_info()
        
        print("\n" + "=" * 60)
        print("Project Chimera - Personal AI Memory System")
        print("让AI真正理解您的知识，成为您思维的延伸")
        print("=" * 60)
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"❌ Deployment check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()