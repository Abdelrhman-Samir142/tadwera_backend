"""
Celery application for RefurbAI backend.
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'refurbai_backend.settings')

app = Celery('refurbai_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
