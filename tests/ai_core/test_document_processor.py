import sys
import os
from unittest.mock import patch

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class TestDocumentProcessor:
    """Tests for DocumentProcessor RAG functionality"""

    def test_init_without_api_key_disables_rag(self):
        """Test that RAG is disabled when no API key is set"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=True):
            with patch("ai_core.document_processor.logger") as mock_logger:
                from ai_core.document_processor import DocumentProcessor
                processor = DocumentProcessor(doc_path="nonexistent_path")
                assert processor.vector_store is None

    def test_init_creates_directory_if_not_exists(self, tmp_path):
        """Test that document directory is created if it doesn't exist"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test_key"}, clear=True):
            with patch("ai_core.document_processor.NVIDIAEmbeddings"):
                from ai_core.document_processor import DocumentProcessor
                doc_path = str(tmp_path / "new_docs")
                processor = DocumentProcessor(doc_path=doc_path, collection_name="test")
                assert os.path.exists(doc_path)

    def test_retrieve_returns_empty_for_empty_query(self):
        """Test that retrieve returns empty string for empty query"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test_key"}, clear=True):
            with patch("ai_core.document_processor.NVIDIAEmbeddings"):
                from ai_core.document_processor import DocumentProcessor
                processor = DocumentProcessor(doc_path="nonexistent", collection_name="test")
                result = processor.retrieve_documents("")
                assert result == ""

    def test_retrieve_returns_empty_for_nonexistent_store(self):
        """Test that retrieve returns empty when vector store is None"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=True):
            with patch("ai_core.document_processor.logger"):
                from ai_core.document_processor import DocumentProcessor
                processor = DocumentProcessor(doc_path="nonexistent", collection_name="test")
                result = processor.retrieve_documents("test query")
                assert result == ""

    def test_add_memory_returns_early_for_none_store(self):
        """Test that add_memory returns early if vector store is None"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=True):
            with patch("ai_core.document_processor.logger"):
                from ai_core.document_processor import DocumentProcessor
                processor = DocumentProcessor(doc_path="nonexistent", collection_name="test")
                # Should not raise error
                processor.add_memory("test memory", {"caller_id": "123"})

    def test_index_returns_early_for_none_store(self):
        """Test that index_documents returns early if vector store is None"""
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=True):
            with patch("ai_core.document_processor.logger"):
                from ai_core.document_processor import DocumentProcessor
                processor = DocumentProcessor(doc_path="nonexistent", collection_name="test")
                # Should not raise error
                processor.index_documents()
