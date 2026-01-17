"""Semantic search system using embeddings, TF-IDF, and cosine similarity."""

from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from collections import Counter
import hashlib
import json


class SearchMethod(Enum):
    """Available search methods."""
    KEYWORD = "keyword"  # Basic keyword matching
    TFIDF = "tfidf"  # TF-IDF with cosine similarity
    EMBEDDING = "embedding"  # Neural embeddings (requires API or local model)
    HYBRID = "hybrid"  # Combination of methods


@dataclass
class DocumentChunk:
    """A chunk of text with metadata for indexing."""
    id: str
    content: str
    source_type: str  # character, place, faction, technology, etc.
    source_name: str
    source_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    tfidf_vector: Optional[Dict[str, float]] = None


@dataclass
class SearchResult:
    """A search result with relevance score."""
    chunk: DocumentChunk
    score: float
    match_type: str  # keyword, semantic, hybrid
    matched_terms: List[str] = field(default_factory=list)


class TFIDFIndex:
    """TF-IDF index for text search with cosine similarity."""

    def __init__(self):
        self.documents: Dict[str, DocumentChunk] = {}
        self.idf_cache: Dict[str, float] = {}
        self.vocab: set = set()
        self._dirty = True

    def add_document(self, chunk: DocumentChunk):
        """Add a document to the index."""
        self.documents[chunk.id] = chunk
        self._dirty = True

    def remove_document(self, doc_id: str):
        """Remove a document from the index."""
        if doc_id in self.documents:
            del self.documents[doc_id]
            self._dirty = True

    def clear(self):
        """Clear all documents from the index."""
        self.documents.clear()
        self.idf_cache.clear()
        self.vocab.clear()
        self._dirty = True

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        # Lowercase and split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r'\b[a-z0-9]+\b', text)
        # Remove very short tokens and stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
                     'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
                     'through', 'during', 'before', 'after', 'above', 'below',
                     'between', 'under', 'again', 'further', 'then', 'once',
                     'here', 'there', 'when', 'where', 'why', 'how', 'all',
                     'each', 'few', 'more', 'most', 'other', 'some', 'such',
                     'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
                     'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because',
                     'until', 'while', 'this', 'that', 'these', 'those', 'it', 'its'}
        return [t for t in tokens if len(t) > 2 and t not in stopwords]

    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        """Compute term frequency (normalized)."""
        if not tokens:
            return {}
        counts = Counter(tokens)
        max_count = max(counts.values())
        return {term: count / max_count for term, count in counts.items()}

    def _rebuild_idf(self):
        """Rebuild IDF cache."""
        if not self._dirty:
            return

        self.vocab.clear()
        doc_freq: Dict[str, int] = {}

        # Count document frequency for each term
        for chunk in self.documents.values():
            tokens = set(self._tokenize(chunk.content))
            self.vocab.update(tokens)
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        # Compute IDF
        n_docs = len(self.documents)
        if n_docs > 0:
            self.idf_cache = {
                term: math.log((n_docs + 1) / (freq + 1)) + 1
                for term, freq in doc_freq.items()
            }

        # Pre-compute TF-IDF vectors for all documents
        for chunk in self.documents.values():
            tokens = self._tokenize(chunk.content)
            tf = self._compute_tf(tokens)
            chunk.tfidf_vector = {
                term: tf_val * self.idf_cache.get(term, 0)
                for term, tf_val in tf.items()
            }

        self._dirty = False

    def _cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """Compute cosine similarity between two sparse vectors."""
        if not vec1 or not vec2:
            return 0.0

        # Find common terms
        common_terms = set(vec1.keys()) & set(vec2.keys())

        if not common_terms:
            return 0.0

        # Compute dot product
        dot_product = sum(vec1[t] * vec2[t] for t in common_terms)

        # Compute magnitudes
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[DocumentChunk, float, List[str]]]:
        """Search for documents matching the query.

        Returns:
            List of (chunk, score, matched_terms) tuples
        """
        self._rebuild_idf()

        if not self.documents:
            return []

        # Compute query TF-IDF
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        query_tf = self._compute_tf(query_tokens)
        query_tfidf = {
            term: tf_val * self.idf_cache.get(term, 0)
            for term, tf_val in query_tf.items()
        }

        # Score all documents
        results = []
        for chunk in self.documents.values():
            if chunk.tfidf_vector:
                score = self._cosine_similarity(query_tfidf, chunk.tfidf_vector)
                if score > 0.01:  # Minimum threshold
                    # Find matched terms
                    matched = [t for t in query_tokens if t in chunk.tfidf_vector]
                    results.append((chunk, score, matched))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


class EmbeddingIndex:
    """Index using neural embeddings for semantic search."""

    def __init__(self, embedding_fn: Optional[Callable[[str], List[float]]] = None):
        """Initialize embedding index.

        Args:
            embedding_fn: Function that takes text and returns embedding vector
        """
        self.documents: Dict[str, DocumentChunk] = {}
        self.embedding_fn = embedding_fn
        self._embedding_dim: Optional[int] = None

    def set_embedding_function(self, fn: Callable[[str], List[float]]):
        """Set the embedding function."""
        self.embedding_fn = fn

    def add_document(self, chunk: DocumentChunk, compute_embedding: bool = True):
        """Add a document to the index."""
        if compute_embedding and self.embedding_fn and not chunk.embedding:
            try:
                chunk.embedding = self.embedding_fn(chunk.content[:2000])  # Limit length
                if chunk.embedding and self._embedding_dim is None:
                    self._embedding_dim = len(chunk.embedding)
            except Exception as e:
                print(f"Failed to compute embedding: {e}")

        self.documents[chunk.id] = chunk

    def remove_document(self, doc_id: str):
        """Remove a document from the index."""
        if doc_id in self.documents:
            del self.documents[doc_id]

    def clear(self):
        """Clear all documents."""
        self.documents.clear()

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = math.sqrt(sum(a * a for a in vec1))
        mag2 = math.sqrt(sum(b * b for b in vec2))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[DocumentChunk, float]]:
        """Search for semantically similar documents.

        Returns:
            List of (chunk, score) tuples
        """
        if not self.embedding_fn:
            return []

        try:
            query_embedding = self.embedding_fn(query)
        except Exception as e:
            print(f"Failed to compute query embedding: {e}")
            return []

        if not query_embedding:
            return []

        results = []
        for chunk in self.documents.values():
            if chunk.embedding:
                score = self._cosine_similarity(query_embedding, chunk.embedding)
                if score > 0.3:  # Semantic similarity threshold
                    results.append((chunk, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


class SemanticSearchEngine:
    """Unified semantic search engine combining multiple methods."""

    def __init__(self):
        self.tfidf_index = TFIDFIndex()
        self.embedding_index = EmbeddingIndex()
        self._document_hashes: Dict[str, str] = {}  # Track content changes

    def set_embedding_function(self, fn: Callable[[str], List[float]]):
        """Set the embedding function for semantic search."""
        self.embedding_index.set_embedding_function(fn)

    def _compute_hash(self, content: str) -> str:
        """Compute hash of content for change detection."""
        return hashlib.md5(content.encode()).hexdigest()

    def index_document(self, chunk: DocumentChunk, compute_embedding: bool = False):
        """Index a document for search.

        Args:
            chunk: The document chunk to index
            compute_embedding: Whether to compute neural embeddings (slower)
        """
        # Check if content changed
        content_hash = self._compute_hash(chunk.content)
        if chunk.id in self._document_hashes:
            if self._document_hashes[chunk.id] == content_hash:
                return  # No change, skip re-indexing

        self._document_hashes[chunk.id] = content_hash

        # Add to both indices
        self.tfidf_index.add_document(chunk)
        self.embedding_index.add_document(chunk, compute_embedding)

    def remove_document(self, doc_id: str):
        """Remove a document from all indices."""
        self.tfidf_index.remove_document(doc_id)
        self.embedding_index.remove_document(doc_id)
        if doc_id in self._document_hashes:
            del self._document_hashes[doc_id]

    def clear(self):
        """Clear all indices."""
        self.tfidf_index.clear()
        self.embedding_index.clear()
        self._document_hashes.clear()

    def search(
        self,
        query: str,
        method: SearchMethod = SearchMethod.HYBRID,
        top_k: int = 10,
        source_types: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """Search for relevant documents.

        Args:
            query: Search query
            method: Search method to use
            top_k: Maximum results to return
            source_types: Optional filter by source types

        Returns:
            List of SearchResult objects
        """
        results: List[SearchResult] = []

        if method in (SearchMethod.TFIDF, SearchMethod.KEYWORD, SearchMethod.HYBRID):
            tfidf_results = self.tfidf_index.search(query, top_k * 2)
            for chunk, score, matched in tfidf_results:
                if source_types and chunk.source_type not in source_types:
                    continue
                results.append(SearchResult(
                    chunk=chunk,
                    score=score,
                    match_type="tfidf",
                    matched_terms=matched
                ))

        if method in (SearchMethod.EMBEDDING, SearchMethod.HYBRID):
            embed_results = self.embedding_index.search(query, top_k * 2)
            for chunk, score in embed_results:
                if source_types and chunk.source_type not in source_types:
                    continue
                # Check if already in results
                existing = next((r for r in results if r.chunk.id == chunk.id), None)
                if existing:
                    # Combine scores for hybrid
                    existing.score = (existing.score + score) / 2
                    existing.match_type = "hybrid"
                else:
                    results.append(SearchResult(
                        chunk=chunk,
                        score=score,
                        match_type="semantic"
                    ))

        # Sort by score and return top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def find_similar(
        self,
        text: str,
        exclude_id: Optional[str] = None,
        top_k: int = 5,
        method: SearchMethod = SearchMethod.HYBRID
    ) -> List[SearchResult]:
        """Find documents similar to the given text.

        This is useful for finding related content when a user highlights text.

        Args:
            text: Text to find similar content for
            exclude_id: Optional document ID to exclude from results
            top_k: Maximum results
            method: Search method

        Returns:
            List of similar documents
        """
        results = self.search(text, method, top_k + 1)

        # Filter out the source document if provided
        if exclude_id:
            results = [r for r in results if r.chunk.id != exclude_id]

        return results[:top_k]

    def get_document_count(self) -> int:
        """Get total number of indexed documents."""
        return len(self.tfidf_index.documents)

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        type_counts: Dict[str, int] = {}
        for chunk in self.tfidf_index.documents.values():
            type_counts[chunk.source_type] = type_counts.get(chunk.source_type, 0) + 1

        embedded_count = sum(
            1 for chunk in self.embedding_index.documents.values()
            if chunk.embedding is not None
        )

        return {
            "total_documents": len(self.tfidf_index.documents),
            "documents_by_type": type_counts,
            "vocab_size": len(self.tfidf_index.vocab),
            "embedded_documents": embedded_count
        }
