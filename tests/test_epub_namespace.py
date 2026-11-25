from lxml import etree

from ebook_translator.ingestion.epub import EpubDocument


def test_namespaced_epub_xhtml_blocks_are_detected():
    root = etree.fromstring(b"""
    <html xmlns="http://www.w3.org/1999/xhtml">
      <body>
        <h1>Chapter One</h1>
        <p>Hello world.</p>
        <p>Second paragraph.</p>
      </body>
    </html>
    """)
    nodes = EpubDocument._block_nodes(root)
    assert len(nodes) == 3
    assert ["".join(node.itertext()) for node in nodes] == [
        "Chapter One", "Hello world.", "Second paragraph."
    ]


def test_nested_blocks_are_not_selected_twice():
    root = etree.fromstring(b"""
    <html xmlns="http://www.w3.org/1999/xhtml">
      <body>
        <li><p>Nested paragraph.</p></li>
        <p>Standalone paragraph.</p>
      </body>
    </html>
    """)
    nodes = EpubDocument._block_nodes(root)
    assert ["".join(node.itertext()) for node in nodes] == [
        "Nested paragraph.", "Standalone paragraph."
    ]
