"""
HTML to Markdown Converter

Converts Confluence HTML storage format to clean Markdown.
Special handling for:
- Tables (pipe format)
- Code blocks (with language detection)
- Lists (ordered and unordered)
- Headers
- Links and images
"""

import re
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import MarkdownConverter, ATX


class ConfluenceMarkdownConverter(MarkdownConverter):
    """
    Custom Markdown converter optimized for Confluence HTML.
    
    Extends markdownify with better handling of Confluence-specific elements.
    """

    def __init__(self, **options):
        options.setdefault("heading_style", ATX)
        options.setdefault("bullets", "-")
        options.setdefault("code_language", "")
        super().__init__(**options)

    def convert_table(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Convert table to GitHub-flavored Markdown pipe format."""
        rows = []
        
        for tr in el.find_all("tr", recursive=False):
            cells = tr.find_all(["th", "td"], recursive=False)
            row_content = []
            
            for cell in cells:
                # Get cell text, preserving inline formatting
                cell_text = self.process_text(cell.get_text(separator=" ", strip=True))
                # Escape pipes in content
                cell_text = cell_text.replace("|", "\\|")
                row_content.append(cell_text)
            
            if row_content:
                rows.append("| " + " | ".join(row_content) + " |")
        
        if not rows:
            return ""
        
        # Add header separator after first row
        if len(rows) > 0:
            num_cols = rows[0].count("|") - 1
            separator = "|" + "|".join(["---"] * num_cols) + "|"
            rows.insert(1, separator)
        
        return "\n" + "\n".join(rows) + "\n"

    def convert_pre(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Convert code blocks with language detection."""
        # Try to detect language from class
        code_el = el.find("code")
        lang = ""
        
        if code_el:
            classes = code_el.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls[9:]
                    break
                elif cls in ["java", "python", "javascript", "xml", "json", "sql", "bash", "sh"]:
                    lang = cls
                    break
        
        # Also check data-language attribute (Confluence style)
        if not lang:
            lang = el.get("data-language", "") or el.get("data-syntaxhighlighter-params", "")
            if "brush:" in lang:
                match = re.search(r"brush:\s*(\w+)", lang)
                if match:
                    lang = match.group(1)
        
        code_text = el.get_text()
        return f"\n```{lang}\n{code_text}\n```\n"

    def convert_ac_macro(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Handle Confluence macros (code, panel, info, etc.)."""
        macro_name = el.get("ac:name", "")
        
        if macro_name in ["code", "noformat"]:
            code_body = el.find(["ac:plain-text-body", "pre", "code"])
            if code_body:
                lang = el.get("ac:parameter", {}).get("language", "")
                code_text = code_body.get_text()
                return f"\n```{lang}\n{code_text}\n```\n"
        
        elif macro_name in ["info", "note", "warning", "tip"]:
            body = el.find("ac:rich-text-body")
            if body:
                body_text = self.convert(str(body))
                prefix = {"info": "ℹ️", "note": "📝", "warning": "⚠️", "tip": "💡"}.get(macro_name, "")
                return f"\n> {prefix} {body_text.strip()}\n"
        
        # Default: just return the text content
        return text

    def process_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def html_to_markdown(
    html: str,
    strip_tags: Optional[list] = None,
    preserve_tables: bool = True,
) -> str:
    """
    Convert Confluence HTML to clean Markdown.
    
    Args:
        html: Raw HTML string
        strip_tags: Tags to remove entirely (default: script, style)
        preserve_tables: Whether to convert tables to Markdown format
        
    Returns:
        Clean Markdown string
    """
    if not html:
        return ""
    
    # Pre-process HTML
    soup = BeautifulSoup(html, "lxml")
    
    # Remove unwanted tags
    tags_to_remove = strip_tags or ["script", "style", "noscript"]
    for tag in soup(tags_to_remove):
        tag.decompose()
    
    # Handle Confluence-specific structures
    # Handle nested tables within cells
    for tbody in soup.find_all("tbody"):
        if tbody.parent and tbody.parent.name == "table":
            continue  # Keep normal table structure
    
    # Convert using custom converter
    converter = ConfluenceMarkdownConverter()
    markdown = converter.convert(str(soup))
    
    # Post-process
    # Remove excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    
    # Clean up list formatting
    markdown = re.sub(r"(\n-\s+)", r"\n- ", markdown)
    
    # Normalize whitespace at start/end
    markdown = markdown.strip()
    
    return markdown


def smart_truncate(
    text: str,
    max_chars: int = 12000,
    truncation_message: str = "\n\n---\n*[Content truncated. View full page at: {url}]*",
    url: str = "",
) -> str:
    """
    Intelligently truncate text without cutting mid-sentence.
    
    Args:
        text: Text to truncate
        max_chars: Maximum characters
        truncation_message: Message to append (can include {url})
        url: URL to include in truncation message
        
    Returns:
        Truncated text with optional message
    """
    if len(text) <= max_chars:
        return text
    
    # Reserve space for truncation message
    message = truncation_message.format(url=url)
    effective_max = max_chars - len(message)
    
    if effective_max <= 0:
        return text[:max_chars]
    
    truncated = text[:effective_max]
    
    # Find a good break point
    # Prefer paragraph breaks, then sentence ends, then word breaks
    
    # Try to find paragraph break
    last_para = truncated.rfind("\n\n")
    if last_para > effective_max * 0.7:  # If reasonably close to end
        return truncated[:last_para] + message
    
    # Try to find sentence end
    sentence_ends = [
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("? "),
        truncated.rfind("! "),
    ]
    best_sentence = max(s for s in sentence_ends if s > 0) if any(s > 0 for s in sentence_ends) else -1
    
    if best_sentence > effective_max * 0.7:
        return truncated[:best_sentence + 1] + message
    
    # Fall back to word break
    last_space = truncated.rfind(" ")
    if last_space > effective_max * 0.7:
        return truncated[:last_space] + message
    
    # Last resort: hard cut
    return truncated + message


if __name__ == "__main__":
    # Test the converter
    sample_html = """
    <h1>Kafka Producer Guide</h1>
    <p>This guide explains how to use the Kafka <strong>Producer API</strong>.</p>
    
    <h2>Configuration</h2>
    <table>
        <tr><th>Property</th><th>Default</th><th>Description</th></tr>
        <tr><td>bootstrap.servers</td><td>localhost:9092</td><td>Kafka brokers</td></tr>
        <tr><td>acks</td><td>1</td><td>Acknowledgment level</td></tr>
    </table>
    
    <h2>Example Code</h2>
    <pre data-language="java">
    Producer<String, String> producer = new KafkaProducer<>(props);
    producer.send(new ProducerRecord<>("topic", "key", "value"));
    producer.close();
    </pre>
    
    <div class="confluence-information-macro">
        <p>Remember to close the producer when done!</p>
    </div>
    """
    
    markdown = html_to_markdown(sample_html)
    print("=== Converted Markdown ===")
    print(markdown)
    
    print("\n=== Truncation Test ===")
    long_text = "This is a sentence. " * 1000
    truncated = smart_truncate(long_text, max_chars=500, url="https://example.com/page")
    print(f"Original length: {len(long_text)}")
    print(f"Truncated length: {len(truncated)}")
    print(truncated[-200:])
