try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:
    # Celery not installed — periodic tasks won't run but Django works
    celery_app = None
    __all__ = ()
