"""
Batch evaluation pipeline following VideoRAG's 4-step pattern.

Steps:
1. batch_upload   - Submit judge requests to OpenAI Batch API
2. batch_download - Retrieve completed batch results
3. batch_parse    - Validate responses, retry malformed
4. batch_calculate - Aggregate scores by domain/category
"""
