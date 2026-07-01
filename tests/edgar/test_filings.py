import hashlib
import pytest
from unittest.mock import patch, MagicMock
from tearsheet.edgar.filings import locate_filing, acquire_filing

HISTORY = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077"],
            "form": ["10-K", "10-Q"],
            "primaryDocument": ["aapl-20230930.htm", "aapl-20230701.htm"]
        }
    }
}

INDEX = {
    "directory": {
        "item": [
            {"name": "aapl-20230930.htm", "type": "text.htm", "size": "100"},
            {"name": "ex21.htm", "type": "EX-21", "size": "20"},
            {"name": "images", "type": "dir", "size": ""},
        ]
    }
}

FILES = {
    "aapl-20230930.htm": b"<html>10-K content</html>",
    "ex21.htm": b"<html>subsidiaries</html>",
}


def _make_client(files):
    client = MagicMock()
    client.get_json.return_value = INDEX

    def _get(url):
        name = url.rsplit("/", 1)[-1]
        resp = MagicMock()
        resp.content = files[name]
        return resp

    client.get.side_effect = _get
    return client


@patch("tearsheet.edgar.filings.get_filing_history")
def test_locate_filing(mock_get_history):
    mock_get_history.return_value = HISTORY

    metadata = locate_filing("320193", "10-K")
    assert metadata["accessionNumber"] == "0000320193-23-000106"
    assert metadata["primaryDocument"] == "aapl-20230930.htm"
    assert metadata["form"] == "10-K"


@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.edgar.filings.get_filing_history")
def test_acquire_archives_all_documents_with_hashes(mock_get_history, mock_get_client, tmp_path):
    mock_get_history.return_value = HISTORY
    mock_get_client.return_value = _make_client(FILES)

    result = acquire_filing("320193", "0000320193-23-000106", cache_dir=tmp_path)

    accession_dir = tmp_path / "320193" / "0000320193-23-000106"
    assert result["primary_document"] == "aapl-20230930.htm"
    assert result["primary_path"] == accession_dir / "aapl-20230930.htm"
    assert len(result["documents"]) == 2  # directory entry skipped

    for doc in result["documents"]:
        path = accession_dir / doc["filename"]
        assert path.exists()
        assert path.read_bytes() == FILES[doc["filename"]]
        assert doc["sha256"] == hashlib.sha256(FILES[doc["filename"]]).hexdigest()
        assert doc["byte_size"] == len(FILES[doc["filename"]])
        assert doc["edgar_url"].endswith(doc["filename"])


@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.edgar.filings.get_filing_history")
def test_acquire_second_call_downloads_nothing(mock_get_history, mock_get_client, tmp_path):
    mock_get_history.return_value = HISTORY
    client = _make_client(FILES)
    mock_get_client.return_value = client

    first = acquire_filing("320193", "0000320193-23-000106", cache_dir=tmp_path)
    known_hashes = {d["filename"]: d["sha256"] for d in first["documents"]}
    assert client.get.call_count == 2

    client.get.reset_mock()
    second = acquire_filing(
        "320193", "0000320193-23-000106", cache_dir=tmp_path, known_hashes=known_hashes
    )

    client.get.assert_not_called()
    assert {d["filename"]: d["sha256"] for d in second["documents"]} == known_hashes


@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.edgar.filings.get_filing_history")
def test_tampered_file_is_redownloaded(mock_get_history, mock_get_client, tmp_path):
    mock_get_history.return_value = HISTORY
    client = _make_client(FILES)
    mock_get_client.return_value = client

    first = acquire_filing("320193", "0000320193-23-000106", cache_dir=tmp_path)
    known_hashes = {d["filename"]: d["sha256"] for d in first["documents"]}

    tampered = tmp_path / "320193" / "0000320193-23-000106" / "ex21.htm"
    tampered.write_bytes(b"<html>tampered</html>")

    client.get.reset_mock()
    second = acquire_filing(
        "320193", "0000320193-23-000106", cache_dir=tmp_path, known_hashes=known_hashes
    )

    assert client.get.call_count == 1
    assert tampered.read_bytes() == FILES["ex21.htm"]
    ex21 = next(d for d in second["documents"] if d["filename"] == "ex21.htm")
    assert ex21["sha256"] == known_hashes["ex21.htm"]


@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.edgar.filings.get_filing_history")
def test_same_filename_different_ciks_do_not_collide(mock_get_history, mock_get_client, tmp_path):
    mock_get_history.side_effect = lambda cik: {
        "filings": {
            "recent": {
                "accessionNumber": [f"{cik}-23-000001"],
                "form": ["10-K"],
                "primaryDocument": ["form10-k.htm"]
            }
        }
    }

    index = {"directory": {"item": [{"name": "form10-k.htm", "type": "text.htm"}]}}
    contents = {"111": b"<html>company one</html>", "222": b"<html>company two</html>"}

    def _client_for(cik):
        client = MagicMock()
        client.get_json.return_value = index

        def _get(url):
            resp = MagicMock()
            resp.content = contents[cik]
            return resp

        client.get.side_effect = _get
        return client

    mock_get_client.return_value = _client_for("111")
    acquire_filing("111", "111-23-000001", cache_dir=tmp_path)
    mock_get_client.return_value = _client_for("222")
    acquire_filing("222", "222-23-000001", cache_dir=tmp_path)

    path_one = tmp_path / "111" / "111-23-000001" / "form10-k.htm"
    path_two = tmp_path / "222" / "222-23-000001" / "form10-k.htm"
    assert path_one.read_bytes() == b"<html>company one</html>"
    assert path_two.read_bytes() == b"<html>company two</html>"


@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.edgar.filings.get_filing_history")
def test_acquire_unknown_accession_raises(mock_get_history, mock_get_client, tmp_path):
    mock_get_history.return_value = HISTORY
    mock_get_client.return_value = _make_client(FILES)

    with pytest.raises(ValueError, match="not found"):
        acquire_filing("320193", "9999999999-99-999999", cache_dir=tmp_path)
