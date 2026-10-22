"""Check the explicit shared boundary; channel-specific modules are not copied."""
import argparse
from pathlib import Path

SHARED = ('catalog_order database_pool external_api external_api_logging external_api_schema '
    'inventory_overdelivery inventory_policy order_cancellation order_notification_schema '
    'order_numbering order_pricing private_storage product_weights safe_images '
    'security_settings style_catalog request_telemetry').split()


def differences(admin, store):
    return [name+'.py' for name in SHARED
        if (admin/(name+'.py')).read_text(encoding='utf-8') != (store/(name+'.py')).read_text(encoding='utf-8')]


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--admin',required=True,type=Path,help='admin-backend directory')
    parser.add_argument('--store',required=True,type=Path,help='storefront-backend directory')
    args=parser.parse_args()
    drift=differences(args.admin,args.store)
    print('Shared modules differ: '+', '.join(drift) if drift else f'All {len(SHARED)} shared modules match')
    raise SystemExit(bool(drift))
