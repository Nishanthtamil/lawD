from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
import uuid

class UserManager(BaseUserManager):
    """Custom user manager for phone-based authentication"""
    
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('Phone number is required')
        
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        return self.create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model with phone authentication"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return self.phone_number


class OTP(models.Model):
    """OTP for phone verification"""
    
    phone_number = models.CharField(max_length=15)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'otps'
        ordering = ['-created_at']
    
    def is_valid(self):
        return timezone.now() < self.expires_at and not self.is_verified
    
    def __str__(self):
        return f"{self.phone_number} - {self.otp}"


class ChatSession(models.Model):
    """Chat session for a user"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=255, default="New Conversation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chat_sessions'
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.user.phone_number} - {self.title}"


class ChatMessage(models.Model):
    """Individual chat message"""
    
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class UserDocument(models.Model):
    """Documents uploaded by users"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    
    file_name = models.CharField(max_length=255)
    file_path = models.FileField(upload_to='user_documents/%Y/%m/%d/')
    file_size = models.IntegerField()  # Size in bytes
    file_type = models.CharField(max_length=50)  # pdf, docx, txt
    
    summary_type = models.CharField(max_length=50, blank=True)
    summary = models.TextField(blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_documents'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.phone_number} - {self.file_name}"


class PublicDocument(models.Model):
    """Admin-managed public legal documents"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    DOCUMENT_TYPE_CHOICES = [
        ('amendment', 'Constitutional Amendment'),
        ('case_law', 'Case Law'),
        ('statute', 'Statute'),
        ('regulation', 'Regulation'),
        ('other', 'Other'),
    ]
    
    LEGAL_DOMAIN_CHOICES = [
        ('constitutional', 'Constitutional Law'),
        ('criminal', 'Criminal Law'),
        ('civil', 'Civil Law'),
        ('corporate', 'Corporate Law'),
        ('family', 'Family Law'),
        ('tax', 'Tax Law'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    document_type = models.CharField(max_length=100, choices=DOCUMENT_TYPE_CHOICES)
    file_path = models.FileField(upload_to='public_documents/%Y/%m/%d/')
    uploaded_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        limit_choices_to={'is_staff': True},
        related_name='uploaded_public_documents'
    )
    
    # Processing status
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    entities_extracted = models.JSONField(default=dict, blank=True)
    relationships_count = models.IntegerField(default=0)
    embeddings_count = models.IntegerField(default=0)
    
    # Metadata
    legal_domain = models.CharField(max_length=100, choices=LEGAL_DOMAIN_CHOICES, blank=True)
    jurisdiction = models.CharField(max_length=100, default='India')
    effective_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'public_documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_type']),
            models.Index(fields=['legal_domain']),
            models.Index(fields=['processing_status']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.document_type})"


class ProcessingTask(models.Model):
    """Track document processing tasks"""
    
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    TASK_TYPE_CHOICES = [
        ('public_document', 'Public Document Processing'),
        ('personal_document', 'Personal Document Processing'),
        ('partition_cleanup', 'Partition Cleanup'),
        ('system_maintenance', 'System Maintenance'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_id = models.CharField(max_length=255, unique=True)  # Celery task ID
    task_type = models.CharField(max_length=50, choices=TASK_TYPE_CHOICES)
    
    # Related objects
    public_document = models.ForeignKey(
        PublicDocument, 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE,
        related_name='processing_tasks'
    )
    user_document = models.ForeignKey(
        UserDocument, 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE,
        related_name='processing_tasks'
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='processing_tasks')
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    progress_percentage = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    
    # Metrics
    processing_time_seconds = models.IntegerField(null=True, blank=True)
    entities_extracted = models.IntegerField(default=0)
    embeddings_created = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'processing_tasks'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task_type']),
            models.Index(fields=['status']),
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"{self.task_type} - {self.status} ({self.user.phone_number})"
    
    def calculate_processing_time(self):
        """Calculate processing time if task is completed"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds())
        return None


class UserPartition(models.Model):
    """Track user-specific Milvus partitions"""
    
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='milvus_partition'
    )
    partition_name = models.CharField(max_length=100, unique=True)
    document_count = models.IntegerField(default=0)
    total_embeddings = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_partitions'
        ordering = ['-last_accessed']
        indexes = [
            models.Index(fields=['partition_name']),
            models.Index(fields=['last_accessed']),
        ]
    
    def __str__(self):
        return f"{self.user.phone_number} - {self.partition_name}"
    
    def get_partition_name(self):
        """Generate partition name based on user ID"""
        return f"user_{self.user.id.hex}"
    
    def save(self, *args, **kwargs):
        """Auto-generate partition name if not set"""
        if not self.partition_name:
            self.partition_name = self.get_partition_name()
        super().save(*args, **kwargs)

