"""
RAG Models: ProductEmbedding and RAGQueryLog.

ProductEmbedding stores the 1536-dim vector for each product as a JSON array.
This approach works without the pgvector PostgreSQL extension — similarity
is computed in Python instead.

RAGQueryLog records every RAG query for analytics and debugging.
"""

from django.db import models
from django.contrib.auth.models import User


class ProductEmbedding(models.Model):
    """
    Stores a single vector embedding per product.
    The vector is stored as a JSON array of floats.
    """
    product = models.OneToOneField(
        'marketplace.Product',
        on_delete=models.CASCADE,
        related_name='embedding',
        primary_key=True,
    )
    embedding = models.JSONField(
        help_text="1536-dim embedding vector as a list of floats"
    )
    embedded_text = models.TextField(
        help_text="The text that was used to generate the embedding"
    )
    model_name = models.CharField(max_length=100, default='text-embedding-3-small')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_embeddings'
        verbose_name = 'Product Embedding'
        verbose_name_plural = 'Product Embeddings'

    def __str__(self):
        return f"Embedding for Product #{self.product_id}"


class RAGQueryLog(models.Model):
    """
    Logs every RAG query for debugging and analytics.
    """
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rag_queries'
    )
    query_text = models.TextField()
    generated_sql = models.TextField(blank=True, default='')
    sql_results_count = models.IntegerField(default=0)
    vector_results_count = models.IntegerField(default=0)
    merged_results_count = models.IntegerField(default=0)
    final_answer = models.TextField(blank=True, default='')
    latency_ms = models.IntegerField(default=0, help_text="Total query time in milliseconds")
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rag_query_logs'
        ordering = ['-created_at']
        verbose_name = 'RAG Query Log'
        verbose_name_plural = 'RAG Query Logs'

    def __str__(self):
        return f"[{self.created_at}] {self.query_text[:60]}"


class ChatSession(models.Model):
    """
    A named chat session for the Smart Search / RAG chatbot.
    Each session contains ordered messages between user and AI.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='chat_sessions'
    )
    title = models.CharField(
        max_length=200,
        default='محادثة جديدة',
        help_text="Auto-generated from first message"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_sessions'
        ordering = ['-updated_at']
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'

    def __str__(self):
        return f"[{self.user.username}] {self.title[:50]}"


class ChatMessage(models.Model):
    """
    A single message within a ChatSession.
    role = 'user' | 'assistant'
    products_data is the list of product cards returned by the assistant.
    """
    ROLE_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(help_text="Message text content")
    products_data = models.JSONField(
        blank=True, default=list,
        help_text="Product cards returned by the assistant (empty for user messages)"
    )
    meta = models.JSONField(
        blank=True, default=dict,
        help_text="RAG metadata (latency, sql_results, vector_results, intent)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'

    def __str__(self):
        return f"[{self.session_id}] {self.role}: {self.content[:40]}"
