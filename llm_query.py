import json
import os
import logging

# # if use huggingface API
# from llama_index.llms.huggingface_api import HuggingFaceInferenceAPI
# from llama_index.embeddings.huggingface_api import HuggingFaceInferenceAPIEmbedding

# if use local LLM
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, StorageContext, load_index_from_storage, Document
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.node_parser import SentenceSplitter
import chromadb

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RAGSystem:
    # Constants
    COLLECTION_NAME = "doc"
    DB_PATH = "chroma_db"  # Path to store the ChromaDB database
    CHAT_HISTORY_DIR = "chat_histories"

    def __init__(self):
        # Global variables to store initialized models
        self.chroma_client = None
        self.vector_store = None
        self.index = None

    def initialize_rag(self, api_token, embedding_model, llm_model, chunk_size, chunk_overlap, role):
        """    
        Initializes a RAG database (ChromaDB) system with the given parameters.

        Args:
            api_token (str): API token for authentication with the LLM and embedding model services.
            embedding_model (str): Name or identifier of the embedding model used for vectorization.
            llm_model (str): Name or identifier of the large language model used for generating responses.
            chunk_size (int): Size of each text chunk (number of characters or tokens).
            chunk_overlap (int): Number of overlapping characters or tokens between consecutive chunks.
            role (str): The role or persona that the RAG system should assume when generating responses.

        Returns:
            None or an initialized RAG system object (depending on the implementation).
        """    
        # Set up text splitter
        text_splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        # # Set up Hugging Face LLM
        # Settings.llm = HuggingFaceInferenceAPI(
        #     model_name=llm_model,
        #     token=api_token,
        # )
        # define LLM
        Settings.llm = Ollama(model=llm_model, request_timeout=500.0)  # Replace with your Ollama model

        # # Set up Hugging Face embedding model
        # Settings.embed_model = HuggingFaceInferenceAPIEmbedding(
        #     model_name=embedding_model,
        #     token=api_token,
        # )
        # define embedding model (you can also use Ollama for embeddings if supported)
        Settings.embed_model = HuggingFaceEmbedding(model_name=embedding_model)

        # Store settings
        Settings.chunk_size = chunk_size
        Settings.text_splitter = text_splitter


        # Check if the index exists (check before init the Chroma database)
        index_exists = os.path.lexists(self.DB_PATH) and os.path.isdir(self.DB_PATH) and os.listdir(self.DB_PATH)
        
        # Initialize ChromaDB client
        self.chroma_client = chromadb.PersistentClient(self.DB_PATH)  # Persistent storage

        # Create/retrieve the collection
        chroma_collection = self.chroma_client.get_or_create_collection(name=self.COLLECTION_NAME)

        # Set up the vector store
        self.vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        # === Friendly reminder regarding storage_context ===
        #
        # if index exists, then please include argument persist_dir for when creating StorageContext
        # else, dont include the argument persist_dir, since we have just created it
        # 
        # https://github.com/run-llama/llama_index/issues/9110#issuecomment-1841522080

        if index_exists:
            # load existing index
            logger.info("Loading existing index...")
                        
            # Create a StorageContext
            storage_context = StorageContext.from_defaults(vector_store=self.vector_store, persist_dir=self.DB_PATH)    

            # load the existing index from storage
            self.index = load_index_from_storage(storage_context)  # Now safe to call

        else:
            # create a new index
            logger.info("Creating a new index...")

            # Create a StorageContext
            storage_context = StorageContext.from_defaults(vector_store=self.vector_store)    

            # Load documents via SimpleDirectoryReader
            documents = SimpleDirectoryReader("documents").load_data()

            # load the documents as Vector Store Index
            self.index = VectorStoreIndex.from_documents(documents, storage_context=storage_context, transformations=[text_splitter])
            
        # Persist the updated database
        self.index.storage_context.persist(self.DB_PATH)

    
    def update(self, filename):
        """Update the index with the new documents"""
        import uuid
        new_documents = SimpleDirectoryReader(input_files=[filename]).load_data()
        new_nodes = Settings.text_splitter.get_nodes_from_documents(new_documents)
        for node in new_nodes:
            # Create a unique document ID for each node
            doc_id = str(uuid.uuid4()) # temporary fix, will think how to create the ID soon
            # Convert the TextNode into a Document with required attributes
            new_doc = Document(text=node.text, doc_id=doc_id, metadata=node.metadata)
            self.index.insert(new_doc)
        self.index.storage_context.persist(self.DB_PATH)


    def hugging_face_query(self, prompt, role):
        """Query the preloaded RAG index instead of rebuilding it."""
        if self.index is None:
            return "Error: Index has not been initialized. Call initialize_rag() first."
        query_engine = self.index.as_query_engine()
        response = query_engine.query(prompt)
        return response.response  # Ensure we return only the text response
