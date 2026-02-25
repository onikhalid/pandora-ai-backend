from typing import List, Dict
from app.db.weaviate import get_weaviate_client
from langchain.text_splitter import RecursiveCharacterTextSplitter

class GraphRAGService:
    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        # Using LangChain's RecursiveCharacterTextSplitter for more semantic chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )
        return text_splitter.split_text(text)
        
    @staticmethod
    def ingest_document(document_id: str, content: str, organization_id: str, source_type: str = "PANDORA_DOC", external_id: str = "", created_at: str = "", domain_id: str = None):
        """
        Chunks the text and inserts into Weaviate as vector nodes bounded by the organization_id.
        Persists the timestamp to allow the AI to reason chronologically over document history.
        """
        client = get_weaviate_client()
        try:
            nodes_collection = client.collections.get("DocumentNode")
            chunks = GraphRAGService.chunk_text(content)
            
            with nodes_collection.batch.dynamic() as batch:
                for chunk in chunks:
                    batch.add_object(
                        properties={
                            "content": chunk,
                            "document_id": document_id,
                            "organization_id": organization_id,
                            "source_type": source_type,
                            "external_id": external_id,
                            "created_at": created_at,
                            "domain_id": domain_id
                        }
                    )
            
            if len(nodes_collection.batch.failed_objects) > 0:
                print(f"Failed to ingest document {document_id}. Errors:")
                for failed in nodes_collection.batch.failed_objects:
                    print(failed.message)
                    
            return {"status": "success", "chunks_ingested": len(chunks)}
        finally:
            client.close()
            
    @staticmethod
    def search_similar_content(query: str, organization_id: str, limit: int = 3, allowed_document_ids: List[str] = None, source_type: str = None, domain_id: str = None) -> List[Dict]:
        """
        Performs a semantic search on the GraphRAG knowledge base scoped to the tenant organization.
        When allowed_document_ids is provided, results are strictly limited to those documents
        (enforcing personalized knowledge gates based on user permissions).
        """
        client = get_weaviate_client()
        try:
            nodes_collection = client.collections.get("DocumentNode")
            import weaviate.classes as wvc
            
            # Filter by organization OR allow null org (sandbox/legacy docs)
            if organization_id:
                org_filter = wvc.query.Filter.by_property("organization_id").equal(organization_id) | \
                             wvc.query.Filter.by_property("organization_id").is_none(True)
            else:
                org_filter = wvc.query.Filter.by_property("organization_id").is_none(True)
            
            combined_filter = org_filter
            
            if allowed_document_ids is not None and len(allowed_document_ids) > 0:
                combined_filter = combined_filter & wvc.query.Filter.by_property("document_id").contains_any(allowed_document_ids)
            elif allowed_document_ids is not None and len(allowed_document_ids) == 0:
                return []
            
            if source_type:
                combined_filter = combined_filter & wvc.query.Filter.by_property("source_type").equal(source_type)
            
            if domain_id:
                combined_filter = combined_filter & wvc.query.Filter.by_property("domain_id").equal(domain_id)

            response = nodes_collection.query.near_text(
                query=query,
                limit=limit,
                filters=combined_filter
            )
            
            results = []
            for item in response.objects:
                results.append(item.properties)
            return results
        finally:
            client.close()

    @staticmethod
    def delete_document(document_id: str):
        """
        Deletes all Weaviate vector nodes for a given document_id,
        cleaning up the semantic knowledge base when a document is deleted.
        """
        client = get_weaviate_client()
        try:
            import weaviate.classes as wvc
            nodes_collection = client.collections.get("DocumentNode")
            nodes_collection.data.delete_many(
                where=wvc.query.Filter.by_property("document_id").equal(document_id)
            )
            return {"status": "success", "document_id": document_id}
        except Exception as e:
            print(f"GraphRAG delete error for doc {document_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            client.close()
