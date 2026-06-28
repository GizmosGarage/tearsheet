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

    render_parser = subparsers.add_parser(
        "render",
        help="Render a Markdown dossier from stored data (no network)",
    )
    render_parser.add_argument("ticker", help="Stock ticker symbol (e.g. NVDA)")
    render_parser.add_argument(
        "--out",
        metavar="FILE",
        help="Also write dossier to this path (e.g. data/dossiers/NVDA.md)",
    )

    args = parser.parse_args()
    
    if args.command == "run":
        _setup_logging()
        print(f"Starting Tearsheet for {args.ticker.upper()}...")
        try:
            pipeline = ExecutionPipeline()
            result = pipeline.run_for_ticker(args.ticker)
            facts = result.get("qualitative_facts", [])
            fin_facts = result.get("financial_facts", [])
            errors = result.get("errors", [])
            
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
                        
            print("\n" + "="*50)
            print(f"FINANCIAL FACTS SUMMARY: {len(fin_facts)} rows extracted")
            if errors:
                print("ERRORS:")
                for e in errors:
                    print(f" - {e}")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"\nError: {str(e)}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "render":
        from tearsheet.writer.dossier import build_dossier
        import os
        
        dossier_text = build_dossier(args.ticker)
        if not dossier_text:
            print(f"Error: No data found for ticker {args.ticker.upper()}. Please run extraction first (tearsheet run {args.ticker.upper()}).", file=sys.stderr)
            sys.exit(1)
            
        if args.out:
            out_dir = os.path.dirname(args.out)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(dossier_text)
            print(f"Dossier written to {args.out}")
        else:
            print(dossier_text)

if __name__ == "__main__":
    main()
