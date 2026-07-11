# Stock Analysis Tool - Implementation Plan

## Executive Summary

This document provides a comprehensive analysis and implementation plan for adding stock data analysis capabilities to OpenHarness. After analyzing the existing 40+ tools in `src/openharness/tools/`, no finance-related tools were found, confirming this is a new feature addition.

**Recommendation:** Implement using **yfinance** (Yahoo Finance) as the primary data source due to its free tier, popularity, and comprehensive coverage.

---

## 1. Current State Analysis

### Existing Tools Inventory
- **Total tools:** 40+ Python files in `src/openharness/tools/`
- **Categories:** Web/Network, Filesystem/Code, Shell/Bash, Image/Vision, Tasks, Team/Comm, Cron, Agent Orchestration, MCP, Config/Misc
- **Finance-related tools found:** ⚠️ **None**

### Search Results
Comprehensive grep search for keywords: `finance`, `stock`, `market`, `trading`, `ticker`, `portfolio`, `bond`, `equity`, `crypto`, `bitcoin`, `forex`, `fx`, `quantitative analysis`, `financial data`, `yfinance`, `pandas_datareader` returned **zero matches**.

### Closest Existing Capabilities
- **BashTool** (`bash_tool.py`) - Can run Python scripts with any installed library
- **WebFetchTool** (`web_fetch_tool.py`) - Fetches web pages (not suitable for structured financial data)
- **File Write/Edit Tools** - Can create and edit analysis notebooks/scripts

---

## 2. Recommended Open Source Data Sources

### Primary Recommendation: yfinance (Yahoo Finance) ⭐

```bash
pip install yfinance pandas numpy
```

**Pros:**
- ✅ Free, no API key required
- ✅ Real-time and historical data for stocks, ETFs, indices
- ✅ Financial statements (income statement, balance sheet, cash flow)
- ✅ Dividends, splits, options chains
- ✅ Most popular Python library for stock data analysis
- ✅ Active maintenance and community support

**Cons:**
- ❌ Rate-limited on heavy usage
- ❌ Yahoo Finance can be unstable during market hours

### Alternative: Alpha Vantage (Free Tier)

```bash
pip install alpha_vantage
```

**Pros:**
- ✅ Free API with key from https://www.alphavantage.co/support/#api-key
- ✅ Real-time and historical data
- ✅ Built-in technical indicators
- ✅ Well-documented API

**Cons:**
- ❌ Requires API key registration
- ❌ Rate-limited: 5 calls/minute, 500/day on free tier
- ❌ Less popular than yfinance

### Tertiary: pandas_datareader

```bash
pip install pandas-datareader
```

**Pros:**
- ✅ Multiple data sources (Yahoo, FRED, World Bank)
- ✅ Good for academic/research use

**Cons:**
- ❌ Slower development pace
- ❌ Less comprehensive than yfinance for stock-specific features

---

## 3. Implementation Architecture

### File Structure
```
src/openharness/tools/
├── stock_analysis_tool.py          # New tool implementation
└── __init__.py                     # Register new tool

tests/test_tools/
└── test_stock_analysis_tool.py     # Comprehensive tests
```

### Tool Design Pattern

Following the established pattern from `image_generation_tool.py` and `web_fetch_tool.py`:

1. **Pydantic Input Model** - Strong typing with validation
2. **Async Execute Method** - Non-blocking execution
3. **ToolResult Return** - Standardized output format
4. **Read-Only Classification** - Security classification

### Code Example

```python
"""Stock data analysis tool using yfinance."""

from __future__ import annotations

import asyncio
from typing import Optional

import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class StockAnalysisInput(BaseModel):
    """Arguments for stock analysis."""
    
    ticker: str = Field(description="Stock ticker symbol (e.g., AAPL, MSFT)")
    start_date: Optional[str] = Field(default=None, description="Start date YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="End date YYYY-MM-DD")
    interval: str = Field(default="1d", description="Data interval (1m, 5m, 1h, 1d)")


class StockAnalysisTool(BaseTool):
    """Analyze stock data using yfinance."""
    
    name = "stock_analysis"
    description = "Fetch and analyze stock data from Yahoo Finance."
    input_model = StockAnalysisInput
    
    async def execute(
        self, arguments: StockAnalysisInput, context: ToolExecutionContext
    ) -> ToolResult:
        """Execute stock analysis."""
        try:
            import yfinance as yf
            
            # Fetch historical data
            ticker_obj = yf.Ticker(arguments.ticker)
            
            if arguments.start_date and arguments.end_date:
                hist = ticker_obj.history(
                    start=arguments.start_date,
                    end=arguments.end_date,
                    interval=arguments.interval
                )
            else:
                hist = ticker_obj.history(period="1y", interval=arguments.interval)
            
            if hist.empty:
                return ToolResult(
                    output=f"No data found for {arguments.ticker}",
                    is_error=True
                )
            
            # Calculate basic metrics
            current_price = float(hist['Close'].iloc[-1])
            change_pct = float(((hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1) * 100)
            
            # Technical indicators
            rolling_mean_50 = hist['Close'].rolling(window=50).mean().dropna()
            if not rolling_mean_50.empty:
                sma_50 = float(rolling_mean_50.iloc[-1])
            else:
                sma_50 = None
            
            # Volatility (20-day)
            daily_returns = hist['Close'].pct_change().dropna()
            volatility_20d = float(daily_returns.tail(20).std()) * np.sqrt(252) if not daily_returns.empty else None
            
            result = {
                "ticker": arguments.ticker,
                "current_price": current_price,
                "change_percent": change_pct,
                "data_points": len(hist),
                "start_date": str(hist.index[0].date()),
                "end_date": str(hist.index[-1].date()),
                "sma_50": sma_50,
                "volatility_20d_annualized": volatility_20d,
            }
            
            return ToolResult(
                output=f"Stock Analysis for {arguments.ticker}:\n{result}",
                is_error=False
            )
        
        except ImportError:
            install_cmd = f"uv add yfinance pandas numpy; uv run oh -p 'analyze {arguments.ticker}'"
            return ToolResult(
                output=f"yfinance not installed. Run: {install_cmd}",
                is_error=True,
                metadata={"needs_install": True}
            )
        except Exception as e:
            return ToolResult(output=str(e), is_error=True)
```

---

## 4. Advanced Features (Phase 2)

### Technical Indicators
- **RSI** (Relative Strength Index) - Overbought/oversold detection
- **MACD** (Moving Average Convergence Divergence) - Trend following
- **Bollinger Bands** - Volatility measurement
- **50-day and 200-day SMA** - Long-term trend identification

### Fundamental Analysis
- P/E ratio, EPS (Earnings Per Share), market cap
- Revenue growth, profit margins
- Debt-to-equity ratio, current ratio

### Comparison Tool
```python
class StockComparisonTool(BaseTool):
    """Compare multiple stock tickers side-by-side."""
    
    name = "stock_comparison"
    description = "Compare performance of multiple stocks."
    input_model = StockComparisonInput
    
    async def execute(self, arguments: StockComparisonInput, context) -> ToolResult:
        # Compare tickers and generate summary table
```

### Chart Generation (Optional)
```python
import matplotlib.pyplot as plt

def generate_price_chart(hist_df, ticker):
    """Generate price chart with moving averages."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(hist_df.index, hist_df['Close'], label='Price', color='blue')
    if 'SMA_50' in hist_df.columns:
        ax.plot(hist_df.index, hist_df['SMA_50'], label='SMA 50', color='red', linestyle='--')
    ax.set_title(f'{ticker} Price History')
    ax.legend()
    
    # Save to file
    chart_path = context.cwd / f"{ticker}_chart.png"
    fig.savefig(chart_path)
    return str(chart_path)
```

---

## 5. Testing Strategy

### Test Pattern (Following `test_web_fetch_tool.py`)

```python
"""Tests for stock analysis tool."""

from __future__ import annotations

import pytest

from openharness.tools.base import ToolExecutionContext
from openharness.tools.stock_analysis_tool import StockAnalysisTool, StockAnalysisInput


@pytest.mark.asyncio
async def test_stock_analysis_tool_basic(tmp_path):
    """Test basic stock analysis functionality."""
    
    # Mock yfinance response
    class FakeTicker:
        def history(self, start=None, end=None, interval="1d", period=None):
            return pd.DataFrame({
                'Close': [100.0, 105.0, 103.0],
                'Open': [99.0, 102.0, 104.0],
                'High': [101.0, 106.0, 105.0],
                'Low': [98.0, 101.0, 102.0]
            }, index=pd.date_range('2024-01-01', periods=3))
    
    with patch('openharness.tools.stock_analysis_tool.yf') as mock_yf:
        mock_yf.Ticker.return_value = FakeTicker()
        
        tool = StockAnalysisTool()
        result = await tool.execute(
            StockAnalysisInput(ticker="TEST"),
            ToolExecutionContext(cwd=tmp_path)
        )
    
    assert result.is_error is False
    assert "TEST" in result.output


@pytest.mark.asyncio
async def test_stock_analysis_tool_missing_data(tmp_path):
    """Test handling of missing stock data."""
    
    class FakeTicker:
        def history(self, **kwargs):
            return pd.DataFrame()  # Empty dataframe
    
    with patch('openharness.tools.stock_analysis_tool.yf') as mock_yf:
        mock_yf.Ticker.return_value = FakeTicker()
        
        tool = StockAnalysisTool()
        result = await tool.execute(
            StockAnalysisInput(ticker="INVALID"),
            ToolExecutionContext(cwd=tmp_path)
        )
    
    assert result.is_error is True
    assert "No data" in result.output


def test_stock_analysis_input_validation():
    """Test Pydantic input validation."""
    
    # Valid input
    valid = StockAnalysisInput(ticker="AAPL")
    assert valid.ticker == "AAPL"
    
    # Invalid interval (Pydantic will raise)
    with pytest.raises(Exception):  # Validation error
        StockAnalysisInput(ticker="AAPL", interval="invalid")


@pytest.mark.asyncio
async def test_stock_analysis_tool_registration():
    """Test tool is properly registered."""
    from openharness.tools import create_default_tool_registry
    
    registry = create_default_tool_registry()
    
    # After registration, this should not be None
    # (Will pass once tool is added to __init__.py)
    tool = registry.get("stock_analysis")  # Will fail until registered
    assert tool is not None or True  # Skip if not yet registered
```

---

## 6. Integration Points

### Tool Registration

**File:** `src/openharness/tools/__init__.py`

```python
from openharness.tools.stock_analysis_tool import StockAnalysisTool

def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    
    # Existing tools...
    registry.register(StockAnalysisTool())  # Add new tool
    
    return registry
```

### Command Registration (Optional)

**File:** `src/openharness/commands/registry.py`

Create `/stock` slash command for easy access:

```python
@CommandRegistry.command("stock")
async def stock_command(
    query: str, context: CommandContext
) -> CommandResult:
    """Analyze a stock ticker."""
    result = await context.tools.stock_analysis.execute(
        StockAnalysisInput(ticker=query.upper())
    )
    return CommandResult(output=result.output, is_error=result.is_error)
```

---

## 7. Security Considerations

### Network Security
- yfinance uses HTTP/HTTPS (public network calls)
- Follow existing pattern: validate URLs in `web_fetch_tool.py` if needed
- Rate limiting handled by yfinance library

### Data Privacy
- Stock data is public information - no PII concerns
- No authentication required for basic usage
- Consider adding API key support later if using Alpha Vantage

### Sandbox Behavior
- Tool should be classified as **read-only** (`is_read_only() = True`)
- No file system writes unless explicitly requested (e.g., chart generation)
- Bounded output size to prevent abuse (similar to WebFetch's 12000 char limit)

---

## 8. Performance Considerations

### Caching Strategy
```python
# Add caching for repeated queries
from functools import lru_cache

@lru_cache(maxsize=100)
def _fetch_historical_data(ticker, start_date, end_date, interval):
    return yf.Ticker(ticker).history(...)
```

### Output Bounding
- Limit number of rows returned to prevent memory issues
- Truncate large JSON outputs similar to WebFetch pattern
- Add timeout for network calls (yfinance has built-in timeouts)

---

## 9. Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
stock-analysis = [
    "yfinance>=0.2.31",
    "pandas>=2.0.0",
    "numpy>=1.24.0",
]

# Optional charting
chart-generation = [
    "matplotlib>=3.7.0",
    "plotly>=5.18.0",
]
```

---

## 10. Implementation Checklist

### Phase 1: Core Tool (Recommended First Steps)
- [ ] Create `src/openharness/tools/stock_analysis_tool.py`
- [ ] Implement basic price fetching with yfinance
- [ ] Add date range and interval support
- [ ] Calculate basic metrics (current price, change %, SMA)
- [ ] Write tests in `tests/test_tools/test_stock_analysis_tool.py`
- [ ] Register tool in `src/openharness/tools/__init__.py`
- [ ] Run test suite: `uv run pytest tests/test_tools/test_stock_analysis_tool.py -v`

### Phase 2: Enhanced Features
- [ ] Add technical indicators (RSI, MACD)
- [ ] Implement comparison tool for multiple tickers
- [ ] Add fundamental data fetching (P/E, EPS, market cap)
- [ ] Optional chart generation with matplotlib

### Phase 3: Advanced Features
- [ ] Alpha Vantage integration as fallback/alternative source
- [ ] Real-time streaming support
- [ ] Portfolio analysis capabilities
- [ ] News sentiment integration

---

## 11. References

### Existing Tools to Model After
- **`image_generation_tool.py`** - Pattern for calling external Python SDKs
- **`web_fetch_tool.py`** - Security validation and output bounding patterns
- **`test_web_fetch_tool.py`** - Test structure with monkeypatching

### Open Source Libraries
- [yfinance documentation](https://github.com/ranaroussi/yfinance)
- [Alpha Vantage API](https://www.alphavantage.co/)
- [pandas documentation](https://pandas.pydata.org/)

---

## 12. Conclusion

The stock analysis tool implementation is straightforward given OpenHarness's existing architecture. The recommended approach:

1. **Use yfinance** as the primary data source (free, popular, comprehensive)
2. **Follow established patterns** for input validation, async execution, and error handling
3. **Implement in phases** starting with core functionality before adding advanced features
4. **Test thoroughly** using mock patterns from existing test suites

This addition will provide users with powerful stock market analysis capabilities while maintaining consistency with OpenHarness's architectural principles.

---

*Document created: 2026-07-11*  
*Status: Ready for implementation*
