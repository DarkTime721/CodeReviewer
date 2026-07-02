import chromadb
from chromadb.utils.embedding_functions import EmbeddingFunction
import ollama
import os
from dotenv import load_dotenv

load_dotenv()
chromadb_path = os.getenv("CHROMA_DB_PATH", r"./chroma")
ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

client = chromadb.PersistentClient(path=chromadb_path)


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model="nomic-embed-text", url=ollama_base_url):
        self.model = model
        self.ollama_client = ollama.Client(host=url)
    
    def __call__(self, input):
        response = self.ollama_client.embed(model=self.model, input=input)
        return response['embeddings']
    

collection = OllamaEmbeddingFunction()
