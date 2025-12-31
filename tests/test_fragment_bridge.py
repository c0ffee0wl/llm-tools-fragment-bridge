"""Tests for llm-tools-fragment-bridge plugin."""
import llm


def test_tools_registered():
    """Test that fragment bridge tools are registered."""
    tools = llm.get_tools()

    # Check that at least one of our tools is registered
    # (depends on which fragment plugins are installed)
    tool_names = list(tools.keys())
    expected_tools = ['load_yt', 'load_github', 'load_pdf']

    registered = [name for name in expected_tools if name in tool_names]
    assert len(registered) > 0, f"No fragment bridge tools found. Tools: {tool_names}"


def test_load_yt_registered():
    """Test load_yt tool is registered if yt fragment loader exists."""
    loaders = llm.get_fragment_loaders()
    tools = llm.get_tools()

    if 'yt' in loaders:
        assert 'load_yt' in tools, "load_yt tool should be registered when yt loader exists"
        tool = tools['load_yt']
        assert 'YouTube' in tool.description or 'transcript' in tool.description.lower()


def test_load_github_registered():
    """Test load_github tool is registered if github fragment loader exists."""
    loaders = llm.get_fragment_loaders()
    tools = llm.get_tools()

    if 'github' in loaders:
        assert 'load_github' in tools, "load_github tool should be registered when github loader exists"
        tool = tools['load_github']
        assert 'GitHub' in tool.description or 'repository' in tool.description.lower()


def test_load_pdf_registered():
    """Test load_pdf tool is registered if pdf fragment loader exists."""
    loaders = llm.get_fragment_loaders()
    tools = llm.get_tools()

    if 'pdf' in loaders:
        assert 'load_pdf' in tools, "load_pdf tool should be registered when pdf loader exists"
        tool = tools['load_pdf']
        assert 'PDF' in tool.description or 'pdf' in tool.description.lower()


def test_tool_has_implementation():
    """Test that registered tools have callable implementations."""
    tools = llm.get_tools()

    for name in ['load_yt', 'load_github', 'load_pdf']:
        if name in tools:
            tool = tools[name]
            assert callable(tool.implementation), f"{name} should have callable implementation"
