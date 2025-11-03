#!/usr/bin/env python3
"""
Advanced Hybrid RAG with Query Expansion, Full-Text Search, and Re-ranking.
Uses Groq for LLM synthesis (Llama) and for query expansion.

Usage:
  export GROQ_API_KEY="sk-..."
  python3 hybrid_with_groq.py --query "What is the right to equality?" --topk 3
"""

import os
import re
import json
import time
import argparse
from typing import List, Dict, Any
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pymilvus import connections, Collection
from sentence_transformers import SentenceTransformer, CrossEncoder

# ---------- config (env fallbacks)
load_dotenv()
NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
MILVUS_HOST = os.environ.get("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("MILVUS_COLLECTION", "constitution_vectors")

# Embedding model for search
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-mpnet-base-v2")
# Re-ranking model for improving context quality
RERANK_MODEL = os.environ.get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_ENDPOINT = os.environ.get("GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
# Main model for generation
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
# Fast model for query expansion
GROQ_EXPAND_MODEL = os.environ.get("GROQ_EXPAND_MODEL", "llama-3.3-70b-versatile")
GROQ_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "600"))

# Global models (loaded once)
g_embed_model = None
g_cross_encoder = None

# ---------- 1. Service Connection & Model Loading ----------
def connect_services_and_load_models():
    print("Connecting to Milvus and Neo4j...")
    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    milvus_collection = Collection(MILVUS_COLLECTION)
    milvus_collection.load() # Load collection into memory
    
    neo_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    global g_embed_model, g_cross_encoder
    print(f"Loading embedding model: {EMBEDDING_MODEL}...")
    g_embed_model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Loading re-ranking model: {RERANK_MODEL}...")
    g_cross_encoder = CrossEncoder(RERANK_MODEL)
    
    print("All services and models connected.")
    return milvus_collection, neo_driver, g_embed_model, g_cross_encoder

# ---------- 2. Query Expansion (NEW!) ----------
def expand_query(query: str, model: str = GROQ_EXPAND_MODEL) -> List[str]:
    """Uses a fast LLM to expand the user query for better semantic search."""
    print(f"Expanding query with {model}...")
    if GROQ_API_KEY is None:
        raise RuntimeError("GROQ_API_KEY not found in environment.")
        
    # Updated prompt, asking for JSON without the format parameter
    system_prompt = "You are a helpful search assistant. Rewrite the user's query into 3 different versions, focusing on synonyms, legal phrasing, and related concepts to improve search results in a legal database. Output *only* a JSON list of strings, like [\"query1\", \"query2\"]. Do not add any other text, explanation, or markdown backticks."
    user_prompt = f"Query: {query}"
    
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 200  # <--- THIS WAS THE MISSING LINE CAUSING THE 400 ERROR
    }
    
    try:
        resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=10)
        resp.raise_for_status() # This will throw an error if status is 400
        data = resp.json()
        content = data['choices'][0]['message']['content']
        
        # --- NEW: More Robust JSON parsing ---
        # 1. Strip markdown backticks if they exist
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        
        # 2. Find the JSON list within the LLM's response
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if not match:
            print(f"DEBUG: LLM response did not contain a list: {content}")
            raise ValueError("LLM returned malformed JSON (no list found)")
            
        queries = json.loads(match.group(0))
        # --- End robust parsing ---
        
        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            if query not in queries:
                queries.insert(0, query)
            print(f"Expanded queries: {queries}")
            return queries
        raise ValueError("LLM returned malformed JSON (not a list of strings)")
    except Exception as e:
        print(f"Query expansion failed: {e}. Falling back to original query.")
        # Print response body if available
        if 'resp' in locals() and hasattr(resp, 'text'):
            print(f"--- FAILED RESPONSE BODY (DEBUG) ---")
            print(resp.text)
            print(f"--- END FAILED RESPONSE BODY ---")
        return [query] # Fallback
        
def embed_texts(model, texts):
    return model.encode(texts, convert_to_numpy=True)

# ---------- 3. Retrieval Stage (Upgraded) ----------
def milvus_search(collection: Collection, query_embeddings, topk=5, param={"metric_type":"COSINE","params":{"nprobe":10}}):
    """Searches Milvus with a list of query embeddings."""
    results = collection.search(query_embeddings,
                                "embedding", param, topk,
                                output_fields=["meta"])
    # Return hits from all expanded queries
    all_hits = []
    for hit_list in results:
        for h in hit_list:
            all_hits.append({"id": str(h.id), "score": float(h.score)})
    return all_hits

def keyword_search_neo4j(driver, query: str, topk=5) -> List[Dict[str, Any]]:
    """
    UPGRADED: Searches Neo4j using a specific regex first, then falls back
    to the Full-Text Index for broader keyword matches.
    """
    results = []
    
    # 1. Try improved regex for specific articles first (e.g., "Article 19(1)(a)")
    # This is much faster and more accurate than full-text for this case.
    article_match = re.search(r'article\s+([0-9A-Z]+(\([0-9a-z]+\))?(\([0-9a-z]+\))?)', query, re.IGNORECASE)
    
    cypher_query = ""
    params = {}

    if article_match:
        article_num_str = article_match.group(1)
        print(f"Keyword search: Matched specific article: {article_num_str}")
        cypher_query = """
        MATCH (c:Clause {article_no: $article_num})
        RETURN c.milvus_id AS milvus_id, 20.0 AS score  // Give it a very high score
        LIMIT 1
        """
        params = {"article_num": article_num_str}
    else:
        # 2. Fallback to Full-Text Index (needs index `clauseTextIndex` to exist)
        print("Keyword search: No specific article found, using Full-Text Index...")
        cypher_query = """
        CALL db.index.fulltext.queryNodes("clauseTextIndex", $query) YIELD node, score
        WHERE node:Clause
        RETURN node.milvus_id AS milvus_id, score
        LIMIT $topk
        """
        params = {"query": query, "topk": topk}

    try:
        with driver.session() as session:
            records = session.run(cypher_query, params)
            for rec in records:
                if rec["milvus_id"]:
                    results.append({"id": rec["milvus_id"], "score": rec["score"]})
    except Exception as e:
        print(f"Neo4j keyword search failed: {e}")
        if "no such index" in str(e).lower():
            print("ERROR: Neo4j Full-Text Index 'clauseTextIndex' not found.")
            print("Please run this in Neo4j: CREATE FULLTEXT INDEX clauseTextIndex FOR (c:Clause) ON EACH [c.text, c.article_title]")
        
    return results

def fetch_clauses_from_neo4j(driver, milvus_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetches full clause data from Neo4j given a list of milvus_ids."""
    results = []
    with driver.session() as session:
        if not milvus_ids:
            return []
        
        rec_iter = session.run(
            """
            UNWIND $mids AS mid
            MATCH (c:Clause {milvus_id: mid})
            RETURN c.id AS clause_id, 
                   c.article_no AS article_no, 
                   c.article_title AS article_title,
                   c.text AS text, 
                   c.milvus_id AS milvus_id
            """,
            mids=milvus_ids
        )
        
        # --- THIS IS THE FIX ---
        # Convert the immutable 'Record' object to a mutable 'dict'
        clauses_by_mid = {rec["milvus_id"]: dict(rec) for rec in rec_iter} 
        # --- END FIX ---
        
        # Return in the original order of milvus_ids
        results = [clauses_by_mid[mid] for mid in milvus_ids if mid in clauses_by_mid]
            
    return results

# ---------- 4. Re-ranking Stage (NEW!) ----------
def rerank_documents(encoder: CrossEncoder, query: str, clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Uses a CrossEncoder to re-rank fetched clauses based on relevance to the query."""
    if not clauses:
        return []
    
    print(f"Re-ranking {len(clauses)} candidate documents...")
    
    # Create pairs of [query, document_text]
    pairs = []
    for clause in clauses:
        text = f"Article {clause.get('article_no')}: {clause.get('article_title', '')}\n{clause.get('text', '')}"
        pairs.append([query, text])
    
    # Run the model
    scores = encoder.predict(pairs)
    
    # Add scores to clauses and sort
    for i, clause in enumerate(clauses):
        clause['rerank_score'] = scores[i]
        
    sorted_clauses = sorted(clauses, key=lambda x: x['rerank_score'], reverse=True)
    
    print(f"Top 3 re-ranked results (Article Nos): {[c.get('article_no') for c in sorted_clauses[:3]]}")
    return sorted_clauses

# ---------- 5. Synthesis Stage (Upgraded) ----------
def assemble_context(reranked_clauses: List[Dict[str, Any]], max_clauses=3) -> Dict[str, Any]:
    """Assembles the final context from the top re-ranked clauses."""
    # This is simpler now: just take the top N from the re-ranked list
    top_clauses = reranked_clauses[:max_clauses]
    
    ctx_clauses = []
    for i, c in enumerate(top_clauses, start=1):
        ctx_clauses.append({
            "milvus_id": c.get("milvus_id"),
            "article_no": c.get("article_no"),
            "text": c.get("text", ""),
            "rerank_score": c.get("rerank_score")
        })
    return {"clauses": ctx_clauses}

def build_prompt(user_question: str, ctx: dict) -> str:
    """Builds the user-facing prompt with context."""
    user_preface = f"User question: {user_question}\n\nContext (ONLY use these):\n"
    block_txts = []
    for i, c in enumerate(ctx.get("clauses", []), start=1):
        header = f"--- CLAUSE {i} [Article:{c.get('article_no')}] [rerank_score:{c.get('rerank_score'):.4f}] ---"
        body = c.get("text","").replace("\n", " ").strip()
        block_txts.append(f"{header}\n{body}\n")
    context_str = "\n".join(block_txts)

    instructions = (
        "INSTRUCTIONS:\n"
        "1) Provide a concise answer (<= 250 words).\n"
        "2) Your answer MUST be based ONLY on the provided context.\n"
        "3. Return explicit citations in the format [Article:<number>].\n"
        "4) If the answer is not in the context, reply exactly: \"The provided context does not contain this information.\"\n"
    )

    prompt = "\n".join([user_preface, context_str, instructions])
    return prompt

def call_groq(prompt: str, model: str = GROQ_MODEL, max_tokens: int = GROQ_MAX_TOKENS, timeout: int = 60):
    """Calls Groq with the UPGRADED stricter system prompt."""
    if GROQ_API_KEY is None:
        raise RuntimeError("GROQ_API_KEY not found in environment.")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    # UPGRADED: Stricter system prompt
    system_msg = {
        "role": "system",
        "content": (
            "You are a precise legal assistant. Your answer MUST be based *only* on the provided sources (CLAUSE 1, CLAUSE 2, etc.). "
            "You MUST quote the source for every claim you make using the [Article:...] citation. "
            "Do NOT use any other knowledge. If the answer is not fully supported by the sources, you MUST state "
            "'The provided context does not contain this information.'"
        )
    }
    user_msg = {"role": "user", "content": prompt}

    payload = {"model": model, "messages": [system_msg, user_msg], "max_tokens": max_tokens, "temperature": 0.0}
    
    try:
        resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = data['choices'][0]['message']['content']
        return {"raw": data, "text": text}
    except requests.exceptions.RequestException as e:
        print(f"Groq API call failed: {e}")
        return {"error": str(e), "raw": None}

# ---------- 6. Main Flow (NEW Pipeline) ----------
def hybrid_query_with_groq(query: str, semantic_topk: int=5, candidate_k: int=20, final_topk: int=3):
    
    # --- 1. CONNECT ---
    milvus_collection, neo_driver, model, cross_encoder = connect_services_and_load_models()
    
    # --- 2. QUERY EXPANSION ---
    expanded_queries = expand_query(query)
    
    # --- 3. RETRIEVAL (Parallel) ---
    qvecs = embed_texts(model, expanded_queries)
    print(f"Searching Milvus (semantic) with {len(qvecs)} expanded queries...")
    milvus_hits = milvus_search(milvus_collection, qvecs, topk=semantic_topk)
    
    print("Searching Neo4j (keyword)...")
    neo_hits = keyword_search_neo4j(neo_driver, query, topk=semantic_topk)
    
    # --- 4. FUSION ---
    print("Fusing semantic and keyword results...")
    fused_results = {}
    k = 60  # RRF tuning parameter

    # Process Milvus results (from all expanded queries)
    for hit in milvus_hits:
        if hit['id'] not in fused_results:
            fused_results[hit['id']] = 0.0
        # Simple RRF-like score addition
        fused_results[hit['id']] += hit.get('score', 0) 
        
    # Process Neo4j results
    for hit in neo_hits:
        if hit['id'] not in fused_results:
            fused_results[hit['id']] = 0.0
        fused_results[hit['id']] += hit.get('score', 1.0) # Add keyword score

    if not fused_results:
        print("No hits returned by Milvus or Neo4j.")
        return

    sorted_fused = sorted(fused_results.items(), key=lambda item: item[1], reverse=True)
    
    # Get the top N *candidates* for re-ranking
    candidate_ids = [id for id, score in sorted_fused[:candidate_k]]
    print(f"Top {len(candidate_ids)} candidates for re-ranking: {candidate_ids}")
    
    # --- 5. FETCH & RE-RANK ---
    print("Fetching candidate clauses from Neo4j...")
    candidate_clauses = fetch_clauses_from_neo4j(neo_driver, candidate_ids)
    
    reranked_clauses = rerank_documents(cross_encoder, query, candidate_clauses)
    
    # --- 6. SYNTHESIS (RAG) ---
    ctx = assemble_context(reranked_clauses, max_clauses=final_topk)
    
    print("Assembled final context; building prompt for Groq...")
    prompt = build_prompt(query, ctx)

    print("Prompt length (chars):", len(prompt))
    print("\n--- Prompt preview (first 1000 chars) ---")
    print(prompt[:1000])
    print("--- end preview ---\n")

    print("Calling Groq LLM for final answer...")
    start = time.time()
    resp = call_groq(prompt)
    took = time.time() - start
    print(f"Groq call finished in {took:.2f}s")

    if resp.get("error"):
        print("Groq error:", resp["error"])
        return
        
    model_text = resp.get("text","")
    print("\n--- MODEL OUTPUT ---\n")
    print(model_text)
    print("\n--- RAW RESPONSE (truncated) ---\n")
    print(json.dumps(resp.get("raw",{}), indent=2)[:2000])
    print("\n--- END ---\n")
    
    # Disconnect
    connections.disconnect("default")
    neo_driver.close()
    return {"context": ctx, "prompt": prompt, "model_text": model_text, "raw": resp.get("raw")}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    # The --topk param now controls the *final* context size
    parser.add_argument("--topk", type=int, default=3, help="Final number of context chunks to send to LLM.")
    args = parser.parse_args()
    hybrid_query_with_groq(args.query, final_topk=args.topk)