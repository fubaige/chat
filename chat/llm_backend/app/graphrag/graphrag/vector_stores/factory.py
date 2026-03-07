# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""A package containing a factory and supported vector store types."""

from enum import Enum
from typing import ClassVar

try:
    from graphrag.vector_stores.azure_ai_search import AzureAISearchVectorStore
except ImportError:
    AzureAISearchVectorStore = None

from graphrag.vector_stores.base import BaseVectorStore

try:
    from graphrag.vector_stores.cosmosdb import CosmosDBVectoreStore
except ImportError:
    CosmosDBVectoreStore = None

try:
    # 优先使用项目内版本，确保 connect 逻辑和表名匹配
    from app.graphrag.graphrag.vector_stores.lancedb import LanceDBVectorStore
except ImportError:
    try:
        from graphrag.vector_stores.lancedb import LanceDBVectorStore
    except ImportError:
        LanceDBVectorStore = None


class VectorStoreType(str, Enum):
    """The supported vector store types."""

    LanceDB = "lancedb"
    AzureAISearch = "azure_ai_search"
    CosmosDB = "cosmosdb"


class VectorStoreFactory:
    """A factory for vector stores.

    Includes a method for users to register a custom vector store implementation.
    """

    vector_store_types: ClassVar[dict[str, type]] = {}

    @classmethod
    def register(cls, vector_store_type: str, vector_store: type):
        """Register a custom vector store implementation."""
        cls.vector_store_types[vector_store_type] = vector_store

    @classmethod
    def create_vector_store(
        cls, vector_store_type: VectorStoreType | str, kwargs: dict
    ) -> BaseVectorStore:
        """Create or get a vector store from the provided type."""
        match vector_store_type:
            case VectorStoreType.LanceDB:
                if LanceDBVectorStore is None:
                    msg = "LanceDB is not installed. Please install lancedb and pyarrow."
                    raise ImportError(msg)
                return LanceDBVectorStore(**kwargs)
            case VectorStoreType.AzureAISearch:
                if AzureAISearchVectorStore is None:
                    msg = "Azure AI Search is not installed. Please install azure-search-documents and azure-identity."
                    raise ImportError(msg)
                return AzureAISearchVectorStore(**kwargs)
            case VectorStoreType.CosmosDB:
                if CosmosDBVectoreStore is None:
                    msg = "CosmosDB is not installed. Please install azure-cosmos and azure-identity."
                    raise ImportError(msg)
                return CosmosDBVectoreStore(**kwargs)
            case _:
                if vector_store_type in cls.vector_store_types:
                    return cls.vector_store_types[vector_store_type](**kwargs)
                msg = f"Unknown vector store type: {vector_store_type}"
                raise ValueError(msg)
