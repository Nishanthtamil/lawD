"""
Django management command to initialize Milvus collections.
Creates public and personal document collections with proper schemas and indexes.
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from api.database import MilvusManager


class Command(BaseCommand):
    help = 'Initialize Milvus collections for segregated hybrid RAG pipeline'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--validate-only',
            action='store_true',
            help='Only validate existing collections without creating new ones'
        )
        parser.add_argument(
            '--force-recreate',
            action='store_true',
            help='Drop and recreate collections (WARNING: This will delete all data)'
        )
        parser.add_argument(
            '--collection',
            choices=['public', 'personal', 'all'],
            default='all',
            help='Specify which collection to initialize (default: all)'
        )
    
    def handle(self, *args, **options):
        """Handle the management command"""
        
        self.stdout.write(
            self.style.SUCCESS('Starting Milvus collection initialization...')
        )
        
        try:
            # Test connection first
            self._test_connection()
            
            if options['validate_only']:
                self._validate_collections()
            elif options['force_recreate']:
                self._recreate_collections(options['collection'])
            else:
                self._initialize_collections(options['collection'])
                
        except Exception as e:
            raise CommandError(f'Failed to initialize Milvus collections: {e}')
    
    def _test_connection(self):
        """Test Milvus connection"""
        self.stdout.write('Testing Milvus connection...')
        
        try:
            milvus_manager = MilvusManager()
            milvus_manager.connect()
            
            if milvus_manager.is_connected():
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Connected to Milvus at {getattr(settings, "MILVUS_HOST", "localhost")}:{getattr(settings, "MILVUS_PORT", "19530")}'
                    )
                )
            else:
                raise Exception("Connection test failed")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Failed to connect to Milvus: {e}')
            )
            raise
    
    def _validate_collections(self):
        """Validate existing collections"""
        self.stdout.write('Validating Milvus collections...')
        
        try:
            milvus_manager = MilvusManager()
            milvus_manager.connect()
            
            # Check if collections exist
            from pymilvus import utility
            
            public_exists = utility.has_collection("public_documents")
            personal_exists = utility.has_collection("personal_documents")
            
            self.stdout.write(f'Public collection exists: {"✓" if public_exists else "✗"}')
            self.stdout.write(f'Personal collection exists: {"✓" if personal_exists else "✗"}')
            
            if public_exists and personal_exists:
                self.stdout.write(
                    self.style.SUCCESS('✓ All collections are valid and ready')
                )
            else:
                self.stdout.write(
                    self.style.WARNING('⚠ Some collections are missing')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Collections validation failed: {e}')
            )
    
    def _initialize_collections(self, collection_type):
        """Initialize collections"""
        self.stdout.write(f'Initializing {collection_type} collection(s)...')
        
        milvus_manager = MilvusManager()
        milvus_manager.connect()
        
        results = {}
        
        if collection_type in ['all', 'public']:
            success = milvus_manager.create_collection("public_documents")
            results['public'] = success
            self._display_single_result('public', success)
        
        if collection_type in ['all', 'personal']:
            success = milvus_manager.create_collection("personal_documents")
            results['personal'] = success
            self._display_single_result('personal', success)
        
        # Validate after initialization
        self.stdout.write('\nValidating initialized collections...')
        self._validate_collections()
    
    def _recreate_collections(self, collection_type):
        """Recreate collections (drops existing ones first)"""
        self.stdout.write(
            self.style.WARNING(
                f'WARNING: This will delete all data in {collection_type} collection(s)!'
            )
        )
        
        # Confirm with user
        confirm = input('Are you sure you want to continue? (yes/no): ')
        if confirm.lower() != 'yes':
            self.stdout.write('Operation cancelled.')
            return
        
        from pymilvus import utility
        
        # Drop collections
        if collection_type in ['all', 'public']:
            if utility.has_collection("public_documents"):
                utility.drop_collection("public_documents")
                self.stdout.write('Dropped public collection')
        
        if collection_type in ['all', 'personal']:
            if utility.has_collection("personal_documents"):
                utility.drop_collection("personal_documents")
                self.stdout.write('Dropped personal collection')
        
        # Recreate collections
        self._initialize_collections(collection_type)
    

    
    def _display_single_result(self, collection_type, success):
        """Display result for a single collection initialization"""
        if success:
            self.stdout.write(
                f'  ✓ {collection_type.title()} collection: {self.style.SUCCESS("Success")}'
            )
        else:
            self.stdout.write(
                f'  ✗ {collection_type.title()} collection: {self.style.ERROR("Failed")}'
            )