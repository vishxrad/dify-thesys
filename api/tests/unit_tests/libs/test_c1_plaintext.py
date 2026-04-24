"""Tests for libs.c1_plaintext."""

from __future__ import annotations

from libs.c1_plaintext import extract_plaintext, is_c1_content


class TestIsC1Content:
    def test_returns_false_for_empty(self) -> None:
        assert is_c1_content("") is False
        assert is_c1_content(None) is False

    def test_returns_false_for_plain_markdown(self) -> None:
        assert is_c1_content("Hello, world.") is False
        assert is_c1_content("## Heading\n\nbody") is False

    def test_returns_true_for_content_envelope(self) -> None:
        assert is_c1_content('<content thesys="true">{"component":"Card"}</content>') is True
        assert is_c1_content('<content thesys="true" version="2">body</content>') is True


class TestExtractPlaintextPassThrough:
    def test_non_c1_content_returns_as_is(self) -> None:
        assert extract_plaintext("Hello, world.") == "Hello, world."

    def test_empty_input_returns_empty_string(self) -> None:
        assert extract_plaintext("") == ""
        assert extract_plaintext(None) == ""


class TestExtractPlaintextOpenUILang:
    """Cover the `version="2"` openui-lang DSL path."""

    def test_extracts_header_and_body(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'root = Card([header, body])\n'
            'header = Header("Hello!", "How can I help you today?")\n'
            'body = TextContent("I can plan trips and build dashboards.")\n'
            "```\n"
            "</content>"
        )

        result = extract_plaintext(content)

        assert "Hello!" in result
        assert "How can I help you today?" in result
        assert "I can plan trips and build dashboards." in result
        # Card is a container — should not show up literally.
        assert "Card" not in result

    def test_decodes_html_entities(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'greeting = TextContent(&quot;Hello, I&#39;m here.&quot;)\n'
            "```\n"
            "</content>"
        )

        assert extract_plaintext(content) == "Hello, I'm here."

    def test_follow_up_block_joins_options(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'fu = FollowUpBlock(["Plan a trip", "Build a form", "Summarise a doc"])\n'
            "```\n"
            "</content>"
        )

        assert extract_plaintext(content) == (
            "Follow-ups: Plan a trip · Build a form · Summarise a doc"
        )

    def test_skips_state_declarations(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            '$days = "7"\n'
            'header = Header("Pick a range", "")\n'
            "```\n"
            "</content>"
        )

        result = extract_plaintext(content)
        assert "7" not in result  # state default should not leak into prose
        assert "Pick a range" in result

    def test_skips_icon_and_query_plumbing(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'ic = Icon("map", "travel")\n'
            'data = Query("fetchOrders", {}, {rows: []})\n'
            'msg = TextContent("visible text")\n'
            "```\n"
            "</content>"
        )

        result = extract_plaintext(content)
        assert result == "visible text"
        assert "map" not in result
        assert "fetchOrders" not in result

    def test_unknown_component_falls_back_to_strings(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'weird = FancyNewWidget("meaningful label", "more prose")\n'
            "```\n"
            "</content>"
        )

        assert extract_plaintext(content) == "meaningful label more prose"

    def test_chart_emits_semantic_placeholder(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "```openui-lang\n"
            'chart = BarChart(data)\n'
            "```\n"
            "</content>"
        )

        assert extract_plaintext(content) == "[bar chart]"

    def test_malformed_body_degrades_gracefully(self) -> None:
        content = (
            '<content thesys="true" version="2">\n'
            "this isn't a statement at all\n"
            "</content>"
        )

        # Nothing parses cleanly → empty string, no exception raised.
        assert extract_plaintext(content) == ""


class TestExtractPlaintextJsonV1:
    """Cover the `version="1"` / default JSON path."""

    def test_walks_json_component_tree(self) -> None:
        content = (
            '<content thesys="true">'
            '{"component":"Card","props":{"children":['
            '{"component":"Header","props":{"title":"Hello","description":"Welcome back."}},'
            '{"component":"TextContent","props":{"content":"Body prose goes here."}}'
            "]}}"
            "</content>"
        )

        result = extract_plaintext(content)
        assert "Hello" in result
        assert "Welcome back." in result
        assert "Body prose goes here." in result

    def test_malformed_json_falls_back_to_string_sweep(self) -> None:
        content = (
            '<content thesys="true">'
            '{"component":"Card","props":{"children":[{"component":"Header","props"'
            "</content>"
        )

        result = extract_plaintext(content)
        # Truncated JSON → we pull whatever strings we can.
        assert "Card" in result or "Header" in result

    def test_decodes_entities_in_v1(self) -> None:
        # Thesys serialises JSON into XML text by escaping structural quotes
        # as `&quot;`. Content-internal escaped quotes are serialised as
        # `\&quot;` so that after entity decoding the JSON parser sees `\"`.
        content = (
            '<content thesys="true">'
            "{&quot;component&quot;:&quot;Header&quot;,"
            "&quot;props&quot;:{&quot;title&quot;:&quot;Hello, I&#39;m here.&quot;,"
            "&quot;description&quot;:&quot;call it \\&quot;quoted\\&quot;&quot;}}"
            "</content>"
        )

        result = extract_plaintext(content)
        assert "Hello, I'm here." in result
        assert 'call it "quoted"' in result
