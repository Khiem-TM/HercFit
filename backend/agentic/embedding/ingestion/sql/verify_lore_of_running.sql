-- Read-only verification; no activation or publication.
SELECT d.source_key, r.version, r.review_status, d.active_revision = r.id AS published,
       p.id AS profile_id, p.model, p.dimension, p.active,
       count(DISTINCT c.id) AS chunks, count(e.chunk_id) AS embeddings,
       min(vector_dims(e.embedding)) AS min_dimensions,
       max(vector_dims(e.embedding)) AS max_dimensions
FROM knowledge_documents d
JOIN knowledge_revisions r ON r.document_id = d.id
JOIN knowledge_jobs j ON j.revision_id = r.id
JOIN knowledge_profiles p ON p.id = j.profile_id
LEFT JOIN knowledge_chunks c ON c.revision_id = r.id
LEFT JOIN knowledge_embeddings e ON e.chunk_id = c.id AND e.profile_id = p.id
WHERE d.source_key = 'lore-of-running-4th-ed'
GROUP BY d.id, r.id, p.id;
