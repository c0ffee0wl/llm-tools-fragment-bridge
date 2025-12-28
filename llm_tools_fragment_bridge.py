"""
llm-tools-fragment-bridge - Expose fragment loaders as callable tools.

This plugin wraps whitelisted fragment loaders (yt, github, pdf) as tools
that can be called by LLMs during conversations.
"""
import llm
import os
import re
import tempfile
import urllib.request

# Whitelist of fragment prefixes to expose as tools
WHITELISTED_PREFIXES = ['yt', 'github', 'pdf']

# Content protection limits
MAX_CONTENT_CHARS = 150_000  # ~37k tokens, safe for most context windows

# GitHub-specific: files/directories to filter out (noise reduction)
GITHUB_SKIP_FILES = {
    # Lock files (huge, low signal)
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'Cargo.lock', 'poetry.lock', 'Gemfile.lock', 'composer.lock',
    'Pipfile.lock', 'go.sum', 'pubspec.lock', 'mix.lock',
    # Other low-value files
    '.gitignore', '.gitattributes', '.editorconfig',
    '.prettierrc', '.eslintrc', '.stylelintrc',
}

GITHUB_SKIP_DIRS = {
    'node_modules/', 'vendor/', '.venv/', 'venv/',
    '__pycache__/', '.git/', '.idea/', '.vscode/',
    'dist/', 'build/', 'target/', '.next/', '.nuxt/',
    'coverage/', '.tox/', '.mypy_cache/', '.pytest_cache/',
}

GITHUB_SKIP_EXTENSIONS = {
    # Minified/generated
    '.min.js', '.min.css', '.map', '.d.ts',
    # Binary-ish text
    '.svg', '.woff', '.woff2', '.ttf', '.eot', '.ico',
    # Data files (often huge)
    '.csv', '.jsonl', '.ndjson',
}

# Tool metadata for each prefix
TOOL_METADATA = {
    'yt': {
        'name': 'load_yt',
        'doc': '''Load transcript from a YouTube video.

Extracts the video transcript with timestamps and speaker labels when available.
Returns full metadata including title, channel name, view count, and duration.
Videos must have captions (auto-generated or manual) to extract text.

Args:
    argument: YouTube URL or video ID
        Examples: "https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"

Returns:
    Transcript text with video metadata (title, channel, duration, view count).
    Fails on: age-restricted, private, or caption-less videos.
''',
    },
    'github': {
        'name': 'load_github',
        'doc': '''Load source code from a GitHub repository.

Fetches text files from a public GitHub repository and returns them as
concatenated content with file path headers. Noise files (lock files,
node_modules, vendor dirs, build artifacts) are filtered out automatically.
Large repositories are truncated to ~150k chars after filtering.

Args:
    argument: Repository in "owner/repo" format or full GitHub URL
        Examples: "simonw/llm", "https://github.com/simonw/llm"

Returns:
    Repository files as text with source attribution headers.
    A [Protection: ...] header indicates if filtering/truncation occurred.
    Not for: single file URLs, issues, PRs, or private repositories.
''',
    },
    'pdf': {
        'name': 'load_pdf',
        'doc': '''Extract text from a PDF document.

Parses PDF files and extracts text content in markdown format, preserving
basic structure like headings and lists where possible. Supports both local
files and remote URLs. Works best with text-based PDFs.

Args:
    argument: Local file path or URL to PDF
        Examples: "/path/to/doc.pdf", "https://example.com/report.pdf"

Returns:
    Extracted text in markdown format.
    Limitations: Scanned/image PDFs and password-protected files will fail.
''',
    },
}


def _should_skip_github_file(filepath: str) -> bool:
    """Check if a GitHub file should be filtered out."""
    filename = os.path.basename(filepath)

    # Skip known noise files
    if filename in GITHUB_SKIP_FILES:
        return True

    # Skip files in noise directories
    # Check if any path component matches a skip directory
    path_parts = filepath.replace('\\', '/').split('/')
    for skip_dir in GITHUB_SKIP_DIRS:
        dir_name = skip_dir.rstrip('/')
        if dir_name in path_parts:
            return True

    # Skip by extension
    for ext in GITHUB_SKIP_EXTENSIONS:
        if filepath.endswith(ext):
            return True

    return False


def _filter_github_content(content: str) -> tuple[str, dict]:
    """
    Filter GitHub content by removing noise files.
    Returns (filtered_content, stats_dict).
    """
    # GitHub fragment format: "--- Source: path/to/file ---\n<content>"
    file_pattern = re.compile(r'--- Source: ([^\n]+) ---\n')

    parts = file_pattern.split(content)
    # parts = [preamble, path1, content1, path2, content2, ...]

    if len(parts) < 3:
        # No file markers found, return as-is
        return content, {'files_kept': 0, 'files_skipped': 0, 'skipped_list': []}

    filtered_parts = []
    preamble = parts[0]
    if preamble.strip():
        filtered_parts.append(preamble)

    files_kept = 0
    files_skipped = 0
    skipped_list = []

    # Process path/content pairs
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        filepath = parts[i].strip()
        file_content = parts[i + 1]

        if _should_skip_github_file(filepath):
            files_skipped += 1
            skipped_list.append(filepath)
        else:
            files_kept += 1
            filtered_parts.append(f"--- Source: {filepath} ---\n{file_content}")

    stats = {
        'files_kept': files_kept,
        'files_skipped': files_skipped,
        'skipped_list': skipped_list[:10],  # Only keep first 10 for brevity
    }

    return '\n\n'.join(filtered_parts), stats


def _truncate_content(content: str, max_chars: int = MAX_CONTENT_CHARS) -> tuple[str, bool]:
    """
    Truncate content if it exceeds max_chars.
    Returns (content, was_truncated).
    """
    if len(content) <= max_chars:
        return content, False

    # Find a clean break point (end of a file section or line)
    truncated = content[:max_chars]

    # Try to break at a file boundary
    last_source = truncated.rfind('\n--- Source:')
    if last_source > max_chars * 0.8:  # Only if we keep >80% of content
        truncated = truncated[:last_source]
    else:
        # Fall back to line boundary
        last_newline = truncated.rfind('\n')
        if last_newline > 0:
            truncated = truncated[:last_newline]

    return truncated, True


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

        content = "\n\n".join(parts) if parts else "[No content returned]"

        # Apply content protection
        filter_stats = None
        was_truncated = False

        # GitHub-specific: filter noise files first
        if prefix == 'github':
            content, filter_stats = _filter_github_content(content)

        # Capture size after filtering but before truncation
        size_before_truncation = len(content)

        # Apply truncation to all content types
        content, was_truncated = _truncate_content(content)

        # Add protection summary if modifications were made
        if (filter_stats and filter_stats['files_skipped'] > 0) or was_truncated:
            summary_parts = []
            if filter_stats and filter_stats['files_skipped'] > 0:
                summary_parts.append(
                    f"Filtered {filter_stats['files_skipped']} noise files "
                    f"(lock files, vendor dirs, etc.)"
                )
            if was_truncated:
                summary_parts.append(
                    f"Truncated from {size_before_truncation:,} to {len(content):,} chars "
                    f"({MAX_CONTENT_CHARS:,} limit)"
                )
            content = f"[Protection: {'; '.join(summary_parts)}]\n\n{content}"

        return content

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
