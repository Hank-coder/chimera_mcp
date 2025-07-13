#!/usr/bin/env python3
"""
Database Setup Script
Initializes the Neo4j database with necessary constraints and indices.
"""

import asyncio
import sys
from loguru import logger

from config.settings import get_settings
from config.logging import setup_logging
from core.graphiti_client import GraphitiClient


async def setup_database():
    """
    Set up the Neo4j database with necessary constraints and indices.
    """
    logger.info("Setting up database...")
    
    settings = get_settings()
    
    # Initialize graph client
    graph_client = GraphitiClient(
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_username,
        neo4j_password=settings.neo4j_password
    )
    
    try:
        await graph_client.initialize()
        
        # Create constraints and indices
        await create_constraints(graph_client)
        await create_indices(graph_client)
        
        logger.info("Database setup completed successfully")
        
    except Exception as e:
        logger.exception(f"Database setup failed: {e}")
        raise
    finally:
        await graph_client.close()


async def create_constraints(graph_client: GraphitiClient):
    """Create database constraints."""
    logger.info("Creating database constraints...")
    
    constraints = [
        # Unique constraint on NotionPage.notion_id
        "CREATE CONSTRAINT notion_page_id_unique IF NOT EXISTS FOR (p:NotionPage) REQUIRE p.notion_id IS UNIQUE",
        
        # Unique constraint on Tag.name
        "CREATE CONSTRAINT tag_name_unique IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE",
        
        # Existence constraints
        "CREATE CONSTRAINT notion_page_id_exists IF NOT EXISTS FOR (p:NotionPage) REQUIRE p.notion_id IS NOT NULL",
        "CREATE CONSTRAINT notion_page_title_exists IF NOT EXISTS FOR (p:NotionPage) REQUIRE p.title IS NOT NULL",
        "CREATE CONSTRAINT tag_name_exists IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS NOT NULL",
    ]
    
    for constraint in constraints:
        try:
            await graph_client._graphiti.driver.execute_query(constraint)
            logger.info(f"Created constraint: {constraint.split(' ')[2]}")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent constraint already exists" in str(e).lower():
                logger.info(f"Constraint already exists: {constraint.split(' ')[2]}")
            else:
                logger.warning(f"Failed to create constraint: {e}")


async def create_indices(graph_client: GraphitiClient):
    """Create database indices for performance."""
    logger.info("Creating database indices...")
    
    indices = [
        # Index on NotionPage properties
        "CREATE INDEX notion_page_title_index IF NOT EXISTS FOR (p:NotionPage) ON (p.title)",
        "CREATE INDEX notion_page_type_index IF NOT EXISTS FOR (p:NotionPage) ON (p.type)",
        "CREATE INDEX notion_page_last_edited_index IF NOT EXISTS FOR (p:NotionPage) ON (p.last_edited_time)",
        "CREATE INDEX notion_page_parent_index IF NOT EXISTS FOR (p:NotionPage) ON (p.parent_id)",
        
        # Index on Tag properties
        "CREATE INDEX tag_name_index IF NOT EXISTS FOR (t:Tag) ON (t.name)",
        
        # Composite indices for common queries
        "CREATE INDEX notion_page_title_type_index IF NOT EXISTS FOR (p:NotionPage) ON (p.title, p.type)",
        
        # Full-text search indices
        "CREATE FULLTEXT INDEX notion_page_fulltext IF NOT EXISTS FOR (p:NotionPage) ON EACH [p.title, p.tags]",
    ]
    
    for index in indices:
        try:
            await graph_client._graphiti.driver.execute_query(index)
            logger.info(f"Created index: {index.split(' ')[2]}")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent index already exists" in str(e).lower():
                logger.info(f"Index already exists: {index.split(' ')[2]}")
            else:
                logger.warning(f"Failed to create index: {e}")


async def test_database_connection():
    """Test the database connection and setup."""
    logger.info("Testing database connection...")
    
    settings = get_settings()
    graph_client = GraphitiClient(
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_username,
        neo4j_password=settings.neo4j_password
    )
    
    try:
        await graph_client.initialize()
        
        # Test basic query
        query = "RETURN 'Database connection successful' as message"
        result = await graph_client._graphiti.driver.execute_query(query)
        
        if result.records:
            logger.info(result.records[0]["message"])
        
        # Test constraints and indices
        await verify_setup(graph_client)
        
        return True
        
    except Exception as e:
        logger.exception(f"Database connection test failed: {e}")
        return False
    finally:
        await graph_client.close()


async def verify_setup(graph_client: GraphitiClient):
    """Verify that constraints and indices were created correctly."""
    logger.info("Verifying database setup...")
    
    try:
        # Check constraints
        constraints_query = "SHOW CONSTRAINTS"
        constraints_result = await graph_client._graphiti.driver.execute_query(constraints_query)
        
        constraint_count = len(constraints_result.records)
        logger.info(f"Found {constraint_count} constraints")
        
        # Check indices
        indices_query = "SHOW INDEXES"
        indices_result = await graph_client._graphiti.driver.execute_query(indices_query)
        
        index_count = len(indices_result.records)
        logger.info(f"Found {index_count} indices")
        
        # Test a sample operation
        test_query = """
        MERGE (test:NotionPage {notion_id: 'test-setup-page'})
        SET test.title = 'Test Setup Page',
            test.type = 'page',
            test.last_edited_time = datetime(),
            test.url = 'https://test.com'
        RETURN test.notion_id as test_id
        """
        
        test_result = await graph_client._graphiti.driver.execute_query(test_query)
        if test_result.records:
            logger.info("Sample operation successful")
            
            # Clean up test node
            cleanup_query = "MATCH (test:NotionPage {notion_id: 'test-setup-page'}) DELETE test"
            await graph_client._graphiti.driver.execute_query(cleanup_query)
            logger.info("Test data cleaned up")
        
        logger.info("Database setup verification completed")
        
    except Exception as e:
        logger.warning(f"Setup verification failed: {e}")


async def reset_database():
    """Reset the database by removing all data (use with caution)."""
    logger.warning("Resetting database - this will delete ALL data!")
    
    # Ask for confirmation
    confirmation = input("Are you sure you want to reset the database? Type 'yes' to confirm: ")
    if confirmation.lower() != 'yes':
        logger.info("Database reset cancelled")
        return
    
    settings = get_settings()
    graph_client = GraphitiClient(
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_username,
        neo4j_password=settings.neo4j_password
    )
    
    try:
        await graph_client.initialize()
        
        # Clear all data
        success = await graph_client.clear_all_data()
        
        if success:
            logger.info("Database reset completed")
        else:
            logger.error("Database reset failed")
            
    except Exception as e:
        logger.exception(f"Database reset failed: {e}")
    finally:
        await graph_client.close()


async def main():
    """Main entry point."""
    setup_logging()
    
    import argparse
    parser = argparse.ArgumentParser(description="Database setup script")
    parser.add_argument("--test", action="store_true", help="Test database connection")
    parser.add_argument("--reset", action="store_true", help="Reset database (delete all data)")
    parser.add_argument("--setup", action="store_true", default=True, help="Setup database (default)")
    
    args = parser.parse_args()
    
    try:
        if args.reset:
            await reset_database()
        elif args.test:
            success = await test_database_connection()
            sys.exit(0 if success else 1)
        else:
            await setup_database()
            
            # Test after setup
            logger.info("Testing setup...")
            success = await test_database_connection()
            if not success:
                logger.error("Setup test failed")
                sys.exit(1)
                
        logger.info("Database setup script completed successfully")
        
    except Exception as e:
        logger.exception(f"Database setup script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())