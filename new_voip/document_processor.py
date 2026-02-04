import os
import logging
import rich.logging
from typing import List
import hashlib
import time

from langchain_community.document_loaders import PyPDFLoader, TextLoader, UnstructuredMarkdownLoader, UnstructuredWordDocumentLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

os.environ["ANONYMIZED_TELEMETRY"]= "False"

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger("RAG")

class DocumentProcessor:
    def __init__(self, doc_path: str = "knowledge_base", collection_name: str = "phoneguy_brain"):
        # ИСПРАВЛЕНИЕ: Используем абсолютный путь от места запуска скрипта
        # Это надежнее, чем вычислять через __file__
        self.doc_path = os.path.abspath(doc_path)
        
        # 1. Сразу создаем папку, если её нет
        try:
            if not os.path.exists(self.doc_path):
                os.makedirs(self.doc_path, exist_ok=True)
                logger.info(f"📁 Created folder for documents: '{self.doc_path}'")
            else:
                logger.info(f"📁 Documents folder found: '{self.doc_path}'")
        except Exception as e:
            logger.error(f"❌ Failed to create folder: {e}")
        
        # Проверяем ключ
        if not os.getenv("NVIDIA_API_KEY"):
            logger.warning("⚠️ No NVIDIA_API_KEY found. RAG will be disabled.")
            self.vector_store = None
            return

        try:
            self.embeddings = NVIDIAEmbeddings(
                model="nvidia/llama-3.2-nemoretriever-300m-embed-v2",
                base_url=os.getenv("NVIDIA_API_BASE") or "https://integrate.api.nvidia.com/v1",
                nvidia_api_key=os.getenv("NVIDIA_API_KEY")
            )
        except Exception as e:
            logger.error(f"Failed to init Embeddings: {e}")
            self.vector_store = None
            return

        self.persist_directory = os.path.abspath(f"chroma_db/{collection_name}")
        
        # Инициализация ChromaDB
        try:
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
                self.index_documents()
        except Exception as e:
            logger.error(f"❌ Error initializing ChromaDB: {e}")
            self.vector_store = None
            return

    def index_documents(self):
        """Читает документы и добавляет в базу"""
        if self.vector_store is None: return
        logger.info(f"🔍 Starting indexing form: {self.doc_path}")

        documents = []
        # Расширенный список форматов
        loaders = {
            '.pdf': PyPDFLoader,
            '.txt': TextLoader,
            '.md': UnstructuredMarkdownLoader
        }
        
        for filename in os.listdir(self.doc_path):
            ext = os.path.splitext(filename)[1].lower()
            if ext in loaders:
                filepath = os.path.join(self.doc_path, filename)
                logger.info(f"📖 Reading: {filename}")
                try:
                    loader = loaders[ext](filepath)
                    documents.extend(loader.load())
                except Exception as e:
                    logger.error(f"Error reading {filename}: {e}")
        
        if not documents:
            logger.warning(f"No documents found in {self.doc_path}")
            return

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
        chunks = text_splitter.split_documents(documents)
        logger.info(f"🧩 Split into {len(chunks)} chunks.")
        
        # Пакетное добавление (стабильнее)
        batch_size = 10
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            try:
                self.vector_store.add_documents(batch)
            except Exception as e:
                logger.error(f"Error adding batch {i}: {e}")
                
        logger.info("✅ Indexing complete.")

    def retrieve_documents(self, query: str, k: int = 2) -> str:
        if not self.vector_store or not query:
            return ""
        
        try:
            logger.info(f"🔍 RAG Search: '{query}'")
            docs = self.vector_store.similarity_search(query, k=k)
            if not docs: return ""
            
            # Формируем красивый контекст
            context = "\n".join([f"- {d.page_content}" for d in docs])
            return context
        except Exception as e:
            logger.error(f"RAG Error: {e}")
            return ""