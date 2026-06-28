import pytest
from unittest.mock import MagicMock, patch
from tearsheet.store.models import Document, QualitativeFact, Citation, Filing
from tearsheet.extract.schemas import RiskList, RiskFactor
from tearsheet.extract.qualitative import extract_risk_factors, _chunk_text


class TestSemanticChunking:
    """Semantic chunker and large-document extraction tests.

    - [ ] **Chunker units:** a short text → exactly one chunk; a >40k-char text → multiple chunks, each ≤ 40k; assert consecutive chunks share overlap; assert no chunk cuts a paragraph except the logged oversized-paragraph fallback.
    - [ ] **Anti-split:** craft a risk paragraph positioned to straddle a boundary; assert it appears whole in the next chunk's overlap and grounds to a single global span.
    - [ ] **Offset integrity:** with a multi-chunk doc, assert every accepted `start/end_offset` indexes into `document.text` such that `document.text[start:end]` equals the stored `quote` (proves global, not chunk-local, offsets).
    - [ ] **Dedup:** mock the LLM to emit the same risk from two overlapping chunks (incl. a summary-drift variant grounding to the same span); assert `dedupe_by_span` yields one fact with one citation; assert a second `save_qualitative_facts` call is an idempotent no-op (no `IntegrityError`).
    - [ ] **No-overflow regression:** feed an NVDA-sized (>100k char) synthetic Item 1A; assert it no longer raises and produces grounded facts.
    - [ ] Run full suite — all green, zero network calls.
    """

    def test_chunk_text_boundaries(self):
        # 1. Short text -> exactly one chunk
        short_text = "Just one paragraph."
        chunks = _chunk_text(short_text, chunk_size=100, overlap=20)
        assert len(chunks) == 1
        assert chunks[0] == short_text

        # 2. Multiple chunks with exact paragraph splits and overlap
        # 5 paragraphs, each 30 chars. chunk_size=100, overlap=20
        # p1+p2+p3 = 90. +p4 = 120 (breaks).
        # chunk 1: p1, p2, p3
        # overlap = p3 (30 chars) -> > 20, so keeps p3
        # chunk 2: p3, p4, p5
        text = "A"*28 + ".\n\n" + "B"*28 + ".\n\n" + "C"*28 + ".\n\n" + "D"*28 + ".\n\n" + "E"*28 + ".\n\n"
        chunks = _chunk_text(text, chunk_size=100, overlap=20)
        
        assert len(chunks) == 2
        assert chunks[0] == "A"*28 + ".\n\n" + "B"*28 + ".\n\n" + "C"*28 + ".\n\n"
        assert chunks[1] == "C"*28 + ".\n\n" + "D"*28 + ".\n\n" + "E"*28 + ".\n\n"

        # 3. Oversized paragraph fallback
        text_large = "A"*150
        chunks_l = _chunk_text(text_large, chunk_size=100, overlap=20)
        assert len(chunks_l) == 2
        assert len(chunks_l[0]) == 100
        assert chunks_l[0] == "A"*100
        assert chunks_l[1] == "A"*50

    def test_chunk_text_ceiling_enforcement(self):
        # Create an edge case where overlap + next paragraph strictly exceeds chunk_size.
        # chunk_size = 100, overlap = 20
        # p1 = 30, p2 = 60, p3 = 30, p4 = 90
        # Chunk 2 will end with p3 (30). Overlap for Chunk 3 will be p3 (30 chars > 20).
        # Next is p4 (90). Overlap + p4 = 30 + 90 = 120 > 100.
        # It must drop p3 from the overlap to fit p4.
        text = "A"*28 + ".\n\n" + "B"*58 + ".\n\n" + "C"*28 + ".\n\n" + "D"*88 + ".\n\n"
        chunks = _chunk_text(text, chunk_size=100, overlap=20)
        
        for i, c in enumerate(chunks):
            assert len(c) <= 100, f"Chunk {i} exceeded max size: {len(c)}"
            
        assert chunks[0] == "A"*28 + ".\n\n" + "B"*58 + ".\n\n"
        assert chunks[1] == "B"*58 + ".\n\n" + "C"*28 + ".\n\n"
        # C is dropped from overlap to ensure D fits
        assert chunks[2] == "D"*88 + ".\n\n"

    def test_extract_risk_factors_large_document(self):
        # Create a document > 100k characters (e.g. 101k)
        prefix = "A" * 40000 + "\n\n"
        risk_text = "We face significant large document risks."
        suffix = "\n\n" + "B" * 65000
        
        full_text = prefix + risk_text + suffix
        assert len(full_text) > 100000
        
        from tearsheet.store.models import Filing, Document
        filing = Filing(company_id=10)
        doc = Document(id=42, filing=filing, text=full_text, section="1A")
        
        # Setup mock LLM Client to return the SAME risk multiple times
        # simulating it being found in consecutive overlapping chunks.
        mock_llm = MagicMock()
        mock_llm.complete_structured.return_value = RiskList(risks=[
            RiskFactor(summary="Large Document Risk", exact_quote="large document risks.")
        ])
        
        with patch("tearsheet.extract.qualitative._load_prompt", return_value="Test prompt"):
            facts = extract_risk_factors(doc, llm=mock_llm)
            
        # Ensure it didn't crash
        # The LLM mock will be called multiple times (for each chunk)
        # Because we return the same quote, the grounding gate will find it at the exact same global offset.
        # Dedupe should catch it and return only 1 fact.
        assert len(facts) == 1
        
        fact = facts[0]
        assert fact.summary == "Large Document Risk"
        assert len(fact.citations) == 1
        
        cit = fact.citations[0]
        assert cit.quote == "large document risks."
        
        # Verify the offset is globally correct
        expected_start = full_text.find("large document risks.")
        assert cit.start_offset == expected_start
        assert full_text[cit.start_offset:cit.end_offset] == "large document risks."
        
        # Verify LLM was called multiple times due to chunking
        assert mock_llm.complete_structured.call_count > 1


def test_extract_risk_factors():
    # Setup mock document
    filing = Filing(company_id=10)
    doc = Document(id=42, filing=filing, text="We face significant liquidity risks.", section="1A")
    
    # Setup mock LLM Client
    mock_llm = MagicMock()
    
    # Return a RiskList with one valid and one hallucinated quote
    mock_llm.complete_structured.return_value = RiskList(risks=[
        RiskFactor(summary="Liquidity", exact_quote="liquidity risks."),
        RiskFactor(summary="Market", exact_quote="market volatility risks.") # Hallucination
    ])
    
    # Call orchestrator
    with patch("tearsheet.extract.qualitative._load_prompt", return_value="Test prompt"):
        facts = extract_risk_factors(doc, llm=mock_llm)
    
    # Verify only the grounded fact is returned
    assert len(facts) == 1
    fact = facts[0]
    assert fact.category == "risk_factor"
    assert fact.summary == "Liquidity"
    assert fact.company_id == 10
    
    assert len(fact.citations) == 1
    citation = fact.citations[0]
    assert citation.quote == "liquidity risks."
    assert citation.document_id == 42
    assert citation.start_offset == 20
    assert citation.end_offset == 36

def test_extract_risk_factors_validations():
    mock_llm = MagicMock()
    
    # Unpersisted document
    doc1 = Document(id=None, filing=Filing(company_id=10), text="valid", section="1A")
    with pytest.raises(ValueError, match="must be persisted"):
        extract_risk_factors(doc1, llm=mock_llm)
        
    # Missing filing/company_id
    doc2 = Document(id=42, filing=None, text="valid", section="1A")
    with pytest.raises(ValueError, match="valid filing and company_id"):
        extract_risk_factors(doc2, llm=mock_llm)
