#!/usr/bin/env python3

import streamlit as st
import pandas as pd
import time
import json
import os
import sys
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.core.scraper import (
    get_markdown_from_jina,
    extract_blog_list_with_gemini,
    fetch_individual_blog_content,
    validate_and_format_items,
    TokenUsage,
    BlogItem
)
from src.core.pdf_processor import process_pdf_file

st.set_page_config(
    page_title="Blog Scraper",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stage-container {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
    }
    .main > div {
        padding-top: 1rem;
    }
    /* Remove white bar on home page */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0rem !important;
    }
    /* Hide streamlit default spacing */
    .element-container:first-child {
        margin-top: -1rem;
    }
    /* Make input labels bigger with glow effect */
    label[data-testid="stWidgetLabel"] {
        font-size: 200px !important;
        font-weight: 700 !important;
        color: #00FFFF !important;
    }
    
    /* Alternative selector for input labels */
    .stTextInput label, 
    .stNumberInput label,
    .stFileUploader label,
    .stTextInput > div > div > label,
    .stNumberInput > div > div > label,
    .stFileUploader > div > div > label {
        font-size: 200px !important;
        font-weight: 700 !important;
        color: #00FFFF !important;
    }
    
    /* Make help text more visible */
    .stTextInput .help,
    .stNumberInput .help,
    .stFileUploader .help {
        font-size: 14px !important;
        color: #CCCCCC !important;
    }
</style>
""", unsafe_allow_html=True)

def initialize_session_state():
    if 'stage' not in st.session_state:
        st.session_state.stage = 'input'
    if 'blog_items' not in st.session_state:
        st.session_state.blog_items = []
    if 'processing_complete' not in st.session_state:
        st.session_state.processing_complete = False
    if 'processing_mode' not in st.session_state:
        st.session_state.processing_mode = 'website'

def extract_content_directly():
    st.markdown('<div class="stage-container">', unsafe_allow_html=True)
    st.subheader("🔍 Blog Content Extraction")
    
    url = st.text_input(
        "Blog Website URL:",
        value="https://interviewing.io/blog",
        placeholder="Enter the main blog page URL...",
        help="Enter the URL of the main blog page"
    )
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("🔑 **API Key Required**: Please set GEMINI_API_KEY or GOOGLE_API_KEY environment variable")
        st.code("export GEMINI_API_KEY=your_api_key_here")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    max_posts = st.number_input(
        "Maximum posts to extract: (  use this because if website contains 20 post it could take longer time to fetch all of those  )",
        min_value=1,
        max_value=20,
        value=5,
        help="Limit the number of posts to process"
    )
    
    if st.button("🚀 Start Content Extraction", type="primary", use_container_width=True):
        if not url.strip():
            st.error("Please enter a valid URL")
            return
        
        overall_progress = st.progress(0)
        status_text = st.empty()
        post_progress_container = st.container()
        
        try:
            # Step 1: Get blog list
            status_text.text("📄 Finding blog posts...")
            overall_progress.progress(0.1)
            
            markdown = get_markdown_from_jina(url)
            if not markdown.strip():
                st.error("❌ Failed to get markdown content from the URL")
                return
            
            status_text.text("🔍 Extracting blog post URLs...")
            overall_progress.progress(0.2)
            
            raw_items, token_usage = extract_blog_list_with_gemini(markdown, url)
            if not raw_items:
                st.error("❌ No blog posts found on the page")
                return
            
            # Show blog list found
            st.success(f"✅ Found {len(raw_items)} blog posts!")
            
            # Download JSON button for blog list
            blog_list_json = json.dumps(raw_items, indent=2)
            st.download_button(
                label="📥 Download Blog List JSON",
                data=blog_list_json,
                file_name="blog_list.json",
                mime="application/json",
                key="download_blog_list"
            )
            
            # Limit posts to process
            posts_to_process = raw_items[:max_posts]
            total_posts = len(posts_to_process)
            
            status_text.text(f"📝 Found {total_posts} posts - extracting content...")
            
            # Step 2: Extract content from each post
            processed_items = []
            
            for i, item in enumerate(posts_to_process):
                progress = 0.2 + (0.8 * i / total_posts)
                overall_progress.progress(progress)
                status_text.text(f"📖 Processing post {i+1} of {total_posts}: {item.get('title', 'Unknown')[:40]}...")
                
                with post_progress_container:
                    with st.expander(f"📝 Post {i+1}/{total_posts}: {item.get('title', 'Unknown')[:60]}...", expanded=(i==0)):
                        post_col1, post_col2 = st.columns([3, 1])
                        
                        with post_col1:
                            post_progress = st.progress(0)
                            post_status = st.empty()
                        
                        with post_col2:
                            post_metrics = st.empty()
                        
                        post_status.text("🔄 Fetching content...")
                        post_progress.progress(50)
                        
                        content, content_tokens = fetch_individual_blog_content(item)
                        item["content"] = content
                        
                        post_progress.progress(100)
                        post_status.text("✅ Complete")
                        
                        with post_metrics:
                            st.metric("Characters", f"{len(content):,}")
                            if content.strip():
                                st.success("✅ Extracted")
                                # Show full content in scrollable format
                                with st.expander(f"📖 Full Content - {item.get('title', 'Unknown')[:40]}...", expanded=False):
                                    st.write(f"**Author:** {item.get('author', 'Unknown')}")
                                    st.write(f"**Type:** {item.get('content_type', 'blog')}")
                                    st.write(f"**URL:** {item.get('source_url', '')}")
                                    
                                    st.markdown("### 📝 Full Content:")
                                    # Show raw content in text area
                                    st.text_area(
                                        label="Raw Content",
                                        value=content,
                                        height=400,
                                        disabled=True,
                                        label_visibility="collapsed",
                                        key=f"content_extraction_{i}"
                                    )
                            else:
                                st.warning("❌ No content found")
                
                processed_items.append(item)
            
            # Final processing
            overall_progress.progress(1.0)
            status_text.text(f"✅ Content extraction complete! Found {len(processed_items)} posts.")
            
            validated_items = validate_and_format_items(processed_items)
            st.session_state.blog_items = validated_items
            st.session_state.processing_complete = True
            st.session_state.stage = 'results'
            
            time.sleep(1)
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error during extraction: {str(e)}")
    
    st.markdown('</div>', unsafe_allow_html=True)

def extract_pdf_content():
    st.markdown('<div class="stage-container">', unsafe_allow_html=True)
    st.subheader("📄 PDF Content Extraction")
    
    uploaded_file = st.file_uploader(
        "Upload PDF File (Upload Alice Chapter 1-7 PDF):",
        type=['pdf'],
        help="Upload a PDF file to extract content from (e.g., Alice's book chapters)"
    )
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("🔑 **API Key Required**: Please set GEMINI_API_KEY or GOOGLE_API_KEY environment variable")
        st.code("export GEMINI_API_KEY=your_api_key_here")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    if uploaded_file is not None:
        st.success(f"✅ File uploaded: {uploaded_file.name}")
        st.write(f"**File size:** {uploaded_file.size:,} bytes. Please wait it can take time to generate results (2-5 min)")
        
        if st.button("🚀 Start PDF Extraction", type="primary", use_container_width=True):
            # Save uploaded file temporarily
            temp_path = f"temp_{uploaded_file.name}"
            try:
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                overall_progress = st.progress(0)
                status_text = st.empty()
                
                # Process PDF
                status_text.text("📄 Extracting text from PDF...")
                overall_progress.progress(0.2)
                
                extracted_items, token_usage = process_pdf_file(temp_path)
                
                if not extracted_items:
                    st.error("❌ No content could be extracted from the PDF")
                    return
                
                # Show extraction results
                st.success(f"✅ Extracted {len(extracted_items)} chapters from PDF!")
                
                # Download JSON button for PDF content
                pdf_content_json = json.dumps(extracted_items, indent=2)
                st.download_button(
                    label="📥 Download PDF Content JSON",
                    data=pdf_content_json,
                    file_name="pdf_content.json",
                    mime="application/json",
                    key="download_pdf_content"
                )
                
                overall_progress.progress(0.8)
                status_text.text("🔄 Processing PDF chunks...")
                
                # Show progress for each chunk
                chunk_container = st.container()
                
                for i, item in enumerate(extracted_items):
                    progress = 0.8 + (0.2 * i / len(extracted_items))
                    overall_progress.progress(progress)
                    
                    with chunk_container:
                        with st.expander(f"📝 Chunk {i+1}/{len(extracted_items)}: {item.get('title', 'Unknown')[:60]}...", expanded=(i==0)):
                            col1, col2 = st.columns([3, 1])
                            
                            with col1:
                                st.write(f"**Title:** {item.get('title', 'Unknown')}")
                                st.write(f"**Page Range:** {item.get('page_range', 'Unknown')}")
                                st.write(f"**Chapter:** {item.get('chapter', 'Unknown')}")
                                st.write(f"**Content Length:** {len(item.get('content', '')):,} characters")
                                
                                # Show full content in scrollable format
                                if item.get('content', '').strip():
                                    with st.expander(f"📖 Full Content - {item.get('title', 'Unknown')[:40]}...", expanded=False):
                                        st.markdown("### 📝 Full Content:")
                                        # Show raw content in text area
                                        st.text_area(
                                            label="Raw Content",
                                            value=item.get('content', ''),
                                            height=400,
                                            disabled=True,
                                            label_visibility="collapsed",
                                            key=f"pdf_content_{i}"
                                        )
                            
                            with col2:
                                st.metric("Characters", f"{len(item.get('content', '')):,}")
                                st.success("✅ Extracted")
                
                # Convert to BlogItem format for consistency
                blog_items = []
                for item in extracted_items:
                    blog_item = BlogItem(
                        title=item.get('title', 'Unknown'),
                        content=item.get('content', ''),
                        content_type=item.get('content_type', 'pdf_chapter'),
                        source_url=item.get('source_url', uploaded_file.name),
                        author=item.get('author', 'Unknown'),
                        user_id=item.get('user_id', '')
                    )
                    blog_items.append(blog_item)
                
                overall_progress.progress(1.0)
                status_text.text(f"✅ PDF extraction complete! Processed {len(extracted_items)} chunks.")
                
                st.session_state.blog_items = blog_items
                st.session_state.processing_complete = True
                st.session_state.processing_mode = 'pdf'
                st.session_state.stage = 'results'
                
                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error during PDF extraction: {str(e)}")
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    
    st.markdown('</div>', unsafe_allow_html=True)

def display_final_results():
    # Add back button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Back", use_container_width=True):
            st.session_state.stage = 'input'
            st.session_state.processing_complete = False
            st.rerun()
    
    st.subheader("🎉 Extraction Complete!")
    
    # Determine content type for display
    processing_mode = st.session_state.get('processing_mode', 'website')
    if processing_mode == 'pdf':
        st.write(f"**Successfully extracted {len(st.session_state.blog_items)} PDF chapters:**")
    else:
        st.write(f"**Successfully extracted {len(st.session_state.blog_items)} blog posts:**")
    
    # Prepare full results JSON
    all_results = {
        "team_id": "aline123",
        "items": [
            {
                "title": item.title,
                "content": item.content,
                "content_type": item.content_type,
                "source_url": item.source_url,
                "author": item.author,
                "user_id": item.user_id
            }
            for item in st.session_state.blog_items
        ]
    }
    
    # For website extraction, show full JSON preview
    processing_mode = st.session_state.get('processing_mode', 'website')
    if processing_mode == 'website':
        with st.expander("🔍 Full JSON Preview - All Results", expanded=False):
            st.json(all_results)
    
    # Download all results button
    st.download_button(
        label="📥 Download All Results (JSON)",
        data=json.dumps(all_results, indent=2),
        file_name="content_extraction_results.json",
        mime="application/json",
        type="primary",
        use_container_width=True
    )
    
    # Dynamic section header based on content type
    processing_mode = st.session_state.get('processing_mode', 'website')
    if processing_mode == 'pdf':
        st.subheader("📄 Extracted PDF Content")
    else:
        st.subheader("📝 Extracted Blog Posts")
    
    for i, item in enumerate(st.session_state.blog_items, 1):
        with st.expander(f"📰 {i}. {item.title}"):
            col1, col2 = st.columns([3, 2])
            
            with col1:
                st.write(f"**URL:** {item.source_url}")
                st.write(f"**Author:** {item.author or 'Unknown'}")
                st.write(f"**Type:** {item.content_type}")
                
                # Only show content length for PDF
                processing_mode = st.session_state.get('processing_mode', 'website')
                if processing_mode == 'pdf':
                    st.write(f"**Content Length:** {len(item.content):,} characters")
                
                if item.content:
                    st.markdown("### 📝 Full Content:")
                    # Show raw content in text area with scrollbar
                    st.text_area(
                        label="Raw Content",
                        value=item.content,
                        height=400,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"content_final_{i}"
                    )
                else:
                    st.warning("No content extracted - the post might be empty or inaccessible")
            
            with col2:
                processing_mode = st.session_state.get('processing_mode', 'website')
                item_json = {
                    "title": item.title,
                    "content": item.content,
                    "content_type": item.content_type,
                    "source_url": item.source_url,
                    "author": item.author,
                    "user_id": item.user_id
                }
                
                st.markdown("### 📥 Download Options")
                
                # Download button for both website and PDF
                filename_prefix = "blog_post" if processing_mode == 'website' else "pdf_chapter"
                st.download_button(
                    label="📥 Download JSON",
                    data=json.dumps(item_json, indent=2),
                    file_name=f"{filename_prefix}_{i}.json",
                    mime="application/json",
                    key=f"download_{i}",
                    use_container_width=True
                )
                
                # Show content metrics only for PDF
                if processing_mode == 'pdf':
                    st.metric("Content Length", f"{len(item.content):,} chars")
                    st.metric("Content Type", item.content_type)
    
    st.divider()
    
    # Bottom actions
    col1, col2 = st.columns(2)
    with col1:
        processing_mode = st.session_state.get('processing_mode', 'website')
        action_text = "🔄 Extract More Content" if processing_mode == 'pdf' else "🔄 Start New Extraction"
        if st.button(action_text, use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    with col2:
        # Summary info - only show for PDF
        processing_mode = st.session_state.get('processing_mode', 'website')
        if processing_mode == 'pdf':
            total_chars = sum(len(item.content) for item in st.session_state.blog_items)
            st.metric("Total Content", f"{total_chars:,} characters")
        else:
            # For website, show different summary
            st.metric("Total Posts", len(st.session_state.blog_items))

def main():
    initialize_session_state()
    
    st.title("📰 Content Scraper")
    st.write("Extract content from websites and PDFs with AI-powered processing")
    
    # Processing mode tabs
    if st.session_state.stage == 'input':
        tab1, tab2 = st.tabs(["🌐 Website Extraction", "📄 PDF Extraction"])
        
        with tab1:
            extract_content_directly()
        
        with tab2:
            extract_pdf_content()
    
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            st.success("✅ API Key configured")
        else:
            st.error("❌ API Key not found")
            st.code("export GEMINI_API_KEY=your_key")
        
        st.header("📋 Process Overview")
        if st.session_state.get('processing_mode') == 'pdf':
            st.write("""
            **PDF Content Extraction**
            - Upload Alice Chapter 1-7 PDF
            - Extract text and structure content
            - Identify chapters and sections
            - Process with AI for clean content
            """)
        else:
            st.write("""
            **Website Content Extraction**
            - Finds all blog posts on the page
            - Extracts full content from each post
            - Shows progress: "Processing 3 of 10 posts"
            """)
        
        if st.session_state.processing_complete:
            st.header("📊 Status")
            mode = st.session_state.get('processing_mode', 'website')
            if mode == 'pdf':
                st.write("✅ PDF extraction complete!")
            else:
                st.write("✅ Website extraction complete!")
    
    if st.session_state.stage == 'results':
        display_final_results()

if __name__ == "__main__":
    main() 