import os
import logging
from typing import Optional
import PyPDF2
from docx import Document
from PIL import Image
import pytesseract
from django.conf import settings

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """
    Handles document text extraction and processing
    """
    
    def __init__(self):
        self.supported_formats = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg']
    
    def extract_text(self, file_path: str) -> str:
        """
        Extract text from various document formats
        """
        try:
            file_extension = os.path.splitext(file_path)[1].lower()
            
            if file_extension == '.pdf':
                return self._extract_from_pdf(file_path)
            elif file_extension == '.docx':
                return self._extract_from_docx(file_path)
            elif file_extension == '.txt':
                return self._extract_from_txt(file_path)
            elif file_extension in ['.png', '.jpg', '.jpeg']:
                return self._extract_from_image(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")
                
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {str(e)}")
            raise
    
    def _extract_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {str(e)}")
            raise
        return text.strip()
    
    def _extract_from_docx(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            doc = Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        except Exception as e:
            logger.error(f"Error reading DOCX {file_path}: {str(e)}")
            raise
        return text.strip()
    
    def _extract_from_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                text = file.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as file:
                text = file.read()
        except Exception as e:
            logger.error(f"Error reading TXT {file_path}: {str(e)}")
            raise
        return text.strip()
    
    def _extract_from_image(self, file_path: str) -> str:
        """Extract text from image using OCR"""
        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
        except Exception as e:
            logger.error(f"Error performing OCR on {file_path}: {str(e)}")
            raise
        return text.strip()
    
    def generate_summary(self, text: str, max_length: int = 500) -> str:
        """
        Generate a summary of the document text
        """
        try:
            # Simple extractive summarization - take first few sentences
            sentences = text.split('.')
            summary = ""
            
            for sentence in sentences:
                if len(summary + sentence) < max_length:
                    summary += sentence.strip() + ". "
                else:
                    break
            
            if not summary:
                # If no sentences fit, take first max_length characters
                summary = text[:max_length] + "..."
            
            return summary.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            return "Summary generation failed."
    
    def validate_file(self, file_path: str) -> bool:
        """
        Validate if file format is supported and file exists
        """
        if not os.path.exists(file_path):
            return False
        
        file_extension = os.path.splitext(file_path)[1].lower()
        return file_extension in self.supported_formats
    
    def get_file_info(self, file_path: str) -> dict:
        """
        Get basic information about the file
        """
        try:
            stat = os.stat(file_path)
            file_extension = os.path.splitext(file_path)[1].lower()
            
            return {
                'size': stat.st_size,
                'format': file_extension,
                'supported': file_extension in self.supported_formats,
                'created': stat.st_ctime,
                'modified': stat.st_mtime
            }
        except Exception as e:
            logger.error(f"Error getting file info for {file_path}: {str(e)}")
            return {}