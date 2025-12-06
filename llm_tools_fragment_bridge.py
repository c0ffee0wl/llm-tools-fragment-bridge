"""
llm-tools-fragment-bridge - Expose fragment loaders as callable tools.

This plugin wraps whitelisted fragment loaders (yt, github, pdf) as tools
that can be called by LLMs during conversations.
"""
import llm
import os
import tempfile
import urllib.request

# Whitelist of fragment prefixes to expose as tools
WHITELISTED_PREFIXES = ['yt', 'github', 'pdf']

# Tool metadata for each prefix
TOOL_METADATA = {
    'yt': {
        'name': 'load_yt',
        'doc': '''Load a YouTube video transcript.

Args:
    argument: YouTube video URL (e.g., https://youtube.com/watch?v=xxx) or video ID

Returns:
    The video transcript as text, with metadata (title, channel, duration) if available.
''',
    },
    'github': {
        'name': 'load_github',
        'doc': '''Load files from a GitHub repository.

Args:
    argument: GitHub repository in format "owner/repo" or full URL

Returns:
    Repository files as text fragments, each with source attribution.
''',
    },
    'pdf': {
        'name': 'load_pdf',
        'doc': '''Extract text from a PDF document.

Args:
    argument: Path to local PDF file or URL to remote PDF

Returns:
    Extracted text content from the PDF, converted to markdown format.
''',
    },
}


def _download_url_to_temp(url: str, suffix: str = '') -> str:
    """Download URL to a temporary file, return the path."""
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
    )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        with urllib.request.urlopen(request) as response:
            tmp.write(response.read())
        return tmp.name


def _make_tool(prefix: str, loader):
    """Create a tool function that wraps a fragment loader."""
    metadata = TOOL_METADATA.get(prefix, {
        'name': f'load_{prefix}',
        'doc': f'Load content from {prefix}:<argument>. Returns text.',
    })

    def tool_fn(argument: str) -> str:
        temp_file = None
        actual_arg = argument

        # For PDF: download remote URLs to temp file
        if prefix == 'pdf' and argument.startswith(('http://', 'https://')):
            try:
                temp_file = _download_url_to_temp(argument, suffix='.pdf')
                actual_arg = temp_file
            except Exception as e:
                return f"Error downloading PDF from {argument}: {e}"

        try:
            results = loader(actual_arg)
        except Exception as e:
            return f"Error loading {prefix}:{argument}: {e}"
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                os.unlink(temp_file)

        if not isinstance(results, list):
            results = [results]

        parts = []
        for r in results:
            if isinstance(r, llm.Fragment):
                source = getattr(r, 'source', f'{prefix}:{argument}')
                parts.append(f"--- Source: {source} ---\n{str(r)}")
            elif isinstance(r, llm.Attachment):
                mime_type = getattr(r, 'type', 'unknown')
                location = r.path or r.url or 'inline'
                parts.append(f"[Attachment: {mime_type} at {location}]")
            else:
                # String or other content
                parts.append(str(r))

        return "\n\n".join(parts) if parts else "[No content returned]"

    # Set function metadata
    tool_fn.__name__ = metadata['name']
    tool_fn.__doc__ = metadata['doc']

    return tool_fn


@llm.hookimpl
def register_tools(register):
    """Register fragment loaders as tools."""
    loaders = llm.get_fragment_loaders()

    for prefix in WHITELISTED_PREFIXES:
        if prefix in loaders:
            tool = _make_tool(prefix, loaders[prefix])
            register(tool)
