---
name: ragflow
description: "Deep document understanding and RAG (Retrieval-Augmented Generation) using RAGFlow patterns. Handles PDF, DOCX, Excel, images, and web pages with intelligent chunking, hybrid search (BM25+vector), and citation-grounded answers. Use for document Q&A, knowledge base management, and research."
source: https://github.com/infiniflow/ragflow
---

# RAGFlow (Urai Knowledge Base)

Urai's Wiki and knowledge base system uses RAGFlow-inspired patterns for deep document understanding.

## Capabilities

- **Document ingestion**: PDF, DOCX, TXT, MD, HTML, images
- **Intelligent chunking**: preserves structure (headings, tables, lists)
- **Hybrid search**: BM25 keyword + vector semantic search
- **Citation grounding**: every answer includes source references
- **Multi-document Q&A**: query across hundreds of documents
- **Table/figure extraction**: understands structured data in documents

## Usage

### Add Documents
```bash
# Add a PDF to the knowledge base
urai wiki add --file report.pdf --tag finance

# Add a URL
urai wiki add --url https://example.com/docs --tag reference

# Add text directly
urai wiki add --text "Key fact: Urai v1.3 was released in November 2026" --tag urai
```

### Search and Query
```bash
# Semantic search
urai wiki search "what are the revenue projections for Q4"

# Ask a question (RAG)
urai ask "summarize the key risks mentioned in the financial reports" --use-wiki

# Deep research with citations
urai research "competitive analysis of AI assistants" --cite-sources
```

### Via API
```bash
# Add document
curl -X POST http://localhost:8777/v1/wiki/add \
  -H "Content-Type: application/json" \
  -d '{"text": "content here", "source": "doc.pdf", "tags": ["finance"]}'

# Search
curl -X POST http://localhost:8777/v1/wiki/search \
  -d '{"query": "revenue projections", "limit": 5}'
```

## Knowledge Base Structure

Urai uses a 3-tier memory system:
1. **Short-term**: current conversation context
2. **Medium-term**: session summaries and key facts
3. **Long-term**: Wiki knowledge base (persistent, searchable)

## Best Practices (from RAGFlow)

- Chunk size: 512 tokens optimal for most documents
- Overlap: 50 tokens between chunks preserves context
- Tags: use consistent tags for filtering
- Re-index after major document updates
- For tables: use CSV/JSON format for better extraction
