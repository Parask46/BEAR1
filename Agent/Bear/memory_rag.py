import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings

# Define paths based on BEAR structure
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
MEMORY_LONG_DIR = os.path.join(BEAR_ROOT, "MEMORY", "MEMORY-LONG")
CHROMA_DB_DIR = os.path.join(BEAR_ROOT, "MEMORY", "chroma_db")

def update_vector_db():
    """Reads all markdown files in MEMORY-LONG and updates ChromaDB."""
    loader = DirectoryLoader(MEMORY_LONG_DIR, glob="**/*.md", loader_cls=TextLoader)
    docs = loader.load()
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_documents(docs)
    
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vector_db = Chroma.from_documents(
        documents=chunks, 
        embedding=embeddings, 
        persist_directory=CHROMA_DB_DIR
    )
    return vector_db

def get_relevant_memory(query: str, k: int = 3):
    """Retrieves relevant past memories based on semantic search."""
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vector_db = Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=embeddings)
    results = vector_db.similarity_search(query, k=k)
    return "\n\n".join([doc.page_content for doc in results])