"""Infrastructure: the code that talks to things outside pure Python logic.

Databases now, and later file stores and model providers. Keeping them here
means the domain code never imports a database or an SDK directly
(TECHNICAL_REQUIREMENTS TR-02), so it stays easy to test and to swap.

Talking points:
    - "Business rules don't know which database they run on; only this
      package does."
"""
