import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from marketplace.models import Auction, UserAgent, Bid
from marketplace.serializers import run_auto_bidding

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Runs the AI Agent polling loop to monitor all active auctions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Seconds to wait between loops (default: 60)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        self.stdout.write(self.style.SUCCESS(f"AI Agent Loop started (Interval: {interval}s)"))
        self.stdout.write("Press Ctrl+C to stop.")

        try:
            while True:
                self.process_auctions()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nAgent loop stopped."))

    def process_auctions(self):
        """Find active auctions and trigger agent check for each."""
        now = timezone.now()
        active_auctions = Auction.objects.filter(
            is_active=True,
            end_time__gt=now
        ).select_related('product')

        if not active_auctions.exists():
            # self.stdout.write(f"[{now.strftime('%H:%M:%S')}] No active auctions found.")
            return

        for auction in active_auctions:
            detected_item = auction.product.detected_item
            if not detected_item:
                continue

            # Check if there are any agents that SHOULD be bidding but aren't the leader
            # This logic is encapsulated in run_auto_bidding (which handles bidding wars etc.)
            # We call it synchronously here since it's a background process anyway
            try:
                # We reuse run_auto_bidding which already handles:
                # 1. Matching agents for the detected_item
                # 2. Filtering by budget
                # 3. LLM evaluation
                # 4. Bidding wars
                
                # Check if the highest bidder is already an agent
                # (To avoid unnecessary LLM calls if an agent is already winning)
                # However, run_auto_bidding is smart enough to handle price updates.
                
                # Current logic in run_auto_bidding places bids at starting_bid or outbids.
                # If an auction already has a high bid, run_auto_bidding might need a tweak
                # to handle "ongoing" auctions. Actually, it's designed for "initial" bidding.
                
                # Let's see if we need a specialized 'check_and_outbid' logic here.
                # For now, run_auto_bidding is a good start.
                run_auto_bidding(auction, detected_item)
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing auction {auction.id}: {e}"))
