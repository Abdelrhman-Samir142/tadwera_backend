from django.contrib import admin
from .models import ProductEmbedding, RAGQueryLog, ChatSession, ChatMessage


@admin.register(ProductEmbedding)
class ProductEmbeddingAdmin(admin.ModelAdmin):
    list_display = ['product', 'model_name', 'updated_at']
    readonly_fields = ['product', 'embedded_text', 'model_name', 'created_at', 'updated_at']
    search_fields = ['product__title', 'embedded_text']


@admin.register(RAGQueryLog)
class RAGQueryLogAdmin(admin.ModelAdmin):
    list_display = ['query_text_short', 'user', 'merged_results_count', 'latency_ms', 'created_at']
    list_filter = ['created_at']
    readonly_fields = [
        'user', 'query_text', 'generated_sql', 'sql_results_count',
        'vector_results_count', 'merged_results_count', 'final_answer',
        'latency_ms', 'error', 'created_at'
    ]
    search_fields = ['query_text', 'final_answer']

    def query_text_short(self, obj):
        return obj.query_text[:60]
    query_text_short.short_description = 'Query'


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'title_short', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['title', 'user__username']
    readonly_fields = ['created_at', 'updated_at']

    def title_short(self, obj):
        return obj.title[:60]
    title_short.short_description = 'Title'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'session', 'role', 'content_short', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['content']
    readonly_fields = ['session', 'role', 'content', 'products_data', 'meta', 'created_at']

    def content_short(self, obj):
        return obj.content[:60]
    content_short.short_description = 'Content'
