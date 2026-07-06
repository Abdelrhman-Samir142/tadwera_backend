from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    name = 'marketplace'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import marketplace.signals  # noqa: F401
