import fitz  # PyMuPDF
import docx
import io
from fastapi import UploadFile
import markdown

class FileParsingService:
    """
    Service responsible for extracting plain text from uploaded unstructured documents.
    Supports PDF, DOCX, and Text/Markdown files.
    """
    
    @staticmethod
    async def extract_text(file: UploadFile) -> str:
        content_bytes = await file.read()
        filename = file.filename.lower()
        
        if filename.endswith(".pdf"):
            return FileParsingService._parse_pdf(content_bytes)
        elif filename.endswith(".docx"):
            return FileParsingService._parse_docx(content_bytes)
        elif filename.endswith(".md") or filename.endswith(".txt"):
            text = content_bytes.decode("utf-8")
            if filename.endswith(".md"):
                # Optional: strip markdown tags or keep raw. We keep raw for LLM diffing.
                return text
            return text
        else:
            raise ValueError(f"Unsupported file format: {filename}")

    @staticmethod
    def _parse_pdf(content_bytes: bytes) -> str:
        """Extract text from PDF using PyMuPDF"""
        doc = fitz.open(stream=content_bytes, filetype="pdf")
        text_chunks = []
        for page in doc:
            text_chunks.append(page.get_text())
        return "\n".join(text_chunks)

    @staticmethod
    def _parse_docx(content_bytes: bytes) -> str:
        """Extract text from DOCX using python-docx"""
        doc_io = io.BytesIO(content_bytes)
        doc = docx.Document(doc_io)
        text_chunks = [paragraph.text for paragraph in doc.paragraphs]
        return "\n".join(text_chunks)
