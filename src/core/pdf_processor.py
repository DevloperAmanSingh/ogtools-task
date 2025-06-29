#!/usr/bin/env python3

import os
import json
import re
import fitz  # PyMuPDF
import pdfplumber
import time
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from google import genai
from dotenv import load_dotenv

load_dotenv()

TEAM_ID = "aline123"
MAX_CHUNK_SIZE = 15000
CHUNK_OVERLAP = 1000

PRICING = {
    "input": 0.00035,
    "output": 0.00053
}

@dataclass
class PDFChunk:
    title: str
    content: str
    content_type: str
    source_url: str
    author: str
    user_id: str
    page_range: str
    chapter: str

@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float

def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000) * PRICING["input"]
    output_cost = (output_tokens / 1000) * PRICING["output"]
    return input_cost + output_cost

def extract_text_from_pdf(pdf_path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract text from PDF and return full text plus page information"""
    
    full_text = ""
    page_info = []
    
    try:
        doc = fitz.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            
            if page_text.strip():
                full_text += f"\n\n--- Page {page_num + 1} ---\n\n"
                full_text += page_text
                
                page_info.append({
                    "page_number": page_num + 1,
                    "text": page_text,
                    "char_count": len(page_text)
                })
        
        doc.close()
        return full_text, page_info
        
    except Exception as e:
        return "", []

def chunk_pdf_content(text: str, page_info: List[Dict], max_size: int = MAX_CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """Chunk PDF content intelligently, respecting page boundaries when possible"""
    
    if len(text) <= max_size:
        return [{
            "content": text,
            "page_range": f"1-{len(page_info)}" if page_info else "1",
            "chunk_index": 1
        }]
    
    chunks = []
    current_chunk = ""
    current_pages = []
    chunk_index = 1
    
    pages = text.split("--- Page ")
    
    for i, page_content in enumerate(pages):
        if not page_content.strip():
            continue
            
        page_text = page_content if i == 0 else f"--- Page {page_content}"
        
        if len(current_chunk + page_text) > max_size and current_chunk:
            page_range = "unknown"
            if current_pages:
                if len(current_pages) > 1:
                    page_range = f"{min(current_pages)}-{max(current_pages)}"
                else:
                    page_range = str(current_pages[0])
            
            chunks.append({
                "content": current_chunk.strip(),
                "page_range": page_range,
                "chunk_index": chunk_index
            })
            
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + "\n\n" + page_text
            current_pages = [current_pages[-1]] if current_pages else []
            chunk_index += 1
        else:
            current_chunk += "\n\n" + page_text if current_chunk else page_text
        
        try:
            if "--- Page " in page_text:
                parts = page_text.split("--- Page ")[1] if len(page_text.split("--- Page ")) > 1 else ""
                if parts and "---" in parts:
                    page_num_str = parts.split("---")[0].strip()
                    if page_num_str.isdigit():
                        page_num = int(page_num_str)
                        if page_num not in current_pages:
                            current_pages.append(page_num)
        except (IndexError, ValueError, AttributeError):
            pass
    
    if current_chunk:
        page_range = "unknown"
        if current_pages:
            if len(current_pages) > 1:
                page_range = f"{min(current_pages)}-{max(current_pages)}"
            else:
                page_range = str(current_pages[0])
        
        chunks.append({
            "content": current_chunk.strip(),
            "page_range": page_range,
            "chunk_index": chunk_index
        })
    
    return chunks

def clean_and_deduplicate_chapters(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean up and deduplicate extracted chapters"""
    
    if not chapters:
        return chapters
    
    grouped_chapters = {}
    
    for chapter in chapters:
        title = chapter.get('title', '').strip()
        
        if title.startswith('PDF Content - Pages'):
            content = chapter.get('content', '')[:500]
            
            chapter_patterns = [
                r'(?:CHAPTER\s+\d+[:\.]?\s*)?([A-Z][A-Z\s]+?)(?:\n|\r|$)',
                r'(\d+\.\s*[A-Z][A-Z\s]+?)(?:\n|\r|$)',
                r'^([A-Z][A-Z\s]{10,}?)(?:\n|\r|$)',
            ]
            
            for pattern in chapter_patterns:
                match = re.search(pattern, content)
                if match:
                    extracted_title = match.group(1).strip()
                    extracted_title = re.sub(r'^\d+\.\s*', '', extracted_title)
                    extracted_title = extracted_title.title()
                    if len(extracted_title) > 5:
                        title = extracted_title
                        chapter['title'] = title
                        break
        
        normalized_title = title.lower().strip()
        normalized_title = re.sub(r'[^\w\s]', '', normalized_title)
        normalized_title = re.sub(r'\s+', ' ', normalized_title)
        
        if normalized_title in grouped_chapters:
            existing = grouped_chapters[normalized_title]
            existing['content'] += '\n\n' + chapter.get('content', '')
            
            existing_range = existing.get('page_range', '')
            new_range = chapter.get('page_range', '')
            if existing_range and new_range and existing_range != new_range:
                existing['page_range'] = f"{existing_range}, {new_range}"
        else:
            grouped_chapters[normalized_title] = chapter.copy()
    
    deduplicated = list(grouped_chapters.values())
    
    for chapter in deduplicated:
        title = chapter.get('title', '')
        
        if title.isupper():
            title = title.title()
            
        title = re.sub(r'^(Chapter\s+\d+[:\.]?\s*)', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^\d+\.\s*', '', title)
        
        chapter['title'] = title.strip()
    
    return deduplicated

def extract_chapters_with_gemini(pdf_chunks: List[Dict], pdf_filename: str) -> Tuple[List[Dict[str, Any]], TokenUsage]:
    """Use Gemini to extract structured content from PDF chunks"""
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("API key not set")
    
    client = genai.Client(api_key=api_key)
    total_token_usage = TokenUsage(0, 0, 0, 0.0)
    extracted_items = []
    
    for chunk in pdf_chunks:
        prompt = f"""Extract structured content from this PDF chunk. Source: {pdf_filename}

CRITICAL RULES FOR TITLE EXTRACTION:
- Look for ACTUAL chapter/section titles in the content (usually in ALL CAPS, bold, or header format)
- NEVER use generic titles like "PDF Content - Pages X-Y" 
- Extract the EXACT chapter/section name from the text
- If you see titles like "CHAPTER 1: INTRODUCTION" use "Introduction"
- If you see "3. A BRIEF HISTORY OF TECHNICAL INTERVIEWS" use "A Brief History of Technical Interviews"
- Remove chapter numbers and formatting, keep the descriptive title
- If no clear title exists, create a descriptive title based on the main topic discussed
- Clean and structure the content, removing page markers, headers, footers
- Extract author name if mentioned

PDF Content (Pages {chunk.get('page_range', 'unknown')}):
{chunk.get('content', '')}

ANALYZE THE CONTENT ABOVE AND:
1. Find the main chapter/section title(s) - look for headings, chapter markers, section titles
2. Extract clean, meaningful titles (NOT generic page references)
3. Clean the content by removing page markers, headers, footers
4. If multiple distinct sections exist, return an array; if one section, return a single object

Return format - If MULTIPLE distinct sections:
[
    {{
        "title": "Actual Chapter Title From Content",
        "content": "Clean content without page markers",
        "content_type": "pdf_chapter",
        "source_url": "{pdf_filename}",
        "author": "Author name if found in content",
        "user_id": "",
        "page_range": "{chunk.get('page_range', 'unknown')}",
        "chapter": "Chapter identifier if found"
    }}
]

If SINGLE section:
{{
    "title": "Actual Chapter Title From Content", 
    "content": "Clean content without page markers",
    "content_type": "pdf_chapter",
    "source_url": "{pdf_filename}",
    "author": "Author name if found in content",
    "user_id": "",
    "page_range": "{chunk.get('page_range', 'unknown')}",
    "chapter": "Chapter identifier if found"
}}

Return only valid JSON:"""

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0, "max_output_tokens": 3000}
            )
            
            input_tokens = len(prompt) // 4
            output_tokens = len(response.text) // 4
            chunk_cost = calculate_cost(input_tokens, output_tokens)
            
            total_token_usage.input_tokens += input_tokens
            total_token_usage.output_tokens += output_tokens
            total_token_usage.total_tokens += input_tokens + output_tokens
            total_token_usage.cost += chunk_cost
            
            content = response.text.strip()
            
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            
            parsed_data = None
            
            try:
                parsed_data = json.loads(content)
            except json.JSONDecodeError:
                try:
                    array_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if array_match:
                        json_str = array_match.group()
                        parsed_data = json.loads(json_str)
                    else:
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            json_str = json_match.group()
                            parsed_data = json.loads(json_str)
                except (json.JSONDecodeError, AttributeError):
                    try:
                        start_bracket = content.find('[')
                        end_bracket = content.rfind(']')
                        if start_bracket != -1 and end_bracket != -1 and end_bracket > start_bracket:
                            json_str = content[start_bracket:end_bracket+1]
                            parsed_data = json.loads(json_str)
                        else:
                            start = content.find('{')
                            end = content.rfind('}')
                            if start != -1 and end != -1 and end > start:
                                json_str = content[start:end+1]
                                parsed_data = json.loads(json_str)
                    except json.JSONDecodeError:
                        parsed_data = None
            
            if parsed_data:
                items_to_process = []
                
                if isinstance(parsed_data, list):
                    items_to_process = parsed_data
                elif isinstance(parsed_data, dict):
                    items_to_process = [parsed_data]
                
                for item_data in items_to_process:
                    if isinstance(item_data, dict):
                        title = item_data.get("title", "")
                        if not title or "PDF Content" in title:
                            content_preview = item_data.get("content", "")[:300]
                            
                            patterns = [
                                r'(?:CHAPTER\s+\d+[:\.]?\s*)?([A-Z][A-Z\s]{5,50}?)(?:\n|\r|\.)',
                                r'(\d+\.\s*[A-Z][A-Z\s]{5,50}?)(?:\n|\r)',
                                r'^([A-Z][A-Z\s]{5,50}?)(?:\n|\r)',
                                r'([A-Z][a-z]+(?:\s+[A-Z][a-z]*){2,})(?:\n|\r|\.)'
                            ]
                            
                            fallback_title = None
                            for pattern in patterns:
                                match = re.search(pattern, content_preview)
                                if match:
                                    candidate = match.group(1).strip()
                                    candidate = re.sub(r'^\d+\.\s*', '', candidate)
                                    if len(candidate) >= 5 and len(candidate) <= 60:
                                        fallback_title = candidate.title() if candidate.isupper() else candidate
                                        break
                            
                            if fallback_title:
                                item_data["title"] = fallback_title
                            else:
                                keywords = re.findall(r'\b(?:interview|coding|technical|resume|career|job|algorithm|programming|software|engineer|developer|hiring|recruiter)\w*\b', content_preview.lower())
                                if keywords:
                                    main_topic = max(set(keywords), key=keywords.count)
                                    item_data["title"] = f"{main_topic.title()} Content"
                                else:
                                    item_data["title"] = f"Content Section (Pages {chunk.get('page_range', 'unknown')})"
                        
                        item_data.setdefault("content_type", "pdf_chapter")
                        item_data.setdefault("source_url", pdf_filename)
                        item_data.setdefault("author", "Unknown")
                        item_data.setdefault("user_id", "")
                        item_data.setdefault("page_range", chunk.get('page_range', 'unknown'))
                        item_data.setdefault("chapter", f"Chunk {chunk.get('chunk_index', 1)}")
                        
                        extracted_items.append(item_data)
            
            if not parsed_data or not any(isinstance(item, dict) for item in (parsed_data if isinstance(parsed_data, list) else [parsed_data])):
                raise Exception("Could not parse AI response as JSON")
            
            time.sleep(0.5)
            
        except Exception as e:
            chunk_content = chunk.get('content', '')
            
            fallback_title = f"Content Section (Pages {chunk.get('page_range', 'unknown')})"
            
            if chunk_content:
                patterns = [
                    r'(?:CHAPTER\s+\d+[:\.]?\s*)?([A-Z][A-Z\s]{5,50}?)(?:\n|\r|\.)',
                    r'(\d+\.\s*[A-Z][A-Z\s]{5,50}?)(?:\n|\r)',
                    r'^([A-Z][A-Z\s]{5,50}?)(?:\n|\r)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, chunk_content[:300])
                    if match:
                        candidate = match.group(1).strip()
                        candidate = re.sub(r'^\d+\.\s*', '', candidate)
                        if len(candidate) >= 5 and len(candidate) <= 60:
                            fallback_title = candidate.title() if candidate.isupper() else candidate
                            break
            
            extracted_items.append({
                "title": fallback_title,
                "content": chunk_content[:1000] + "..." if len(chunk_content) > 1000 else chunk_content,
                "content_type": "pdf_chapter",
                "source_url": pdf_filename,
                "author": "Unknown", 
                "user_id": "",
                "page_range": chunk.get('page_range', 'unknown'),
                "chapter": f"Chunk {chunk.get('chunk_index', 1)}"
            })
            continue
    
    cleaned_items = clean_and_deduplicate_chapters(extracted_items)
    
    return cleaned_items, total_token_usage

def process_pdf_file(pdf_path: str) -> Tuple[List[Dict[str, Any]], TokenUsage]:
    """Main function to process PDF file and return structured data"""
    
    try:
        full_text, page_info = extract_text_from_pdf(pdf_path)
        
        if not full_text.strip():
            return [], TokenUsage(0, 0, 0, 0.0)
        
        chunks = chunk_pdf_content(full_text, page_info)
        
        if not chunks:
            return [], TokenUsage(0, 0, 0, 0.0)
        
        pdf_filename = os.path.basename(pdf_path)
        extracted_items, token_usage = extract_chapters_with_gemini(chunks, pdf_filename)
        
        return extracted_items, token_usage
        
    except Exception as e:
        return [], TokenUsage(0, 0, 0, 0.0) 