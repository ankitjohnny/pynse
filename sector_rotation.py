#!/usr/bin/env python3
"""
Run from repo root:
    KITE_API_KEY=xxx KITE_ACCESS_TOKEN=yyy python sector_rotation.py

Or pass credentials as arguments:
    python sector_rotation.py --api-key xxx --access-token yyy
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from pynse.kite_holdings import sector_rotation_analysis, print_report


def main():
    parser = argparse.ArgumentParser(description="Kite Holdings Sector Rotation Analysis")
    parser.add_argument("--api-key",      help="Kite API key (or set KITE_API_KEY)")
    parser.add_argument("--access-token", help="Kite access token (or set KITE_ACCESS_TOKEN)")
    args = parser.parse_args()

    try:
        result = sector_rotation_analysis(
            api_key=args.api_key,
            access_token=args.access_token,
        )
        print_report(result)
    except ValueError as e:
        print(f"\nCredential error: {e}")
        print("\nHow to get your Kite access token:")
        print("  1. Log in to https://kite.zerodha.com")
        print("  2. Open browser devtools → Network tab")
        print("  3. Look for any API request with 'authorization' header")
        print("  4. The token after 'enctoken ' is your access token")
        print("\nOr use Kite Connect developer API:")
        print("  https://developers.kite.trade/apps")
        sys.exit(1)


if __name__ == "__main__":
    main()
