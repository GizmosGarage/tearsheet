import pytest
from unittest.mock import patch, MagicMock
from tearsheet.extract.llm_client import LLMClient
from pydantic import BaseModel

class DummyResponse(BaseModel):
    dummy_text: str

def test_llm_client_complete_structured():
    client = LLMClient(api_key="test-key", model="gpt-4o-mini")
    
    with patch("tearsheet.extract.llm_client.OpenAI") as mock_openai_cls:
        # Mock the SDK client
        mock_sdk_client = MagicMock()
        mock_openai_cls.return_value = mock_sdk_client
        
        # We also need to re-initialize client._client since it was initialized in __init__
        # before the patch took effect. Or better, just patch it directly.
        client._client = mock_sdk_client
        
        # Mock the beta.chat.completions.parse return value
        mock_parse = MagicMock()
        mock_sdk_client.beta.chat.completions.parse = mock_parse
        
        mock_message = MagicMock()
        mock_message.parsed = DummyResponse(dummy_text="Parsed result")
        
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        
        mock_parsed_response = MagicMock()
        mock_parsed_response.choices = [mock_choice]
        mock_parse.return_value = mock_parsed_response
        
        # Call the method
        result = client.complete_structured(
            system_prompt="You are a system",
            user_prompt="Do something",
            response_model=DummyResponse
        )
        
        # Verify the result is the parsed object
        assert isinstance(result, DummyResponse)
        assert result.dummy_text == "Parsed result"
        
        # Verify the parse method was called with correct arguments
        mock_parse.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a system"},
                {"role": "user", "content": "Do something"}
            ],
            response_format=DummyResponse,
            temperature=0.0
        )

def test_llm_client_refusal():
    client = LLMClient(api_key="test-key")
    
    with patch("tearsheet.extract.llm_client.OpenAI") as mock_openai_cls:
        mock_sdk_client = MagicMock()
        mock_openai_cls.return_value = mock_sdk_client
        client._client = mock_sdk_client
        
        mock_parse = MagicMock()
        mock_sdk_client.beta.chat.completions.parse = mock_parse
        
        mock_message = MagicMock()
        mock_message.parsed = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        
        mock_parsed_response = MagicMock()
        mock_parsed_response.choices = [mock_choice]
        mock_parse.return_value = mock_parsed_response
        
        with pytest.raises(RuntimeError, match="LLM refused or failed"):
            client.complete_structured(
                system_prompt="sys",
                user_prompt="user",
                response_model=DummyResponse
            )
