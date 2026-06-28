"""Terminal interface for Tearsheet."""

import argparse
import sys
import logging
from tearsheet.pipeline import ExecutionPipeline

def _setup_logging():
    # Only show info logs to user, hide debug
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def main():
    parser = argparse.ArgumentParser(description="Tearsheet: Autonomous SEC 10-K Analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    run_parser = subparsers.add_parser("run", help="Run extraction for a specific ticker")
    run_parser.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL)")
    
    args = parser.parse_args()
    
    if args.command == "run":
        _setup_logging()
        print(f"Starting Tearsheet for {args.ticker.upper()}...")
        try:
            pipeline = ExecutionPipeline()
            facts = pipeline.run_for_ticker(args.ticker)
            
            print("\n" + "="*50)
            print(f"VERIFIED RISK FACTORS FOR {args.ticker.upper()}")
            print("="*50)
            
            if not facts:
                print("No qualitative risk factors found.")
            else:
                for i, fact in enumerate(facts, 1):
                    print(f"\n{i}. {fact.summary}")
                    if fact.citations:
                        print(f"   > \"{fact.citations[0].quote}\"")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"\nError: {str(e)}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
