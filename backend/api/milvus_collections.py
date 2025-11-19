"""
Milvus collection schemas and initialization for segregated hybrid RAG pipeline.
Defines public and personal document collection schemas with proper field types.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from pymilvus import (
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    Index,
    utility,
    MilvusException
)

from .milvus_manager import MilvusConnectionManager

logger = logging.getLogger(__name__)


class CollectionSchemaManager:
    """Manages Milvus collection schemas for public and personal documents"""
    
    # Collection names
    PUBLIC_COLLECTION_NAME = "public_legal_knowledge"
    PERSONAL_COLLECTION_NAME = "personal_documents"
    
    # Embedding dimensions (using sentence-transformers all-mpnet-base-v2)
    EMBEDDING_DIM = 768
    
    @classmethod
    def get_public_collection_schema(cls) -> CollectionSchema:
        """
        Define schema for public legal knowledge collection.
        Stores admin-managed constitutional law, legal precedents, and amendments.
        
        Returns:
            CollectionSchema: Schema for public documents collection
        """
        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.INT64,
                is_primary=True,
                auto_id=True,
                description="Primary key for the document chunk"
            ),
            FieldSchema(
                name="document_id",
                dtype=DataType.VARCHAR,
                max_length=36,
                description="UUID of the source PublicDocument"
            ),
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Unique identifier for the text chunk within document"
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=cls.EMBEDDING_DIM,
                description="Vector embedding of the text chunk"
            ),
            FieldSchema(
                name="text_content",
                dtype=DataType.VARCHAR,
                max_length=5000,
                description="Original text content of the chunk"
            ),
            FieldSchema(
                name="document_type",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Type of legal document (amendment, case_law, statute, etc.)"
            ),
            FieldSchema(
                name="legal_domain",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Legal domain (constitutional, criminal, civil, etc.)"
            ),
            FieldSchema(
                name="jurisdiction",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Legal jurisdiction (India, state-specific, etc.)"
            ),
            FieldSchema(
                name="effective_date",
                dtype=DataType.INT64,
                description="Effective date as Unix timestamp (nullable)"
            ),
            FieldSchema(
                name="chunk_index",
                dtype=DataType.INT32,
                description="Index of chunk within the document"
            ),
            FieldSchema(
                name="created_at",
                dtype=DataType.INT64,
                description="Creation timestamp as Unix timestamp"
            )
        ]
        
        schema = CollectionSchema(
            fields=fields,
            description="Public legal knowledge base for constitutional law and legal precedents",
            enable_dynamic_field=True  # Allow additional metadata fields
        )
        
        return schema
    
    @classmethod
    def get_personal_collection_schema(cls) -> CollectionSchema:
        """
        Define schema for personal documents collection with user partitioning.
        Stores user-specific case files and documents with strict segregation.
        
        Returns:
            CollectionSchema: Schema for personal documents collection
        """
        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.INT64,
                is_primary=True,
                auto_id=True,
                description="Primary key for the document chunk"
            ),
            FieldSchema(
                name="user_id",
                dtype=DataType.VARCHAR,
                max_length=36,
                description="UUID of the user who owns this document"
            ),
            FieldSchema(
                name="document_id",
                dtype=DataType.VARCHAR,
                max_length=36,
                description="UUID of the source UserDocument"
            ),
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Unique identifier for the text chunk within document"
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=cls.EMBEDDING_DIM,
                description="Vector embedding of the text chunk"
            ),
            FieldSchema(
                name="text_content",
                dtype=DataType.VARCHAR,
                max_length=5000,
                description="Original text content of the chunk"
            ),
            FieldSchema(
                name="file_type",
                dtype=DataType.VARCHAR,
                max_length=50,
                description="Type of file (pdf, docx, txt)"
            ),
            FieldSchema(
                name="chunk_index",
                dtype=DataType.INT32,
                description="Index of chunk within the document"
            ),
            FieldSchema(
                name="created_at",
                dtype=DataType.INT64,
                description="Creation timestamp as Unix timestamp"
            )
        ]
        
        schema = CollectionSchema(
            fields=fields,
            description="Personal documents collection with user-specific partitions",
            enable_dynamic_field=True  # Allow additional metadata fields
        )
        
        return schema
    
    @classmethod
    def get_index_params(cls) -> Dict[str, Any]:
        """
        Get index parameters for vector similarity search.
        Uses IVF_FLAT for good balance of performance and accuracy.
        
        Returns:
            Dict: Index parameters for vector fields
        """
        return {
            "metric_type": "COSINE",  # Cosine similarity for semantic search
            "index_type": "IVF_FLAT",
            "params": {
                "nlist": 1024  # Number of cluster units
            }
        }
    
    @classmethod
    def get_search_params(cls) -> Dict[str, Any]:
        """
        Get search parameters for vector queries.
        
        Returns:
            Dict: Search parameters for vector queries
        """
        return {
            "metric_type": "COSINE",
            "params": {
                "nprobe": 10  # Number of clusters to search
            }
        }


class CollectionManager:
    """Manages Milvus collection creation, initialization, and configuration"""
    
    def __init__(self):
        self.connection_manager = MilvusConnectionManager()
        self.schema_manager = CollectionSchemaManager()
    
    def initialize_collections(self) -> Dict[str, bool]:
        """
        Initialize both public and personal document collections.
        Creates collections if they don't exist and sets up indexes.
        
        Returns:
            Dict[str, bool]: Status of collection initialization
        """
        results = {}
        
        try:
            # Ensure connection
            self.connection_manager.get_connection()
            
            # Initialize public collection
            results['public'] = self._initialize_public_collection()
            
            # Initialize personal collection
            results['personal'] = self._initialize_personal_collection()
            
            logger.info("Successfully initialized all Milvus collections")
            return results
            
        except Exception as e:
            logger.error(f"Failed to initialize collections: {e}")
            raise
    
    def _initialize_public_collection(self) -> bool:
        """
        Initialize the public legal knowledge collection.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            collection_name = self.schema_manager.PUBLIC_COLLECTION_NAME
            
            # Check if collection exists
            if utility.has_collection(collection_name):
                logger.info(f"Public collection '{collection_name}' already exists")
                collection = Collection(collection_name)
            else:
                # Create collection with schema
                schema = self.schema_manager.get_public_collection_schema()
                collection = Collection(
                    name=collection_name,
                    schema=schema,
                    using='default'
                )
                logger.info(f"Created public collection '{collection_name}'")
            
            # Create index on embedding field
            self._create_vector_index(collection, "embedding")
            
            # Create scalar indexes for filtering
            self._create_scalar_indexes(collection, [
                "document_type",
                "legal_domain",
                "jurisdiction",
                "document_id"
            ])
            
            # Load collection into memory
            collection.load()
            logger.info(f"Loaded public collection '{collection_name}' into memory")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize public collection: {e}")
            return False
    
    def _initialize_personal_collection(self) -> bool:
        """
        Initialize the personal documents collection with partitioning support.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            collection_name = self.schema_manager.PERSONAL_COLLECTION_NAME
            
            # Check if collection exists
            if utility.has_collection(collection_name):
                logger.info(f"Personal collection '{collection_name}' already exists")
                collection = Collection(collection_name)
            else:
                # Create collection with schema
                schema = self.schema_manager.get_personal_collection_schema()
                collection = Collection(
                    name=collection_name,
                    schema=schema,
                    using='default'
                )
                logger.info(f"Created personal collection '{collection_name}'")
            
            # Create index on embedding field
            self._create_vector_index(collection, "embedding")
            
            # Create scalar indexes for filtering
            self._create_scalar_indexes(collection, [
                "user_id",
                "document_id",
                "file_type"
            ])
            
            # Load collection into memory
            collection.load()
            logger.info(f"Loaded personal collection '{collection_name}' into memory")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize personal collection: {e}")
            return False
    
    def _create_vector_index(self, collection: Collection, field_name: str) -> bool:
        """
        Create vector index on the specified field.
        
        Args:
            collection: Milvus collection object
            field_name: Name of the vector field
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if index already exists
            if collection.has_index():
                logger.info(f"Vector index already exists on field '{field_name}'")
                return True
            
            # Create index
            index_params = self.schema_manager.get_index_params()
            collection.create_index(
                field_name=field_name,
                index_params=index_params
            )
            
            logger.info(f"Created vector index on field '{field_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create vector index on '{field_name}': {e}")
            return False
    
    def _create_scalar_indexes(self, collection: Collection, field_names: List[str]) -> bool:
        """
        Create scalar indexes for filtering fields.
        
        Args:
            collection: Milvus collection object
            field_names: List of scalar field names to index
            
        Returns:
            bool: True if all indexes created successfully
        """
        success_count = 0
        
        for field_name in field_names:
            try:
                # Create scalar index for filtering
                collection.create_index(
                    field_name=field_name,
                    index_params={"index_type": "TRIE"}  # Trie index for string fields
                )
                logger.debug(f"Created scalar index on field '{field_name}'")
                success_count += 1
                
            except Exception as e:
                # Log warning but continue with other indexes
                logger.warning(f"Failed to create scalar index on '{field_name}': {e}")
        
        logger.info(f"Created {success_count}/{len(field_names)} scalar indexes")
        return success_count == len(field_names)
    
    def get_collection(self, collection_name: str) -> Optional[Collection]:
        """
        Get a Milvus collection by name.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Collection: Milvus collection object or None if not found
        """
        try:
            if utility.has_collection(collection_name):
                return Collection(collection_name)
            else:
                logger.warning(f"Collection '{collection_name}' does not exist")
                return None
                
        except Exception as e:
            logger.error(f"Error getting collection '{collection_name}': {e}")
            return None
    
    def get_public_collection(self) -> Optional[Collection]:
        """Get the public legal knowledge collection"""
        return self.get_collection(self.schema_manager.PUBLIC_COLLECTION_NAME)
    
    def get_personal_collection(self) -> Optional[Collection]:
        """Get the personal documents collection"""
        return self.get_collection(self.schema_manager.PERSONAL_COLLECTION_NAME)
    
    def drop_collection(self, collection_name: str) -> bool:
        """
        Drop a collection (use with caution).
        
        Args:
            collection_name: Name of the collection to drop
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                logger.info(f"Dropped collection '{collection_name}'")
                return True
            else:
                logger.warning(f"Collection '{collection_name}' does not exist")
                return False
                
        except Exception as e:
            logger.error(f"Failed to drop collection '{collection_name}': {e}")
            return False
    
    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """
        Get information about a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dict: Collection information
        """
        try:
            if not utility.has_collection(collection_name):
                return {'error': f'Collection {collection_name} does not exist'}
            
            collection = Collection(collection_name)
            
            info = {
                'name': collection_name,
                'schema': {
                    'fields': [
                        {
                            'name': field.name,
                            'type': str(field.dtype),
                            'description': field.description
                        }
                        for field in collection.schema.fields
                    ],
                    'description': collection.schema.description
                },
                'num_entities': collection.num_entities,
                'partitions': [p.name for p in collection.partitions],
                'indexes': collection.indexes,
                'is_loaded': utility.load_state(collection_name).name == 'Loaded'
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting collection info for '{collection_name}': {e}")
            return {'error': str(e)}
    
    def validate_collections(self) -> Dict[str, Any]:
        """
        Validate that all required collections exist and are properly configured.
        
        Returns:
            Dict: Validation results
        """
        results = {
            'public_collection': {},
            'personal_collection': {},
            'overall_status': 'unknown'
        }
        
        try:
            # Validate public collection
            public_name = self.schema_manager.PUBLIC_COLLECTION_NAME
            results['public_collection'] = self._validate_single_collection(public_name)
            
            # Validate personal collection
            personal_name = self.schema_manager.PERSONAL_COLLECTION_NAME
            results['personal_collection'] = self._validate_single_collection(personal_name)
            
            # Determine overall status
            public_ok = results['public_collection'].get('status') == 'valid'
            personal_ok = results['personal_collection'].get('status') == 'valid'
            
            if public_ok and personal_ok:
                results['overall_status'] = 'valid'
            elif public_ok or personal_ok:
                results['overall_status'] = 'partial'
            else:
                results['overall_status'] = 'invalid'
            
            return results
            
        except Exception as e:
            logger.error(f"Error validating collections: {e}")
            results['overall_status'] = 'error'
            results['error'] = str(e)
            return results
    
    def store_personal_embeddings(self, partition_name: str, embeddings_data: List[Dict[str, Any]]) -> int:
        """
        Store personal document embeddings in user-specific partition.
        
        Args:
            partition_name: Name of the user partition
            embeddings_data: List of embedding data dictionaries
            
        Returns:
            int: Number of embeddings successfully stored
            
        Raises:
            Exception: If storage fails
        """
        try:
            collection = self.get_personal_collection()
            if not collection:
                raise Exception("Personal collection not available")
            
            # Prepare data for insertion
            insert_data = {
                'user_id': [],
                'document_id': [],
                'chunk_id': [],
                'embedding': [],
                'text_content': [],
                'created_at': []
            }
            
            for item in embeddings_data:
                insert_data['user_id'].append(item['user_id'])
                insert_data['document_id'].append(item['document_id'])
                insert_data['chunk_id'].append(item['chunk_id'])
                insert_data['embedding'].append(item['embedding'])
                insert_data['text_content'].append(item['text_content'])
                insert_data['created_at'].append(item['created_at'])
            
            # Insert data into the specific partition
            insert_result = collection.insert(
                data=insert_data,
                partition_name=partition_name
            )
            
            # Flush to ensure data is persisted
            collection.flush()
            
            logger.info(f"Stored {len(embeddings_data)} embeddings in partition {partition_name}")
            return len(embeddings_data)
            
        except Exception as e:
            logger.error(f"Error storing personal embeddings in partition {partition_name}: {e}")
            raise
    
    def store_public_embeddings(self, embeddings_data: List[Dict[str, Any]]) -> int:
        """
        Store public document embeddings in the public collection.
        
        Args:
            embeddings_data: List of embedding data dictionaries
            
        Returns:
            int: Number of embeddings successfully stored
            
        Raises:
            Exception: If storage fails
        """
        try:
            collection = self.get_public_collection()
            if not collection:
                raise Exception("Public collection not available")
            
            # Prepare data for insertion
            insert_data = {
                'document_id': [],
                'chunk_id': [],
                'embedding': [],
                'text_content': [],
                'document_type': [],
                'legal_domain': [],
                'jurisdiction': [],
                'effective_date': [],
                'chunk_index': [],
                'created_at': []
            }
            
            for item in embeddings_data:
                insert_data['document_id'].append(item['document_id'])
                insert_data['chunk_id'].append(item['chunk_id'])
                insert_data['embedding'].append(item['embedding'])
                insert_data['text_content'].append(item['text_content'])
                insert_data['document_type'].append(item.get('document_type', ''))
                insert_data['legal_domain'].append(item.get('legal_domain', ''))
                insert_data['jurisdiction'].append(item.get('jurisdiction', 'India'))
                insert_data['effective_date'].append(item.get('effective_date', 0))
                insert_data['chunk_index'].append(item.get('chunk_index', 0))
                insert_data['created_at'].append(item['created_at'])
            
            # Insert data
            insert_result = collection.insert(data=insert_data)
            
            # Flush to ensure data is persisted
            collection.flush()
            
            logger.info(f"Stored {len(embeddings_data)} public embeddings")
            return len(embeddings_data)
            
        except Exception as e:
            logger.error(f"Error storing public embeddings: {e}")
            raise
    
    def _validate_single_collection(self, collection_name: str) -> Dict[str, Any]:
        """
        Validate a single collection.
        
        Args:
            collection_name: Name of the collection to validate
            
        Returns:
            Dict: Validation results for the collection
        """
        result = {
            'name': collection_name,
            'exists': False,
            'has_index': False,
            'is_loaded': False,
            'status': 'invalid'
        }
        
        try:
            # Check existence
            if not utility.has_collection(collection_name):
                result['error'] = 'Collection does not exist'
                return result
            
            result['exists'] = True
            collection = Collection(collection_name)
            
            # Check index
            result['has_index'] = collection.has_index()
            
            # Check load status
            load_state = utility.load_state(collection_name)
            result['is_loaded'] = load_state.name == 'Loaded'
            
            # Determine status
            if result['exists'] and result['has_index'] and result['is_loaded']:
                result['status'] = 'valid'
            else:
                result['status'] = 'incomplete'
                issues = []
                if not result['has_index']:
                    issues.append('missing index')
                if not result['is_loaded']:
                    issues.append('not loaded')
                result['issues'] = issues
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            return result


# Utility functions for collection management
def initialize_milvus_collections() -> Dict[str, bool]:
    """
    Utility function to initialize all Milvus collections.
    Can be called from Django management commands or startup scripts.
    
    Returns:
        Dict[str, bool]: Initialization results
    """
    manager = CollectionManager()
    return manager.initialize_collections()


def get_collection_manager() -> CollectionManager:
    """
    Get a CollectionManager instance.
    
    Returns:
        CollectionManager: Configured collection manager
    """
    return CollectionManager()


def validate_milvus_setup() -> Dict[str, Any]:
    """
    Validate the entire Milvus setup.
    
    Returns:
        Dict: Validation results
    """
    manager = CollectionManager()
    return manager.validate_collections()