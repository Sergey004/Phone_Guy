import os
import logging
import rich.logging
from typing import List

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger("RAG")

class DocumentProcessor:
    def __init__(self, doc_path: str = "knowledge_base", collection_name: str = "phoneguy_brain"):
        self.doc_path = doc_path
        
        # Проверяем, есть ли ключ
        if not os.getenv("NVIDIA_API_KEY"):
            logger.warning("⚠️ No NVIDIA_API_KEY found. RAG will be disabled.")
            self.vector_store = None
            return

        try:
            self.embeddings = NVIDIAEmbeddings(
                model="nvidia/llama-3.2-nemoretriever-300m-embed-v1", # Актуальная модель эмбеддингов
                model_type="passage",
                nvidia_api_key=os.getenv("NVIDIA_API_KEY")
            )
        except Exception as e:
            logger.error(f"Failed to init Embeddings: {e}")
            self.vector_store = None
            return

        self.persist_directory = f"./chroma_db/{collection_name}"
        
        # Инициализация ChromaDB
        if os.path.exists(self.persist_directory) and os.listdir(self.persist_directory):
            logger.info(f"📂 Loading existing knowledge base from {self.persist_directory}")
            self.vector_store = Chroma(
                persist_directory=self.persist_directory, 
                collection_name=collection_name, 
                embedding_function=self.embeddings
            )
        else:
            logger.info(f"🆕 Creating new knowledge base in {self.persist_directory}")
            self.vector_store = Chroma(
                collection_name=collection_name, 
                embedding_function=self.embeddings, 
                persist_directory=self.persist_directory
            )
            # Если база новая - сразу индексируем файлы
            self.index_documents()

    def index_documents(self):
        """Читает PDF из папки и добавляет в базу"""
        if not self.vector_store: return

        if not os.path.exists(self.doc_path):
            os.makedirs(self.doc_path)
            logger.warning(f"Created folder '{self.doc_path}'. Put PDF files there!")
            return

        documents = []
        for filename in os.listdir(self.doc_path):
            if filename.endswith(".pdf"):
                filepath = os.path.join(self.doc_path, filename)
                logger.info(f"📖 Reading: {filename}")
                try:
                    loader = PyPDFLoader(filepath)
                    documents.extend(loader.load())
                except Exception as e:
                    logger.error(f"Error reading {filename}: {e}")
        
        if not documents:
            logger.warning("No PDF documents found to index.")
            return

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=100,
            length_function=len,
        )
        chunks = text_splitter.split_documents(documents)
        logger.info(f"🧩 Split into {len(chunks)} chunks. Indexing...")
        
        self.vector_store.add_documents(chunks)
        # Chroma сохраняет автоматически в последних версиях, но на всякий случай
        # self.vector_store.persist() 
        logger.info("✅ Indexing complete.")

    def retrieve_documents(self, query: str, k: int = 2) -> str:
        """Возвращает текст релевантных документов одной строкой"""
        if not self.vector_store or not query:
            return ""
        
        try:
            # logger.info(f"🔍 Searching knowledge base for: '{query}'")
            docs = self.vector_store.similarity_search(query, k=k)
            
            if not docs:
                return ""
            
            # Собираем контекст
            context_text = "\n\n".join([f"[File: {d.metadata.get('source', 'Unknown')}]\n{d.page_content}" for d in docs])
            return context_text
            
        except Exception as e:
            logger.error(f"RAG Search failed: {e}")
            return ""