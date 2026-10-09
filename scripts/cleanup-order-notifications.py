"""Daily event retention; imports DB helpers only, never initializes business data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
from order_notifications import cleanup

if __name__ == '__main__':
    print(f'Expired notification events removed: {cleanup()}')
