from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal



class Video(models.Model):
    """Extended video format with comprehensive metadata for epilepsy screening"""
    
    VIDEO_FORMATS = [
        ('SD', 'Standard Definition'),
        ('HD', 'High Definition'),
        ('4K', 'Ultra HD'),
        ('RAW', 'Raw/Uncompressed'),
        ('HDR', 'High Dynamic Range'),
        ('Dolby', 'Dolby Vision/ATMOS'),
    ]
    
    VIDEO_TYPES = [
        ('monitoring', 'Epilepsy Monitoring'),
        ('research', 'Research'),
        ('clinical', 'Clinical Trial'),
        ('educational', 'Educational'),
        ('demonstration', 'Demonstration'),
    ]
    
    SAFETY_RATINGS = [
        ('safe', 'Safe'),
        ('warning', 'Warning'),
        ('caution', 'Caution'),
        ('avoid', 'Avoid'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    url = models.URLField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    thumbnail = models.URLField(max_length=2000, blank=True)
    category = models.CharField(max_length=100, blank=True)
    content_type = models.CharField(max_length=50, blank=True)
    
    # Video format fields
    video_format = models.CharField(max_length=20, choices=VIDEO_FORMATS, default='HD')
    resolution = models.CharField(max_length=20, blank=True)
    framerate = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(120)])
    bitrate = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(50000)])
    codec = models.CharField(max_length=50, blank=True)
    hdr_enabled = models.BooleanField(default=False)
    dolby_atmos = models.BooleanField(default=False)
    aspect_ratio = models.CharField(max_length=10, choices=[('16:9', '16:9'), ('4:3', '4:3'), ('2.35:1', '2.35:1')], default='16:9')
    
    # Analysis data
    seizure_threshold = models.FloatField(null=True, blank=True)
    seizure_duration = models.IntegerField(null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    safety_rating = models.CharField(max_length=20, default='safe', choices=SAFETY_RATINGS)
    
    # Store functionality
    is_premium = models.BooleanField(default=False)
    price_cents = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'videos'
        indexes = [
            models.Index(fields=['category'], name='video_category_idx'),
            models.Index(fields=['is_premium'], name='video_premium_idx'),
            models.Index(fields=['video_format'], name='video_format_idx'),
            models.Index(fields=['safety_rating'], name='video_safety_idx'),
            models.Index(fields=['category', 'is_premium'], name='video_cat_prem_idx'),
            models.Index(fields=['category', 'video_format'], name='video_cat_fmt_idx'),
        ]



class StoreProduct(models.Model):
    """Store product for selling video formats and bundles"""
    
    PRODUCT_TYPES = [
        ('format', 'Format Bundle'),
        ('category', 'Category Pack'),
        ('premium', 'Premium Content'),
        ('research', 'Research Package'),
    ]
    
    active = models.BooleanField(default=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    product_type = models.CharField(max_length=50, choices=PRODUCT_TYPES, default='format')
    price_cents = models.IntegerField(validators=[MinValueValidator(0)])
    duration_seconds = models.IntegerField(default=0)
    thumbnail = models.URLField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['price_cents']
        db_table = 'store_products'
        indexes = [
            models.Index(fields=['active', 'price_cents'], name='store_active_price_idx'),
            models.Index(fields=['title'], name='store_title_idx'),
            models.Index(fields=['product_type'], name='store_type_idx'),
        ]



class Purchase(models.Model):
    """Track store purchases"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    product = models.ForeignKey(StoreProduct, on_delete=models.CASCADE, related_name='purchases')
    email = models.EmailField()
    payment_method = models.CharField(max_length=30, default='card')
    card_last4 = models.CharField(max_length=4, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    amount_cents = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'purchases'
        indexes = [
            models.Index(fields=['email'], name='purchase_email_idx'),
            models.Index(fields=['status'], name='purchase_status_idx'),
            models.Index(fields=['product'], name='purchase_product_idx'),
            models.Index(fields=['completed_at'], name='purchase_completed_idx'),
        ]



class VideoFormat(models.Model):
    """Pre-defined video format specifications"""
    
    name = models.CharField(max_length=50, unique=True)
    resolution = models.CharField(max_length=20)
    framerate_ranges = models.TextField(help_text="e.g., 24-60fps")
    codec_recommendations = models.TextField()
    bitrate_min = models.IntegerField()
    bitrate_max = models.IntegerField()
    description = models.TextField()
    
    class Meta:
        ordering = ['name']
        db_table = 'video_formats'



class VideoPurchase(models.Model):
    """Purchase history for individual videos"""
    
    VIDEO = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='video_purchases')
    PURCHASED_BY = models.CharField(max_length=255)
    PURCHASED_AT = models.DateTimeField(auto_now_add=True)
    price_cents = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    
    class Meta:
        db_table = 'video_purchases'



class StoreSubscription(models.Model):
    """Premium subscription for store access"""
    email = models.EmailField(unique=True)
    status = models.CharField(max_length=20, default='pending')
    plan_type = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    renewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'store_subscriptions'
        indexes = [
            models.Index(fields=['status'], name='subscription_status_idx'),
            models.Index(fields=['expires_at'], name='subscription_expires_idx'),
        ]



class VideoCategory(models.Model):
    """Video categories for better organization"""
    
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories')
    ordering = models.IntegerField(default=0)
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['ordering', 'name']
        db_table = 'video_categories'
        indexes = [
            models.Index(fields=['slug'], name='category_slug_idx'),
            models.Index(fields=['is_active'], name='category_active_idx'),
        ]