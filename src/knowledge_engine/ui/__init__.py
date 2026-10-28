"""The local web interface: ``ke ui`` (UI-001 onwards).

A small website that runs only on your own computer. It shows the same
things as the ``ke`` commands, as pages: past imports, their reports in
plain words, and (in later tickets) an Import button and a chat browser.

It adds screens, not logic: every page reads what the importer and the
renderers already store. Pages are rendered on the server with Jinja2
templates, which escape everything by default, so text from chats can't
inject markup into a page.

Talking points:
    - "One command opens my archive in the browser. It only listens on my
      own machine, with no accounts and nothing in the cloud."
    - "The web pages reuse the same code as the command line; they're just
      another way to look at it."
"""
