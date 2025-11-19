# Database Management - Consolidated database operations

import logging
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.core.cache import cache
from pymilvus import connections, Collection, utility, FieldSchema, CollectionSchema, DataType
import neo4j
import redis

logger = logging.getLogger(__name__)

# ============================================================================
# CONNECTION POOL MANAGER
# ============================================================================

class ConnectionPool:
    """Manages database connections"""
    
    def __init__(self):
        self.milvus_manager = MilvusManager()
        self.neo4j_manager = Neo4jManager()
        self.redis_client = None
        self._initialized = False
    
    def initialize(self):
        """Initialize all database connections"""
        try:
            self.milvus_manager.connect()
            self.neo4j_manager.connect()
            self.redis_client = redis.from_url(settings.REDIS_URL)
            self._initialized = True
            logger.info("Database connections initialized")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            self._initialized = False
    
    def health_check(self) -> Dict[str, bool]:
        """Check health of all database connections"""
        health = {}
        
        # Check Milvus
        try:
            health['milvus'] = self.milvus_manager.is_connected()
        except Exception:
            health['milvus'] = False
        
        # Check Neo4j
        try:
            health['neo4j'] = self.neo4j_manager.is_connected()
        except Exception:
            health['neo4j'] = False
        
        # Check Redis
        try:
            self.redis_client.ping()
            health['redis'] = True
        except Exception:
            health['redis'] = False
        
        return health


# ============================================================================
# MILVUS MANAGER
# ============================================================================

class MilvusManager:
    """Manages Milvus vector database operations"""
    
    def __init__(self):
        self.connection_alias = "default"
        self.connected = False
    
    def connect(self):
        """Connect to Milvus"""
        try:
            connections.connect(
                alias=self.connection_alias,
                host=getattr(settings, 'MILVUS_HOST', 'localhost'),
                port=getattr(settings, 'MILVUS_PORT', '19530'),
                user=getattr(settings, 'MILVUS_USER', ''),
                password=getattr(settings, 'MILVUS_PASSWORD', '')
            )
            self.connected = True
            logger.info("Connected to Milvus")
        except Exception as e:
            logger.error(f"Milvus connection failed: {e}")
            self.connected = False
    
    def is_connected(self) -> bool:
        """Check if connected to Milvus"""
        try:
            return connections.has_connection(self.connection_alias) and self.connected
        except Exception:
            return False
    
    def create_collection(self, collection_name: str, dimension: int = 768):
        """Create a new collection"""
        try:
            if utility.has_collection(collection_name):
                return True
            
            # Define schema
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=100),
                FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=100),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
                FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=65535)
            ]
            
            schema = CollectionSchema(fields, "Legal document collection")
            collection = Collection(collection_name, schema)
            
            # Create index
            index_params = {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            collection.create_index("embedding", index_params)
            
            logger.info(f"Created Milvus collection: {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            return False
    
    def insert_documents(self, collection_name: str, documents: List[Dict]):
        """Insert documents into collection"""
        try:
            collection = Collection(collection_name)
            collection.insert(documents)
            collection.flush()
            logger.info(f"Inserted {len(documents)} documents into {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to insert documents: {e}")
            return False
    
    def search_vectors(self, collection_name: str, query_embedding: List[float], 
                      top_k: int = 10, filters: Optional[str] = None) -> List[Dict]:
        """Search vectors in collection"""
        try:
            collection = Collection(collection_name)
            collection.load()
            
            search_params = {
                "metric_type": "COSINE",
                "params": {"nprobe": 10}
            }
            
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filters,
                output_fields=["document_id", "user_id", "content", "metadata"]
            )
            
            formatted_results = []
            for hits in results:
                for hit in hits:
                    formatted_results.append({
                        'document_id': hit.entity.get('document_id'),
                        'user_id': hit.entity.get('user_id'),
                        'content': hit.entity.get('content'),
                        'score': float(hit.score),
                        'metadata': hit.entity.get('metadata', '{}')
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []


# ============================================================================
# NEO4J MANAGER
# ============================================================================

class Neo4jManager:
    """Manages Neo4j graph database operations"""
    
    def __init__(self):
        self.driver = None
        self.connected = False
    
    def connect(self):
        """Connect to Neo4j"""
        try:
            uri = getattr(settings, 'NEO4J_URI', 'bolt://localhost:7687')
            user = getattr(settings, 'NEO4J_USER', 'neo4j')
            password = getattr(settings, 'NEO4J_PASSWORD', 'password')
            
            self.driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
            
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            
            self.connected = True
            logger.info("Connected to Neo4j")
            
        except Exception as e:
            logger.error(f"Neo4j connection failed: {e}")
            self.connected = False
    
    def is_connected(self) -> bool:
        """Check if connected to Neo4j"""
        try:
            if not self.driver:
                return False
            
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
            
        except Exception:
            return False
    
    def create_document_node(self, document_data: Dict[str, Any]):
        """Create document node in graph"""
        try:
            with self.driver.session() as session:
                query = """
                CREATE (d:Document {
                    document_id: $document_id,
                    user_id: $user_id,
                    title: $title,
                    content: $content,
                    document_type: $document_type,
                    created_at: $created_at,
                    metadata: $metadata
                })
                """
                session.run(query, document_data)
                logger.info(f"Created document node: {document_data.get('document_id')}")
                
        except Exception as e:
            logger.error(f"Failed to create document node: {e}")
    
    def query_entities(self, filters: Dict[str, Any], limit: int = 10) -> List[Dict]:
        """Query entities from graph"""
        try:
            with self.driver.session() as session:
                # Simple entity query
                query = """
                MATCH (n)
                WHERE n.name CONTAINS $name
                RETURN n
                LIMIT $limit
                """
                
                result = session.run(query, {
                    'name': filters.get('name', ''),
                    'limit': limit
                })
                
                entities = []
                for record in result:
                    node = record['n']
                    entities.append(dict(node))
                
                return entities
                
        except Exception as e:
            logger.error(f"Entity query failed: {e}")
            return []
    
    def query_relationships(self, source_id: str, limit: int = 10) -> List[Dict]:
        """Query relationships from source entity"""
        try:
            with self.driver.session() as session:
                query = """
                MATCH (source)-[r]->(target)
                WHERE source.id = $source_id
                RETURN source, r, target
                LIMIT $limit
                """
                
                result = session.run(query, {
                    'source_id': source_id,
                    'limit': limit
                })
                
                relationships = []
                for record in result:
                    relationships.append({
                        'source': dict(record['source']),
                        'relationship': dict(record['r']),
                        'target': dict(record['target'])
                    })
                
                return relationships
                
        except Exception as e:
            logger.error(f"Relationship query failed: {e}")
            return []
    
    def get_database_stats(self) -> Dict[str, int]:
        """Get database statistics"""
        try:
            with self.driver.session() as session:
                # Count nodes
                node_result = session.run("MATCH (n) RETURN count(n) as count")
                node_count = node_result.single()['count']
                
                # Count relationships
                rel_result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
                rel_count = rel_result.single()['count']
                
                return {
                    'total_entities': node_count,
                    'total_relationships': rel_count
                }
                
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {'total_entities': 0, 'total_relationships': 0}
    
    def close(self):
        """Close Neo4j connection"""
        if self.driver:
            self.driver.close()
            self.connected = False


# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    """Unified database manager for all operations"""
    
    def __init__(self):
        self.milvus = MilvusManager()
        self.neo4j = Neo4jManager()
        self.connection_pool = ConnectionPool()
    
    def initialize(self):
        """Initialize all database connections"""
        self.connection_pool.initialize()
    
    def search_vectors(self, query_embedding: List[float], user, 
                      include_public: bool = True, top_k: int = 10) -> List[Dict]:
        """Search vectors across collections"""
        results = []
        
        # Search user's personal documents
        if user:
            user_collection = f"user_documents_{user.id}"
            user_results = self.milvus.search_vectors(
                user_collection, query_embedding, top_k//2
            )
            results.extend(user_results)
        
        # Search public documents
        if include_public:
            public_results = self.milvus.search_vectors(
                "public_documents", query_embedding, top_k//2
            )
            results.extend(public_results)
        
        return results
    
    def search_graph(self, query: str, user, include_public: bool = True, 
                    top_k: int = 10) -> List[Dict]:
        """Search graph database"""
        # Extract entities from query (simplified)
        entities = self._extract_entities(query)
        
        results = []
        for entity in entities[:3]:  # Limit entity searches
            entity_results = self.neo4j.query_entities(
                {'name': entity}, limit=top_k//len(entities) + 1
            )
            results.extend(entity_results)
        
        return results[:top_k]
    
    def _extract_entities(self, query: str) -> List[str]:
        """Simple entity extraction from query"""
        # This is a simplified version - in production use NER
        import re
        
        entities = []
        
        # Look for article numbers
        articles = re.findall(r'\b[Aa]rticle\s+(\d+)\b', query)
        entities.extend([f"Article {num}" for num in articles])
        
        # Look for common legal terms
        legal_terms = [
            'fundamental rights', 'directive principles', 'parliament',
            'supreme court', 'constitution', 'amendment'
        ]
        
        query_lower = query.lower()
        for term in legal_terms:
            if term in query_lower:
                entities.append(term)
        
        return entities


# Create singleton instances
connection_pool = ConnectionPool()

def get_neo4j_manager():
    """Get Neo4j manager instance"""
    return connection_pool.neo4j_manager