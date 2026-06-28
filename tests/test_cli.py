import pytest
import sys
from unittest.mock import patch, MagicMock
from tearsheet.cli import main

@patch("tearsheet.cli.ExecutionPipeline")
def test_cli_run_success(mock_pipeline_cls, capsys):
    # Mock pipeline
    mock_pipeline = MagicMock()
    
    # Create mock qualitative facts
    mock_fact = MagicMock()
    mock_fact.summary = "Global pandemic risk"
    
    mock_citation = MagicMock()
    mock_citation.quote = "We might be affected by viruses."
    mock_fact.citations = [mock_citation]
    
    mock_pipeline.run_for_ticker.return_value = [mock_fact]
    mock_pipeline_cls.return_value = mock_pipeline
    
    with patch.object(sys, 'argv', ['tearsheet', 'run', 'MSFT']):
        main()
        
    captured = capsys.readouterr()
    assert "Global pandemic risk" in captured.out
    assert "We might be affected by viruses." in captured.out
    mock_pipeline.run_for_ticker.assert_called_once_with("MSFT")


@patch("tearsheet.cli.ExecutionPipeline")
def test_cli_run_failure(mock_pipeline_cls, capsys):
    mock_pipeline = MagicMock()
    mock_pipeline.run_for_ticker.side_effect = ValueError("Ticker MSFT not found in SEC map.")
    mock_pipeline_cls.return_value = mock_pipeline
    
    with patch.object(sys, 'argv', ['tearsheet', 'run', 'MSFT']):
        # Suppress SystemExit
        try:
            main()
        except SystemExit:
            pass
            
    captured = capsys.readouterr()
    assert "Ticker MSFT not found" in captured.err
