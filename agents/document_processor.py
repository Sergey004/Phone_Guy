# bot/document_processor.py

import os
import logging
import rich.logging
from typing import List

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import os
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self, doc_path: str, embedding_model_name: str = "nvidia/llama-3.2-nemoretriever-300m-embed-v1", collection_name: str = "tech_docs_collection"):
        self.doc_path = doc_path
        self.embeddings = NVIDIAEmbeddings(
            model=embedding_model_name,
            base_url=os.getenv("NVIDIA_API_BASE"),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY")
        )
        self.persist_directory = f"./chroma_db/{collection_name}"
        if os.path.exists(self.persist_directory):
            logger.info(f"Loading existing Chroma collection from {self.persist_directory}")
            self.vector_store = Chroma(persist_directory=self.persist_directory, collection_name=collection_name, embedding_function=self.embeddings)
        else:
            logger.info(f"Creating new Chroma collection and persisting to {self.persist_directory}")
            self.vector_store = Chroma(collection_name=collection_name, embedding_function=self.embeddings, persist_directory=self.persist_directory)
            self.vector_store.persist()

    def load_and_split_documents(self) -> List[Document]:
        """Loads PDF documents from the specified path and splits them into chunks."""
        documents = []
        for filename in os.listdir(self.doc_path):
            if filename.endswith(".pdf"):
                filepath = os.path.join(self.doc_path, filename)
                logger.info(f"Loading document: {filepath}")
                loader = PyPDFLoader(filepath)
                documents.extend(loader.load())
        
        if not documents:
            logger.warning(f"No PDF documents found in {self.doc_path}")
            return []

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            add_start_index=True,
        )
        chunks = text_splitter.split_documents(documents)
        logger.info(f"Split {len(documents)} documents into {len(chunks)} chunks.")
        return chunks

    def index_documents(self):
        """Loads, splits, and indexes documents into the vector store."""
        chunks = self.load_and_split_documents()
        if chunks:
            logger.info(f"Adding {len(chunks)} chunks to vector store.")
            self.vector_store.add_documents(chunks)
            logger.info("Documents indexed successfully.")
        else:
            logger.warning("No chunks to index.")

    def retrieve_documents(self, query: str, k: int = 3) -> List[Document]:
        """Retrieves top-k relevant documents from the vector store based on the query."""
        if not query:
            return []
        logger.info(f"Retrieving top {k} documents for query: {query}")
        docs = self.vector_store.similarity_search(query, k=k)
        logger.info(f"Retrieved {len(docs)} documents.")
        return docs

# Example usage (for testing purposes, can be removed later)
if __name__ == "__main__":
    # Ensure you have a .env file with OPENAI_API_KEY
    from dotenv import load_dotenv
    load_dotenv()

    # Create a dummy Docs folder and a dummy PDF file for testing
    dummy_doc_path = "../../uploads/Docs"
    os.makedirs(dummy_doc_path, exist_ok=True)
    with open(os.path.join(dummy_doc_path, "test_doc.pdf"), "w") as f:
        f.write("This is a test document. It contains information about AI assistants and their capabilities.")

    processor = DocumentProcessor(doc_path=dummy_doc_path)
    processor.index_documents()
    
    query = "What are AI assistants?"
    retrieved_docs = processor.retrieve_documents(query)
    for doc in retrieved_docs:
        print(f"Content: {doc.page_content}\nSource: {doc.metadata.get("source")}")