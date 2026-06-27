# Tearsheet

SEC EDGAR extraction pipeline: gather filings, parse sections, extract grounded facts with citations.

## Setup

```bash
uv sync
# or: pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and set required variables.

## Usage

```bash
tearsheet run AAPL
```
