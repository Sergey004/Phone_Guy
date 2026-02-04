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
        # Получаем путь к корню проекта (родительская папка new_voip)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.doc_path = os.path.join(project_root, doc_path)
        
        # Создаём папку для документов сразу, независимо от состояния базы
        if not os.path.exists(self.doc_path):
            os.makedirs(self.doc_path)
            logger.info(f"📁 Created folder '{self.doc_path}' for PDF files")
        
        # Проверяем, есть ли ключ
        if not os.getenv("NVIDIA_API_KEY"):
            logger.warning("⚠️ No NVIDIA_API_KEY found. RAG will be disabled.")
            self.vector_store = None
            return

        try:
            self.embeddings = NVIDIAEmbeddings(
                model="nvidia/llama-3.2-nemoretriever-300m-embed-v2",  # Обновлено на v2
                base_url=os.getenv("NVIDIA_API_BASE") or "https://integrate.api.nvidia.com/v1",
                nvidia_api_key=os.getenv("NVIDIA_API_KEY")
            )
        except Exception as e:
            logger.error(f"Failed to init Embeddings: {e}")
            self.vector_store = None
            return

        self.persist_directory = os.path.join(project_root, f"chroma_db/{collection_name}")
        
        # Инициализация ChromaDB
        try:
            if os.path.exists(self.persist_directory) and os.listdir(self.persist_directory):
                logger.info(f"📂 Loading existing knowledge base from {self.persist_directory}")
                self.vector_store = Chroma(
                    persist_directory=self.persist_directory, 
                    collection_name=collection_name, 
                    embedding_function=self.embeddings
                )
                logger.info(f"✅ Chroma loaded: {type(self.vector_store)}, is None: {self.vector_store is None}")
            else:
                logger.info(f"🆕 Creating new knowledge base in {self.persist_directory}")
                self.vector_store = Chroma(
                    collection_name=collection_name, 
                    embedding_function=self.embeddings, 
                    persist_directory=self.persist_directory
                )
                logger.info(f"✅ Chroma initialized: {type(self.vector_store)}, is None: {self.vector_store is None}")
                # Если база новая - сразу индексируем файлы
                self.index_documents()
        except Exception as e:
            logger.error(f"❌ Error initializing ChromaDB: {e}")
            self.vector_store = None
            return

    def index_documents(self):
        """Читает документы разных форматов из папки и добавляет в базу с retry логикой"""
        if self.vector_store is None: 
            logger.warning("Vector store not initialized, skipping indexing")
            return
        logger.info(f"🔍 Starting indexing...")

        if not os.path.exists(self.doc_path):
            os.makedirs(self.doc_path)
            logger.warning(f"Created folder '{self.doc_path}'. Put documents there!")
            return

        documents = []
        supported_extensions = {
            '.pdf': PyPDFLoader,
            '.md': UnstructuredMarkdownLoader,
            '.docx': UnstructuredWordDocumentLoader,
            '.txt': TextLoader
        }
        
        for filename in os.listdir(self.doc_path):
            # Пропускаем скрытые файлы и Windows метаданные
            if filename.startswith('.') or filename == '.gitkeep' or ':Zone.Identifier' in filename:
                continue
            
            file_ext = os.path.splitext(filename)[1].lower()
            if not file_ext:
                continue
                
            filepath = os.path.join(self.doc_path, filename)
            
            if file_ext in supported_extensions:
                logger.info(f"📖 Reading: {filename}")
                loader_class = supported_extensions[file_ext]
                try:
                    loader = loader_class(filepath)
                    documents.extend(loader.load())
                except Exception as e:
                    logger.error(f"Error reading {filename}: {e}")
            else:
                logger.warning(f"⚠️ Unsupported file type: {filepath} (extension: {file_ext})")
        
        if not documents:
            logger.warning("No documents found to index. Supported formats: PDF, TXT, MD, DOCX")
            return

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            add_start_index=True,
        )
        chunks = text_splitter.split_documents(documents)
        logger.info(f"🧩 Split {len(documents)} documents into {len(chunks)} chunks.")
        
        # Генерируем уникальные ID для каждого chunk
        chunk_ids = [
            hashlib.sha256(
                (chunk.page_content + str(chunk.metadata)).encode()
            ).hexdigest()
            for chunk in chunks
        ]
        
        # Проверяем подключение к embeddings API
        try:
            if self.embeddings:
                _ = self.embeddings.embed_query("ping")
                logger.info("✅ Embeddings API connectivity check passed")
        except Exception as e:
            logger.error(f"❌ Embeddings connectivity check failed: {e}")
            return
        
        # Пакетная загрузка с retry логикой
        batch_size = 8
        added_count = 0
        logger.info(f"📝 Adding {len(chunks)} chunks to vector store in batches of {batch_size}...")
        
        for start in range(0, len(chunks), batch_size):
            end = min(start + batch_size, len(chunks))
            batch = chunks[start:end]
            batch_ids = chunk_ids[start:end]
            attempts = 0
            
            while attempts < 3:
                try:
                    self.vector_store.add_documents(batch, ids=batch_ids)
                    # Явно сохраняем
                    try:
                        self.vector_store.persist()
                    except Exception as e:
                        logger.warning(f"Persist warning (non-critical): {e}")
                    
                    added_count += len(batch)
                    logger.info(f"✅ Batch {start}-{end} added successfully ({added_count}/{len(chunks)})")
                    break
                except Exception as e:
                    attempts += 1
                    logger.error(f"❌ Error adding batch {start}-{end} (attempt {attempts}/3): {e}")
                    if attempts < 3:
                        time.sleep(2)
            
            # Если все попытки неудачны, пробуем по одному документу
            if attempts >= 3:
                logger.warning(f"⚠️ Batch failed, trying individual documents...")
                for i, doc in enumerate(batch):
                    doc_attempts = 0
                    while doc_attempts < 3:
                        try:
                            self.vector_store.add_documents([doc], ids=[batch_ids[i]])
                            try:
                                self.vector_store.persist()
                            except Exception:
                                pass
                            added_count += 1
                            logger.info(f"✅ Document {start+i} added individually")
                            break
                        except Exception as e:
                            doc_attempts += 1
                            logger.error(f"❌ Error adding doc {start+i} (attempt {doc_attempts}/3): {e}")
                            if doc_attempts < 3:
                                time.sleep(2)
            
            time.sleep(0.5)  # Небольшая пауза между батчами
        
        logger.info(f"✅ Indexing complete: {added_count}/{len(chunks)} chunks indexed.")

    def retrieve_documents(self, query: str, k: int = 3) -> str:
        """Возвращает текст релевантных документов одной строкой с retry логикой"""
        if not self.vector_store or not query:
            return ""
        
        context_text = ""
        for attempt in range(3):
            try:
                logger.info(f"🔍 Searching knowledge base for: '{query}' (attempt {attempt+1})")
                docs = self.vector_store.similarity_search(query, k=k)
                
                if not docs:
                    logger.warning("⚠️ No relevant documents found")
                    return ""
                
                # Собираем контекст
                context_text = "\n\n".join([f"[File: {os.path.basename(d.metadata.get('source', 'Unknown'))}]\n{d.page_content}" for d in docs])
                logger.info(f"✅ Found {len(docs)} relevant documents")
                return context_text
                
            except Exception as e:
                logger.error(f"❌ RAG Search failed (attempt {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(1)
        
        return ""

    def reindex_documents(self):
        """Принудительное переиндексирование всех документов"""
        logger.info("🔄 Reindexing all documents...")
        self.index_documents()