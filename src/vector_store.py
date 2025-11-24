"""Vector store module with Elasticsearch integration"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from elasticsearch import Elasticsearch
from langchain.schema import Document
from langchain_elasticsearch import ElasticsearchStore

from src.config import config
from src.models import EmbeddingModel

logger = structlog.get_logger(__name__)


class VectorStore:
    """Vector store with Elasticsearch backend and hybrid search"""

    def __init__(self):
        """Initialize vector store"""
        self.config = config.es_config
        self.embedding_model = EmbeddingModel()
        
        # Initialize Elasticsearch client
        es_hosts = self.config.get('hosts', ['http://localhost:9200'])
        es_username = self.config.get('username', '')
        es_password = self.config.get('password', '')
        
        self.es_client = Elasticsearch(
            es_hosts,
            basic_auth=(es_username, es_password) if es_username else None,
            timeout=self.config.get('timeout', 30),
            max_retries=self.config.get('max_retries', 3),
            retry_on_timeout=self.config.get('retry_on_timeout', True),
        )
        
        self.index_name = self.config.get('index_name', 'aiops_knowledge_base')
        
        # Initialize LangChain Elasticsearch store
        self.store = ElasticsearchStore(
            es_connection=self.es_client,
            index_name=self.index_name,
            embedding=self.embedding_model.get_langchain_embeddings(),
            vector_query_field="content_vector",
        )
        
        logger.info("vector_store_initialized", index_name=self.index_name)
    
    def add_documents(
        self,
        documents: List[Document],
        batch_size: int = 50
    ) -> List[str]:
        """
        Add documents to vector store
        
        Args:
            documents: List of documents to add
            batch_size: Batch size for bulk indexing
        
        Returns:
            List of document IDs
        """
        try:
            logger.info("starting_document_validation", total_documents=len(documents))
            
            # Validate and clean documents
            valid_documents = []
            for idx, doc in enumerate(documents):
                logger.debug(
                    "validating_document",
                    doc_index=idx,
                    content_type=type(doc.page_content).__name__,
                    content_length=len(doc.page_content) if hasattr(doc.page_content, '__len__') else 'N/A',
                    has_metadata=bool(doc.metadata)
                )
                
                # Ensure page_content is a non-empty string
                if not isinstance(doc.page_content, str):
                    logger.warning(
                        "converting_document_content_to_string",
                        doc_index=idx,
                        original_type=type(doc.page_content).__name__
                    )
                    doc.page_content = str(doc.page_content)
                
                # Skip empty documents
                if not doc.page_content.strip():
                    logger.warning(
                        "skipping_empty_document",
                        doc_index=idx,
                        metadata=doc.metadata
                    )
                    continue
                
                # Add indexed_at timestamp
                doc.metadata['indexed_at'] = datetime.utcnow().isoformat()
                
                valid_documents.append(doc)
                logger.debug(
                    "document_validated",
                    doc_index=idx,
                    content_length=len(doc.page_content)
                )
            
            if not valid_documents:
                logger.warning("no_valid_documents_to_index")
                return []
            
            logger.info("validation_complete", valid_documents=len(valid_documents), skipped=len(documents) - len(valid_documents))
            
            # Add documents in batches
            ids = []
            logger.info("starting_batch_indexing", total_batches=(len(valid_documents) + batch_size - 1) // batch_size)
            
            for i in range(0, len(valid_documents), batch_size):
                batch = valid_documents[i:i + batch_size]
                batch_num = i // batch_size + 1
                
                logger.info(
                    "indexing_batch",
                    batch_num=batch_num,
                    batch_size=len(batch),
                    total_docs=len(valid_documents)
                )
                
                try:
                    # Log first document in batch for debugging
                    logger.debug(
                        "batch_first_doc",
                        batch_num=batch_num,
                        content_length=len(batch[0].page_content),
                        content_preview=batch[0].page_content[:100],
                        metadata_keys=list(batch[0].metadata.keys())
                    )
                    
                    # Try to add the batch
                    logger.info("calling_langchain_add_documents", batch_size=len(batch))
                    batch_ids = self.store.add_documents(batch)
                    ids.extend(batch_ids)
                    
                    logger.info(
                        "batch_indexed_successfully",
                        batch_num=batch_num,
                        batch_size=len(batch),
                        num_ids=len(batch_ids),
                        sample_ids=batch_ids[:3] if batch_ids else []
                    )
                except Exception as batch_error:
                    # If batch fails, try adding documents one by one
                    logger.error(
                        "batch_indexing_failed",
                        batch_num=batch_num,
                        error=str(batch_error),
                        error_type=type(batch_error).__name__
                    )
                    logger.warning("retrying_documents_individually", batch_size=len(batch))
                    
                    for doc_idx, doc in enumerate(batch):
                        try:
                            logger.debug("indexing_single_document", doc_index=doc_idx, content_length=len(doc.page_content))
                            doc_ids = self.store.add_documents([doc])
                            ids.extend(doc_ids)
                            logger.debug("single_document_indexed", doc_index=doc_idx, doc_ids=doc_ids)
                        except Exception as doc_error:
                            logger.error(
                                "single_document_indexing_failed",
                                doc_index=doc_idx,
                                error=str(doc_error),
                                error_type=type(doc_error).__name__,
                                content_preview=doc.page_content[:100]
                            )
            
            logger.info("documents_added", total_docs=len(ids), attempted=len(valid_documents))
            
            return ids
        
        except Exception as e:
            logger.error("document_indexing_failed", error=str(e), num_docs=len(documents))
            raise
    
    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Perform similarity search
        
        Args:
            query: Search query
            k: Number of results to return
            filter_dict: Metadata filters
        
        Returns:
            List of matching documents
        """
        try:
            results = self.store.similarity_search(
                query=query,
                k=k,
                filter=filter_dict
            )
            
            logger.info("similarity_search_completed", query=query, num_results=len(results))
            
            return results
        
        except Exception as e:
            logger.error("similarity_search_failed", error=str(e), query=query)
            raise
    
    def hybrid_search(
        self,
        query: str,
        k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
        vector_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search (vector + BM25)
        
        Args:
            query: Search query
            k: Number of results to return
            filter_dict: Metadata filters
            vector_weight: Weight for vector search (default from config)
            bm25_weight: Weight for BM25 search (default from config)
        
        Returns:
            List of matching documents with scores
        """
        hybrid_config = self.config.get('hybrid_search', {})
        vector_weight = vector_weight or hybrid_config.get('vector_weight', 0.7)
        bm25_weight = bm25_weight or hybrid_config.get('bm25_weight', 0.3)
        
        try:
            # Get vector search results
            vector_query = self.embedding_model.embed_text(query)
            
            # Build ES query
            query_body = {
                "size": k,
                "query": {
                    "bool": {
                        "should": [
                            {
                                "script_score": {
                                    "query": {"match_all": {}},
                                    "script": {
                                        "source": f"cosineSimilarity(params.query_vector, 'content_vector') * {vector_weight}",
                                        "params": {"query_vector": vector_query}
                                    }
                                }
                            },
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["text^2", "metadata.description"],  # LangChain uses 'text' field
                                    "type": "best_fields",
                                    "boost": bm25_weight
                                }
                            }
                        ]
                    }
                },
                "highlight": {
                    "fields": {
                        "text": {
                            "fragment_size": 150,
                            "number_of_fragments": 3,
                            "pre_tags": ["<mark>"],
                            "post_tags": ["</mark>"]
                        },
                        "metadata.description": {
                            "fragment_size": 150,
                            "number_of_fragments": 1,
                            "pre_tags": ["<mark>"],
                            "post_tags": ["</mark>"]
                        }
                    }
                }
            }
            
            # Add filters if provided
            if filter_dict:
                query_body["query"]["bool"]["filter"] = [
                    {"term": {f"metadata.{k}": v}} for k, v in filter_dict.items()
                ]
            
            # Execute search
            response = self.es_client.search(
                index=self.index_name,
                body=query_body
            )
            
            # Parse results
            results = []
            for hit in response['hits']['hits']:
                # Get highlighted text if available
                highlighted_text = None
                if 'highlight' in hit:
                    if 'text' in hit['highlight']:
                        highlighted_text = ' ... '.join(hit['highlight']['text'])
                    elif 'metadata.description' in hit['highlight']:
                        highlighted_text = ' ... '.join(hit['highlight']['metadata.description'])
                
                source = hit['_source']
                results.append({
                    'id': hit['_id'],
                    'score': hit['_score'],
                    'content': source.get('text', ''),  # LangChain uses 'text' field
                    'content_snippet': source.get('text', '')[:500],  # Content snippet
                    'highlighted': highlighted_text,  # Highlighted fragments
                    'metadata': source.get('metadata', {}),
                    # Page-level fields
                    'document_name': source.get('document_name', ''),
                    'page_number': source.get('page_number', 1),
                    'total_pages': source.get('total_pages', 1),
                    'page_type': source.get('page_type', 'text'),
                    'page_json': source.get('original_content', {}),
                    # Searchable fields
                    'drawing_number': source.get('drawing_number', ''),
                    'project_name': source.get('project_name', ''),
                    'equipment_tags': source.get('equipment_tags', []),
                    'component_details': source.get('component_details', []),
                })
            
            logger.info(
                "hybrid_search_completed",
                query=query,
                num_results=len(results),
                vector_weight=vector_weight,
                bm25_weight=bm25_weight
            )
            
            return results
        
        except Exception as e:
            logger.error("hybrid_search_failed", error=str(e), query=query)
            raise
    
    def delete_by_metadata(self, filter_dict: Dict[str, Any]) -> int:
        """
        Delete documents by metadata filter
        
        Args:
            filter_dict: Metadata filters
        
        Returns:
            Number of documents deleted
        """
        try:
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {f"metadata.{k}": v}} for k, v in filter_dict.items()
                        ]
                    }
                }
            }
            
            response = self.es_client.delete_by_query(
                index=self.index_name,
                body=query
            )
            
            deleted_count = response.get('deleted', 0)
            
            logger.info("documents_deleted", filter=filter_dict, count=deleted_count)
            
            return deleted_count
        
        except Exception as e:
            logger.error("delete_failed", error=str(e), filter=filter_dict)
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get index statistics
        
        Returns:
            Dictionary containing index stats
        """
        try:
            # Check if index exists
            if not self.es_client.indices.exists(index=self.index_name):
                return {
                    'document_count': 0,
                    'index_size_bytes': 0,
                    'categories': [],
                    'file_types': []
                }
            
            # Get document count
            try:
                count_response = self.es_client.count(index=self.index_name)
                doc_count = count_response['count']
            except Exception:
                doc_count = 0
            
            # Get index stats
            try:
                stats = self.es_client.indices.stats(index=self.index_name)
                index_stats = stats['indices'][self.index_name]
                size_bytes = index_stats['total']['store']['size_in_bytes']
            except Exception:
                size_bytes = 0
            
            # Get aggregations for categories (try both with and without metadata prefix)
            categories = []
            file_types = []
            
            if doc_count > 0:
                try:
                    agg_query = {
                        "size": 0,
                        "aggs": {
                            "categories": {
                                "terms": {"field": "metadata.category", "size": 10, "missing": "uncategorized"}
                            },
                            "file_types": {
                                "terms": {"field": "metadata.file_type", "size": 10, "missing": "unknown"}
                            }
                        }
                    }
                    
                    agg_response = self.es_client.search(
                        index=self.index_name,
                        body=agg_query
                    )
                    
                    categories = [
                        {'name': b['key'], 'count': b['doc_count']}
                        for b in agg_response['aggregations']['categories']['buckets']
                    ]
                    
                    file_types = [
                        {'name': b['key'], 'count': b['doc_count']}
                        for b in agg_response['aggregations']['file_types']['buckets']
                    ]
                except Exception as e:
                    logger.warning("aggregation_failed", error=str(e))
            
            return {
                'document_count': doc_count,
                'index_size_bytes': size_bytes,
                'categories': categories,
                'file_types': file_types
            }
        
        except Exception as e:
            logger.error("stats_retrieval_failed", error=str(e))
            # Return empty stats instead of raising
            return {
                'document_count': 0,
                'index_size_bytes': 0,
                'categories': [],
                'file_types': []
            }
    
    def search_component(
        self,
        component_id: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for pages containing specific component
        
        Args:
            component_id: Component ID to search for (e.g., "C1", "V-2001", "R100")
            k: Number of results to return
            filter_dict: Additional metadata filters
        
        Returns:
            List of matching pages with component information
        """
        try:
            query_body = {
                "size": k,
                "query": {
                    "bool": {
                        "should": [
                            # Exact match in equipment tags
                            {"term": {"equipment_tags": component_id}},
                            # Match in component details (nested)
                            {
                                "nested": {
                                    "path": "component_details",
                                    "query": {
                                        "term": {"component_details.id": component_id}
                                    }
                                }
                            },
                            # Match in all_components field
                            {"match": {"all_components": component_id}},
                            # Fuzzy match in text
                            {
                                "match": {
                                    "text": {
                                        "query": component_id,
                                        "fuzziness": "AUTO"
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                }
            }
            
            # Add additional filters
            if filter_dict:
                query_body["query"]["bool"]["filter"] = [
                    {"term": {f"metadata.{k}": v}} for k, v in filter_dict.items()
                ]
            
            # Execute search
            response = self.es_client.search(
                index=self.index_name,
                body=query_body
            )
            
            # Parse results
            results = []
            for hit in response['hits']['hits']:
                source = hit['_source']
                
                # Find matched components in this page
                matched_components = []
                if 'component_details' in source:
                    matched_components = [
                        c for c in source['component_details']
                        if c.get('id', '').lower() == component_id.lower()
                    ]
                
                results.append({
                    'id': hit['_id'],
                    'score': hit['_score'],
                    'document_name': source.get('document_name', ''),
                    'page_number': source.get('page_number', 1),
                    'total_pages': source.get('total_pages', 1),
                    'page_type': source.get('page_type', 'text'),
                    'content_snippet': source.get('text', '')[:500],
                    'page_json': source.get('original_content', {}),
                    'matched_components': matched_components,
                    'drawing_number': source.get('drawing_number', ''),
                    'project_name': source.get('project_name', ''),
                    'metadata': source.get('metadata', {})
                })
            
            logger.info(
                "component_search_completed",
                component_id=component_id,
                num_results=len(results)
            )
            
            return results
        
        except Exception as e:
            logger.error("component_search_failed", error=str(e), component_id=component_id)
            raise

